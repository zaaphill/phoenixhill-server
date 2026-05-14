import atexit
import datetime
import json
import os
import subprocess
import sys
import threading
import time

from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectEntry, DirectButton
from panda3d.core import (
    Point3, TextNode, TransparencyAttrib, Filename,
    LColor, AmbientLight, DirectionalLight, CardMaker, BitMask32,
    PNMImage, StringStream, Texture,
)

import auth_client

_HERE = os.path.dirname(os.path.abspath(__file__))

# User data directory — writable in both dev and packaged builds.
_USER_DATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PhoenixHill")
os.makedirs(_USER_DATA, exist_ok=True)

_SESSION_FILE  = os.path.join(_USER_DATA, ".session")
_SERVER_LOCK   = os.path.join(_USER_DATA, ".server_starting")

DARK    = (0.11, 0.12, 0.17, 0.97)
DARKER  = (0.07, 0.08, 0.11, 1.0)
MED     = (0.17, 0.19, 0.26, 1.0)
BTN     = (0.19, 0.21, 0.29, 1.0)
SEL     = (0.18, 0.38, 0.72, 1.0)
TEXT    = (0.88, 0.90, 0.95, 1.0)
TEXT_D  = (0.54, 0.57, 0.65, 1.0)
RED     = (1.0,  0.40, 0.40, 1.0)
GREEN   = (0.45, 0.90, 0.55, 1.0)

# ── RetroStudios-style browse palette ─────────────────────────────────────────
_RS_BG      = (0.78, 0.75, 0.88, 1.0)
_RS_NAV     = (0.55, 0.45, 0.76, 1.0)
_RS_CARD    = (0.84, 0.82, 0.93, 1.0)
_RS_ORANGE  = (0.58, 0.18, 0.82, 1.0)
_RS_BORDER  = (0.48, 0.38, 0.66, 1.0)
_RS_WHITE   = (0.00, 0.00, 0.00, 1.0)
_RS_GRAY    = (0.00, 0.00, 0.00, 1.0)
_RS_GREEN   = (0.27, 0.82, 0.43, 1.0)
_RS_RED     = (0.85, 0.18, 0.18, 1.0)
_THUMB_TINTS = [
    (0.48, 0.32, 0.68, 1), (0.28, 0.40, 0.72, 1),
    (0.28, 0.56, 0.44, 1), (0.68, 0.38, 0.30, 1),
    (0.54, 0.28, 0.70, 1), (0.28, 0.50, 0.70, 1),
    (0.38, 0.64, 0.28, 1), (0.68, 0.42, 0.56, 1),
]
_GRID_COLS  = 5
_CARD_W     = 0.60
_CARD_TH    = 0.34   # thumbnail height portion
_CARD_INFO  = 0.16   # text area height below thumbnail
_CARD_H     = _CARD_TH + _CARD_INFO  # 0.50
_CARD_GAP_X = 0.04
_CARD_GAP_Y = 0.04
_PAGE_SIZE  = 15     # 5 cols × 3 rows

# ── Shop screen layout constants ───────────────────────────────────────────
_SHOP_COLS  = 6
_SHOP_CW    = 0.52   # card full width
_SHOP_CTH   = 0.30   # thumbnail full height
_SHOP_CIH   = 0.18   # info area full height
_SHOP_CH    = 0.48   # total card full height
_SHOP_GAPX  = 0.03
_SHOP_GAPY  = 0.04
_SHOP_PAGE  = 18     # 6 × 3



