import atexit
import datetime
import json
import math
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
    Camera, PerspectiveLens,
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
_CARD_W     = 0.54
_CARD_TH    = 0.30   # thumbnail height portion
_CARD_INFO  = 0.14   # text area height below thumbnail
_CARD_H     = _CARD_TH + _CARD_INFO  # 0.44
_CARD_GAP_X = 0.04
_CARD_GAP_Y = 0.04
_PAGE_SIZE  = 15     # 5 cols × 3 rows

# ── Shop screen layout constants ───────────────────────────────────────────
_SHOP_COLS  = 6
_SHOP_CW    = 0.36   # card full width
_SHOP_CTH   = 0.36   # thumbnail height — must equal CW for square (no distortion)
_SHOP_CIH   = 0.09   # info strip height
_SHOP_CH    = 0.45   # total card height (CTH + CIH)
_SHOP_GAPX  = 0.026
_SHOP_GAPY  = 0.026
_SHOP_PAGE  = 18     # 6 × 3



class LoginScreenMixin:

    # ── Hat detection helpers ──────────────────────────────────────────────
    # Hats embed their 3-D data inside image_data using the "|HATDATA|" separator.
    # This works with the existing Render server — no schema changes required.

    @staticmethod
    def _item_is_hat(item):
        return "|HATDATA|" in (item.get("image_data") or "")

    @staticmethod
    def _item_is_shirt(item):
        return "|SHIRTDATA|" in (item.get("image_data") or "")

    @staticmethod
    def _item_is_pants(item):
        return "|PANTSDATA|" in (item.get("image_data") or "")

    @staticmethod
    def _item_is_face(item):
        return "|FACEDATA|" in (item.get("image_data") or "")

    @staticmethod
    def _item_shirt_b64(item):
        """Return the raw template base64, stripped of the |SHIRTDATA| marker."""
        img = item.get("image_data") or ""
        return img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img

    @staticmethod
    def _item_thumbnail(item):
        img = item.get("image_data") or ""
        if "|HATDATA|" in img:
            return img.split("|HATDATA|")[0]
        if "|SHIRTDATA|" in img:
            return img.split("|SHIRTDATA|")[0]
        if "|PANTSDATA|" in img:
            return img.split("|PANTSDATA|")[0]
        if "|FACEDATA|" in img:
            return img.split("|FACEDATA|")[0]
        return img

    @staticmethod
    def _item_hat_data_json(item):
        img = item.get("image_data") or ""
        if "|HATDATA|" not in img:
            return None
        import base64
        try:
            return base64.b64decode(img.split("|HATDATA|", 1)[1]).decode()
        except Exception:
            return None

    def setup_login_screen(self):
        self._session_token    = None
        self._session_username = None
        self._login_ui         = None
        self._main_menu_ui     = None
        self._login_status     = None
        self._server_proc      = None
        self._is_play_only     = False
        self._equipped_tshirt_id = None
        self._equipped_hat_id    = None
        self._equipped_face_id   = None

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
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
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
            equipped = (av_res or {}).get("equipped_tshirt")
            self._equipped_tshirt_id = int(equipped) if equipped is not None else None
            eq_hat = (av_res or {}).get("equipped_hat")
            self._equipped_hat_id = int(eq_hat) if eq_hat is not None else None
            eq_shirt = (av_res or {}).get("equipped_shirt")
            self._equipped_shirt_id = int(eq_shirt) if eq_shirt is not None else None
            print(f"[SHIRT_DBG] _sync_avatar: server equipped_shirt={eq_shirt} -> _equipped_shirt_id={self._equipped_shirt_id}", flush=True)
            eq_pants = (av_res or {}).get("equipped_pants")
            self._equipped_pants_id = int(eq_pants) if eq_pants is not None else None
            eq_face = (av_res or {}).get("equipped_face")
            self._equipped_face_id = int(eq_face) if eq_face is not None else None
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

    def _apply_equipped_items_bg(self):
        """Background-fetch equipped tshirt/hat/shirt/face data and apply them to the character."""
        import auth_client as _ac
        equipped_tshirt = getattr(self, '_equipped_tshirt_id', None)
        equipped_hat    = getattr(self, '_equipped_hat_id',    None)
        equipped_shirt  = getattr(self, '_equipped_shirt_id',  None)
        equipped_pants  = getattr(self, '_equipped_pants_id',  None)
        equipped_face   = getattr(self, '_equipped_face_id',   None)
        print(f"[SHIRT_DBG] _apply_equipped_items_bg: sh_id={equipped_shirt}", flush=True)
        def worker(ts_id=equipped_tshirt, hat_id=equipped_hat, sh_id=equipped_shirt, pt_id=equipped_pants, fc_id=equipped_face):
            print(f"[SHIRT_DBG] worker thread: sh_id={sh_id}", flush=True)
            if ts_id:
                full, _ = _ac.get_shop_item(ts_id)
                if full and full.get("image_data"):
                    b64 = full["image_data"]
                    def _apply_ts(task, _b64=b64):
                        if hasattr(self, "apply_tshirt"):
                            self.apply_tshirt(_b64)
                        return task.done
                    self.taskMgr.doMethodLater(0, _apply_ts, "_loginApplyTshirt", appendTask=True)
            if hat_id:
                full, _ = _ac.get_shop_item(hat_id)
                hd = self._item_hat_data_json(full) if full else None
                if hd:
                    def _apply_hat(task, _hd=hd):
                        if hasattr(self, "apply_hat"):
                            self.apply_hat(_hd)
                        return task.done
                    self.taskMgr.doMethodLater(0, _apply_hat, "_loginApplyHat", appendTask=True)
            if sh_id:
                full, _ = _ac.get_shop_item(sh_id)
                print(f"[SHIRT_DBG] get_shop_item({sh_id}): found={full is not None}, has_image={bool((full or {}).get('image_data'))}", flush=True)
                if full and full.get("image_data"):
                    img = full["image_data"]
                    b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                    def _apply_sh(task, _b=b64):
                        if hasattr(self, "apply_shirt"):
                            self.apply_shirt(_b)
                        return task.done
                    self.taskMgr.doMethodLater(0, _apply_sh, "_loginApplyShirt", appendTask=True)
            if pt_id:
                full, _ = _ac.get_shop_item(pt_id)
                if full and full.get("image_data"):
                    img = full["image_data"]
                    b64 = img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in img else img
                    def _apply_pt(task, _b=b64):
                        if hasattr(self, "apply_pants"):
                            self.apply_pants(_b)
                        return task.done
                    self.taskMgr.doMethodLater(0, _apply_pt, "_loginApplyPants", appendTask=True)
            if fc_id:
                full, _ = _ac.get_shop_item(fc_id)
                if full and full.get("image_data") and "|FACEDATA|" in full["image_data"]:
                    frames_part = full["image_data"].split("|FACEDATA|", 1)[1]
                    frames_b64  = [f for f in frames_part.split(",") if f]
                    def _apply_fc(task, _frames=frames_b64):
                        if hasattr(self, "apply_face"):
                            self.apply_face(_frames)
                        return task.done
                    self.taskMgr.doMethodLater(0, _apply_fc, "_loginApplyFace", appendTask=True)

        threading.Thread(target=worker, daemon=True).start()

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
        self._apply_equipped_items_bg()
        self._build_browse_screen()
        if hasattr(self, '_avatar_start_prefetch'):
            self._avatar_start_prefetch()
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
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
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
        self._apply_equipped_items_bg()
        if self._login_ui:
            self._login_ui.destroy()
            self._login_ui = None
        self._build_browse_screen()
        if hasattr(self, '_avatar_start_prefetch'):
            self._avatar_start_prefetch()
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
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
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
        self._music_fade_in()
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar (Build tab active) ─────────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.076, 0.090),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.075 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.038, 0.038),
                              parent=nav, pos=(-1.55, 0, 0.005))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        _nav_icons = ["games.png", "avatar.png", "shirt.png", "buildd.png", "Settings.png"]
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",    self._build_browse_screen),
            ("Avatar",   self._build_avatar_screen),
            ("Catalog",  self._build_shop_screen),
            ("Workshop", self._build_main_menu),
            ("Settings", self._build_settings_screen),
        ]):
            is_active = (i == 3)
            _btn = DirectButton(
                text="",
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.095, 0.095, -0.072, 0.075),
                parent=nav, pos=((i - 2) * 0.24, 0, 0.005),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
            _it = None
            try:
                _it = self.loader.loadTexture(Filename.fromOsSpecific(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), _nav_icons[i])))
            except Exception:
                pass
            if _it:
                _iw = 0.074 * (_it.getXSize() / max(_it.getYSize(), 1))
                _if2 = DirectFrame(
                    frameTexture=_it, frameColor=(1, 1, 1, 1),
                    frameSize=(-_iw/2, _iw/2, -0.034, 0.034),
                    parent=_btn, pos=(0, 0, 0.022),
                )
                _if2.setTransparency(TransparencyAttrib.MAlpha)
            DirectLabel(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.029,
                frameColor=(0, 0, 0, 0),
                parent=_btn, pos=(0, 0, -0.051),
            )
        _nav_av_tex = self._get_nav_avatar_texture()
        if _nav_av_tex:
            _nav_av_f = DirectFrame(
                frameTexture=_nav_av_tex, frameColor=(1, 1, 1, 1),
                frameSize=(-0.065, 0.065, -0.065, 0.065),
                parent=nav, pos=(1.15, 0, 0.005),
            )
            _nav_av_f.setTransparency(TransparencyAttrib.MAlpha)
            if not hasattr(self, '_nav_avatar_frames'):
                self._nav_avatar_frames = []
            self._nav_avatar_frames.append(_nav_av_f)
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.07, 0, -0.008),
            text_align=TextNode.ARight,
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, 0.005),
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
            parent=bg, pos=(1.55, 0, 0.688),
            command=self._show_upload_tshirt_dialog, relief=1,
        )
        DirectButton(
            text="Upload Shirt",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.130, 0.130, -0.030, 0.030),
            parent=bg, pos=(1.55, 0, 0.619),
            command=self._show_upload_shirt_dialog, relief=1,
        )
        DirectButton(
            text="Upload Pants",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.130, 0.130, -0.030, 0.030),
            parent=bg, pos=(1.55, 0, 0.550),
            command=self._show_upload_pants_dialog, relief=1,
        )
        if getattr(self, "_session_username", None) == "bob":
            DirectButton(
                text="Upload Face",
                text_fg=_RS_WHITE, text_scale=0.026,
                frameColor=_RS_BORDER,
                frameSize=(-0.130, 0.130, -0.030, 0.030),
                parent=bg, pos=(1.55, 0, 0.481),
                command=self._show_upload_face_dialog, relief=1,
            )
        # ── Build list ──────────────────────────────────────────────────────
        self._build_list_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-1.70, 1.70, -1.60, 0.66),
            parent=bg, pos=(0, 0, -0.16),
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

        self._shop_owned_ids    = getattr(self, "_shop_owned_ids", set())
        self._shop_item_popup   = None
        self._shop_cat_filter   = getattr(self, "_shop_cat_filter", "all")
        self._shop_search       = getattr(self, "_shop_search", "")

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar (Catalog tab active) ───────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.076, 0.090),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.075 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.038, 0.038),
                              parent=nav, pos=(-1.55, 0, 0.005))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        _nav_icons = ["games.png", "avatar.png", "shirt.png", "buildd.png", "Settings.png"]
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",    self._build_browse_screen),
            ("Avatar",   self._build_avatar_screen),
            ("Catalog",  self._build_shop_screen),
            ("Workshop", self._build_main_menu),
            ("Settings", self._build_settings_screen),
        ]):
            is_active = (i == 2)
            _btn = DirectButton(
                text="",
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.095, 0.095, -0.072, 0.075),
                parent=nav, pos=((i - 2) * 0.24, 0, 0.005),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
            _it = None
            try:
                _it = self.loader.loadTexture(Filename.fromOsSpecific(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), _nav_icons[i])))
            except Exception:
                pass
            if _it:
                _iw = 0.074 * (_it.getXSize() / max(_it.getYSize(), 1))
                _if2 = DirectFrame(
                    frameTexture=_it, frameColor=(1, 1, 1, 1),
                    frameSize=(-_iw/2, _iw/2, -0.034, 0.034),
                    parent=_btn, pos=(0, 0, 0.022),
                )
                _if2.setTransparency(TransparencyAttrib.MAlpha)
            DirectLabel(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.029,
                frameColor=(0, 0, 0, 0),
                parent=_btn, pos=(0, 0, -0.051),
            )
        _nav_av_tex = self._get_nav_avatar_texture()
        if _nav_av_tex:
            _nav_av_f = DirectFrame(
                frameTexture=_nav_av_tex, frameColor=(1, 1, 1, 1),
                frameSize=(-0.065, 0.065, -0.065, 0.065),
                parent=nav, pos=(1.15, 0, 0.005),
            )
            _nav_av_f.setTransparency(TransparencyAttrib.MAlpha)
            if not hasattr(self, '_nav_avatar_frames'):
                self._nav_avatar_frames = []
            self._nav_avatar_frames.append(_nav_av_f)
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.07, 0, -0.008),
            text_align=TextNode.ARight,
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, 0.005),
            relief=1, command=self._do_logout,
        )

        # ── RIGHT SIDEBAR (categories) ─────────────────────────────────
        _SB_BG  = (0.62, 0.58, 0.78, 1.0)
        _SEL_C  = (0.44, 0.32, 0.64, 1.0)
        _NORM_C = (0.55, 0.46, 0.72, 1.0)
        _TEXT_H = (0.12, 0.08, 0.28, 1.0)
        sidebar = DirectFrame(
            frameColor=_SB_BG,
            frameSize=(-0.27, 0.27, -0.87, 0.81),
            parent=bg, pos=(1.49, 0, -0.05),
        )
        _BTN_H = 0.25
        _GAP   = 0.015
        _CATS  = [
            ("All",      "all",    None),
            ("Hats",     "hat",    "hat.png"),
            ("Faces",    "face",   "face.png"),
            ("Shirts",   "shirt",  "shirt.png"),
            ("Pants",    "pants",  "pantss.png"),
            ("T-Shirts", "tshirt", "t shirt.png"),
        ]
        _n      = len(_CATS)
        _total  = _n * _BTN_H + (_n - 1) * _GAP
        _start_z = (-0.87 + 0.81) / 2 + _total / 2 - _BTN_H / 2
        cur_cat = getattr(self, "_shop_cat_filter", "all")
        self._shop_sidebar_buttons = {}
        for _i, (_lbl, _val, _ico) in enumerate(_CATS):
            _bz     = _start_z - _i * (_BTN_H + _GAP)
            _is_sel = (_val == cur_cat)
            _has_ico = (_ico is not None)
            def _make_cmd(_v=_val):
                def _cmd():
                    self._shop_cat_filter = _v
                    self._build_shop_screen()
                return _cmd
            _btn = DirectButton(
                text="",
                frameColor=_SEL_C if _is_sel else _NORM_C,
                frameSize=(-0.27, 0.27, -_BTN_H / 2, _BTN_H / 2),
                parent=sidebar, pos=(0, 0, _bz),
                relief=1, command=_make_cmd(),
            )
            self._shop_sidebar_buttons[_val] = _btn
            if _has_ico:
                _ip = os.path.join(os.path.dirname(os.path.abspath(__file__)), _ico)
                if os.path.exists(_ip):
                    _it = self.loader.loadTexture(Filename.fromOsSpecific(_ip))
                    if _it:
                        _ih = 0.11
                        _iw = min(_ih * (_it.getXSize() / max(_it.getYSize(), 1)), 0.22)
                        _if = DirectFrame(
                            frameTexture=_it, frameColor=(1, 1, 1, 1),
                            frameSize=(-_iw / 2, _iw / 2, -_ih / 2, _ih / 2),
                            parent=_btn, pos=(0, 0, 0.038),
                        )
                        _if.setTransparency(TransparencyAttrib.MAlpha)
            DirectLabel(
                text=_lbl, text_fg=_TEXT_H, text_scale=0.036,
                frameColor=(0, 0, 0, 0),
                parent=_btn, pos=(0, 0, -0.072 if _has_ico else 0.0),
            )

        # ── CONTENT PANEL (search + grid + pagination) ─────────────────
        _PANEL_BG  = (0.68, 0.65, 0.82, 1.0)
        _PANEL_DIV = (0.50, 0.40, 0.68, 1.0)
        _TEXT_M    = (0.22, 0.15, 0.40, 1.0)
        content = DirectFrame(
            frameColor=_PANEL_BG,
            frameSize=(-1.33, 1.33, -0.87, 0.81),
            parent=bg, pos=(-0.35, 0, -0.05),
        )

        # Search bar
        _search_hints = {"hat": "Hats", "face": "Faces", "shirt": "Shirts",
                         "pants": "Pants", "tshirt": "T-Shirts"}
        _ph = f"Search for {_search_hints[cur_cat]}..." if cur_cat in _search_hints else "Search..."
        _sse = DirectEntry(
            text="", initialText=self._shop_search or _ph,
            width=42, numLines=1, scale=0.026,
            text_fg=(0.15, 0.10, 0.25, 1),
            frameColor=(0.93, 0.91, 0.97, 1),
            relief=1,
            parent=content, pos=(-1.20, 0, 0.72),
            command=self._on_shop_search,
            focusInCommand=lambda e=None: _sse.enterText("") if _sse.get() == _ph else None,
            focusOutCommand=lambda e=None: _sse.enterText(_ph) if not _sse.get().strip() else None,
        )
        self._shop_search_entry = _sse

        # Grid container
        self._shop_grid_parent = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-1.33, 1.33, -0.87, 0.64),
            parent=content,
        )
        self._shop_loading_lbl = DirectLabel(
            text="Loading...",
            text_fg=_TEXT_M, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._shop_grid_parent, pos=(0, 0, 0.10),
        )

        # Pagination
        self._shop_page = 0
        _DIM = (0.40, 0.35, 0.52, 1.0)
        self._shop_prev_btn = DirectButton(
            text="<",
            text_fg=_TEXT_H, text_scale=0.038,
            frameColor=_PANEL_DIV,
            frameSize=(-0.090, 0.090, -0.038, 0.038),
            parent=content, pos=(-0.30, 0, -0.820),
            relief=1, command=self._shop_goto_page, extraArgs=[-1],
        )
        self._shop_page_lbl = DirectLabel(
            text="Page 1/1",
            text_fg=_TEXT_H, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=content, pos=(0, 0, -0.820),
        )
        self._shop_next_btn = DirectButton(
            text=">",
            text_fg=_TEXT_H, text_scale=0.038,
            frameColor=_PANEL_DIV,
            frameSize=(-0.090, 0.090, -0.038, 0.038),
            parent=content, pos=(0.30, 0, -0.820),
            relief=1, command=self._shop_goto_page, extraArgs=[+1],
        )

        threading.Thread(target=self._fetch_shop_items_thread, daemon=True).start()

    def _fetch_shop_items_thread(self):
        catalog_cache = getattr(self, '_shop_items_full_cache', None)
        if catalog_cache is not None:
            all_items = catalog_cache
            items_err = None
        else:
            items_result, items_err = auth_client.list_shop_items()
            all_items = (items_result or {}).get("items", [])
            self._shop_items_full_cache = all_items
        cat = getattr(self, "_shop_cat_filter", "all")
        if cat == "all":
            items = all_items
        elif cat == "hat":
            items = [it for it in all_items if self._item_is_hat(it)]
        elif cat == "shirt":
            items = [it for it in all_items if self._item_is_shirt(it)]
        elif cat == "pants":
            items = [it for it in all_items if self._item_is_pants(it)]
        elif cat == "face":
            items = [it for it in all_items if self._item_is_face(it)]
        else:
            items = [it for it in all_items if not self._item_is_hat(it)
                     and not self._item_is_shirt(it)
                     and not self._item_is_pants(it)
                     and not self._item_is_face(it)]
        owned_cache = getattr(self, '_avatar_items_full_cache', None)
        if owned_cache is not None:
            owned = {it["id"] for it in owned_cache}
        else:
            owned_result, _ = auth_client.get_owned_items(self._session_token)
            owned = {it["id"] for it in (owned_result or {}).get("items", [])}
        self.taskMgr.doMethodLater(
            0, self._draw_shop_grid_task, "_drawShopGrid",
            extraArgs=[items, items_err, owned], appendTask=True,
        )

    def _get_nav_avatar_texture(self):
        """Set up a persistent live RTT rig for the topbar avatar (head+torso portrait).
        Uses the same approach as the avatar preview tab: a live buffer that renders every frame,
        so clothing appears automatically when applied. Returns buf.getTexture() (live, cached).
        PMASK bit(7) keeps the nav rig invisible to the main camera."""
        cached = getattr(self, '_nav_avatar_tex', 'UNSET')
        if cached != 'UNSET':
            return cached
        self._nav_avatar_tex = None
        try:
            _DEF = {
                "head":      (244/255, 204/255,  67/255, 1),
                "torso":     ( 23/255, 107/255, 170/255, 1),
                "left_arm":  (244/255, 204/255,  67/255, 1),
                "right_arm": (244/255, 204/255,  67/255, 1),
            }
            colors = self.load_avatar_colors()
            PMASK  = BitMask32.bit(7)

            # Rig parked at y=5000 (avatar preview=2000, shop thumbs=3000)
            root = self.render.attachNewNode("nav_av_root")
            root.setPos(0, 5000, 0)
            self._nav_av_root            = root
            self._nav_av_pmask           = PMASK
            self._nav_av_tshirt_anchor   = None
            self._nav_av_tshirt_np       = None
            self._nav_av_hat_model       = None
            self._nav_av_shirt_nodes     = []

            def _box(parent, sc, pos, key):
                m = self.loader.loadModel("models/box")
                m.reparentTo(parent); m.setScale(*sc); m.setPos(*pos)
                m.setColor(*colors.get(key, _DEF[key]))
                m.setTextureOff(1); m.show(PMASK)
                return m

            self._nav_av_torso_box = _box(root, (2, 1, 2), (-1, -0.5, 2), "torso")
            _la = root.attachNewNode("nav_av_la"); _la.setPos(-1.5, 0, 4)
            self._nav_av_la_box = _box(_la, (1, 1, 2), (-0.5, -0.5, -2), "left_arm")
            _ra = root.attachNewNode("nav_av_ra"); _ra.setPos(1.5, 0, 4)
            self._nav_av_ra_box = _box(_ra, (1, 1, 2), (-0.5, -0.5, -2), "right_arm")
            self._nav_av_la_piv = _la
            self._nav_av_ra_piv = _ra

            _hd = self.create_cylinder(radius=0.7, height=1.1, segments=16)
            _hd.reparentTo(root); _hd.setColor(*colors.get("head", _DEF["head"]))
            _hd.setTwoSided(True); _hd.setTextureOff(1); _hd.setPos(0, 0, 4.55)
            _hd.show(PMASK)
            self._nav_av_head_node = _hd

            # Face sprite on -Y side of head (toward camera at -Y), same as _build_preview_rig
            _face_textures = getattr(self, '_face_textures', [])
            self._nav_av_face_sprite  = None
            self._nav_av_face_anchor  = None
            if _face_textures:
                from panda3d.core import CardMaker
                _fcm = CardMaker('nav_av_face'); _fcm.setFrame(-0.70, 0.70, -0.55, 0.55)
                _fa = root.attachNewNode("nav_av_face_anchor"); _fa.setPos(0, -0.72, 4.55)
                _fnp = _fa.attachNewNode(_fcm.generate())
                _fnp.setTransparency(TransparencyAttrib.MAlpha)
                _fnp.setTwoSided(False); _fnp.setLightOff(); _fnp.setShaderOff()
                _fnp.setDepthWrite(False); _fnp.setTexture(_face_textures[0])
                _fnp.show(PMASK)
                self._nav_av_face_sprite = _fnp
                self._nav_av_face_anchor = _fa

            # Lighting — same as avatar preview tab
            _al = AmbientLight("nav_av_al"); _al.setColor(LColor(0.22, 0.22, 0.25, 1))
            root.setLight(root.attachNewNode(_al))
            _dl = DirectionalLight("nav_av_dl"); _dl.setColor(LColor(0.50, 0.50, 0.52, 1))
            _dlnp = root.attachNewNode(_dl); _dlnp.setHpr(20, 15, 0)
            root.setLight(_dlnp)

            # Persistent 128×128 live buffer — texture updates every frame automatically
            _buf = self.win.makeTextureBuffer("nav_av_buf", 256, 256)
            _buf.setClearColor(LColor(0.55, 0.45, 0.76, 1.0))
            _buf.setClearColorActive(True)
            self._nav_av_buf = _buf

            # Camera: dist=9.5 at -Y, look at z=4.85 → frame z≈2.3–7.4 (more crown visible)
            _cn = Camera("nav_av_cam")
            _ln = PerspectiveLens(); _ln.setFov(30.0); _ln.setAspectRatio(1.0)
            _ln.setNearFar(0.1, 1000); _cn.setLens(_ln); _cn.setCameraMask(PMASK)
            _cnp = self.render.attachNewNode(_cn)
            _cnp.setPos(0, 5000 - 9.5, 4.85); _cnp.lookAt(Point3(0, 5000, 4.85))
            _dr = _buf.makeDisplayRegion(0, 1, 0, 1); _dr.setSort(10); _dr.setCamera(_cnp)
            self._nav_av_cam_np = _cnp

            # Remove PMASK bit from main camera so it never sees the nav rig
            self.camNode.setCameraMask(self.camNode.getCameraMask() & ~PMASK)

            self._nav_avatar_tex = _buf.getTexture()
        except Exception as _e:
            print(f"[NAV_AVATAR] setup failed: {_e}", flush=True)
        return self._nav_avatar_tex

    def _nav_av_apply_tshirt(self, image_b64):
        """Apply tshirt to the nav avatar rig (mirrors _preview_apply_tshirt)."""
        from panda3d.core import CardMaker, TransparencyAttrib, Filename
        for attr in ('_nav_av_tshirt_anchor', '_nav_av_tshirt_np'):
            n = getattr(self, attr, None)
            if n and not n.isEmpty(): n.removeNode()
            setattr(self, attr, None)
        root  = getattr(self, '_nav_av_root',  None)
        pmask = getattr(self, '_nav_av_pmask', None)
        if not root or root.isEmpty() or not image_b64:
            return
        try:
            import base64, tempfile, os as _os2
            raw = base64.b64decode(image_b64)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                tf.write(raw); tmp = tf.name
            tex = self.loader.loadTexture(Filename.fromOsSpecific(tmp))
            _os2.unlink(tmp)
            if not tex: return
            cm = CardMaker('nav_av_tshirt'); cm.setFrame(-1, 1, 0, 2)
            anchor = root.attachNewNode("nav_av_tshirt_anchor")
            anchor.setPos(0, -0.51, 2)
            np_ = anchor.attachNewNode(cm.generate())
            np_.setTexture(tex)
            np_.setTransparency(TransparencyAttrib.MAlpha)
            np_.setLightOff(); np_.setShaderOff()
            np_.setDepthWrite(False); np_.setDepthOffset(3)
            np_.show(pmask)
            self._nav_av_tshirt_anchor = anchor
            self._nav_av_tshirt_np     = np_
        except Exception as e:
            print(f"[NAV_AV_TSHIRT] {e}", flush=True)

    def _nav_av_apply_hat(self, hat_data_json):
        """Apply hat to the nav avatar rig (mirrors _preview_apply_hat)."""
        n = getattr(self, '_nav_av_hat_model', None)
        if n and not n.isEmpty(): n.removeNode()
        self._nav_av_hat_model = None
        root  = getattr(self, '_nav_av_root',  None)
        pmask = getattr(self, '_nav_av_pmask', None)
        if not root or root.isEmpty() or not hat_data_json: return
        import json as _json, base64, tempfile, os as _os2, shutil
        from panda3d.core import Filename
        tmp_dir = None
        try:
            data = _json.loads(hat_data_json)
            tmp_dir = tempfile.mkdtemp(prefix="phx_navhat_")
            obj_tmp = _os2.path.join(tmp_dir, "hat.obj")
            with open(obj_tmp, 'wb') as f:
                f.write(base64.b64decode(data["obj_b64"]))
            mtl_b64  = data.get("mtl_b64")
            mtl_name = data.get("mtl_name") or "hat.mtl"
            if mtl_b64:
                with open(_os2.path.join(tmp_dir, mtl_name), 'wb') as f:
                    f.write(base64.b64decode(mtl_b64))
            hat_model = self.loader.loadModel(Filename.fromOsSpecific(obj_tmp))
            shutil.rmtree(tmp_dir, ignore_errors=True); tmp_dir = None
            if not hat_model: return
            hat_model.setR(-90)
            tex_b64 = data.get("texture_b64")
            if tex_b64:
                from panda3d.core import PNMImage, StringStream, Texture
                raw = base64.b64decode(tex_b64); ss = StringStream(raw); pnm = PNMImage()
                if pnm.read(ss):
                    tex = Texture(); tex.load(pnm); hat_model.setTexture(tex, 1)
            bs = data.get("brick_scale", [2, 2, 2]); ms = data.get("model_scale", [1, 1, 1])
            hat_model.reparentTo(root)
            hat_model.setScale(*[bs[i]*ms[i] for i in range(3)])
            h0, p0, r0 = data.get("model_hpr", [0, 0, -90])
            hat_model.setHpr(h0 + 180, p0, r0)
            hat_model.setPos(float(data.get("x_offset", 0.0)), float(data.get("y_offset", 0.0)), 4.55 + 0.55 + float(data.get("z_offset", 0.0)))
            hat_model.setShaderOff(); hat_model.setTwoSided(True); hat_model.show(pmask)
            self._nav_av_hat_model = hat_model
        except Exception as e:
            print(f"[NAV_AV_HAT] {e}", flush=True)
        finally:
            if tmp_dir: shutil.rmtree(tmp_dir, ignore_errors=True)

    def _nav_av_apply_shirt(self, image_b64):
        """Apply shirt to the nav avatar rig (mirrors _preview_apply_shirt)."""
        for n in getattr(self, '_nav_av_shirt_nodes', []):
            if n and not n.isEmpty(): n.removeNode()
        self._nav_av_shirt_nodes = []
        root   = getattr(self, '_nav_av_root',   None)
        pmask  = getattr(self, '_nav_av_pmask',  None)
        la_piv = getattr(self, '_nav_av_la_piv', None)
        ra_piv = getattr(self, '_nav_av_ra_piv', None)
        if not root or root.isEmpty() or not image_b64: return
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib
            from character import CharacterMixin
            raw = base64.b64decode(image_b64); ss = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss): return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            R = CharacterMixin._SHIRT_REGIONS

            def attach(parent, reg_map, w, d, h, pos):
                if parent is None or parent.isEmpty(): return None
                node = CharacterMixin._make_shirt_box_geom(w, d, h, reg_map)
                np_ = parent.attachNewNode(node)
                np_.setPos(*pos); np_.setTexture(tex)
                np_.setTwoSided(True); np_.setShaderOff()
                np_.setDepthOffset(2); np_.setTransparency(TransparencyAttrib.MAlpha)
                if pmask: np_.show(pmask)
                return np_

            # Camera at -Y → swap front↔back and left↔right (same as _preview_apply_shirt)
            nodes = [n for n in [
                attach(root, {
                    'front': R['torso_back'],  'back':  R['torso_front'],
                    'left':  R['torso_right'], 'right': R['torso_left'],
                    'top':   R['torso_up'],    'bottom':R['torso_down'],
                }, 2, 1, 2, (-1, -0.5, 2)),
                attach(ra_piv, {
                    'front': R['rarm_back'],  'back':  R['rarm_front'],
                    'left':  R['rarm_right'], 'right': R['rarm_left'],
                    'top':   R['rarm_up'],    'bottom':R['rarm_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
                attach(la_piv, {
                    'front': R['larm_back'],  'back':  R['larm_front'],
                    'left':  R['larm_right'], 'right': R['larm_left'],
                    'top':   R['larm_up'],    'bottom':R['larm_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
            ] if n is not None]
            self._nav_av_shirt_nodes = nodes
        except Exception as e:
            print(f"[NAV_AV_SHIRT] {e}", flush=True)

    def _nav_av_apply_face(self, frames_b64):
        """Update the nav avatar face sprite with a custom face texture (frame 0)."""
        root  = getattr(self, '_nav_av_root',  None)
        pmask = getattr(self, '_nav_av_pmask', None)
        if not root or root.isEmpty() or not frames_b64: return
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, CardMaker
            raw = base64.b64decode(frames_b64[0])
            ss  = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss): return
            tex = Texture(); tex.load(pnm)
            sprite = getattr(self, '_nav_av_face_sprite', None)
            if sprite and not sprite.isEmpty():
                sprite.setTexture(tex)
            else:
                # Face sprite didn't exist at rig build time — create it now
                _fcm = CardMaker('nav_av_face'); _fcm.setFrame(-0.70, 0.70, -0.55, 0.55)
                _fa = root.attachNewNode("nav_av_face_anchor"); _fa.setPos(0, -0.72, 4.55)
                _fnp = _fa.attachNewNode(_fcm.generate())
                _fnp.setTransparency(TransparencyAttrib.MAlpha)
                _fnp.setTwoSided(False); _fnp.setLightOff(); _fnp.setShaderOff()
                _fnp.setDepthWrite(False); _fnp.setTexture(tex)
                _fnp.show(pmask)
                self._nav_av_face_sprite = _fnp
                self._nav_av_face_anchor = _fa
        except Exception as e:
            print(f"[NAV_AV_FACE] {e}", flush=True)

    def _nav_av_cleanup(self):
        """Destroy the nav avatar rig and buffer (call on logout or session end)."""
        buf = getattr(self, '_nav_av_buf', None)
        if buf:
            try: self.graphicsEngine.removeWindow(buf)
            except Exception: pass
        self._nav_av_buf = None
        for attr in ('_nav_av_cam_np', '_nav_av_tshirt_anchor', '_nav_av_tshirt_np',
                     '_nav_av_hat_model', '_nav_av_face_anchor', '_nav_av_root'):
            n = getattr(self, attr, None)
            if n:
                try:
                    if not n.isEmpty(): n.removeNode()
                except Exception: pass
            setattr(self, attr, None)
        for n in getattr(self, '_nav_av_shirt_nodes', []):
            try:
                if n and not n.isEmpty(): n.removeNode()
            except Exception: pass
        self._nav_av_shirt_nodes = []
        self._nav_av_face_sprite = None
        self._nav_avatar_tex     = 'UNSET'
        try:
            PMASK = BitMask32.bit(7)
            self.camNode.setCameraMask(self.camNode.getCameraMask() | PMASK)
        except Exception: pass

    def _nav_av_update_colors(self):
        """Sync nav avatar rig body/head colors with the current avatar colors."""
        colors = self.load_avatar_colors()
        _DEF = {
            "head":      (244/255, 204/255,  67/255, 1),
            "torso":     ( 23/255, 107/255, 170/255, 1),
            "left_arm":  (244/255, 204/255,  67/255, 1),
            "right_arm": (244/255, 204/255,  67/255, 1),
        }
        for attr, key in [
            ('_nav_av_torso_box', 'torso'),
            ('_nav_av_la_box',    'left_arm'),
            ('_nav_av_ra_box',    'right_arm'),
            ('_nav_av_head_node', 'head'),
        ]:
            n = getattr(self, attr, None)
            if n and not n.isEmpty():
                n.setColor(*colors.get(key, _DEF[key]))

    def _render_shop_thumbnails(self, items, buf_w=300, buf_h=173):
        """RTT-render one avatar+tshirt/shirt frame per item; returns {item_id: Texture}."""
        items_with_img = []
        for it in items:
            img = it.get("image_data", "")
            if not img:
                continue
            if "|SHIRTDATA|" in img:
                b64 = img.split("|SHIRTDATA|")[0]
                items_with_img.append((it["id"], b64, "shirt"))
            elif "|PANTSDATA|" in img:
                b64 = img.split("|PANTSDATA|")[0]
                items_with_img.append((it["id"], b64, "pants"))
            else:
                items_with_img.append((it["id"], img, "tshirt"))
        if not items_with_img:
            return {}

        result = {}
        PMASK  = BitMask32.bit(6)
        BUF_W, BUF_H = buf_w, buf_h

        _DEFAULTS = {
            "head":      (244/255, 204/255,  67/255, 1),
            "torso":     ( 23/255, 107/255, 170/255, 1),
            "left_arm":  (244/255, 204/255,  67/255, 1),
            "right_arm": (244/255, 204/255,  67/255, 1),
            "left_leg":  (165/255, 188/255,  80/255, 1),
            "right_leg": (165/255, 188/255,  80/255, 1),
        }
        # Fixed neutral grey for all shop thumbnails so they look the same
        # for every player and the clothing is the focus, not skin colour.
        _GREY  = (0.72, 0.72, 0.72, 1)
        colors = {k: _GREY for k in ("head","torso","left_arm","right_arm","left_leg","right_leg")}

        # ── Avatar rig parked far from the game world ──────────────────────────
        rig = self.render.attachNewNode("shop_thumb_root")
        rig.setPos(0, 3000, 0)

        def box(parent, scale, pos, key):
            m = self.loader.loadModel("models/box")
            m.reparentTo(parent)
            m.setScale(*scale)
            m.setPos(*pos)
            m.setColor(*colors.get(key, _DEFAULTS[key]))
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
        head.setColor(*colors.get("head", _DEFAULTS["head"]))
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

        _cam_dist = 12
        _h_fov    = 32.0
        _aspect   = BUF_W / BUF_H
        _cam_x    = 0.0
        _cam_z    = 3.3

        _camNode = Camera("shop_thumb_cam")
        _lens = PerspectiveLens()
        _lens.setFov(_h_fov)
        _lens.setAspectRatio(_aspect)
        _lens.setNearFar(0.1, 10000)
        _camNode.setLens(_lens)
        _camNode.setCameraMask(PMASK)
        cam_np = self.render.attachNewNode(_camNode)
        cam_np.setPos(_cam_x, 3000 - _cam_dist, _cam_z)
        cam_np.lookAt(Point3(_cam_x, 3000, _cam_z))
        _dr = buf.makeDisplayRegion(0, 1, 0, 1)
        _dr.setSort(10)
        _dr.setCamera(cam_np)

        orig_mask = self.camNode.getCameraMask()
        self.camNode.setCameraMask(orig_mask & ~PMASK)

        # Pre-warm: one blank render so the buffer/texture is fully initialised.
        self.graphicsEngine.renderFrame()

        # ── Render each item ───────────────────────────────────────────────────
        shirt_nodes = []
        R = self._SHIRT_REGIONS

        def _swap_shirt(image_b64):
            nonlocal shirt_nodes
            for n in shirt_nodes:
                if n and not n.isEmpty(): n.removeNode()
            shirt_nodes = []
            import base64 as _sb64
            raw = _sb64.b64decode(image_b64)
            ss = StringStream(raw); pnm2 = PNMImage()
            if not pnm2.read(ss): return
            tex2 = Texture(); tex2.load(pnm2)
            tex2.setMagfilter(Texture.FTLinear); tex2.setMinfilter(Texture.FTLinear)
            def sa(parent, reg_map, w, d, h, pos):
                node = self._make_shirt_box_geom(w, d, h, reg_map)
                np2 = parent.attachNewNode(node)
                np2.setPos(*pos); np2.setTexture(tex2)
                np2.setTwoSided(True); np2.setShaderOff()
                np2.setDepthOffset(1); np2.setTransparency(TransparencyAttrib.MAlpha)
                np2.show(PMASK); return np2
            # Thumbnail camera looks from -Y so front/back are flipped vs in-game camera (+Y)
            shirt_nodes.append(sa(rig,{'front':R['torso_back'],'back':R['torso_front'],
                'left':R['torso_right'],'right':R['torso_left'],
                'top':R['torso_up'],'bottom':R['torso_down']},2,1,2,(-1,-0.5,2)))
            shirt_nodes.append(sa(ra,{'front':R['rarm_back'],'back':R['rarm_front'],
                'left':R['rarm_right'],'right':R['rarm_left'],
                'top':R['rarm_up'],'bottom':R['rarm_down']},1,1,2,(-0.5,-0.5,-2)))
            shirt_nodes.append(sa(la,{'front':R['larm_back'],'back':R['larm_front'],
                'left':R['larm_right'],'right':R['larm_left'],
                'top':R['larm_up'],'bottom':R['larm_down']},1,1,2,(-0.5,-0.5,-2)))

        pants_nodes = []
        PR = self._PANTS_REGIONS

        def _swap_pants(image_b64):
            nonlocal pants_nodes
            for n in pants_nodes:
                if n and not n.isEmpty(): n.removeNode()
            pants_nodes = []
            import base64 as _pb64
            raw = _pb64.b64decode(image_b64)
            ss = StringStream(raw); pnm2 = PNMImage()
            if not pnm2.read(ss): return
            tex2 = Texture(); tex2.load(pnm2)
            tex2.setMagfilter(Texture.FTLinear); tex2.setMinfilter(Texture.FTLinear)
            def pa(parent, reg_map, w, d, h, pos):
                node = self._make_shirt_box_geom(w, d, h, reg_map,
                    template_w=self._PANTS_TEMPLATE_W, template_h=self._PANTS_TEMPLATE_H)
                np2 = parent.attachNewNode(node)
                np2.setPos(*pos); np2.setTexture(tex2)
                np2.setTwoSided(True); np2.setShaderOff()
                np2.setDepthOffset(1); np2.setTransparency(TransparencyAttrib.MAlpha)
                np2.show(PMASK); return np2
            # Thumbnail camera at -Y: swap front/back and left/right
            pants_nodes.append(pa(rig,{'front':PR['torso_back'],'back':PR['torso_front'],
                'left':PR['torso_right'],'right':PR['torso_left'],
                'top':PR['torso_up'],'bottom':PR['torso_down']},2,1,2,(-1,-0.5,2)))
            pants_nodes.append(pa(rl,{'front':PR['rleg_back'],'back':PR['rleg_front'],
                'left':PR['rleg_right'],'right':PR['rleg_left'],
                'top':PR['rleg_up'],'bottom':PR['rleg_down']},1,1,2,(-0.5,-0.5,-2)))
            pants_nodes.append(pa(ll,{'front':PR['lleg_back'],'back':PR['lleg_front'],
                'left':PR['lleg_right'],'right':PR['lleg_left'],
                'top':PR['lleg_up'],'bottom':PR['lleg_down']},1,1,2,(-0.5,-0.5,-2)))

        for item_id, image_b64, kind in items_with_img:
            if kind == "shirt":
                _swap_shirt(image_b64)
            elif kind == "pants":
                _swap_pants(image_b64)
            else:
                _swap_tshirt(image_b64)
            self.graphicsEngine.renderFrame()
            # extractTextureData forces GPU→CPU readback so store() succeeds.
            rtex = buf.getTexture()
            self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
            pnm = PNMImage()
            if rtex.store(pnm):
                out_tex = Texture()
                out_tex.load(pnm)
                out_tex.setMagfilter(Texture.FTLinear)
                out_tex.setMinfilter(Texture.FTLinearMipmapLinear)
                result[item_id] = out_tex
            else:
                print(f"[SHOP_THUMB] store failed for item {item_id}", flush=True)

        # ── Cleanup ────────────────────────────────────────────────────────────
        if tshirt_anchor[0] and not tshirt_anchor[0].isEmpty():
            tshirt_anchor[0].removeNode()
        for n in shirt_nodes:
            if n and not n.isEmpty(): n.removeNode()
        for n in pants_nodes:
            if n and not n.isEmpty(): n.removeNode()
        self.graphicsEngine.removeWindow(buf)
        cam_np.removeNode()
        rig.removeNode()
        self.camNode.setCameraMask(orig_mask)

        return result

    def _render_hat_thumbnails(self, items, buf_w=512, buf_h=512):
        """RTT-render each hat model alone — no mannequin, close-up framing."""
        import json as _json, base64 as _b64, tempfile, os as _os, shutil

        items_with_data = []
        for it in items:
            hd_json = self._item_hat_data_json(it)
            if hd_json:
                items_with_data.append((it["id"], hd_json))
        if not items_with_data:
            return {}

        result = {}
        PMASK  = BitMask32.bit(6)
        BUF_W, BUF_H = buf_w, buf_h

        # Minimal scene — just the hat, no avatar body parts.
        rig = self.render.attachNewNode("hat_thumb_root")
        rig.setPos(0, 3000, 0)
        hat_anchor = rig.attachNewNode("hat_anchor")
        hat_anchor.setPos(0, 0, 0)

        al = AmbientLight("ht_al"); al.setColor(LColor(0.30, 0.30, 0.32, 1))
        rig.setLight(rig.attachNewNode(al))
        dl = DirectionalLight("ht_dl"); dl.setColor(LColor(0.70, 0.70, 0.72, 1))
        dlnp = rig.attachNewNode(dl); dlnp.setHpr(25, -30, 0)
        rig.setLight(dlnp)

        buf = self.win.makeTextureBuffer("hat_thumb_buf", BUF_W, BUF_H)
        buf.setClearColor(LColor(0.78, 0.75, 0.88, 1.0))
        buf.setClearColorActive(True)

        _aspect = BUF_W / BUF_H
        camNode = Camera("hat_thumb_cam")
        lens = PerspectiveLens()
        # Close-up: camera 5 units in front of the hat anchor, centred on it.
        lens.setFov(42.0); lens.setAspectRatio(_aspect); lens.setNearFar(0.1, 10000)
        camNode.setLens(lens); camNode.setCameraMask(PMASK)
        cam_np = self.render.attachNewNode(camNode)
        cam_np.setPos(0, 3000 - 5, 0)
        cam_np.lookAt(Point3(0, 3000, 1.2))
        dr = buf.makeDisplayRegion(0, 1, 0, 1); dr.setSort(10); dr.setCamera(cam_np)

        orig_mask = self.camNode.getCameraMask()
        self.camNode.setCameraMask(orig_mask & ~PMASK)
        self.graphicsEngine.renderFrame()

        hat_node = [None]

        def _load_hat(hd_json):
            if hat_node[0] and not hat_node[0].isEmpty():
                hat_node[0].removeNode(); hat_node[0] = None
            try:
                data = _json.loads(hd_json)
                tmp_dir = tempfile.mkdtemp(prefix="phx_hat_th_")
                obj_tmp = _os.path.join(tmp_dir, "hat.obj")
                with open(obj_tmp, 'wb') as f:
                    f.write(_b64.b64decode(data["obj_b64"]))
                mtl_b64 = data.get("mtl_b64")
                if mtl_b64:
                    mtl_name = data.get("mtl_name") or "hat.mtl"
                    with open(_os.path.join(tmp_dir, mtl_name), 'wb') as f:
                        f.write(_b64.b64decode(mtl_b64))
                model = self.loader.loadModel(Filename.fromOsSpecific(obj_tmp))
                shutil.rmtree(tmp_dir, ignore_errors=True)
                if not model:
                    return
                model.setR(-90)
                tex_b64 = data.get("texture_b64")
                if tex_b64:
                    raw = _b64.b64decode(tex_b64); ss = StringStream(raw); pnm = PNMImage()
                    if pnm.read(ss):
                        tex = Texture(); tex.load(pnm); model.setTexture(tex, 1)
                bs = data.get("brick_scale", [2, 2, 2])
                ms = data.get("model_scale", [1, 1, 1])
                model.setScale(*[bs[i] * ms[i] for i in range(3)])
                model.setHpr(*data.get("model_hpr", [0, 0, -90]))
                model.setShaderOff(); model.setTwoSided(True)
                model.reparentTo(hat_anchor)
                # Centre hat at the anchor; z_offset shifts vertically if needed.
                model.setPos(0, 0, float(data.get("z_offset", 0.0)))
                model.show(PMASK)
                hat_node[0] = model
            except Exception as e:
                print(f"[HAT_THUMB] load error: {e}", flush=True)

        for item_id, hd_json in items_with_data:
            _load_hat(hd_json)
            self.graphicsEngine.renderFrame()
            rtex = buf.getTexture()
            self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
            pnm = PNMImage()
            if rtex.store(pnm):
                out_tex = Texture(); out_tex.load(pnm)
                out_tex.setMagfilter(Texture.FTLinear)
                out_tex.setMinfilter(Texture.FTLinearMipmapLinear)
                result[item_id] = out_tex

        if hat_node[0] and not hat_node[0].isEmpty():
            hat_node[0].removeNode()
        self.graphicsEngine.removeWindow(buf)
        cam_np.removeNode(); rig.removeNode()
        self.camNode.setCameraMask(orig_mask)
        return result

    def _render_shirt_thumbnails(self, items, buf_w=512, buf_h=512):
        """RTT-render one avatar+shirt frame per item; returns {item_id: Texture}."""
        import base64 as _b64
        items_with_img = []
        for it in items:
            img = it.get("image_data", "")
            if img:
                b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                items_with_img.append((it["id"], b64))
        if not items_with_img:
            return {}

        result = {}
        # Use the same camera mask bit as tshirts (bit 6) — same isolation, same rig Y offset avoids overlap
        PMASK  = BitMask32.bit(6)
        BUF_W, BUF_H = buf_w, buf_h
        _DEFAULTS = {
            "head":      (244/255, 204/255,  67/255, 1),
            "torso":     ( 23/255, 107/255, 170/255, 1),
            "left_arm":  (244/255, 204/255,  67/255, 1),
            "right_arm": (244/255, 204/255,  67/255, 1),
            "left_leg":  (165/255, 188/255,  80/255, 1),
            "right_leg": (165/255, 188/255,  80/255, 1),
        }
        colors = getattr(self, "_avatar_colors", None) or self.load_avatar_colors()

        rig = self.render.attachNewNode("shirt_thumb_root")
        rig.setPos(0, 3000, 0)

        def box(parent, scale, pos, key):
            m = self.loader.loadModel("models/box")
            m.reparentTo(parent); m.setScale(*scale); m.setPos(*pos)
            m.setColor(*colors.get(key, _DEFAULTS[key])); m.setTextureOff(1); m.show(PMASK)
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
        head.reparentTo(rig); head.setColor(*colors.get("head", _DEFAULTS["head"]))
        head.setTwoSided(True); head.setTextureOff(1); head.setPos(0, 0, 4.55); head.show(PMASK)

        al = AmbientLight("sh_al"); al.setColor(LColor(0.22, 0.22, 0.25, 1))
        rig.setLight(rig.attachNewNode(al))
        dl = DirectionalLight("sh_dl"); dl.setColor(LColor(0.50, 0.50, 0.52, 1))
        dlnp = rig.attachNewNode(dl); dlnp.setHpr(20, 15, 0); rig.setLight(dlnp)

        shirt_nodes = [[]]
        R = self._SHIRT_REGIONS

        def _swap_shirt(image_b64):
            for n in shirt_nodes[0]:
                if n and not n.isEmpty(): n.removeNode()
            shirt_nodes[0] = []
            raw = _b64.b64decode(image_b64)
            ss = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                print("[SHIRT_THUMB] PNMImage read failed", flush=True); return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            nodes = []
            def attach(parent, reg_map, w, d, h, pos):
                node = self._make_shirt_box_geom(w, d, h, reg_map)
                np = parent.attachNewNode(node)
                np.setPos(*pos); np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setDepthOffset(1); np.setTransparency(TransparencyAttrib.MAlpha)
                np.show(PMASK); return np
            nodes.append(attach(rig, {'front':R['torso_front'],'back':R['torso_back'],
                'left':R['torso_left'],'right':R['torso_right'],
                'top':R['torso_up'],'bottom':R['torso_down']}, 2, 1, 2, (-1,-0.5,2)))
            nodes.append(attach(ra, {'front':R['rarm_front'],'back':R['rarm_back'],
                'left':R['rarm_left'],'right':R['rarm_right'],
                'top':R['rarm_up'],'bottom':R['rarm_down']}, 1, 1, 2, (-0.5,-0.5,-2)))
            nodes.append(attach(la, {'front':R['larm_front'],'back':R['larm_back'],
                'left':R['larm_left'],'right':R['larm_right'],
                'top':R['larm_up'],'bottom':R['larm_down']}, 1, 1, 2, (-0.5,-0.5,-2)))
            shirt_nodes[0] = nodes

        buf = self.win.makeTextureBuffer("shirt_thumb_buf", BUF_W, BUF_H)
        buf.setClearColor(LColor(0.78, 0.75, 0.88, 1.0)); buf.setClearColorActive(True)
        _camNode = Camera("shirt_thumb_cam")
        _lens = PerspectiveLens(); _lens.setFov(32.0)
        _lens.setAspectRatio(BUF_W / BUF_H); _lens.setNearFar(0.1, 10000)
        _camNode.setLens(_lens); _camNode.setCameraMask(PMASK)
        cam_np = self.render.attachNewNode(_camNode)
        cam_np.setPos(0, 4000 - 12, 3.3); cam_np.lookAt(Point3(0, 4000, 3.3))
        _dr = buf.makeDisplayRegion(0, 1, 0, 1); _dr.setSort(10); _dr.setCamera(cam_np)
        orig_mask = self.camNode.getCameraMask()
        self.camNode.setCameraMask(orig_mask & ~PMASK)
        self.graphicsEngine.renderFrame()

        for item_id, image_b64 in items_with_img:
            _swap_shirt(image_b64)
            self.graphicsEngine.renderFrame()
            rtex = buf.getTexture()
            self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
            pnm = PNMImage()
            if rtex.store(pnm):
                out_tex = Texture(); out_tex.load(pnm)
                out_tex.setMagfilter(Texture.FTLinear)
                out_tex.setMinfilter(Texture.FTLinearMipmapLinear)
                result[item_id] = out_tex
            else:
                print(f"[SHOP_THUMB] shirt store failed for {item_id}", flush=True)

        for n in shirt_nodes[0]:
            if n and not n.isEmpty(): n.removeNode()
        self.graphicsEngine.removeWindow(buf)
        cam_np.removeNode(); rig.removeNode()
        self.camNode.setCameraMask(orig_mask)
        return result

    def _draw_shop_grid_task(self, items, err, owned, task):
        self._shop_items_cache = items
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
        self._shop_thumb_textures = {}
        self._shop_page = 0
        self._draw_shop_grid(items, frame, {})
        self._schedule_page_thumb_render()
        return task.done

    def _schedule_page_thumb_render(self):
        items = getattr(self, "_shop_items_cache", [])
        frame = getattr(self, "_shop_grid_parent", None)
        if not items or not frame or frame.isEmpty():
            return
        page = getattr(self, "_shop_page", 0)
        page_items = items[page * _SHOP_PAGE:(page + 1) * _SHOP_PAGE]
        cache = getattr(self, "_shop_thumb_textures", {})
        to_render = [it for it in page_items if it.get("id") not in cache]
        if not to_render:
            return
        self.taskMgr.doMethodLater(
            0, self._render_page_thumbs_task, "_renderPageThumbs",
            extraArgs=[to_render], appendTask=True,
        )

    def _render_page_thumbs_task(self, to_render, task):
        cache = getattr(self, "_shop_thumb_textures", {})
        hat_items    = [it for it in to_render if self._item_is_hat(it)]
        shirt_items  = [it for it in to_render if self._item_is_shirt(it)]
        pants_items  = [it for it in to_render if self._item_is_pants(it)]
        face_items   = [it for it in to_render if self._item_is_face(it)]
        tshirt_items = [it for it in to_render if not self._item_is_hat(it)
                        and not self._item_is_shirt(it)
                        and not self._item_is_pants(it)
                        and not self._item_is_face(it) and it.get("image_data")]
        try:
            if tshirt_items:
                cache.update(self._render_shop_thumbnails(tshirt_items, buf_w=512, buf_h=512))
        except Exception as e:
            print(f"[SHOP_THUMB] RTT failed: {e}", flush=True)
        try:
            if shirt_items:
                cache.update(self._render_shop_thumbnails(shirt_items, buf_w=512, buf_h=512))
        except Exception as e:
            print(f"[SHOP_THUMB] shirt RTT failed: {e}", flush=True)
        try:
            if pants_items:
                cache.update(self._render_shop_thumbnails(pants_items, buf_w=512, buf_h=512))
        except Exception as e:
            print(f"[SHOP_THUMB] pants RTT failed: {e}", flush=True)
        try:
            if hat_items:
                cache.update(self._render_hat_thumbnails(hat_items, buf_w=512, buf_h=512))
        except Exception as e:
            print(f"[SHOP_THUMB] hat RTT failed: {e}", flush=True)
        try:
            if face_items:
                cache.update(self._render_face_thumbnails(face_items))
        except Exception as e:
            print(f"[SHOP_THUMB] face thumb failed: {e}", flush=True)
        thumb_frames = getattr(self, "_shop_thumb_frames", {})
        for it in to_render:
            iid = it.get("id")
            tex = cache.get(iid)
            frm = thumb_frames.get(iid)
            if tex and frm and not frm.isEmpty():
                try:
                    frm["frameTexture"] = tex
                    frm["frameColor"]   = (1, 1, 1, 1)
                except Exception:
                    pass
        return task.done

    def _render_face_thumbnails(self, items):
        """Decode the first frame PNG from face items, composite onto white, return {item_id: Texture}."""
        import base64 as _b64
        from panda3d.core import Texture, PNMImage, StringStream
        result = {}
        for it in items:
            iid = it.get("id")
            img = it.get("image_data") or ""
            if "|FACEDATA|" not in img:
                continue
            try:
                thumb_b64 = img.split("|FACEDATA|")[0]
                raw = _b64.b64decode(thumb_b64)
                face = PNMImage()
                face.read(StringStream(raw), "face.png")
                w, h = face.getXSize(), face.getYSize()
                if w == 0 or h == 0:
                    continue
                # White background, same size
                bg = PNMImage(w, h)
                bg.fill(1, 1, 1)
                bg.alphaFill(1)
                if face.hasAlpha():
                    bg.blendSubImage(face, 0, 0)
                else:
                    bg.copySubImage(face, 0, 0)
                tex = Texture()
                tex.load(bg)
                tex.setMagfilter(Texture.FTLinear)
                tex.setMinfilter(Texture.FTLinear)
                result[iid] = tex
            except Exception as e:
                print(f"[FACE_THUMB] item {iid}: {e}", flush=True)
        return result

    def _on_shop_search(self, text):
        self._shop_search = text.strip()
        self._shop_page = 0
        items = getattr(self, "_shop_items_cache", [])
        frame = getattr(self, "_shop_grid_parent", None)
        if frame and not frame.isEmpty():
            self._draw_shop_grid(items, frame, getattr(self, "_shop_thumb_textures", {}))
            self._schedule_page_thumb_render()

    def _shop_goto_page(self, delta):
        items = getattr(self, "_shop_items_cache", [])
        if not items:
            return
        max_page = max(0, (len(items) - 1) // _SHOP_PAGE)
        new_page = max(0, min(getattr(self, "_shop_page", 0) + delta, max_page))
        if new_page == getattr(self, "_shop_page", 0):
            return
        self._shop_page = new_page
        frame = getattr(self, "_shop_grid_parent", None)
        if not frame or frame.isEmpty():
            return
        sub = getattr(self, "_shop_grid_cards", None)
        if sub and not sub.isEmpty():
            sub.destroy()
        self._draw_shop_grid(items, frame, getattr(self, "_shop_thumb_textures", {}))
        self._schedule_page_thumb_render()

    def _draw_shop_grid(self, items, frame, thumb_textures=None):
        sub = getattr(self, "_shop_grid_cards", None)
        if sub and not sub.isEmpty():
            sub.destroy()
        cards_frame = DirectFrame(frameColor=(0, 0, 0, 0), frameSize=(-3, 3, -3, 3), parent=frame)
        self._shop_grid_cards  = cards_frame
        self._shop_thumb_frames = {}
        _CARD_BG  = (0.52, 0.44, 0.70, 1.0)
        _OWN_BG   = (0.38, 0.26, 0.58, 1.0)
        _THUMB_BG = (0.48, 0.38, 0.66, 1.0)
        _TEXT_H   = (0.12, 0.08, 0.28, 1.0)
        _TEXT_D   = (0.32, 0.22, 0.50, 1.0)
        _PANEL_DIV = (0.50, 0.40, 0.68, 1.0)
        if thumb_textures is None:
            thumb_textures = {}

        q = getattr(self, "_shop_search", "").strip().lower()
        if q:
            items = [it for it in items if q in (it.get("name") or "").lower()]
        page     = getattr(self, "_shop_page", 0)
        max_page = max(0, (len(items) - 1) // _SHOP_PAGE)
        page_items = items[page * _SHOP_PAGE:(page + 1) * _SHOP_PAGE]
        owned_ids  = getattr(self, "_shop_owned_ids", set())

        total_w  = _SHOP_COLS * _SHOP_CW + (_SHOP_COLS - 1) * _SHOP_GAPX
        left_cx  = -total_w / 2 + _SHOP_CW / 2
        GRID_TOP = 0.64
        THUMB_CY = _SHOP_CH / 2 - _SHOP_CTH / 2
        NAME_Z   = -_SHOP_CH / 2 + _SHOP_CIH * 0.66
        BADGE_Z  = -_SHOP_CH / 2 + _SHOP_CIH * 0.22

        for idx, item in enumerate(page_items):
            col     = idx % _SHOP_COLS
            row     = idx // _SHOP_COLS
            cx      = left_cx + col * (_SHOP_CW + _SHOP_GAPX)
            cz      = GRID_TOP - _SHOP_CH / 2 - row * (_SHOP_CH + _SHOP_GAPY)
            item_id = item.get("id")
            name    = item.get("name", "")
            creator = item.get("username", "")
            owned   = item_id in owned_ids

            card = DirectButton(
                frameColor=_OWN_BG if owned else _CARD_BG,
                frameSize=(-_SHOP_CW / 2, _SHOP_CW / 2, -_SHOP_CH / 2, _SHOP_CH / 2),
                parent=cards_frame, pos=(cx, 0, cz),
                sortOrder=5, relief=1,
                command=self._show_shop_item_popup,
                extraArgs=[item],
            )
            thumb_frame = DirectFrame(
                frameColor=_THUMB_BG,
                frameSize=(-_SHOP_CW / 2, _SHOP_CW / 2, -_SHOP_CTH / 2, _SHOP_CTH / 2),
                parent=card, pos=(0, 0, THUMB_CY),
                sortOrder=6,
            )
            self._shop_thumb_frames[item_id] = thumb_frame
            rtt_tex = thumb_textures.get(item_id)
            if rtt_tex:
                thumb_frame["frameTexture"] = rtt_tex
                thumb_frame["frameColor"]   = (1, 1, 1, 1)

            short = (name[:10] + "…") if len(name) > 11 else name
            DirectLabel(
                text=short, text_fg=_TEXT_H, text_scale=0.022,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(0, 0, NAME_Z), sortOrder=6,
            )
            if owned:
                DirectLabel(
                    text="Owned",
                    text_fg=(0.08, 0.88, 0.32, 1), text_scale=0.015,
                    frameColor=(0.12, 0.52, 0.24, 1.0),
                    frameSize=(-0.036, 0.036, -0.011, 0.011),
                    parent=card, pos=(-_SHOP_CW / 2 + 0.050, 0, BADGE_Z), sortOrder=6,
                )
            if creator:
                short_c = (creator[:8] + "…") if len(creator) > 9 else creator
                DirectLabel(
                    text=f"by {short_c}", text_fg=_TEXT_D, text_scale=0.013,
                    frameColor=(0, 0, 0, 0),
                    parent=card, pos=(_SHOP_CW / 2 - 0.040, 0, BADGE_Z),
                    text_align=TextNode.ARight, sortOrder=6,
                )

        # Update pagination controls
        _DIM = (0.40, 0.35, 0.52, 1.0)
        lbl  = getattr(self, "_shop_page_lbl",  None)
        prev = getattr(self, "_shop_prev_btn",  None)
        nxt  = getattr(self, "_shop_next_btn",  None)
        if lbl  and not lbl.isEmpty():  lbl["text"] = f"Page {page + 1} / {max_page + 1}"
        if prev and not prev.isEmpty(): prev["frameColor"] = _PANEL_DIV if page > 0        else _DIM
        if nxt  and not nxt.isEmpty():  nxt["frameColor"]  = _PANEL_DIV if page < max_page else _DIM

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
            frameSize=(-0.50, 0.50, -0.50, 0.50),
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
        item_id = item_summary.get("id")
        owned   = item_id in getattr(self, "_shop_owned_ids", set())
        is_mine = (item_summary.get("username") == getattr(self, "_session_username", None))

        if is_mine:
            def _do_delete(iid=item_id):
                token = self._session_token
                def worker():
                    result, err = auth_client.delete_shop_item(token, iid)
                    def _done(task, ok=(result is not None), err=err):
                        if ok:
                            popup = getattr(self, "_shop_item_popup", None)
                            if popup:
                                try: popup.destroy()
                                except Exception: pass
                            self._shop_item_popup = None
                            self._show_toast("Item deleted.", GREEN)
                            self._build_shop_screen()
                        else:
                            self._show_toast(f"Delete failed: {err}", RED)
                        return task.done
                    self.taskMgr.doMethodLater(0, _done, "_delShopDone", appendTask=True)
                threading.Thread(target=worker, daemon=True).start()
            DirectButton(
                text="Delete",
                text_fg=_RS_WHITE, text_scale=0.026,
                frameColor=_RS_RED,
                frameSize=(-0.10, 0.10, -0.032, 0.032),
                parent=card, pos=(RX + 0.18, 0, -HH + 0.14),
                relief=1, command=_do_delete,
            )

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

        _popup_is_hat  = self._item_is_hat(item_summary)
        _popup_is_face = self._item_is_face(item_summary)
        # For shirts keep the full image_data (with |SHIRTDATA|) so RTT can detect it
        _popup_img_raw = item_summary.get("image_data") or ""
        _popup_b64     = self._item_thumbnail(item_summary)  # hat/tshirt path (stripped)

        def _apply_popup_thumb(task, _is_hat=_popup_is_hat, _is_face=_popup_is_face,
                               _img_raw=_popup_img_raw,
                               _b64=_popup_b64, frm=img_frame, _id=item_id,
                               _item=item_summary):
            if not frm or frm.isEmpty():
                return task.done
            try:
                if _is_face:
                    textures = self._render_face_thumbnails([_item])
                    rtt = textures.get(_id)
                    if rtt:
                        frm["frameTexture"] = rtt
                        frm["frameColor"]   = (1, 1, 1, 1)
                elif _is_hat:
                    textures = self._render_hat_thumbnails(
                        [_item], buf_w=256, buf_h=256)
                    rtt = textures.get(_id)
                    if rtt:
                        frm["frameTexture"] = rtt
                        frm["frameColor"]   = (1, 1, 1, 1)
                else:
                    # Pass full image_data so _render_shop_thumbnails detects |SHIRTDATA|
                    img_data = _img_raw if _img_raw else _b64
                    if not img_data: return task.done
                    textures = self._render_shop_thumbnails(
                        [{"id": _id, "image_data": img_data}], buf_w=256, buf_h=256)
                    rtt = textures.get(_id)
                    if rtt:
                        frm["frameTexture"] = rtt
                        frm["frameColor"]   = (1, 1, 1, 1)
            except Exception as e:
                print(f"[POPUP_THUMB] {e}", flush=True)
            return task.done
        self.taskMgr.doMethodLater(0, _apply_popup_thumb, "_applyShopImg", appendTask=True)

    def _buy_shop_item(self, item_id):
        token = self._session_token
        def worker():
            result, err = auth_client.buy_shop_item(token, item_id)
            def _done(task, ok=(result is not None), err=err):
                if ok:
                    self._shop_owned_ids.add(item_id)
                    # Invalidate owned-items cache so avatar tab reflects new purchase
                    self._avatar_items_full_cache = None
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

    def _show_upload_shirt_dialog(self):
        existing = getattr(self, "_upload_shirt_popup", None)
        if existing:
            try: existing.destroy()
            except Exception: pass
        self._upload_shirt_popup = None
        self._upload_shirt_path  = ""

        overlay = DirectFrame(frameColor=(0, 0, 0, 0.82), frameSize=(-3, 3, -3, 3),
                              sortOrder=500, state='normal')
        self._upload_shirt_popup = overlay

        card = DirectFrame(frameColor=_RS_CARD, frameSize=(-0.70, 0.70, -0.54, 0.54),
                           parent=overlay, sortOrder=501)
        DirectLabel(text="Upload Shirt", text_fg=_RS_WHITE, text_scale=0.036,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, 0.42))
        DirectLabel(text="Use the standard Roblox shirt template (585×559).",
                    text_fg=_RS_GRAY, text_scale=0.020,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, 0.33))

        img_lbl = DirectLabel(text="No file chosen", text_fg=_RS_GRAY, text_scale=0.024,
                              text_align=TextNode.ALeft, frameColor=(0, 0, 0, 0),
                              parent=card, pos=(-0.10, 0, 0.20))

        def _browse():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                path = filedialog.askopenfilename(parent=root, title="Select Shirt template",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
                root.destroy()
                if path:
                    self._upload_shirt_path = path
                    short = path.replace("\\", "/").split("/")[-1]
                    if len(short) > 30: short = "..." + short[-27:]
                    img_lbl["text"] = short; img_lbl["text_fg"] = _RS_WHITE
            except Exception as e:
                print(f"[UPLOAD_SHIRT] browse: {e}", flush=True)

        DirectButton(text="Choose Image", text_fg=_RS_WHITE, text_scale=0.026,
                     frameColor=_RS_BORDER, frameSize=(-0.13, 0.13, -0.030, 0.030),
                     parent=card, pos=(-0.50, 0, 0.20), relief=1, command=_browse)

        DirectLabel(text="Name", text_fg=_RS_GRAY, text_scale=0.026, text_align=TextNode.ALeft,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(-0.64, 0, 0.06))
        name_entry = DirectEntry(text="", scale=0.028, width=14, numLines=1,
                                 frameColor=(0.18, 0.16, 0.28, 1), text_fg=_RS_WHITE,
                                 parent=card, pos=(-0.62, 0, 0.00))
        DirectLabel(text="Description", text_fg=_RS_GRAY, text_scale=0.026,
                    text_align=TextNode.ALeft, frameColor=(0, 0, 0, 0),
                    parent=card, pos=(-0.64, 0, -0.10))
        desc_entry = DirectEntry(text="", scale=0.028, width=14, numLines=1,
                                 frameColor=(0.18, 0.16, 0.28, 1), text_fg=_RS_WHITE,
                                 parent=card, pos=(-0.62, 0, -0.16))
        upload_status = DirectLabel(text="", text_fg=_RS_GRAY, text_scale=0.022,
                                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, -0.30))

        def _do_upload():
            path = self._upload_shirt_path
            if not path:
                upload_status["text"] = "Choose an image first."; upload_status["text_fg"] = _RS_RED; return
            item_name = name_entry.get().strip()
            if not item_name:
                upload_status["text"] = "Enter a name."; upload_status["text_fg"] = _RS_RED; return
            item_desc = desc_entry.get().strip()
            token = getattr(self, "_session_token", None)
            if not token:
                upload_status["text"] = "Not logged in."; upload_status["text_fg"] = _RS_RED; return
            upload_status["text"] = "Uploading..."; upload_status["text_fg"] = _RS_GRAY

            def worker():
                try:
                    from PIL import Image as _PIL
                    import io as _io, base64
                    img = _PIL.open(path).convert("RGBA")
                    # Always normalize to exactly 585×559 so crop coordinates match
                    if img.size != (585, 559):
                        img = img.resize((585, 559), _PIL.LANCZOS)
                    buf = _io.BytesIO(); img.save(buf, "PNG")
                    image_b64 = base64.b64encode(buf.getvalue()).decode()
                except Exception as e:
                    def _err(task, msg=str(e)):
                        upload_status["text"] = f"Image error: {msg[:40]}"; upload_status["text_fg"] = _RS_RED
                        return task.done
                    self.taskMgr.doMethodLater(0, _err, "_shirtUploadErr", appendTask=True); return
                # Embed marker so client can distinguish shirts from T-shirts.
                # Server only accepts "tshirt"/"hat", so category stays "tshirt".
                combined = image_b64 + "|SHIRTDATA|"
                result, err = auth_client.upload_shop_item(
                    token, item_name, item_desc, 0, combined, category="tshirt")
                def _done(task, ok=(result is not None), err=err):
                    if ok:
                        upload_status["text"] = "Published!"; upload_status["text_fg"] = _RS_GREEN
                    else:
                        upload_status["text"] = f"Error: {err}"; upload_status["text_fg"] = _RS_RED
                    return task.done
                self.taskMgr.doMethodLater(0, _done, "_shirtUploadDone", appendTask=True)
            threading.Thread(target=worker, daemon=True).start()

        def _cancel():
            p = getattr(self, "_upload_shirt_popup", None)
            if p:
                try: p.destroy()
                except Exception: pass
            self._upload_shirt_popup = None

        DirectButton(text="Upload to Shop", text_fg=_RS_WHITE, text_scale=0.030,
                     frameColor=_RS_ORANGE, frameSize=(-0.18, 0.18, -0.038, 0.038),
                     parent=card, pos=(-0.22, 0, -0.48), relief=1, command=_do_upload)
        DirectButton(text="Cancel", text_fg=_RS_GRAY, text_scale=0.028,
                     frameColor=_RS_BORDER, frameSize=(-0.12, 0.12, -0.034, 0.034),
                     parent=card, pos=(0.34, 0, -0.48), relief=1, command=_cancel)

    def _show_upload_pants_dialog(self):
        existing = getattr(self, "_upload_pants_popup", None)
        if existing:
            try: existing.destroy()
            except Exception: pass
        self._upload_pants_popup = None
        self._upload_pants_path  = ""

        overlay = DirectFrame(frameColor=(0, 0, 0, 0.82), frameSize=(-3, 3, -3, 3),
                              sortOrder=500, state='normal')
        self._upload_pants_popup = overlay

        card = DirectFrame(frameColor=_RS_CARD, frameSize=(-0.70, 0.70, -0.54, 0.54),
                           parent=overlay, sortOrder=501)
        DirectLabel(text="Upload Pants", text_fg=_RS_WHITE, text_scale=0.036,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, 0.42))
        DirectLabel(text="Use the standard Roblox pants template (585×559).",
                    text_fg=_RS_GRAY, text_scale=0.020,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, 0.33))

        img_lbl = DirectLabel(text="No file chosen", text_fg=_RS_GRAY, text_scale=0.024,
                              text_align=TextNode.ALeft, frameColor=(0, 0, 0, 0),
                              parent=card, pos=(-0.10, 0, 0.20))

        def _browse():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                path = filedialog.askopenfilename(parent=root, title="Select Pants template",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
                root.destroy()
                if path:
                    self._upload_pants_path = path
                    short = path.replace("\\", "/").split("/")[-1]
                    if len(short) > 30: short = "..." + short[-27:]
                    img_lbl["text"] = short; img_lbl["text_fg"] = _RS_WHITE
            except Exception as e:
                print(f"[UPLOAD_PANTS] browse: {e}", flush=True)

        DirectButton(text="Choose Image", text_fg=_RS_WHITE, text_scale=0.026,
                     frameColor=_RS_BORDER, frameSize=(-0.13, 0.13, -0.030, 0.030),
                     parent=card, pos=(-0.50, 0, 0.20), relief=1, command=_browse)

        DirectLabel(text="Name", text_fg=_RS_GRAY, text_scale=0.026, text_align=TextNode.ALeft,
                    frameColor=(0, 0, 0, 0), parent=card, pos=(-0.64, 0, 0.06))
        name_entry = DirectEntry(text="", scale=0.028, width=14, numLines=1,
                                 frameColor=(0.18, 0.16, 0.28, 1), text_fg=_RS_WHITE,
                                 parent=card, pos=(-0.62, 0, 0.00))
        DirectLabel(text="Description", text_fg=_RS_GRAY, text_scale=0.026,
                    text_align=TextNode.ALeft, frameColor=(0, 0, 0, 0),
                    parent=card, pos=(-0.64, 0, -0.10))
        desc_entry = DirectEntry(text="", scale=0.028, width=14, numLines=1,
                                 frameColor=(0.18, 0.16, 0.28, 1), text_fg=_RS_WHITE,
                                 parent=card, pos=(-0.62, 0, -0.16))
        upload_status = DirectLabel(text="", text_fg=_RS_GRAY, text_scale=0.022,
                                    frameColor=(0, 0, 0, 0), parent=card, pos=(0, 0, -0.30))

        def _do_upload():
            path = self._upload_pants_path
            if not path:
                upload_status["text"] = "Choose an image first."; upload_status["text_fg"] = _RS_RED; return
            item_name = name_entry.get().strip()
            if not item_name:
                upload_status["text"] = "Enter a name."; upload_status["text_fg"] = _RS_RED; return
            item_desc = desc_entry.get().strip()
            token = getattr(self, "_session_token", None)
            if not token:
                upload_status["text"] = "Not logged in."; upload_status["text_fg"] = _RS_RED; return
            upload_status["text"] = "Uploading..."; upload_status["text_fg"] = _RS_GRAY

            def worker():
                try:
                    from PIL import Image as _PIL
                    import io as _io, base64
                    img = _PIL.open(path).convert("RGBA")
                    if img.size != (585, 559):
                        img = img.resize((585, 559), _PIL.LANCZOS)
                    buf = _io.BytesIO(); img.save(buf, "PNG")
                    image_b64 = base64.b64encode(buf.getvalue()).decode()
                except Exception as e:
                    def _err(task, msg=str(e)):
                        upload_status["text"] = f"Image error: {msg[:40]}"; upload_status["text_fg"] = _RS_RED
                        return task.done
                    self.taskMgr.doMethodLater(0, _err, "_pantsUploadErr", appendTask=True); return
                combined = image_b64 + "|PANTSDATA|"
                result, err = auth_client.upload_shop_item(
                    token, item_name, item_desc, 0, combined, category="tshirt")
                def _done(task, ok=(result is not None), err=err):
                    if ok:
                        upload_status["text"] = "Published!"; upload_status["text_fg"] = _RS_GREEN
                    else:
                        upload_status["text"] = f"Error: {err}"; upload_status["text_fg"] = _RS_RED
                    return task.done
                self.taskMgr.doMethodLater(0, _done, "_pantsUploadDone", appendTask=True)
            threading.Thread(target=worker, daemon=True).start()

        def _cancel():
            p = getattr(self, "_upload_pants_popup", None)
            if p:
                try: p.destroy()
                except Exception: pass
            self._upload_pants_popup = None

        DirectButton(text="Upload to Shop", text_fg=_RS_WHITE, text_scale=0.030,
                     frameColor=_RS_ORANGE, frameSize=(-0.18, 0.18, -0.038, 0.038),
                     parent=card, pos=(-0.22, 0, -0.48), relief=1, command=_do_upload)
        DirectButton(text="Cancel", text_fg=_RS_GRAY, text_scale=0.028,
                     frameColor=_RS_BORDER, frameSize=(-0.12, 0.12, -0.034, 0.034),
                     parent=card, pos=(0.34, 0, -0.48), relief=1, command=_cancel)

    def _show_upload_face_dialog(self):
        """Bob-only: pick 3 PNG frames and upload a face item."""
        import tkinter as tk
        from tkinter import filedialog
        import base64 as _b64, threading

        token = getattr(self, '_session_token', None)
        if not token:
            return

        root = tk.Tk(); root.withdraw()
        paths = filedialog.askopenfilenames(
            title="Pick 3 face frames (select in order: frame1, frame2, frame3)",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")],
        )
        root.destroy()
        if not paths or len(paths) < 1:
            return

        frames_b64 = []
        for p in list(paths)[:3]:
            with open(p, "rb") as fh:
                raw = fh.read()
                b64str = _b64.b64encode(raw).decode()
                print(f"[FACE_UPLOAD] file={p} raw_len={len(raw)} b64_len={len(b64str)} first32={raw[:32]}", flush=True)
                frames_b64.append(b64str)

        # Pad to 3 frames by repeating the last one
        while len(frames_b64) < 3:
            frames_b64.append(frames_b64[-1])

        # Thumbnail = first frame; payload = thumbnail|FACEDATA|f1,f2,f3
        thumbnail_b64 = frames_b64[0]
        payload_str   = ",".join(frames_b64)
        image_data    = thumbnail_b64 + "|FACEDATA|" + payload_str
        print(f"[FACE_UPLOAD] total image_data len={len(image_data)}", flush=True)

        # Name dialog
        name_root = tk.Tk(); name_root.withdraw()
        import tkinter.simpledialog as _sd
        item_name = _sd.askstring("Face name", "Enter face item name:",
                                   parent=name_root) or "Custom Face"
        name_root.destroy()

        def _upload():
            result, err = auth_client.upload_shop_item(
                token, item_name, "", 0, image_data, category="tshirt")
            if result:
                print(f"[FACE_UPLOAD] OK id={result.get('id')}", flush=True)
                self.taskMgr.doMethodLater(
                    0, lambda t: (self._build_avatar_screen("face"), t.done)[1],
                    "_faceUploadRefresh", appendTask=True)
            else:
                print(f"[FACE_UPLOAD] error: {err}", flush=True)
        threading.Thread(target=_upload, daemon=True).start()

    def _show_upload_hat_from_menu(self):
        """Open a file dialog to pick an OBJ, then show the hat upload dialog."""
        token = getattr(self, '_session_token', None)
        if not token:
            self._show_toast("Please log in first.", RED)
            return
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            obj_path = filedialog.askopenfilename(
                parent=root,
                title="Select Hat OBJ file",
                filetypes=[("OBJ files", "*.obj"), ("All files", "*.*")],
            )
            root.destroy()
        except Exception as e:
            print(f"[UPLOAD_HAT_MENU] browse error: {e}", flush=True)
            return
        if not obj_path:
            return
        # Load the OBJ in the editor system then open the upload dialog.
        # If we're not in the editor (no hat_config_button / no inspector built),
        # we call _load_hat_for_editor which also creates the inspector buttons,
        # so we guard against that by calling _show_upload_hat_dialog directly
        # with the path via a standalone upload popup.
        self._show_hat_upload_standalone(obj_path, token)

    def _show_hat_upload_standalone(self, obj_path, token):
        """Upload a hat OBJ directly from the main menu without entering the editor."""
        import os as _os2
        existing = getattr(self, '_hat_upload_popup', None)
        if existing:
            try: existing.destroy()
            except Exception: pass

        _RS_CARD   = (0.84, 0.82, 0.93, 1.0)
        _RS_ORANGE = (0.58, 0.18, 0.82, 1.0)
        _RS_BORDER = (0.48, 0.38, 0.66, 1.0)
        _RS_WHITE  = (0.00, 0.00, 0.00, 1.0)
        _RS_GRAY   = (0.00, 0.00, 0.00, 1.0)
        _RS_RED    = (0.85, 0.18, 0.18, 1.0)
        _RS_GREEN  = (0.22, 0.75, 0.40, 1.0)

        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=500, state='normal',
        )
        self._hat_upload_popup = overlay

        card = DirectFrame(
            frameColor=_RS_CARD,
            frameSize=(-0.72, 0.72, -0.50, 0.50),
            parent=overlay, sortOrder=501,
        )

        short_path = obj_path.replace("\\", "/").split("/")[-1]
        DirectLabel(
            text="Upload Hat to Shop",
            text_fg=_RS_WHITE, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.38),
        )
        DirectLabel(
            text=f"File: {short_path[:40]}",
            text_fg=_RS_GRAY, text_scale=0.022,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.28),
        )

        DirectLabel(
            text="Name",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.66, 0, 0.17),
        )
        name_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.64, 0.64, -0.036, 0.036),
            parent=card, pos=(0, 0, 0.11),
        )
        name_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=42, numLines=1,
            parent=name_bg, pos=(-0.62, 0, -0.012),
        )

        DirectLabel(
            text="Description",
            text_fg=_RS_GRAY, text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.66, 0, -0.02),
        )
        desc_bg = DirectFrame(
            frameColor=(0.72, 0.69, 0.80, 1.0),
            frameSize=(-0.64, 0.64, -0.036, 0.036),
            parent=card, pos=(0, 0, -0.08),
        )
        desc_entry = DirectEntry(
            text_fg=_RS_WHITE, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            width=42, numLines=1,
            parent=desc_bg, pos=(-0.62, 0, -0.012),
        )

        # Optional texture picker
        self._hat_menu_tex_path = None
        tex_lbl = DirectLabel(
            text="No texture selected (optional)",
            text_fg=_RS_GRAY, text_scale=0.022,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.20, 0, -0.19),
        )
        def _browse_tex():
            try:
                import tkinter as _tk2
                from tkinter import filedialog as _fd2
                r2 = _tk2.Tk(); r2.withdraw(); r2.attributes("-topmost", True)
                p = _fd2.askopenfilename(
                    parent=r2, title="Select hat texture (PNG/JPG)",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
                )
                r2.destroy()
                if p:
                    self._hat_menu_tex_path = p
                    tex_lbl["text"] = p.replace("\\","/").split("/")[-1][:40]
                    tex_lbl["text_fg"] = _RS_WHITE
            except Exception as e:
                print(f"[HAT_MENU_TEX] {e}", flush=True)
        DirectButton(
            text="Texture...",
            text_fg=_RS_WHITE, text_scale=0.022,
            frameColor=_RS_BORDER,
            frameSize=(-0.10, 0.10, -0.026, 0.026),
            parent=card, pos=(-0.55, 0, -0.19),
            relief=1, command=_browse_tex,
        )

        status_lbl = DirectLabel(
            text="",
            text_fg=_RS_GREEN, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.32),
        )

        def _cancel():
            p = getattr(self, '_hat_upload_popup', None)
            if p:
                try: p.destroy()
                except Exception: pass
            self._hat_upload_popup = None

        def _do_upload():
            item_name = name_entry.get().strip()
            if not item_name:
                status_lbl["text"] = "Enter a name."
                status_lbl["text_fg"] = _RS_RED
                return
            item_desc = desc_entry.get().strip()
            tex_path  = self._hat_menu_tex_path
            status_lbl["text"] = "Packaging..."
            status_lbl["text_fg"] = _RS_GRAY

            def worker():
                import base64, tempfile, json as _json, os as _os3, re as _re
                from panda3d.core import PNMImage, Filename as _Fn
                try:
                    with open(obj_path, 'rb') as fh:
                        obj_raw = fh.read()
                    obj_b64 = base64.b64encode(obj_raw).decode()

                    mtl_b64 = None; mtl_name = None
                    try:
                        obj_text = obj_raw.decode('utf-8', errors='replace')
                        m = _re.search(r'^mtllib\s+(.+)$', obj_text, _re.MULTILINE)
                        if m:
                            mtl_name = m.group(1).strip()
                            mtl_path = _os3.path.join(_os3.path.dirname(obj_path), mtl_name)
                            if _os3.path.exists(mtl_path):
                                with open(mtl_path, 'rb') as fh:
                                    mtl_b64 = base64.b64encode(fh.read()).decode()
                    except Exception as _me:
                        print(f"[HAT_MENU_MTL] {_me}", flush=True)

                    tex_b64 = None
                    if tex_path and _os3.path.exists(tex_path):
                        img = PNMImage()
                        img.read(_Fn.fromOsSpecific(tex_path))
                        if img.getXSize() > 512 or img.getYSize() > 512:
                            s = PNMImage(512, 512); s.gaussianFilterFrom(1.0, img); img = s
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                            tmp = tf.name
                        img.write(_Fn.fromOsSpecific(tmp))
                        with open(tmp, 'rb') as fh:
                            tex_b64 = base64.b64encode(fh.read()).decode()
                        _os3.unlink(tmp)

                    hat_data = _json.dumps({
                        "obj_b64": obj_b64, "mtl_b64": mtl_b64,
                        "mtl_name": mtl_name, "texture_b64": tex_b64,
                        "brick_scale": [2, 2, 2], "model_scale": [1, 1, 1],
                        "model_hpr": [0, 0, -90], "z_offset": 0.0,
                    })
                except Exception as e:
                    def _err(task, msg=str(e)):
                        status_lbl["text"] = f"Pack error: {msg[:40]}"
                        status_lbl["text_fg"] = _RS_RED
                        return task.done
                    self.taskMgr.doMethodLater(0, _err, "_hatMenuPackErr", appendTask=True)
                    return

                # Thumbnail render — on main thread
                def _thumb_and_upload(task):
                    import tempfile, base64 as _b64
                    from panda3d.core import (Camera, PerspectiveLens, PNMImage,
                                              Filename as _Fn2, LColor, Point3, BitMask32)
                    thumb_b64 = ""
                    try:
                        PMASK = BitMask32.bit(9)
                        BUF_W = BUF_H = 256
                        thumb_model = self.loader.loadModel(_Fn2.fromOsSpecific(obj_path))
                        if thumb_model:
                            thumb_model.setR(-90)
                            thumb_model.reparentTo(self.render)
                            thumb_model.setPos(0, 6000, 5)
                            thumb_model.setShaderOff(); thumb_model.setTwoSided(True)
                            if tex_path and tex_b64:
                                tex2 = self.loader.loadTexture(_Fn2.fromOsSpecific(tex_path))
                                if tex2:
                                    thumb_model.setTexture(tex2, 1)
                            thumb_model.show(PMASK)
                            buf = self.win.makeTextureBuffer("hat_menu_thumb", BUF_W, BUF_H)
                            buf.setClearColor(LColor(0.20, 0.20, 0.28, 1.0))
                            buf.setClearColorActive(True)
                            _cn = Camera("hat_menu_thumb_cam")
                            _lens = PerspectiveLens(); _lens.setFov(40); _lens.setNearFar(0.1, 10000)
                            _cn.setLens(_lens); _cn.setCameraMask(PMASK)
                            cam_np = self.render.attachNewNode(_cn)
                            cam_np.setPos(0, 6000 - 8, 5)
                            cam_np.lookAt(Point3(0, 6000, 5))
                            _dr = buf.makeDisplayRegion(); _dr.setSort(10); _dr.setCamera(cam_np)
                            orig_mask = self.camNode.getCameraMask()
                            self.camNode.setCameraMask(orig_mask & ~PMASK)
                            self.graphicsEngine.renderFrame()
                            rtex = buf.getTexture()
                            self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
                            pnm = PNMImage()
                            if rtex.store(pnm):
                                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                                    tmp2 = tf.name
                                pnm.write(_Fn2.fromOsSpecific(tmp2))
                                with open(tmp2, 'rb') as fh:
                                    thumb_b64 = _b64.b64encode(fh.read()).decode()
                                import os as _os4; _os4.unlink(tmp2)
                            self.graphicsEngine.removeWindow(buf)
                            cam_np.removeNode(); thumb_model.removeNode()
                            self.camNode.setCameraMask(orig_mask)
                    except Exception as e:
                        print(f"[HAT_MENU_THUMB] {e}", flush=True)

                    import threading as _thr2, auth_client as _ac
                    def _upload():
                        result, err = _ac.upload_shop_item(
                            token, item_name, item_desc, 0, thumb_b64,
                            category="hat", hat_data=hat_data)
                        def _done(task2, ok=(result is not None), err=err):
                            if ok:
                                status_lbl["text"] = "Published!"
                                status_lbl["text_fg"] = _RS_GREEN
                                self._show_toast("Hat uploaded to shop!", GREEN)
                            else:
                                status_lbl["text"] = f"Error: {(err or '')[:40]}"
                                status_lbl["text_fg"] = _RS_RED
                            return task2.done
                        self.taskMgr.doMethodLater(0, _done, "_hatMenuUploadDone", appendTask=True)
                    _thr2.Thread(target=_upload, daemon=True).start()
                    return task.done

                self.taskMgr.doMethodLater(0, _thumb_and_upload, "_hatMenuThumb", appendTask=True)

            threading.Thread(target=worker, daemon=True).start()

        DirectButton(
            text="Upload to Shop",
            text_fg=_RS_WHITE, text_scale=0.030,
            frameColor=_RS_ORANGE,
            frameSize=(-0.18, 0.18, -0.038, 0.038),
            parent=card, pos=(-0.22, 0, -0.44),
            relief=1, command=_do_upload,
        )
        DirectButton(
            text="Cancel",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=_RS_BORDER,
            frameSize=(-0.12, 0.12, -0.034, 0.034),
            parent=card, pos=(0.34, 0, -0.44),
            relief=1, command=_cancel,
        )

    # ── Settings screen ────────────────────────────────────────────────────

    def _build_settings_screen(self):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None

        _RS_BG     = (0.78, 0.75, 0.88, 1.0)
        _RS_NAV    = (0.55, 0.45, 0.76, 1.0)
        _RS_ORANGE = (0.58, 0.18, 0.82, 1.0)
        _RS_WHITE  = (0.95, 0.95, 1.00, 1.0)
        _RS_GRAY   = (0.00, 0.00, 0.00, 1.0)  # black so inactive nav tabs are readable
        _RS_CARD   = (0.70, 0.66, 0.82, 1.0)
        _RS_ON     = (0.28, 0.72, 0.42, 1.0)
        _RS_OFF    = (0.52, 0.44, 0.70, 1.0)
        _RS_BTN    = (0.52, 0.44, 0.70, 1.0)

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Nav bar ────────────────────────────────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.076, 0.090),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.075 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.038, 0.038),
                              parent=nav, pos=(-1.55, 0, 0.005))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        _nav_icons = ["games.png", "avatar.png", "shirt.png", "buildd.png", "Settings.png"]
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",    self._build_browse_screen),
            ("Avatar",   self._build_avatar_screen),
            ("Catalog",  self._build_shop_screen),
            ("Workshop", self._build_main_menu),
            ("Settings", self._build_settings_screen),
        ]):
            is_active = (i == 4)
            _btn = DirectButton(
                text="",
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.095, 0.095, -0.072, 0.075),
                parent=nav, pos=((i - 2) * 0.24, 0, 0.005),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
            _it = None
            try:
                _it = self.loader.loadTexture(Filename.fromOsSpecific(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), _nav_icons[i])))
            except Exception:
                pass
            if _it:
                _iw = 0.074 * (_it.getXSize() / max(_it.getYSize(), 1))
                _if2 = DirectFrame(
                    frameTexture=_it, frameColor=(1, 1, 1, 1),
                    frameSize=(-_iw/2, _iw/2, -0.034, 0.034),
                    parent=_btn, pos=(0, 0, 0.022),
                )
                _if2.setTransparency(TransparencyAttrib.MAlpha)
            DirectLabel(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.029,
                frameColor=(0, 0, 0, 0),
                parent=_btn, pos=(0, 0, -0.051),
            )
        _nav_av_tex = self._get_nav_avatar_texture()
        if _nav_av_tex:
            _nav_av_f = DirectFrame(
                frameTexture=_nav_av_tex, frameColor=(1, 1, 1, 1),
                frameSize=(-0.065, 0.065, -0.065, 0.065),
                parent=nav, pos=(1.15, 0, 0.005),
            )
            _nav_av_f.setTransparency(TransparencyAttrib.MAlpha)
            if not hasattr(self, '_nav_avatar_frames'):
                self._nav_avatar_frames = []
            self._nav_avatar_frames.append(_nav_av_f)
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.07, 0, -0.008),
            text_align=TextNode.ARight,
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=(0.48, 0.38, 0.66, 1.0),
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, 0.005),
            relief=1, command=self._do_logout,
        )

        # ── Settings panel ─────────────────────────────────────────────────
        _C_ON     = (0.20, 0.72, 0.38, 1.0)   # toggle ON  (green)
        _C_OFF    = (0.52, 0.44, 0.70, 1.0)   # toggle OFF (purple)
        _C_BTN    = (0.52, 0.44, 0.70, 1.0)   # stepper buttons
        _C_VAL    = (0.48, 0.40, 0.64, 1.0)   # stepper value box
        _C_TITLE  = (0.10, 0.07, 0.28, 1.0)   # panel title
        _C_HDR    = (0.18, 0.12, 0.40, 1.0)   # section header
        _C_LBL    = (0.18, 0.12, 0.40, 1.0)   # row labels
        _C_VAL_T  = (0.95, 0.93, 1.00, 1.0)   # value text (light, on dark bg)

        panel = DirectFrame(
            frameColor=(0.72, 0.68, 0.84, 1.0),
            frameSize=(-0.72, 0.72, -0.86, 0.72),
            parent=bg, pos=(0, 0, 0.0),
        )
        DirectLabel(
            text="Settings",
            text_fg=_C_TITLE, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=panel, pos=(0, 0, 0.60),
        )

        # Divider under title
        DirectFrame(
            frameColor=(0.58, 0.52, 0.74, 1.0),
            frameSize=(-0.64, 0.64, -0.002, 0.002),
            parent=panel, pos=(0, 0, 0.52),
        )

        row_z    = 0.42
        row_step = 0.148

        def section_hdr(label, z):
            DirectLabel(
                text=label,
                text_fg=_C_HDR, text_scale=0.028,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=panel, pos=(-0.68, 0, z),
            )

        def row_toggle(label, attr,
                       on_col=_C_ON, off_col=_C_OFF):
            nonlocal row_z
            z = row_z
            row_z -= row_step
            DirectLabel(
                text=label,
                text_fg=_C_LBL, text_scale=0.026,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=panel, pos=(-0.68, 0, z),
            )
            btn_ref = [None]
            def _toggle(a=attr, br=btn_ref, oc=on_col, fc=off_col):
                new_val = not getattr(self, a)
                setattr(self, a, new_val)
                self.save_settings()
                b = br[0]
                if b and not b.isEmpty():
                    b['text']       = 'ON'  if new_val else 'OFF'
                    b['frameColor'] = oc    if new_val else fc
            btn = DirectButton(
                text='ON' if getattr(self, attr) else 'OFF',
                text_fg=_C_VAL_T, text_scale=0.026,
                frameColor=on_col if getattr(self, attr) else off_col,
                frameSize=(-0.060, 0.060, -0.024, 0.024),
                parent=panel, pos=(0.36, 0, z),
                relief=1, command=_toggle,
            )
            btn_ref[0] = btn

        def row_stepper(label, attr, min_val, max_val, step,
                        fmt='{:.0f}', apply_fn=None):
            nonlocal row_z
            z = row_z
            row_z -= row_step
            DirectLabel(
                text=label,
                text_fg=_C_LBL, text_scale=0.026,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=panel, pos=(-0.68, 0, z),
            )
            val_ref = [None]
            def _set(delta, a=attr, mn=min_val, mx=max_val, vr=val_ref, f=fmt, af=apply_fn):
                new_v = max(mn, min(mx, getattr(self, a) + delta))
                setattr(self, a, new_v)
                if af:
                    af(new_v)
                self.save_settings()
                v = vr[0]
                if v and not v.isEmpty():
                    v['text'] = f.format(new_v)
            DirectButton(
                text='–', text_fg=_C_VAL_T, text_scale=0.030,
                frameColor=_C_BTN,
                frameSize=(-0.030, 0.030, -0.024, 0.024),
                parent=panel, pos=(0.20, 0, z),
                relief=1, command=lambda s=-step: _set(s),
            )
            val_lbl = DirectLabel(
                text=fmt.format(getattr(self, attr)),
                text_fg=_C_VAL_T, text_scale=0.028,
                frameColor=_C_VAL,
                frameSize=(-0.058, 0.058, -0.024, 0.024),
                parent=panel, pos=(0.30, 0, z),
            )
            val_ref[0] = val_lbl
            DirectButton(
                text='+', text_fg=_C_VAL_T, text_scale=0.030,
                frameColor=_C_BTN,
                frameSize=(-0.030, 0.030, -0.024, 0.024),
                parent=panel, pos=(0.40, 0, z),
                relief=1, command=lambda s=step: _set(s),
            )

        # ── Camera ─────────────────────────────────────────────────────────
        section_hdr("Camera", row_z); row_z -= row_step * 0.7
        row_toggle("Play mode — invert vertical",   '_settings_invert_play')
        row_toggle("Editor mode — invert vertical", '_settings_invert_editor')

        # ── Editor Speed ───────────────────────────────────────────────────
        row_z -= row_step * 0.5
        section_hdr("Editor Speed", row_z); row_z -= row_step * 0.7
        row_stepper("Camera speed  (units/s)", '_settings_editor_speed',
                    min_val=1, max_val=200, step=5)

        # ── Field of View ──────────────────────────────────────────────────
        row_z -= row_step * 0.5
        section_hdr("Field of View", row_z); row_z -= row_step * 0.7

        def _apply_fov(v):
            if getattr(self, 'is_playtest', False):
                self.camLens.setFov(v)

        row_stepper("Play mode FOV", '_settings_play_fov',
                    min_val=40, max_val=120, step=5, apply_fn=_apply_fov)

        # ── Rendering ──────────────────────────────────────────────────────
        row_z -= row_step * 0.5
        section_hdr("Rendering", row_z); row_z -= row_step * 0.7
        row_stepper("Render distance  (units)", '_settings_render_distance',
                    min_val=100, max_val=1000, step=50)

    # ── Theme music ────────────────────────────────────────────────────────

    def _ensure_theme_music(self):
        if getattr(self, '_theme_music', None) is None:
            try:
                import os as _os
                from panda3d.core import Filename
                path = Filename.fromOsSpecific(
                    _os.path.join(_os.getcwd(), "PiePlex theme.mp3"))
                m = self.loader.loadMusic(path)
                if m:
                    m.setLoop(True)
                    m.setVolume(0.0)
                    print("[MUSIC] loaded OK")
                else:
                    print("[MUSIC] loadMusic returned None")
                self._theme_music   = m
                self._theme_playing = False
            except Exception as e:
                print(f"[MUSIC] load error: {e}")
                self._theme_music = None
        return getattr(self, '_theme_music', None)

    def _music_fade_in(self, duration=2.5, target=0.70):
        self.taskMgr.remove("_themeMusicFade")
        music = self._ensure_theme_music()
        if not music:
            return
        if not getattr(self, '_theme_playing', False):
            music.setVolume(0.0)
            music.play()
            self._theme_playing = True
        start_vol = music.getVolume()
        elapsed   = [0.0]

        def _fade(task):
            elapsed[0] = min(elapsed[0] + globalClock.getDt(), duration)
            t = elapsed[0] / duration
            music.setVolume(start_vol + (target - start_vol) * t)
            return task.cont if elapsed[0] < duration else task.done

        self.taskMgr.add(_fade, "_themeMusicFade")

    def _music_fade_out(self, duration=1.0):
        self.taskMgr.remove("_themeMusicFade")
        music = getattr(self, '_theme_music', None)
        if not music or not getattr(self, '_theme_playing', False):
            return
        start_vol = music.getVolume()
        elapsed   = [0.0]

        def _fade(task):
            elapsed[0] = min(elapsed[0] + globalClock.getDt(), duration)
            t = elapsed[0] / duration
            music.setVolume(max(0.0, start_vol * (1.0 - t)))
            if elapsed[0] >= duration:
                music.stop()
                self._theme_playing = False
                return task.done
            return task.cont

        self.taskMgr.add(_fade, "_themeMusicFade")

    # ── Browse screen ──────────────────────────────────────────────────────

    def _build_browse_screen(self):
        self._music_fade_in()
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
        self._browse_page        = 0
        self._browse_all_builds  = []
        self._browse_initialized = False
        self._browse_search      = getattr(self, "_browse_search", "")
        self._game_popup         = None

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar ────────────────────────────────────────────────────
        nav = DirectFrame(
            frameColor=_RS_NAV,
            frameSize=(-2.5, 2.5, -0.076, 0.090),
            parent=bg, pos=(0, 0, 0.908),
        )
        _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PiePlex logo.png')))
        if _lt:
            _lw = 0.075 * (_lt.getXSize() / max(_lt.getYSize(), 1))
            _lf = DirectFrame(frameTexture=_lt, frameColor=(1,1,1,1),
                              frameSize=(-_lw/2, _lw/2, -0.038, 0.038),
                              parent=nav, pos=(-1.55, 0, 0.005))
            _lf.setTransparency(TransparencyAttrib.MAlpha)
        # Tabs centred around x=0
        _nav_icons = ["games.png", "avatar.png", "shirt.png", "buildd.png", "Settings.png"]
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",    self._build_browse_screen),
            ("Avatar",   self._build_avatar_screen),
            ("Catalog",  self._build_shop_screen),
            ("Workshop", self._build_main_menu),
            ("Settings", self._build_settings_screen),
        ]):
            is_active = (i == 0)
            _btn = DirectButton(
                text="",
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.095, 0.095, -0.072, 0.075),
                parent=nav, pos=((i - 2) * 0.24, 0, 0.005),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
            _it = None
            try:
                _it = self.loader.loadTexture(Filename.fromOsSpecific(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), _nav_icons[i])))
            except Exception:
                pass
            if _it:
                _iw = 0.074 * (_it.getXSize() / max(_it.getYSize(), 1))
                _if2 = DirectFrame(
                    frameTexture=_it, frameColor=(1, 1, 1, 1),
                    frameSize=(-_iw/2, _iw/2, -0.034, 0.034),
                    parent=_btn, pos=(0, 0, 0.022),
                )
                _if2.setTransparency(TransparencyAttrib.MAlpha)
            DirectLabel(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.029,
                frameColor=(0, 0, 0, 0),
                parent=_btn, pos=(0, 0, -0.051),
            )
        _nav_av_tex = self._get_nav_avatar_texture()
        if _nav_av_tex:
            _nav_av_f = DirectFrame(
                frameTexture=_nav_av_tex, frameColor=(1, 1, 1, 1),
                frameSize=(-0.065, 0.065, -0.065, 0.065),
                parent=nav, pos=(1.15, 0, 0.005),
            )
            _nav_av_f.setTransparency(TransparencyAttrib.MAlpha)
            if not hasattr(self, '_nav_avatar_frames'):
                self._nav_avatar_frames = []
            self._nav_avatar_frames.append(_nav_av_f)
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.07, 0, -0.008),
            text_align=TextNode.ARight,
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.55, 0, 0.005),
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
        _bse = DirectEntry(
            text="", initialText=self._browse_search or "Search...",
            width=14, numLines=1, scale=0.028,
            text_fg=(0.15, 0.10, 0.25, 1),
            frameColor=(0.93, 0.91, 0.97, 1),
            relief=1,
            parent=bg, pos=(0.76, 0, 0.745),
            command=self._on_game_search,
            focusInCommand=lambda e=None: _bse.enterText("") if _bse.get() == "Search..." else None,
            focusOutCommand=lambda e=None: _bse.enterText("Search...") if not _bse.get().strip() else None,
        )
        self._browse_search_entry = _bse

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

    def _on_game_search(self, text):
        self._browse_search = text.strip()
        self._browse_page = 0
        self._draw_game_grid()

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
        if not getattr(self, "_browse_initialized", False):
            self._browse_page = 0
            self._browse_initialized = True
        else:
            max_pg = max(0, (len(builds) - 1) // _PAGE_SIZE)
            self._browse_page = min(getattr(self, "_browse_page", 0), max_pg)
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
        q = getattr(self, "_browse_search", "").strip().lower()
        if q:
            builds = [b for b in builds if q in (b.get("name") or "").lower()]
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
            extraArgs=[build["id"], build.get("name", ""), build.get("thumbnail") or ""],
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

    def _popup_play(self, build_id, name="", thumbnail=""):
        self._close_game_info_popup()
        self._on_play_published(build_id, name, thumbnail)

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
        self._music_fade_out(1.2)
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._is_play_only     = True
        self._cloud_build_id   = None
        self._cloud_build_name = None
        self._show_studio_ui()
        # Hide the black top bar in online play — Menu and Chat buttons are
        # parented directly to a2dTopLeft so they stay visible without the bar.
        tb = getattr(self, "_top_bg", None)
        if tb:
            tb.hide()
        sl = getattr(self, "_status_lbl", None)
        if sl:
            sl.hide()
        self._setup_play_hud()
        mb = getattr(self, "menu_button", None)
        if mb:
            mb.reparentTo(base.a2dTopLeft)
            mb.setPos(0.070, 0, -0.045)
            mb['frameColor'] = (0.15, 0.17, 0.20, 0.62)
            mb['text_fg']    = (0.88, 0.90, 0.95, 1.0)
            mb.show()
        for attr in ("exit_button", "insert_brick_button", "move_button",
                     "scale_button", "rotate_button", "export_button", "import_button",
                     "cloud_save_button", "hat_config_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.hide()
        self.is_playtest = True
        self._apply_hat_mode()
        self._panel.hide()
        self.character.show()
        try:
            self._load_bricks_from_data(json.loads(data_str))
        except Exception as e:
            print("Solo load error:", e)
        self.character.setPos(0, 0, 50)
        self.spawn_unstuck()
        self.cam_distance = 20
        self.cam_angle.set(0, 20)
        self.camLens.setFov(getattr(self, '_settings_play_fov', 80))
        self.updateCamera()
        self._entering_play_mode = False
        # Restore equipped T-shirt, hat, and shirt for solo play
        ts_id = getattr(self, "_equipped_tshirt_id", None)
        if ts_id and hasattr(self, "apply_tshirt"):
            def _solo_ts(eid=ts_id):
                item, _ = auth_client.get_shop_item(eid)
                if item and item.get("image_data"):
                    b64 = item["image_data"]
                    self.taskMgr.doMethodLater(
                        0, lambda task, _b=b64: (self.apply_tshirt(_b), task.done)[1],
                        "_soloRestoreTs", appendTask=True)
            threading.Thread(target=_solo_ts, daemon=True).start()
        ht_id = getattr(self, "_equipped_hat_id", None)
        if ht_id and hasattr(self, "apply_hat"):
            def _solo_hat(hid=ht_id):
                item, _ = auth_client.get_shop_item(hid)
                hd = self._item_hat_data_json(item) if item else None
                if hd:
                    self.taskMgr.doMethodLater(
                        0, lambda task, _h=hd: (self.apply_hat(_h), task.done)[1],
                        "_soloRestoreHat", appendTask=True)
            threading.Thread(target=_solo_hat, daemon=True).start()
        sh_id = getattr(self, "_equipped_shirt_id", None)
        if sh_id and hasattr(self, "apply_shirt"):
            def _solo_shirt(sid=sh_id):
                item, _ = auth_client.get_shop_item(sid)
                if item and item.get("image_data"):
                    img = item["image_data"]
                    b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                    self.taskMgr.doMethodLater(
                        0, lambda task, _b=b64: (self.apply_shirt(_b), task.done)[1],
                        "_soloRestoreShirt", appendTask=True)
            threading.Thread(target=_solo_shirt, daemon=True).start()
        pt_id  = getattr(self, "_equipped_pants_id",  None)
        pt_b64 = getattr(self, "_equipped_pants_b64", None)
        if pt_id and hasattr(self, "apply_pants"):
            if pt_b64:
                self.taskMgr.doMethodLater(
                    0, lambda task, _b=pt_b64: (self.apply_pants(_b), task.done)[1],
                    "_soloRestorePants", appendTask=True)
            else:
                def _solo_pants(pid=pt_id):
                    item, _ = auth_client.get_shop_item(pid)
                    if item and item.get("image_data"):
                        img = item["image_data"]
                        b64 = img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in img else img
                        self._equipped_pants_b64 = b64
                        self.taskMgr.doMethodLater(
                            0, lambda task, _b=b64: (self.apply_pants(_b), task.done)[1],
                            "_soloRestorePants", appendTask=True)
                threading.Thread(target=_solo_pants, daemon=True).start()
        return task.done

    def _show_loading_screen(self, name="", thumbnail=""):
        self._hide_loading_screen()
        overlay = DirectFrame(
            frameColor=(0.05, 0.04, 0.10, 0.96),
            frameSize=(-2, 2, -2, 2),
            sortOrder=200,
        )
        self._loading_overlay = overlay
        CARD_W = 0.82
        TH_W   = CARD_W - 0.06
        TH_H   = TH_W * 9 / 16
        CARD_H = TH_H + 0.18
        card = DirectFrame(
            frameColor=(0.12, 0.10, 0.18, 1.0),
            frameSize=(-CARD_W/2, CARD_W/2, -CARD_H/2, CARD_H/2),
            parent=overlay,
            pos=(0, 0, 0.04),
        )
        thumb = DirectFrame(
            frameColor=(0.20, 0.18, 0.28, 1.0),
            frameSize=(-TH_W/2, TH_W/2, -TH_H/2, TH_H/2),
            parent=card,
            pos=(0, 0, CARD_H/2 - TH_H/2 - 0.03),
        )
        if thumbnail:
            try:
                import base64 as _b64
                _raw = _b64.b64decode(thumbnail)
                _ss  = StringStream(_raw)
                _pnm = PNMImage()
                if _pnm.read(_ss):
                    _tex = Texture()
                    _tex.load(_pnm)
                    _tex.setMinfilter(Texture.FTLinear)
                    _tex.setMagfilter(Texture.FTLinear)
                    # Attach directly to aspect2d at sort=201 (above overlay at 200)
                    # so it's never affected by the overlay's render state.
                    _tp = thumb.getPos(base.aspect2d)
                    _cm = CardMaker("loading_thumb")
                    _cm.setFrame(-TH_W / 2, TH_W / 2, -TH_H / 2, TH_H / 2)
                    _cnp = base.aspect2d.attachNewNode(_cm.generate(), 201)
                    _cnp.setTexture(_tex, 1)
                    _cnp.setTransparency(TransparencyAttrib.MAlpha)
                    _cnp.setPos(_tp.x, 0, _tp.z)
                    self._loading_thumb_np = _cnp
                else:
                    print("[THUMB] loading screen: PNMImage.read failed", flush=True)
            except Exception as _e:
                print(f"[THUMB] loading screen error: {_e}", flush=True)
        disp_name = ((name[:30] + "…") if len(name) > 32 else name) if name else ""
        if disp_name:
            DirectLabel(
                text=disp_name,
                text_fg=(0.95, 0.92, 1.00, 1.0),
                text_scale=0.038,
                frameColor=(0, 0, 0, 0),
                parent=card,
                pos=(0, 0, -CARD_H/2 + 0.12),
            )
        self._loading_label = DirectLabel(
            text="Loading",
            text_fg=(0.60, 0.50, 0.80, 1.0),
            text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=card,
            pos=(0, 0, -CARD_H/2 + 0.055),
        )
        self._loading_dot_t = 0.0

        def _anim(task):
            lbl = getattr(self, '_loading_label', None)
            if lbl is None:
                return task.done
            try:
                self._loading_dot_t += globalClock.getDt()
                if self._loading_dot_t >= 0.35:
                    self._loading_dot_t -= 0.35
                    dots = "." * (int(task.time / 0.35) % 4)
                    lbl["text"] = f"Loading{dots}"
            except Exception:
                return task.done
            return task.cont

        self.taskMgr.add(_anim, "_loadingAnimTask")

    def _hide_loading_screen(self):
        try:
            self.taskMgr.remove("_loadingAnimTask")
        except Exception:
            pass
        self._loading_label = None
        tnp = getattr(self, '_loading_thumb_np', None)
        if tnp:
            try:
                tnp.removeNode()
            except Exception:
                pass
        self._loading_thumb_np = None
        overlay = getattr(self, '_loading_overlay', None)
        if overlay:
            try:
                overlay.destroy()
            except Exception:
                pass
        self._loading_overlay = None

    def _on_play_published(self, build_id, name="", thumbnail=""):
        if getattr(self, "_entering_play_mode", False):
            return
        self._entering_play_mode = True
        self._show_loading_screen(name, thumbnail)
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
                self.taskMgr.doMethodLater(
                    0, lambda t: (self._hide_loading_screen(), None)[1] or t.done,
                    "_hideLoadFail", appendTask=True,
                )
        threading.Thread(target=worker, daemon=True).start()

    def _do_enter_play_mode(self, build_id, name, data_str, task):
        self._hide_loading_screen()
        self._enter_play_mode(build_id, name, data_str)
        return task.done

    def _enter_play_mode(self, build_id, name, data_str):
        """Load a published build and enter play-only mode (no editor)."""
        self._music_fade_out(1.2)
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._is_play_only     = True
        self._cloud_build_id   = None
        self._cloud_build_name = None

        self._show_studio_ui()
        # Hide the black top bar in online play — Menu and Chat buttons are
        # parented directly to a2dTopLeft so they stay visible without the bar.
        tb = getattr(self, "_top_bg", None)
        if tb:
            tb.hide()
        sl = getattr(self, "_status_lbl", None)
        if sl:
            sl.hide()
        self._setup_play_hud()
        mb = getattr(self, "menu_button", None)
        if mb:
            mb.reparentTo(base.a2dTopLeft)
            mb.setPos(0.070, 0, -0.045)
            mb['frameColor'] = (0.15, 0.17, 0.20, 0.62)
            mb['text_fg']    = (0.88, 0.90, 0.95, 1.0)
            mb.show()
        # Hide all editor controls — only the Menu button stays
        for attr in ("exit_button", "insert_brick_button", "move_button",
                     "scale_button", "rotate_button", "export_button", "import_button",
                     "cloud_save_button", "hat_config_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.hide()

        self.is_playtest = True
        self._apply_hat_mode()
        self._panel.hide()
        # Restore equipped T-shirt (fetched from server during login sync)
        equipped_id = getattr(self, "_equipped_tshirt_id", None)
        if equipped_id and hasattr(self, "apply_tshirt"):
            def _load_tshirt(eid=equipped_id):
                item, _ = auth_client.get_shop_item(eid)
                if item and item.get("image_data"):
                    b64 = item["image_data"]
                    self.taskMgr.doMethodLater(
                        0, lambda task, _b=b64: (self.apply_tshirt(_b), task.done)[1],
                        "_restoreEquippedTshirt", appendTask=True,
                    )
            threading.Thread(target=_load_tshirt, daemon=True).start()
        # Restore equipped hat
        hat_id = getattr(self, "_equipped_hat_id", None)
        if hat_id and hasattr(self, "apply_hat"):
            def _load_hat(hid=hat_id):
                item, _ = auth_client.get_shop_item(hid)
                hd = self._item_hat_data_json(item) if item else None
                if hd:
                    self.taskMgr.doMethodLater(
                        0, lambda task, _h=hd: (self.apply_hat(_h), task.done)[1],
                        "_restoreEquippedHat", appendTask=True,
                    )
            threading.Thread(target=_load_hat, daemon=True).start()
        # Restore equipped shirt
        shirt_id = getattr(self, "_equipped_shirt_id", None)
        print(f"[SHIRT_DBG] _enter_play_mode: _equipped_shirt_id={shirt_id}", flush=True)
        if shirt_id and hasattr(self, "apply_shirt"):
            def _load_shirt(sid=shirt_id):
                print(f"[SHIRT_DBG] fetching shop item {sid}", flush=True)
                item, _ = auth_client.get_shop_item(sid)
                print(f"[SHIRT_DBG] get_shop_item returned: item={item is not None}, has_image={bool((item or {}).get('image_data'))}", flush=True)
                if item and item.get("image_data"):
                    img = item["image_data"]
                    b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                    print(f"[SHIRT_DBG] scheduling apply_shirt, b64 len={len(b64)}", flush=True)
                    self.taskMgr.doMethodLater(
                        0, lambda task, _b=b64: (self.apply_shirt(_b), task.done)[1],
                        "_restoreEquippedShirt", appendTask=True,
                    )
            threading.Thread(target=_load_shirt, daemon=True).start()
        pants_id  = getattr(self, "_equipped_pants_id",  None)
        pants_b64 = getattr(self, "_equipped_pants_b64", None)
        if pants_id and hasattr(self, "apply_pants"):
            if pants_b64:
                self.taskMgr.doMethodLater(
                    0, lambda task, _b=pants_b64: (self.apply_pants(_b), task.done)[1],
                    "_restoreEquippedPants", appendTask=True)
            else:
                def _load_pants(pid=pants_id):
                    item, _ = auth_client.get_shop_item(pid)
                    if item and item.get("image_data"):
                        img = item["image_data"]
                        b64 = img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in img else img
                        self._equipped_pants_b64 = b64
                        self.taskMgr.doMethodLater(
                            0, lambda task, _b=b64: (self.apply_pants(_b), task.done)[1],
                            "_restoreEquippedPants", appendTask=True)
                threading.Thread(target=_load_pants, daemon=True).start()
        try:
            self._load_bricks_from_data(json.loads(data_str))
        except Exception as e:
            print("Play-mode load error:", e)
        self.character.setPos(0, 0, 50)
        self.spawn_unstuck()
        # Show character only after it's been placed at the correct spawn position
        self.character.show()
        self.cam_distance = 20
        self.cam_angle.set(0, 20)
        self.camLens.setFov(getattr(self, '_settings_play_fov', 80))
        self.updateCamera()
        self._apply_hat_mode()
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
        self._teardown_play_hud()
        sl = getattr(self, "_status_lbl", None)
        if sl:
            sl.show()
        self.stop_multiplayer()
        for pid in list(getattr(self, "_remote_players", {}).keys()):
            self._remove_remote_player(pid)
        self._remote_players = {}
        self.character.hide()
        self.is_playtest   = False
        self._apply_hat_mode()
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
        self._apply_hat_mode()
        if hasattr(self, "exit_button"):
            self.exit_button["text"] = "Play"
        if hasattr(self, "_panel"):
            self._panel.show()
        for attr in ("exit_button", "insert_brick_button", "move_button", "scale_button",
                     "rotate_button", "export_button", "import_button", "cloud_save_button"):
            btn = getattr(self, attr, None)
            if btn:
                btn.show()
        if getattr(self, '_session_username', None) == "bob":
            btn = getattr(self, 'hat_config_button', None)
            if btn:
                btn.show()
        self.camera.setPos(0, -30, 18)
        self.camera.lookAt(Point3(0, 0, 1))
        self.camLens.setFov(getattr(self, '_settings_play_fov', 80))

    def _do_logout(self):
        token = self._session_token
        self._session_token    = None
        self._session_username = None
        self._equipped_tshirt_id  = None
        self._equipped_hat_id     = None
        self._equipped_shirt_id   = None
        self._equipped_pants_id   = None
        self._equipped_pants_b64  = None
        if hasattr(self, 'remove_tshirt'):
            self.remove_tshirt()
        if hasattr(self, 'remove_hat'):
            self.remove_hat()
        if hasattr(self, 'remove_shirt'):
            self.remove_shirt()
        if hasattr(self, 'remove_pants'):
            self.remove_pants()
        self._delete_saved_token()
        self._nav_av_cleanup()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()
            self._main_menu_ui = None
        self._build_login_ui()
        if token:
            threading.Thread(
                target=lambda: auth_client.logout(token), daemon=True,
            ).start()