class LoginScreenMixin:

    def setup_login_screen(self):
        self._session_token    = None
        self._session_username = None
        self._login_ui         = None
        self._main_menu_ui     = None
        self._login_status     = None
        self._server_proc      = None
        self._is_play_only     = False

        self._hide_studio_ui()
        self._show_startup_splash()
        # Install deps + start server + poll — all in background so the window stays responsive.
        threading.Thread(target=self._wait_for_server_thread, daemon=True).start()

    # ── Server process ─────────────────────────────────────────────────────

    def _install_server_deps(self):
        """Install server + client deps into the running Python if missing."""
        try:
            import fastapi   # noqa: F401
            import uvicorn   # noqa: F401
            import websockets  # noqa: F401
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "fastapi", "uvicorn", "websockets"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _kill_port_8000(self):
        """Kill whatever process is already listening on port 8000."""
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
            killed = set()
            for line in result.stdout.splitlines():
                if ":8000" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid not in killed:
                        subprocess.run(["taskkill", "/F", "/PID", pid],
                                       capture_output=True, text=True)
                        killed.add(pid)
            if killed:
                time.sleep(1.5)
        except Exception:
            pass

    _REQUIRED_SERVER_API_VERSION = 8

    def _start_server(self):
        try:
            fd = os.open(_SERVER_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            owns_lock = True
        except FileExistsError:
            owns_lock = False

        if not owns_lock:
            for _ in range(20):
                time.sleep(0.5)
                result, _ = auth_client.browse_published()
                if result is not None:
                    return
            try:
                os.remove(_SERVER_LOCK)
            except Exception:
                pass

        try:
            self._kill_port_8000()
            server_py = os.path.join(_HERE, "server.py")
            log_path  = os.path.join(_HERE, "server_log.txt")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                log_file = open(log_path, "w", encoding="utf-8")
                self._server_log = log_file
                self._server_proc = subprocess.Popen(
                    [sys.executable, server_py],
                    cwd=os.path.dirname(server_py),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                atexit.register(self._stop_server)
            except Exception as e:
                print(f"[SERVER] Popen failed: {e}", flush=True)
                self._server_proc = None
        finally:
            try:
                os.remove(_SERVER_LOCK)
            except Exception:
                pass

    def _stop_server(self):
        proc = getattr(self, "_server_proc", None)
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        log = getattr(self, "_server_log", None)
        if log:
            try:
                log.close()
            except Exception:
                pass

    def _show_startup_splash(self):
        import config
        cfg = config.get()
        sub = "Starting server…" if cfg["local"] else f"Connecting to {cfg['display']}…"
        self._splash = DirectFrame(
            frameColor=_RS_BG,
            frameSize=(-3, 3, -3, 3),
        )
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=self._splash, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.40, 0.40, -0.14, 0.14),
            parent=self._splash, pos=(0, 0, 0),
        )
        DirectLabel(
            text="Loading…",
            text_fg=_RS_WHITE, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.052),
        )
        DirectLabel(
            text=sub,
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.034),
        )

    def _wait_for_server_thread(self):
        """Background thread: start/connect to server, then poll until ready."""
        import config
        cfg = config.get()
        if cfg["local"] and not getattr(sys, "frozen", False):
            self._install_server_deps()
            self._start_server()
        crash_msg = None
        polls = 34 if cfg["local"] else 20   # remote gets 6 s before giving up
        for _ in range(polls):
            if cfg["local"]:
                proc = getattr(self, "_server_proc", None)
                if proc and proc.poll() is not None:
                    log = getattr(self, "_server_log", None)
                    if log:
                        log.flush()
                    try:
                        with open(os.path.join(_USER_DATA, "server_log.txt")) as f:
                            lines = f.read().strip().splitlines()
                        crash_msg = lines[-1] if lines else "server.py exited unexpectedly"
                    except Exception:
                        crash_msg = "server.py exited unexpectedly — check server_log.txt"
                    break
            _, err = auth_client.verify("ping")
            if err is None or "Cannot connect" not in err:
                break
            time.sleep(0.3)
        self.taskMgr.doMethodLater(0, self._after_server_ready, "_afterServerReady",
                                   extraArgs=[crash_msg], appendTask=True)

    def _after_server_ready(self, crash_msg, task):
        if hasattr(self, "_splash") and self._splash:
            self._splash.destroy()
            self._splash = None
        if crash_msg:
            self._build_login_ui()
            self._set_status(f"Server error: {crash_msg}")
            return task.done
        saved = self._load_saved_token()
        if saved:
            self._verify_token_async(*saved)
        else:
            self._build_login_ui()
        return task.done

    # ── Token file ─────────────────────────────────────────────────────────

    def _load_saved_token(self):
        try:
            with open(_SESSION_FILE) as f:
                lines = f.read().strip().splitlines()
            if len(lines) == 2:
                return lines[0], lines[1]
        except Exception:
            pass
        return None

    def _save_token(self, token, username):
        try:
            with open(_SESSION_FILE, "w") as f:
                f.write(f"{token}\n{username}")
        except Exception:
            pass

    def _delete_saved_token(self):
        try:
            os.remove(_SESSION_FILE)
        except Exception:
            pass

    # ── Studio visibility ──────────────────────────────────────────────────

    def _hide_studio_ui(self):
        for attr in ("_top_bg", "_panel", "_status_lbl"):
            node = getattr(self, attr, None)
            if node:
                node.hide()
        if hasattr(self, "character"):
            self.character.hide()

    def _show_studio_ui(self):
        for attr in ("_top_bg", "_status_lbl"):
            node = getattr(self, attr, None)
            if node:
                node.show()

    # ── Auto-login ─────────────────────────────────────────────────────────

    def _sync_avatar_from_server_bg(self, token, username):
        """Fetch server-side avatar colors and merge into per-account local file (bg-thread safe).
        If the server has no colors yet, push the local colors up so multiplayer sees them."""
        try:
            av_res, _ = auth_client.get_avatar(token)
            server_colors = (av_res or {}).get("colors") or {}
            local = self.load_avatar_colors(username)
            if server_colors and isinstance(server_colors, dict):
                for part in list(local.keys()):
                    sc = server_colors.get(part)
                    if sc and len(sc) == 4:
                        local[part] = tuple(float(v) for v in sc)
                self.save_avatar_colors(local, username)
            else:
                # Server has no colors yet — push local so multiplayer works immediately
                auth_client.put_avatar(token, {k: list(v) for k, v in local.items()})
        except Exception as e:
            print(f"[Avatar] server sync: {e}")

    def _verify_token_async(self, token, username):
        def worker():
            result, _ = auth_client.verify(token)
            if result and result.get("ok"):
                self._sync_avatar_from_server_bg(token, result["username"])
                self.taskMgr.doMethodLater(
                    0, self._on_auto_login_ok, "_autoLoginOk",
                    extraArgs=[token, result["username"]], appendTask=True,
                )
            else:
                self._delete_saved_token()
                self.taskMgr.doMethodLater(
                    0, self._show_login_task, "_showLogin", appendTask=True,
                )
        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_login_ok(self, token, username, task):
        self._session_token    = token
        self._session_username = username
        self.apply_avatar_colors()
        self._build_browse_screen()
        return task.done

    def _show_login_task(self, task):
        self._build_login_ui()
        return task.done

    # ── Login form ─────────────────────────────────────────────────────────

    def _build_login_ui(self):
        if self._login_ui:
            self._login_ui.destroy()

        root = DirectFrame(
            frameColor=_RS_BG,
            frameSize=(-3, 3, -3, 3),
        )
        self._login_ui = root

        # Top nav bar
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=root, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)

        # Login card
        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.52, 0.52, -0.44, 0.42),
            parent=root, pos=(0, 0, 0),
        )
        DirectLabel(
            text="Welcome back",
            text_fg=_RS_WHITE, text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.305),
        )
        DirectLabel(
            text="Sign in or create an account to continue",
            text_fg=_RS_GRAY, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.235),
        )
        DirectFrame(
            frameColor=_RS_BORDER,
            frameSize=(-0.44, 0.44, -0.002, 0.002),
            parent=card, pos=(0, 0, 0.185),
        )

        # Username
        DirectLabel(
            text="Username",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.44, 0, 0.125),
            text_align=TextNode.ALeft,
        )
        u_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.44, 0.44, -0.042, 0.042),
            parent=card, pos=(0, 0, 0.048),
        )
        self._u_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            width=24, numLines=1,
            parent=u_bg, pos=(-0.41, 0, -0.016),
            initialText="",
            focus=1,
        )

        # Password
        DirectLabel(
            text="Password",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.44, 0, -0.060),
            text_align=TextNode.ALeft,
        )
        p_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.44, 0.44, -0.042, 0.042),
            parent=card, pos=(0, 0, -0.140),
        )
        self._p_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            width=24, numLines=1,
            parent=p_bg, pos=(-0.41, 0, -0.016),
            initialText="",
            obscured=1,
            command=self._on_enter_pressed,
        )

        self._login_status = DirectLabel(
            text="",
            text_fg=_RS_RED, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.250),
        )

        DirectButton(
            text="Log In",
            text_fg=_RS_WHITE, text_scale=0.036,
            frameColor=_RS_ORANGE,
            frameSize=(-0.195, 0.195, -0.046, 0.046),
            parent=card, pos=(-0.22, 0, -0.345),
            command=self._do_login, relief=1,
        )
        DirectButton(
            text="Sign Up",
            text_fg=_RS_GRAY, text_scale=0.032,
            frameColor=_RS_BORDER,
            frameSize=(-0.168, 0.168, -0.040, 0.040),
            parent=card, pos=(0.26, 0, -0.345),
            command=self._do_register, relief=1,
        )

    def _on_enter_pressed(self, _text):
        self._do_login()

    def _set_status(self, msg, color=None):
        if color is None:
            color = _RS_RED
        lbl = self._login_status
        if lbl and not lbl.isEmpty():
            lbl["text"]    = msg
            lbl["text_fg"] = color

    def _get_creds(self):
        return self._u_entry.get().strip(), self._p_entry.get()

    def _do_login(self):
        u, p = self._get_creds()
        if not u or not p:
            self._set_status("Enter username and password.")
            return
        self._set_status("Logging in…", _RS_GRAY)
        def worker():
            result, err = auth_client.login(u, p)
            if result and result.get("ok"):
                self._sync_avatar_from_server_bg(result["token"], result["username"])
                self.taskMgr.doMethodLater(
                    0, self._on_login_ok, "_loginOk",
                    extraArgs=[result["token"], result["username"]], appendTask=True,
                )
            else:
                self.taskMgr.doMethodLater(
                    0, self._on_login_fail, "_loginFail",
                    extraArgs=[err or "Login failed."], appendTask=True,
                )
        threading.Thread(target=worker, daemon=True).start()

    def _do_register(self):
        u, p = self._get_creds()
        if not u or not p:
            self._set_status("Enter username and password.")
            return
        self._set_status("Registering…", _RS_GRAY)
        def worker():
            result, err = auth_client.register(u, p)
            if result and result.get("ok"):
                result2, err2 = auth_client.login(u, p)
                if result2 and result2.get("ok"):
                    self._sync_avatar_from_server_bg(result2["token"], result2["username"])
                    self.taskMgr.doMethodLater(
                        0, self._on_login_ok, "_loginOk",
                        extraArgs=[result2["token"], result2["username"]], appendTask=True,
                    )
                else:
                    self.taskMgr.doMethodLater(
                        0, self._on_login_fail, "_loginFail",
                        extraArgs=["Registered! Please log in."], appendTask=True,
                    )
            else:
                self.taskMgr.doMethodLater(
                    0, self._on_login_fail, "_loginFail",
                    extraArgs=[err or "Registration failed."], appendTask=True,
                )
        threading.Thread(target=worker, daemon=True).start()

    def _on_login_ok(self, token, username, task):
        self._session_token    = token
        self._session_username = username
        self._save_token(token, username)
        self.apply_avatar_colors()
        if self._login_ui:
            self._login_ui.destroy()
            self._login_ui = None
        self._build_browse_screen()
        return task.done

    def _on_login_fail(self, msg, task):
        self._set_status(msg)
        return task.done

    # ── Auto-join ──────────────────────────────────────────────────────────

    def _auto_join_server(self):
        """After login, find the best active server and join it automatically."""
        # Show a brief connecting splash
        self._join_splash = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=self._join_splash, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.44, 0.44, -0.20, 0.16),
            parent=self._join_splash, pos=(0, 0, 0),
        )
        DirectLabel(
            text="Finding a server…",
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.082),
        )
        self._join_status_lbl = DirectLabel(
            text="",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.020),
        )
        DirectButton(
            text="Browse servers instead",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=_RS_BORDER,
            frameSize=(-0.22, 0.22, -0.034, 0.034),
            parent=card, pos=(0, 0, -0.130),
            command=self._cancel_auto_join, relief=1,
        )
        threading.Thread(target=self._find_and_join_thread, daemon=True).start()

    def _cancel_auto_join(self):
        if hasattr(self, "_join_splash") and self._join_splash:
            self._join_splash.destroy()
            self._join_splash = None
        self._build_browse_screen()

    def _find_and_join_thread(self):
        result, _ = auth_client.browse_published()
        builds = result["builds"] if result else []
        rooms_result, _ = auth_client.get_rooms()
        rooms = rooms_result.get("rooms", {}) if rooms_result else {}
        for b in builds:
            b["online"] = rooms.get(str(b["id"]), 0)
        # Prefer server with most players; fall back to most recent
        builds.sort(key=lambda b: (b["online"], b["updated_at"]), reverse=True)
        active = [b for b in builds if b.get("online", 0) > 0]
        if not active:
            self.taskMgr.doMethodLater(0, self._no_server_found, "_noServer", appendTask=True)
            return
        best = active[0]
        load_result, err = auth_client.get_published_build(best["id"])
        if load_result and load_result.get("ok"):
            self.taskMgr.doMethodLater(
                0, self._do_auto_join, "_doAutoJoin",
                extraArgs=[load_result["id"], load_result["name"], load_result["data"]],
                appendTask=True,
            )
        else:
            self.taskMgr.doMethodLater(0, self._no_server_found, "_noServer", appendTask=True)

    def _do_auto_join(self, build_id, name, data_str, task):
        if not getattr(self, "_join_splash", None):
            return task.done  # user cancelled or navigated away before the thread finished
        self._join_splash.destroy()
        self._join_splash = None
        self._enter_play_mode(build_id, name, data_str)
        return task.done

    def _no_server_found(self, task):
        if hasattr(self, "_join_splash") and self._join_splash:
            self._join_splash.destroy()
            self._join_splash = None
        self._build_browse_screen()
        return task.done

    # ── Main menu ──────────────────────────────────────────────────────────

    def _build_main_menu(self):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar (Build tab active) ─────────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",  self._build_browse_screen),
            ("Avatar", self._build_avatar_screen),
            ("Shop",   self._build_shop_screen),
            ("Build",  self._build_main_menu),
        ]):
            is_active = (i == 3)
            DirectButton(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.034,
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.10, 0.10, -0.052, 0.052),
                parent=nav, pos=((i - 1.5) * 0.26, 0, -0.008),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.20, 0, -0.014),
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, -0.014),
            relief=1, command=self._do_logout,
        )

        # ── Section header + New Build ──────────────────────────────────────
        DirectLabel(
            text="My Builds",
            text_fg=_RS_WHITE, text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            parent=bg, pos=(-1.62, 0, 0.757),
        )
        DirectButton(
            text="+ New Build",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_ORANGE,
            frameSize=(-0.130, 0.130, -0.034, 0.034),
            parent=bg, pos=(1.55, 0, 0.757),
            command=self._enter_studio, relief=1,
        )
        DirectButton(
            text="Upload T-Shirt",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.130, 0.130, -0.030, 0.030),
            parent=bg, pos=(1.55, 0, 0.690),
            command=self._show_upload_tshirt_dialog, relief=1,
        )

        # ── Build list ──────────────────────────────────────────────────────
        self._build_list_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-1.70, 1.70, -1.60, 0.66),
            parent=bg,
        )
        self._build_list_status = DirectLabel(
            text="Loading…",
            text_fg=_RS_GRAY, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=self._build_list_frame, pos=(0, 0, 0.2),
        )

        threading.Thread(target=self._fetch_builds_thread, daemon=True).start()

    def _fetch_builds_thread(self):
        result, err = auth_client.list_builds(self._session_token)
        builds = result["builds"] if result else []
        self.taskMgr.doMethodLater(
            0, self._populate_build_list, "_populateBuilds",
            extraArgs=[builds, err], appendTask=True,
        )

    def _populate_build_list(self, builds, err, task):
        lbl = self._build_list_status
        if lbl and not lbl.isEmpty():
            lbl.destroy()

        frame = self._build_list_frame
        if not builds:
            DirectLabel(
                text="No saves yet." if not err else f"Error: {err}",
                text_fg=_RS_GRAY, text_scale=0.034,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, 0.2),
            )
            return task.done

        ROW_H  = 0.096
        ROW_BG = (0.70, 0.65, 0.84, 1.0)
        PUB_C  = (0.14, 0.55, 0.25, 1.0)
        for i, build in enumerate(builds[:8]):
            y      = -(i + 0.5) * ROW_H + 0.60
            is_pub = bool(build.get("published", 0))
            DirectFrame(
                frameColor=ROW_BG,
                frameSize=(-1.65, 1.65, -ROW_H / 2 + 0.006, ROW_H / 2 - 0.006),
                parent=frame, pos=(0, 0, y),
            )
            name = build["name"]
            if len(name) > 36:
                name = name[:34] + "…"
            ts = datetime.datetime.fromtimestamp(build["updated_at"]).strftime("%b %d, %Y")
            DirectLabel(
                text=name,
                text_fg=_RS_WHITE, text_scale=0.030,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-1.60, 0, y + 0.018),
            )
            DirectLabel(
                text=ts,
                text_fg=_RS_GRAY, text_scale=0.022,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-1.60, 0, y - 0.020),
            )
            DirectButton(
                text="Settings",
                text_fg=_RS_WHITE, text_scale=0.024,
                frameColor=_RS_BORDER,
                frameSize=(-0.080, 0.080, -0.028, 0.028),
                parent=frame, pos=(0.72, 0, y),
                command=self._open_game_settings,
                extraArgs=[build["id"], build["name"]], relief=1,
            )
            DirectButton(
                text="Unpublish" if is_pub else "Publish",
                text_fg=_RS_WHITE, text_scale=0.022,
                frameColor=PUB_C if is_pub else _RS_BORDER,
                frameSize=(-0.090, 0.090, -0.028, 0.028),
                parent=frame, pos=(1.02, 0, y),
                command=self._on_toggle_publish,
                extraArgs=[build["id"], not is_pub], relief=1,
            )
            DirectButton(
                text="Load",
                text_fg=_RS_WHITE, text_scale=0.024,
                frameColor=_RS_ORANGE,
                frameSize=(-0.065, 0.065, -0.028, 0.028),
                parent=frame, pos=(1.30, 0, y),
                command=self._on_load_build,
                extraArgs=[build["id"]], relief=1,
            )
            DirectButton(
                text="Delete",
                text_fg=_RS_WHITE, text_scale=0.024,
                frameColor=_RS_RED,
                frameSize=(-0.075, 0.075, -0.028, 0.028),
                parent=frame, pos=(1.56, 0, y),
                command=self._on_delete_build,
                extraArgs=[build["id"]], relief=1,
            )
        return task.done

    def _browse_for_thumbnail(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                parent=root,
                title="Select thumbnail image",
                filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
            )
            root.destroy()
            return path or ""
        except Exception as e:
            print(f"[BROWSE_THUMB] error: {e}", flush=True)
            return ""

    def _open_game_settings(self, build_id, build_name):
        existing = getattr(self, "_settings_popup", None)
        if existing:
            try:
                existing.destroy()
            except Exception:
                pass

        _RS_BG     = (0.78, 0.75, 0.88, 1.0)
        _RS_CARD   = (0.84, 0.82, 0.93, 1.0)
        _RS_ROW    = (0.70, 0.65, 0.84, 1.0)
        _RS_ORANGE = (0.58, 0.18, 0.82, 1.0)
        _RS_WHITE  = (0.00, 0.00, 0.00, 1.0)
        _RS_GRAY   = (0.00, 0.00, 0.00, 1.0)
        _RS_GREEN  = (0.22, 0.75, 0.40, 1.0)
        _RS_RED    = (0.82, 0.18, 0.18, 1.0)

        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.78),
            frameSize=(-3, 3, -3, 3),
            sortOrder=80,
            state='normal',
        )
        self._settings_popup = overlay

        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.68, 0.68, -0.50, 0.50),
            parent=overlay, sortOrder=81,
        )

        # Title
        DirectLabel(
            text=f"Settings  -  {build_name[:40]}",
            text_fg=_RS_WHITE, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.38),
        )

        # Divider line
        DirectFrame(
            frameColor=(0.22, 0.20, 0.32, 1.0),
            frameSize=(-0.60, 0.60, -0.002, 0.002),
            parent=card, pos=(0, 0, 0.28),
        )

        # ── Description ──────────────────────────────────────────────────────
        DirectLabel(
            text="Description",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.58, 0, 0.19),
            text_align=TextNode.ALeft,
        )
        desc_bg = DirectFrame(
            frameColor=_RS_ROW,
            frameSize=(-0.60, 0.60, -0.042, 0.042),
            parent=card, pos=(0, 0, 0.11),
        )
        desc_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=40, numLines=1,
            parent=desc_bg, pos=(-0.57, 0, -0.014),
            initialText="",
        )

        # ── Thumbnail ────────────────────────────────────────────────────────
        DirectLabel(
            text="Thumbnail  (PNG / JPG, 1920x1080)",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.58, 0, -0.04),
            text_align=TextNode.ALeft,
        )

        self._pending_thumb_path = ""
        self._current_thumb_b64  = ""

        thumb_lbl = DirectLabel(
            text="No new file selected  (existing thumbnail kept)",
            text_fg=_RS_GRAY, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.58, 0, -0.15),
            text_align=TextNode.ALeft,
        )

        def _browse():
            path = self._browse_for_thumbnail()
            if path:
                self._pending_thumb_path = path
                short = path.replace("\\", "/").split("/")[-1]
                if len(short) > 44:
                    short = "..." + short[-41:]
                thumb_lbl["text"] = short
                thumb_lbl["text_fg"] = _RS_WHITE

        DirectButton(
            text="Browse...",
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=_RS_ROW,
            frameSize=(-0.13, 0.13, -0.036, 0.036),
            parent=card, pos=(-0.46, 0, -0.10),
            command=_browse, relief=1,
        )

        # Status
        self._settings_status = DirectLabel(
            text="",
            text_fg=_RS_GREEN, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.26),
        )

        # Load existing settings
        def _load():
            res, _ = auth_client.get_game_settings(self._session_token, build_id)
            if res:
                def _apply(task, r=res):
                    self._current_thumb_b64 = r.get("thumbnail", "")
                    if desc_entry and not desc_entry.isEmpty():
                        desc_entry.set(r.get("description", ""))
                    if self._current_thumb_b64 and thumb_lbl and not thumb_lbl.isEmpty():
                        thumb_lbl["text"] = "Existing thumbnail loaded"
                        thumb_lbl["text_fg"] = _RS_GREEN
                    return task.done
                self.taskMgr.doMethodLater(0, _apply, "_applySettings", appendTask=True)
        threading.Thread(target=_load, daemon=True).start()

        def _save():
            desc_text  = desc_entry.get().strip()
            thumb_path = self._pending_thumb_path
            if thumb_path:
                try:
                    import base64, tempfile, os
                    from panda3d.core import PNMImage, Filename as _Fn
                    img = PNMImage()
                    if not img.read(_Fn.fromOsSpecific(thumb_path)):
                        raise IOError(f"Cannot read image: {thumb_path}")
                    # Strip alpha so the JPEG is always opaque RGB
                    if img.hasAlpha():
                        img.removeAlpha()
                    # Resize to max 640×360 to keep uploads small
                    MAX_W, MAX_H = 640, 360
                    if img.getXSize() > MAX_W or img.getYSize() > MAX_H:
                        ratio = min(MAX_W / img.getXSize(), MAX_H / img.getYSize())
                        nw = max(1, int(img.getXSize() * ratio))
                        nh = max(1, int(img.getYSize() * ratio))
                        small = PNMImage(nw, nh)
                        small.quickFilterFrom(img)
                        img = small
                    tmp = tempfile.mktemp(suffix=".jpg")
                    img.write(_Fn.fromOsSpecific(tmp))
                    with open(tmp, "rb") as f:
                        thumb_b64 = base64.b64encode(f.read()).decode()
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                except Exception as e:
                    lbl = self._settings_status
                    if lbl and not lbl.isEmpty():
                        lbl["text"] = f"Image error: {e}"
                        lbl["text_fg"] = _RS_RED
                    return
            else:
                # No new file — preserve whatever the server already has
                thumb_b64 = self._current_thumb_b64

            lbl = self._settings_status
            if lbl and not lbl.isEmpty():
                lbl["text"] = "Saving..."
                lbl["text_fg"] = _RS_GRAY

            def worker():
                res, err = auth_client.put_game_settings(
                    self._session_token, build_id, thumb_b64, desc_text)
                def _done(task, ok=(res is not None), err=err):
                    l = getattr(self, "_settings_status", None)
                    if l and not l.isEmpty():
                        l["text"] = "Saved!" if ok else f"Error: {err}"
                        l["text_fg"] = _RS_GREEN if ok else _RS_RED
                    if ok:
                        self._refresh_build_list(task)
                    return task.done
                self.taskMgr.doMethodLater(0, _done, "_settingsDone", appendTask=True)
            threading.Thread(target=worker, daemon=True).start()

        # Buttons row
        DirectButton(
            text="Save",
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=_RS_ORANGE,
            frameSize=(-0.18, 0.18, -0.040, 0.040),
            parent=card, pos=(-0.22, 0, -0.38),
            command=_save, relief=1,
        )
        DirectButton(
            text="Cancel",
            text_fg=_RS_GRAY, text_scale=0.030,
            frameColor=_RS_ROW,
            frameSize=(-0.15, 0.15, -0.036, 0.036),
            parent=card, pos=(0.26, 0, -0.38),
            command=lambda: [overlay.destroy(), setattr(self, "_settings_popup", None)],
            relief=1,
        )

    def _on_toggle_publish(self, build_id, new_state):
        token = self._session_token
        def worker():
            auth_client.set_published(token, build_id, new_state)
            self.taskMgr.doMethodLater(
                0, self._refresh_build_list, "_refreshBuilds", appendTask=True)
        threading.Thread(target=worker, daemon=True).start()

    def _on_load_build(self, build_id):
        def worker():
            result, err = auth_client.load_build(self._session_token, build_id)
            if result and result.get("ok"):
                self.taskMgr.doMethodLater(
                    0, self._do_enter_with_build, "_enterWithBuild",
                    extraArgs=[result["id"], result["name"], result["data"]],
                    appendTask=True,
                )
            else:
                print("Load failed:", err)
        threading.Thread(target=worker, daemon=True).start()

    def _do_enter_with_build(self, build_id, name, data_str, task):
        self._enter_studio()
        self.cloud_load_into_scene(build_id, name, data_str)
        return task.done

    def _on_delete_build(self, build_id):
        token = self._session_token
        def worker():
            auth_client.delete_build(token, build_id)
            self.taskMgr.doMethodLater(
                0, self._refresh_build_list, "_refreshBuilds", appendTask=True,
            )
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_build_list(self, task):
        self._build_main_menu()
        return task.done

    # ── Shop screen ────────────────────────────────────────────────────────

    def _build_shop_screen(self):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        self._shop_owned_ids = getattr(self, "_shop_owned_ids", set())
        self._shop_item_popup = None

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar (Shop tab active) ──────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",  self._build_browse_screen),
            ("Avatar", self._build_avatar_screen),
            ("Shop",   self._build_shop_screen),
            ("Build",  self._build_main_menu),
        ]):
            is_active = (i == 2)
            DirectButton(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.034,
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.10, 0.10, -0.052, 0.052),
                parent=nav, pos=((i - 1.5) * 0.26, 0, -0.008),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.20, 0, -0.014),
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, -0.014),
            relief=1, command=self._do_logout,
        )

        # ── Toolbar ────────────────────────────────────────────────────
        _TOOL_BG = (0.62, 0.55, 0.78, 1.0)
        DirectFrame(
            frameColor=_TOOL_BG,
            frameSize=(-2.5, 2.5, -0.038, 0.038),
            parent=bg, pos=(0, 0, 0.802),
        )

        # ── Grid container with Loading label ──────────────────────────
        self._shop_grid_parent = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-2.0, 2.0, -1.80, 0.72),
            parent=bg,
        )
        self._shop_loading_lbl = DirectLabel(
            text="Loading...",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._shop_grid_parent, pos=(0, 0, 0),
        )

        # ── Pagination ──────────────────────────────────────────────────
        DirectButton(
            text="< Prev",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_NAV,
            frameSize=(-0.070, 0.070, -0.034, 0.034),
            parent=bg, pos=(-0.24, 0, -0.913),
            relief=1,
        )
        DirectLabel(
            text="Page 1",
            text_fg=_RS_GRAY, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=bg, pos=(0, 0, -0.913),
        )
        DirectButton(
            text="Next >",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_NAV,
            frameSize=(-0.070, 0.070, -0.034, 0.034),
            parent=bg, pos=(0.24, 0, -0.913),
            relief=1,
        )

        threading.Thread(target=self._fetch_shop_items_thread, daemon=True).start()

    def _fetch_shop_items_thread(self):
        items_result, items_err = auth_client.list_shop_items()
        items = (items_result or {}).get("items", [])
        owned_result, _ = auth_client.get_owned_items(self._session_token)
        owned = {it["id"] for it in (owned_result or {}).get("items", [])}
        self.taskMgr.doMethodLater(
            0, self._draw_shop_grid_task, "_drawShopGrid",
            extraArgs=[items, items_err, owned], appendTask=True,
        )

    def _render_shop_thumbnails(self, items):
        """RTT-render one avatar+tshirt frame per item; returns {item_id: Texture}."""
        items_with_img = [(it["id"], it["image_data"]) for it in items if it.get("image_data")]
        if not items_with_img:
            return {}

        result = {}
        PMASK  = BitMask32.bit(6)
        BUF_W, BUF_H = 192, 256

        _DEFAULTS = {
            "head":      (244/255, 204/255,  67/255, 1),
            "torso":     ( 23/255, 107/255, 170/255, 1),
            "left_arm":  (244/255, 204/255,  67/255, 1),
            "right_arm": (244/255, 204/255,  67/255, 1),
            "left_leg":  (165/255, 188/255,  80/255, 1),
            "right_leg": (165/255, 188/255,  80/255, 1),
        }

        # ── Avatar rig parked far from the game world ──────────────────────────
        rig = self.render.attachNewNode("shop_thumb_root")
        rig.setPos(0, 3000, 0)

        def box(parent, scale, pos, key):
            m = self.loader.loadModel("models/box")
            m.reparentTo(parent)
            m.setScale(*scale)
            m.setPos(*pos)
            m.setColor(*_DEFAULTS[key])
            m.setTextureOff(1)
            m.show(PMASK)
            return m

        box(rig, (2, 1, 2), (-1, -0.5, 2), "torso")
        la = rig.attachNewNode("la"); la.setPos(-1.5, 0, 4)
        box(la, (1, 1, 2), (-0.5, -0.5, -2), "left_arm")
        ra = rig.attachNewNode("ra"); ra.setPos(1.5, 0, 4)
        box(ra, (1, 1, 2), (-0.5, -0.5, -2), "right_arm")
        ll = rig.attachNewNode("ll"); ll.setPos(-0.5, 0, 2)
        box(ll, (1, 1, 2), (-0.5, -0.5, -2), "left_leg")
        rl = rig.attachNewNode("rl"); rl.setPos(0.5, 0, 2)
        box(rl, (1, 1, 2), (-0.5, -0.5, -2), "right_leg")

        head = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        head.reparentTo(rig)
        head.setColor(*_DEFAULTS["head"])
        head.setTwoSided(True)
        head.setTextureOff(1)
        head.setPos(0, 0, 4.55)
        head.show(PMASK)

        al = AmbientLight("st_al"); al.setColor(LColor(0.22, 0.22, 0.25, 1))
        rig.setLight(rig.attachNewNode(al))
        dl = DirectionalLight("st_dl"); dl.setColor(LColor(0.50, 0.50, 0.52, 1))
        dlnp = rig.attachNewNode(dl); dlnp.setHpr(20, 15, 0)
        rig.setLight(dlnp)

        # T-shirt card (replaced per item)
        tshirt_anchor = [None]

        def _swap_tshirt(image_b64):
            if tshirt_anchor[0] and not tshirt_anchor[0].isEmpty():
                tshirt_anchor[0].removeNode()
                tshirt_anchor[0] = None
            try:
                import base64
                raw = base64.b64decode(image_b64)
                ss  = StringStream(raw)
                pnm = PNMImage()
                if not pnm.read(ss):
                    return
                tex = Texture()
                tex.load(pnm)
                cm = CardMaker("st_tshirt")
                cm.setFrame(-1, 1, 0, 2)
                anchor = rig.attachNewNode("st_tshirt_anchor")
                anchor.setPos(0, -0.51, 2)  # -Y face faces the thumbnail camera
                np_ = anchor.attachNewNode(cm.generate())
                np_.setTexture(tex)
                np_.setTransparency(TransparencyAttrib.MAlpha)
                np_.setLightOff(); np_.setShaderOff()
                np_.setDepthWrite(False); np_.setDepthOffset(1)
                np_.show(PMASK)
                tshirt_anchor[0] = anchor
            except Exception as e:
                print(f"[SHOP_THUMB] tshirt swap error: {e}", flush=True)

        # ── Off-screen buffer + camera ─────────────────────────────────────────
        buf = self.win.makeTextureBuffer("shop_thumb_buf", BUF_W, BUF_H)
        buf.setClearColor(LColor(0.78, 0.75, 0.88, 1.0))
        buf.setClearColorActive(True)

        cam_np = self.makeCamera(buf)
        cam_np.reparentTo(self.render)
        cam_np.setPos(0, 3000 - 8, 0)
        cam_np.lookAt(rig, Point3(0, 0, 2.5))
        lens = cam_np.node().getLens()
        lens.setFov(28, 40)
        lens.setNearFar(0.1, 10000)
        cam_np.node().setCameraMask(PMASK)

        orig_mask = self.camNode.getCameraMask()
        self.camNode.setCameraMask(orig_mask & ~PMASK)

        # ── Render each item ───────────────────────────────────────────────────
        for item_id, image_b64 in items_with_img:
            _swap_tshirt(image_b64)
            self.graphicsEngine.renderFrame()
            pnm = PNMImage()
            if buf.getTexture().store(pnm):
                out_tex = Texture()
                out_tex.load(pnm)
                result[item_id] = out_tex

        # ── Cleanup ────────────────────────────────────────────────────────────
        if tshirt_anchor[0] and not tshirt_anchor[0].isEmpty():
            tshirt_anchor[0].removeNode()
        self.graphicsEngine.removeWindow(buf)
        cam_np.removeNode()
        rig.removeNode()
        self.camNode.setCameraMask(orig_mask)

        return result

    def _draw_shop_grid_task(self, items, err, owned, task):
        self._shop_owned_ids = owned
        lbl = getattr(self, "_shop_loading_lbl", None)
        if lbl and not lbl.isEmpty():
            lbl.destroy()
        frame = getattr(self, "_shop_grid_parent", None)
        if not frame or frame.isEmpty():
            return task.done
        if not items:
            DirectLabel(
                text="No items in the shop yet." if not err else f"Error: {err}",
                text_fg=_RS_GRAY, text_scale=0.034,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, 0),
            )
            return task.done
        try:
            thumb_textures = self._render_shop_thumbnails(items)
        except Exception as e:
            print(f"[SHOP_THUMB] RTT failed: {e}", flush=True)
            thumb_textures = {}
        self._draw_shop_grid(items, frame, thumb_textures)
        return task.done

    def _draw_shop_grid(self, items, frame, thumb_textures=None):
        _CARD_BG  = (0.84, 0.81, 0.93, 1.0)
        _NAME_COL = _RS_WHITE
        _PRICE_COL = _RS_GREEN
        _FREE_COL  = _RS_GREEN
        if thumb_textures is None:
            thumb_textures = {}

        total_w  = _SHOP_COLS * _SHOP_CW + (_SHOP_COLS - 1) * _SHOP_GAPX
        left_cx  = -total_w / 2 + _SHOP_CW / 2
        GRID_TOP = 0.68

        THUMB_CY = _SHOP_CH / 2 - _SHOP_CTH / 2
        NAME_Z   = _SHOP_CH / 2 - _SHOP_CTH - 0.056
        PRICE_Z  = -_SHOP_CH / 2 + 0.038

        for idx, item in enumerate(items[:_SHOP_PAGE]):
            col = idx % _SHOP_COLS
            row = idx // _SHOP_COLS
            cx  = left_cx + col * (_SHOP_CW + _SHOP_GAPX)
            cz  = GRID_TOP - _SHOP_CH / 2 - row * (_SHOP_CH + _SHOP_GAPY)

            card = DirectButton(
                frameColor=_CARD_BG,
                frameSize=(-_SHOP_CW/2, _SHOP_CW/2, -_SHOP_CH/2, _SHOP_CH/2),
                parent=frame, pos=(cx, 0, cz),
                sortOrder=5, relief=1,
                command=self._show_shop_item_popup,
                extraArgs=[item],
            )
            # Thumbnail — RTT avatar render if available, coloured fallback otherwise
            tint_idx = item.get("id", idx) % len(_THUMB_TINTS)
            thumb_frame = DirectFrame(
                frameColor=_THUMB_TINTS[tint_idx],
                frameSize=(-_SHOP_CW/2, _SHOP_CW/2, -_SHOP_CTH/2, _SHOP_CTH/2),
                parent=card, pos=(0, 0, THUMB_CY),
                sortOrder=6,
            )
            rtt_tex = thumb_textures.get(item.get("id"))
            if rtt_tex:
                hw = _SHOP_CW / 2
                hh = _SHOP_CTH / 2
                thumb_frame["frameColor"] = (1, 1, 1, 1)
                thumb_frame["image"]       = rtt_tex
                thumb_frame["image_scale"] = (hw, 1, hh)
            # Item name
            name = item.get("name", "")
            DirectLabel(
                text=(name[:13] + "...") if len(name) > 14 else name,
                text_fg=_NAME_COL, text_scale=0.022,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(0, 0, NAME_Z),
                sortOrder=6,
            )
            # Price
            price = item.get("price", 0)
            if price == 0:
                price_txt = "Free"
                price_col = _FREE_COL
            else:
                price_txt = f"C {price}"
                price_col = _PRICE_COL
            DirectLabel(
                text=price_txt,
                text_fg=price_col, text_scale=0.022,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(0, 0, PRICE_Z),
                sortOrder=6,
            )

    def _show_shop_item_popup(self, item_summary):
        existing = getattr(self, "_shop_item_popup", None)
        if existing:
            try:
                existing.destroy()
            except Exception:
                pass
        self._shop_item_popup = None

        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=500,
            state='normal',
        )
        self._shop_item_popup = overlay

        HW, HH = 1.10, 0.54
        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-HW, HW, -HH, HH),
            parent=overlay, sortOrder=501,
        )

        # Close button
        DirectButton(
            text="X",
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=_RS_RED,
            frameSize=(-0.038, 0.038, -0.038, 0.038),
            parent=card, pos=(HW - 0.056, 0, HH - 0.056),
            relief=1,
            command=lambda: [overlay.destroy(), setattr(self, "_shop_item_popup", None)],
        )

        # Left half — image placeholder
        img_frame = DirectFrame(
            frameColor=_THUMB_TINTS[item_summary.get("id", 0) % len(_THUMB_TINTS)],
            frameSize=(-0.50, 0.50, -0.42, 0.42),
            parent=card, pos=(-0.54, 0, 0),
        )

        # Right half — info
        RX = 0.18
        name = item_summary.get("name", "")
        DirectLabel(
            text=name,
            text_fg=_RS_WHITE, text_scale=0.036,
            text_align=TextNode.ALeft,
            text_wordwrap=20,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(RX, 0, HH - 0.14),
        )
        creator = item_summary.get("username", "")
        DirectLabel(
            text=f"by {creator}",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(RX, 0, HH - 0.24),
        )
        desc = (item_summary.get("description") or "").strip()
        if desc:
            DirectLabel(
                text=(desc[:120] + "...") if len(desc) > 120 else desc,
                text_fg=_RS_GRAY, text_scale=0.024,
                text_align=TextNode.ALeft,
                text_wordwrap=24,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX, 0, HH - 0.36),
            )
        price = item_summary.get("price", 0)
        price_str = "Free" if price == 0 else f"C {price}"
        DirectLabel(
            text=price_str,
            text_fg=_RS_GREEN, text_scale=0.030,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(RX, 0, -HH + 0.16),
        )

        item_id = item_summary.get("id")
        owned = item_id in getattr(self, "_shop_owned_ids", set())

        if owned:
            self._shop_popup_get_btn = DirectLabel(
                text="Owned",
                text_fg=_RS_GREEN, text_scale=0.032,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX + 0.18, 0, -HH + 0.06),
            )
        else:
            self._shop_popup_get_btn = DirectButton(
                text="Get Item",
                text_fg=_RS_WHITE, text_scale=0.032,
                frameColor=_RS_ORANGE,
                frameSize=(-0.14, 0.14, -0.040, 0.040),
                parent=card, pos=(RX + 0.18, 0, -HH + 0.06),
                relief=1,
                command=self._buy_shop_item,
                extraArgs=[item_id],
            )

        # Fetch full item with image in background
        def _fetch_image():
            full, _ = auth_client.get_shop_item(item_id)
            if full and full.get("image_data"):
                def _apply(task, b64=full["image_data"], frm=img_frame):
                    if frm and not frm.isEmpty():
                        self._apply_thumbnail_texture(frm, b64)
                    return task.done
                self.taskMgr.doMethodLater(0, _apply, "_applyShopImg", appendTask=True)
        threading.Thread(target=_fetch_image, daemon=True).start()

    def _buy_shop_item(self, item_id):
        token = self._session_token
        def worker():
            result, err = auth_client.buy_shop_item(token, item_id)
            def _done(task, ok=(result is not None), err=err):
                if ok:
                    self._shop_owned_ids.add(item_id)
                    self._show_toast("Added to your items!", GREEN)
                    btn = getattr(self, "_shop_popup_get_btn", None)
                    if btn and not btn.isEmpty():
                        btn.destroy()
                        self._shop_popup_get_btn = None
                    popup = getattr(self, "_shop_item_popup", None)
                    if popup and not popup.isEmpty():
                        owned_lbl = DirectLabel(
                            text="Owned",
                            text_fg=_RS_GREEN, text_scale=0.032,
                            frameColor=(0, 0, 0, 0),
                            parent=popup.getChild(0),
                            pos=(0.36, 0, -0.48),
                        )
                else:
                    self._show_toast(f"Error: {err}", RED)
                return task.done
            self.taskMgr.doMethodLater(0, _done, "_buyDone", appendTask=True)
        threading.Thread(target=worker, daemon=True).start()

    def _show_upload_tshirt_dialog(self):
        existing = getattr(self, "_upload_tshirt_popup", None)
        if existing:
            try:
                existing.destroy()
            except Exception:
                pass
        self._upload_tshirt_popup = None
        self._upload_tshirt_path  = ""

        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=500,
            state='normal',
        )
        self._upload_tshirt_popup = overlay

        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.70, 0.70, -0.54, 0.54),
            parent=overlay, sortOrder=501,
        )

        DirectLabel(
            text="Upload T-Shirt",
            text_fg=_RS_WHITE, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.42),
        )

        # Image picker
        img_lbl = DirectLabel(
            text="No file chosen",
            text_fg=_RS_GRAY, text_scale=0.024,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.10, 0, 0.28),
        )

        def _browse_img():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    parent=root,
                    title="Select T-Shirt image",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
                )
                root.destroy()
                if path:
                    self._upload_tshirt_path = path
                    short = path.replace("\\", "/").split("/")[-1]
                    if len(short) > 30:
                        short = "..." + short[-27:]
                    img_lbl["text"] = short
                    img_lbl["text_fg"] = _RS_WHITE
            except Exception as e:
                print(f"[UPLOAD_TSHIRT] browse error: {e}", flush=True)

        DirectButton(
            text="Choose Image",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.13, 0.13, -0.030, 0.030),
            parent=card, pos=(-0.50, 0, 0.28),
            relief=1, command=_browse_img,
        )

        # Name field
        DirectLabel(
            text="Name",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.64, 0, 0.12),
        )
        name_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.62, 0.62, -0.036, 0.036),
            parent=card, pos=(0, 0, 0.055),
        )
        name_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=42, numLines=1,
            parent=name_bg, pos=(-0.60, 0, -0.012),
        )

        # Description field
        DirectLabel(
            text="Description",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.64, 0, -0.06),
        )
        desc_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.62, 0.62, -0.036, 0.036),
            parent=card, pos=(0, 0, -0.125),
        )
        desc_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=42, numLines=1,
            parent=desc_bg, pos=(-0.60, 0, -0.012),
        )

        # Price field
        DirectLabel(
            text="Price (0 = free)",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.64, 0, -0.24),
        )
        price_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.62, 0.62, -0.036, 0.036),
            parent=card, pos=(0, 0, -0.305),
        )
        price_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=10, numLines=1,
            parent=price_bg, pos=(-0.60, 0, -0.012),
            initialText="0",
        )

        # Status label
        upload_status = DirectLabel(
            text="",
            text_fg=_RS_GREEN, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.41),
        )

        def _do_upload():
            path = self._upload_tshirt_path
            if not path:
                upload_status["text"] = "Choose an image first."
                upload_status["text_fg"] = _RS_RED
                return
            item_name = name_entry.get().strip()
            if not item_name:
                upload_status["text"] = "Enter a name."
                upload_status["text_fg"] = _RS_RED
                return
            item_desc = desc_entry.get().strip()
            try:
                item_price = max(0, int(price_entry.get().strip() or "0"))
            except ValueError:
                item_price = 0
            upload_status["text"] = "Encoding..."
            upload_status["text_fg"] = _RS_GRAY

            def worker():
                try:
                    import base64, tempfile, os as _os
                    from panda3d.core import PNMImage, Filename as _Fn
                    img = PNMImage()
                    img.read(_Fn.fromOsSpecific(path))
                    if img.getXSize() > 256 or img.getYSize() > 256:
                        target = 256
                        scaled = PNMImage(target, target)
                        scaled.gaussianFilterFrom(1.0, img)
                        img = scaled
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                        tmp = tf.name
                    img.write(_Fn.fromOsSpecific(tmp))
                    with open(tmp, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode()
                    _os.unlink(tmp)
                except Exception as e:
                    def _err(task, msg=str(e)):
                        upload_status["text"] = f"Image error: {msg}"
                        upload_status["text_fg"] = _RS_RED
                        return task.done
                    self.taskMgr.doMethodLater(0, _err, "_uploadErr", appendTask=True)
                    return
                result, err = auth_client.upload_shop_item(
                    self._session_token, item_name, item_desc, item_price, b64)
                def _done(task, ok=(result is not None), err=err):
                    if ok:
                        upload_status["text"] = "Uploaded!"
                        upload_status["text_fg"] = _RS_GREEN
                        self._show_toast("T-Shirt uploaded to shop!", GREEN)
                    else:
                        upload_status["text"] = f"Error: {err}"
                        upload_status["text_fg"] = _RS_RED
                    return task.done
                self.taskMgr.doMethodLater(0, _done, "_uploadDone", appendTask=True)

            threading.Thread(target=worker, daemon=True).start()

        def _cancel():
            p = getattr(self, "_upload_tshirt_popup", None)
            if p:
                try:
                    p.destroy()
                except Exception:
                    pass
            self._upload_tshirt_popup = None

        DirectButton(
            text="Upload to Shop",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_ORANGE,
            frameSize=(-0.18, 0.18, -0.038, 0.038),
            parent=card, pos=(-0.22, 0, -0.48),
            relief=1, command=_do_upload,
        )
        DirectButton(
            text="Cancel",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=_RS_BORDER,
            frameSize=(-0.12, 0.12, -0.034, 0.034),
            parent=card, pos=(0.34, 0, -0.48),
            relief=1, command=_cancel,
        )

    # ── Browse screen ──────────────────────────────────────────────────────

    def _build_browse_screen(self):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
        self._browse_page       = 0
        self._browse_all_builds = []
        self._game_popup        = None

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar ────────────────────────────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.068, 0.068),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.getcwd(), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.090 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.045, 0.045),
                              parent=nav, pos=(-1.55, 0, -0.008))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        # Tabs centred around x=0
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",  self._build_browse_screen),
            ("Avatar", self._build_avatar_screen),
            ("Shop",   self._build_shop_screen),
            ("Build",  self._build_main_menu),
        ]):
            is_active = (i == 0)
            DirectButton(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.034,
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.10, 0.10, -0.052, 0.052),
                parent=nav, pos=((i - 1.5) * 0.26, 0, -0.008),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.20, 0, -0.014),
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, -0.014),
            relief=1, command=self._do_logout,
        )

        # ── Section header ─────────────────────────────────────────────────
        DirectLabel(
            text="Popular",
            text_fg=_RS_WHITE, text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            parent=bg, pos=(-1.62, 0, 0.757),
        )
        DirectButton(
            text="Refresh",
            text_fg=_RS_GRAY, text_scale=0.026,
            frameColor=_RS_NAV,
            frameSize=(-0.080, 0.080, -0.026, 0.026),
            parent=bg, pos=(1.65, 0, 0.757),
            relief=1, command=self._build_browse_screen,
        )

        # ── Game grid container ────────────────────────────────────────────
        self._game_grid_parent = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-2.0, 2.0, -1.80, 0.72),
            parent=bg,
        )
        DirectLabel(
            text="Loading…",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._game_grid_parent, pos=(0, 0, 0),
        )

        # ── Pagination ─────────────────────────────────────────────────────
        self._prev_page_btn = DirectButton(
            text="< Prev",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_NAV,
            frameSize=(-0.070, 0.070, -0.034, 0.034),
            parent=bg, pos=(-0.24, 0, -0.913),
            relief=1, command=self._browse_prev_page,
        )
        self._page_lbl = DirectLabel(
            text="Page 1",
            text_fg=_RS_GRAY, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=bg, pos=(0, 0, -0.913),
        )
        self._next_page_btn = DirectButton(
            text="Next >",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_NAV,
            frameSize=(-0.070, 0.070, -0.034, 0.034),
            parent=bg, pos=(0.24, 0, -0.913),
            relief=1, command=self._browse_next_page,
        )

        threading.Thread(target=self._fetch_browse_thread, daemon=True).start()
        self.taskMgr.doMethodLater(10, self._browse_auto_refresh, "_browseAutoRefresh",
                                   appendTask=True)

    def _browse_auto_refresh(self, task):
        if not getattr(self, "_main_menu_ui", None):
            return task.done  # screen was navigated away from
        threading.Thread(target=self._fetch_browse_thread, daemon=True).start()
        return task.again

    def _fetch_browse_thread(self):
        result, err = auth_client.browse_published()
        builds = result["builds"] if result else []
        rooms_result, _ = auth_client.get_rooms()
        rooms = rooms_result.get("rooms", {}) if rooms_result else {}
        for b in builds:
            b["online"] = rooms.get(str(b["id"]), 0)
        builds.sort(key=lambda b: b["online"], reverse=True)
        self.taskMgr.doMethodLater(
            0, self._populate_browse_list, "_populateBrowse",
            extraArgs=[builds, err], appendTask=True,
        )

    def _populate_browse_list(self, builds, err, task):
        frame = getattr(self, "_game_grid_parent", None)
        if not frame or frame.isEmpty():
            return task.done
        for child in frame.getChildren():
            child.removeNode()
        if not builds:
            DirectLabel(
                text="No published games yet." if not err else f"Error: {err}",
                text_fg=_RS_GRAY, text_scale=0.036,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, 0),
            )
            return task.done
        self._browse_all_builds = builds
        self._browse_page = 0
        self._draw_game_grid()
        return task.done

    def _draw_game_grid(self):
        frame = getattr(self, "_game_grid_parent", None)
        if not frame or frame.isEmpty():
            return
        for child in frame.getChildren():
            child.removeNode()

        page   = getattr(self, "_browse_page", 0)
        builds = getattr(self, "_browse_all_builds", [])
        shown  = builds[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]

        if not shown:
            DirectLabel(
                text="No games here.",
                text_fg=_RS_GRAY, text_scale=0.036,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, 0),
            )
        else:
            total_w  = _GRID_COLS * _CARD_W + (_GRID_COLS - 1) * _CARD_GAP_X
            left_cx  = -total_w / 2 + _CARD_W / 2
            GRID_TOP = 0.62
            THUMB_CY = _CARD_H / 2 - _CARD_TH / 2        # thumbnail center (card-local z)
            NAME_Y   = _CARD_H / 2 - _CARD_TH - 0.042    # name label z (card-local)
            SUB_Y    = -_CARD_H / 2 + 0.042               # creator/count z (card-local)

            for idx, build in enumerate(shown):
                col   = idx % _GRID_COLS
                row   = idx // _GRID_COLS
                cx    = left_cx + col * (_CARD_W + _CARD_GAP_X)
                cy    = GRID_TOP - _CARD_H / 2 - row * (_CARD_H + _CARD_GAP_Y)
                tint  = _THUMB_TINTS[build.get("id", idx) % len(_THUMB_TINTS)]
                online = build.get("online", 0)
                name   = build["name"]
                short  = (name[:12] + "…") if len(name) > 14 else name  # watermark only

                card = DirectButton(
                    frameColor=_RS_CARD,
                    frameSize=(-_CARD_W/2, _CARD_W/2, -_CARD_H/2, _CARD_H/2),
                    parent=frame, pos=(cx, 0, cy),
                    relief=1,
                    command=self._show_game_info_popup,
                    extraArgs=[build],
                )
                # Thumbnail fill
                card_thumb = DirectFrame(
                    frameColor=tint,
                    frameSize=(-_CARD_W/2, _CARD_W/2, -_CARD_TH/2, _CARD_TH/2),
                    parent=card, pos=(0, 0, THUMB_CY),
                    sortOrder=1,
                )
                if build.get("thumbnail"):
                    self._apply_thumbnail_texture(card_thumb, build["thumbnail"])
                # Faint watermark only when no real thumbnail
                if not build.get("thumbnail"):
                    DirectLabel(
                        text=short,
                        text_fg=(1, 1, 1, 0.18), text_scale=0.040,
                        frameColor=(0, 0, 0, 0),
                        parent=card, pos=(0, 0, THUMB_CY),
                        sortOrder=2,
                    )
                # Game name below thumbnail
                DirectLabel(
                    text=name,
                    text_fg=_RS_WHITE, text_scale=0.026,
                    text_align=TextNode.ALeft,
                    text_wordwrap=19,
                    frameColor=(0, 0, 0, 0),
                    parent=card, pos=(-_CARD_W/2 + 0.026, 0, NAME_Y),
                    sortOrder=2,
                )
                # Creator
                creator = build.get("username", "")
                if len(creator) > 10:
                    creator = creator[:9] + "…"
                DirectLabel(
                    text=f"by {creator}",
                    text_fg=_RS_GRAY, text_scale=0.020,
                    text_align=TextNode.ALeft,
                    frameColor=(0, 0, 0, 0),
                    parent=card, pos=(-_CARD_W/2 + 0.026, 0, SUB_Y),
                    sortOrder=2,
                )
                # Online count
                count_col = _RS_GREEN if online else (_RS_GRAY[0], _RS_GRAY[1], _RS_GRAY[2], 0.5)
                DirectLabel(
                    text=f"{online} online" if online else "empty",
                    text_fg=count_col, text_scale=0.020,
                    text_align=TextNode.ARight,
                    frameColor=(0, 0, 0, 0),
                    parent=card, pos=(_CARD_W/2 - 0.026, 0, SUB_Y),
                    sortOrder=2,
                )

        # Update pagination label
        total_pages = max(1, (len(builds) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        lbl = getattr(self, "_page_lbl", None)
        if lbl and not lbl.isEmpty():
            lbl["text"] = f"Page {page + 1}"

    def _browse_prev_page(self):
        if getattr(self, "_browse_page", 0) > 0:
            self._browse_page -= 1
            self._draw_game_grid()

    def _browse_next_page(self):
        builds = getattr(self, "_browse_all_builds", [])
        total  = max(1, (len(builds) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if getattr(self, "_browse_page", 0) < total - 1:
            self._browse_page += 1
            self._draw_game_grid()

    def _show_game_info_popup(self, build):
        self._close_game_info_popup()
        # Record visit when the popup opens — once per account, fire-and-forget
        _tok = getattr(self, "_session_token", "")
        _bid = build.get("id")
        if _tok and _bid:
            threading.Thread(
                target=lambda: auth_client.post_visit(_tok, _bid),
                daemon=True,
            ).start()
        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=60,
            state='normal',
        )
        self._game_popup = overlay

        tint = _THUMB_TINTS[build.get("id", 0) % len(_THUMB_TINTS)]
        HW, HH = 1.08, 0.64
        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-HW, HW, -HH, HH),
            parent=overlay, sortOrder=61,
        )
        # Close button
        DirectButton(
            text="X",
            text_fg=_RS_WHITE, text_scale=0.034,
            frameColor=_RS_RED,
            frameSize=(-0.038, 0.038, -0.038, 0.038),
            parent=card, pos=(HW - 0.056, 0, HH - 0.056),
            relief=1, command=self._close_game_info_popup,
        )

        # Left column — thumbnail + play buttons
        TH_W  = 0.94
        TH_H  = TH_W * 9 / 16   # ≈ 0.529
        TH_CX = -HW + TH_W / 2 + 0.08
        TH_CY = HH / 2 + 0.02
        thumb_frame = DirectFrame(
            frameColor=tint,
            frameSize=(-TH_W/2, TH_W/2, -TH_H/2, TH_H/2),
            parent=card, pos=(TH_CX, 0, TH_CY),
        )
        if build.get("thumbnail"):
            self._apply_thumbnail_texture(thumb_frame, build["thumbnail"])
        PLAY_Y = TH_CY - TH_H / 2 - 0.080
        DirectButton(
            text="Play",
            text_fg=_RS_WHITE, text_scale=0.040,
            frameColor=_RS_ORANGE,
            frameSize=(-TH_W/2, TH_W/2, -0.054, 0.054),
            parent=card, pos=(TH_CX, 0, PLAY_Y),
            relief=1,
            command=self._popup_play,
            extraArgs=[build["id"]],
        )

        # Right column — info
        RX = 0.16
        title = build["name"]
        if len(title) > 48:
            title = title[:46] + "…"
        DirectLabel(
            text=title,
            text_fg=_RS_WHITE, text_scale=0.036,
            text_align=TextNode.ALeft,
            text_wordwrap=25,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(RX, 0, HH - 0.12),
        )
        import datetime
        updated_str = datetime.datetime.fromtimestamp(
            build.get("updated_at", 0)).strftime("%b %d %Y")
        online  = build.get("online", 0)
        visits  = build.get("visits") or 0
        desc    = (build.get("description") or "").strip()
        info_rows = [
            ("Creator:", build.get("username", "?")),
            ("Updated:", updated_str),
            ("Visits:",  str(visits)),
            ("Players:", f"{online} online" if online else "Empty"),
        ]
        for i, (label, value) in enumerate(info_rows):
            y = HH - 0.32 - i * 0.12
            DirectLabel(
                text=label,
                text_fg=_RS_GRAY, text_scale=0.026,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX, 0, y),
            )
            DirectLabel(
                text=value,
                text_fg=_RS_WHITE, text_scale=0.028,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX + 0.22, 0, y),
            )
        if desc:
            desc_short = (desc[:250] + "…") if len(desc) > 250 else desc
            DirectLabel(
                text=desc_short,
                text_fg=_RS_GRAY, text_scale=0.024,
                text_align=TextNode.ALeft,
                text_wordwrap=38,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX, 0, HH - 0.32 - len(info_rows) * 0.12 - 0.06),
            )

    def _apply_thumbnail_texture(self, frame_np, b64_data):
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture
            raw = base64.b64decode(b64_data)
            # Load image entirely from RAM — no temp files, no disk races
            ss  = StringStream(raw)
            pnm = PNMImage()
            if not pnm.read(ss):
                print("[THUMB] PNMImage.read from StringStream failed", flush=True)
                return
            tex = Texture()
            tex.load(pnm)
            tex.setMinfilter(Texture.FTLinear)
            tex.setMagfilter(Texture.FTLinear)
            # Use DirectGUI's own image system — raw setTexture() is overridden
            # by the widget's internal render state and never shows through
            fs = frame_np["frameSize"]   # (l, r, b, t)
            hw = abs(fs[1])              # half-width
            hh = abs(fs[3])             # half-height
            frame_np["frameColor"]  = (1, 1, 1, 1)
            frame_np["image"]       = tex
            frame_np["image_scale"] = (hw, 1, hh)
        except Exception as e:
            print(f"[THUMB] load error: {e}", flush=True)

    def _close_game_info_popup(self):
        popup = getattr(self, "_game_popup", None)
        if popup:
            try:
                popup.destroy()
            except Exception:
                pass
        self._game_popup = None

    def _popup_play(self, build_id):
        self._close_game_info_popup()
        self._on_play_published(build_id)

    def _popup_play_solo(self, build_id):
        self._close_game_info_popup()
        if getattr(self, "_entering_play_mode", False):
            return
        self._entering_play_mode = True
        def worker():
            result, err = auth_client.get_published_build(build_id)
            if result and result.get("ok"):
                self.taskMgr.doMethodLater(
                    0, self._do_enter_play_mode_solo, "_enterPlayModeSolo",
                    extraArgs=[result["id"], result["name"], result["data"]],
                    appendTask=True,
                )
            else:
                self._entering_play_mode = False
        threading.Thread(target=worker, daemon=True).start()

    def _do_enter_play_mode_solo(self, build_id, name, data_str, task):
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._is_play_only     = True
        self._cloud_build_id   = None
        self._cloud_build_name = None
        self._show_studio_ui()
        for attr in ("exit_button", "insert_brick_button", "move_button",
                     "scale_button", "export_button", "import_button",
                     "cloud_save_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.hide()
        self.is_playtest = True
        self._panel.hide()
        self.character.show()
        try:
            self._load_bricks_from_data(json.loads(data_str))
        except Exception as e:
            print("Solo load error:", e)
        self.spawn_unstuck()
        self.cam_distance = 20
        self.cam_angle.set(0, 20)
        self.camLens.setFov(60)
        self.updateCamera()
        self._entering_play_mode = False
        return task.done

    def _on_play_published(self, build_id):
        if getattr(self, "_entering_play_mode", False):
            return
        self._entering_play_mode = True
        def worker():
            result, err = auth_client.get_published_build(build_id)
            if result and result.get("ok"):
                self.taskMgr.doMethodLater(
                    0, self._do_enter_play_mode, "_enterPlayMode",
                    extraArgs=[result["id"], result["name"], result["data"]],
                    appendTask=True,
                )
            else:
                print("Failed to load published build:", err)
                self._entering_play_mode = False
        threading.Thread(target=worker, daemon=True).start()

    def _do_enter_play_mode(self, build_id, name, data_str, task):
        self._enter_play_mode(build_id, name, data_str)
        return task.done

    def _enter_play_mode(self, build_id, name, data_str):
        """Load a published build and enter play-only mode (no editor)."""
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._is_play_only     = True
        self._cloud_build_id   = None
        self._cloud_build_name = None

        self._show_studio_ui()
        # Hide all editor controls — only the Menu button stays
        for attr in ("exit_button", "insert_brick_button", "move_button",
                     "scale_button", "export_button", "import_button",
                     "cloud_save_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.hide()

        self.is_playtest = True
        self._panel.hide()
        self.character.show()
        try:
            self._load_bricks_from_data(json.loads(data_str))
        except Exception as e:
            print("Play-mode load error:", e)
        self.spawn_unstuck()
        self.cam_distance = 20
        self.cam_angle.set(0, 20)
        self.camLens.setFov(60)
        self.updateCamera()
        self.start_multiplayer(build_id, self._session_token)

    # ── Return to menu ─────────────────────────────────────────────────────

    def _return_to_menu(self):
        """Called from the Menu button in the top bar."""
        popup = getattr(self, "_disconnect_popup", None)
        if popup:
            try:
                popup.destroy()
            except Exception:
                pass
            self._disconnect_popup = None
        self._entering_play_mode = False
        if getattr(self, 'is_first_person', False):
            self._exit_first_person()
        self.stop_multiplayer()
        for pid in list(getattr(self, "_remote_players", {}).keys()):
            self._remove_remote_player(pid)
        self._remote_players = {}
        self.character.hide()
        self.is_playtest   = False
        self._clear_all_bricks()
        self._is_play_only = False
        dlg = getattr(self, "_save_dialog", None)
        if dlg:
            try:
                dlg.destroy()
            except Exception:
                pass
            self._save_dialog = None
        self._hide_studio_ui()
        self._build_browse_screen()

    def _enter_studio(self):
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._cloud_build_id   = None
        self._cloud_build_name = None
        self._clear_all_bricks()
        self.create_baseplate()
        self._show_studio_ui()
        self.is_playtest = False
        if hasattr(self, "exit_button"):
            self.exit_button["text"] = "Play"
        if hasattr(self, "_panel"):
            self._panel.show()
        for attr in ("exit_button", "insert_brick_button", "move_button", "scale_button",
                     "export_button", "import_button", "cloud_save_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.show()
        self.camera.setPos(0, -30, 18)
        self.camera.lookAt(Point3(0, 0, 1))
        self.camLens.setFov(80)

    def _do_logout(self):
        token = self._session_token
        self._session_token    = None
        self._session_username = None
        self._delete_saved_token()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._build_login_ui()
        if token:
            threading.Thread(
                target=lambda: auth_client.logout(token), daemon=True,
            ).start()
