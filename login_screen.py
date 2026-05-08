import atexit
import datetime
import json
import os
import subprocess
import sys
import threading
import time

from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectEntry, DirectButton
from panda3d.core import Point3, TextNode

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
_RS_BG      = (0.06, 0.05, 0.10, 1.0)
_RS_NAV     = (0.09, 0.07, 0.15, 1.0)
_RS_CARD    = (0.13, 0.11, 0.21, 1.0)
_RS_ORANGE  = (0.91, 0.47, 0.13, 1.0)
_RS_BORDER  = (0.18, 0.14, 0.28, 1.0)
_RS_WHITE   = (1.00, 1.00, 1.00, 1.0)
_RS_GRAY    = (0.58, 0.56, 0.65, 1.0)
_RS_GREEN   = (0.27, 0.82, 0.43, 1.0)
_RS_RED     = (0.85, 0.18, 0.18, 1.0)
_THUMB_TINTS = [
    (0.22, 0.12, 0.38, 1), (0.10, 0.18, 0.40, 1),
    (0.12, 0.28, 0.20, 1), (0.36, 0.14, 0.10, 1),
    (0.28, 0.10, 0.38, 1), (0.10, 0.26, 0.40, 1),
    (0.18, 0.32, 0.12, 1), (0.36, 0.18, 0.28, 1),
]
_GRID_COLS  = 5
_CARD_W     = 0.60
_CARD_TH    = 0.34   # thumbnail height portion
_CARD_INFO  = 0.16   # text area height below thumbnail
_CARD_H     = _CARD_TH + _CARD_INFO  # 0.50
_CARD_GAP_X = 0.04
_CARD_GAP_Y = 0.04
_PAGE_SIZE  = 15     # 5 cols × 3 rows


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
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and ":8000" in parts[1] and parts[3] == "LISTENING":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", parts[4]],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
        except Exception:
            pass

    _REQUIRED_SERVER_API_VERSION = 4

    def _start_server(self):
        # If a working server is already running, check it has the latest API.
        result, _ = auth_client.browse_published()
        if result is not None:
            rooms_result, _ = auth_client.get_rooms()
            if rooms_result is not None:
                sv_result, _ = auth_client.get_server_version()
                if sv_result and sv_result.get("api_version", 0) >= self._REQUIRED_SERVER_API_VERSION:
                    return   # server is current — leave it alone
            # Server is running but outdated — fall through to kill + restart

        # Use a lock file so two instances that start simultaneously don't both
        # kill-and-restart the server.  Only the winner does the actual launch;
        # the loser waits up to 10 s for the server to come up.
        try:
            fd = os.open(_SERVER_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            owns_lock = True
        except FileExistsError:
            owns_lock = False

        if not owns_lock:
            for _ in range(20):           # 20 × 0.5 s = 10 s
                time.sleep(0.5)
                result, _ = auth_client.browse_published()
                if result is not None:
                    return
            # Stale lock (game crashed mid-start) — clean up and take over.
            try:
                os.remove(_SERVER_LOCK)
            except Exception:
                pass
            result, _ = auth_client.browse_published()
            if result is not None:
                return

        try:
            self._kill_port_8000()
            server_py = os.path.join(_HERE, "server.py")
            log_path  = os.path.join(_USER_DATA, "server_log.txt")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self._server_log = open(log_path, "w")
                self._server_proc = subprocess.Popen(
                    [sys.executable, server_py],
                    stdout=self._server_log,
                    stderr=self._server_log,
                    creationflags=flags,
                )
                atexit.register(self._stop_server)
            except Exception:
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
            frameColor=DARKER,
            frameSize=(-3, 3, -3, 3),
        )
        DirectLabel(
            text="PhoenixHill",
            text_fg=TEXT, text_scale=0.090,
            frameColor=(0, 0, 0, 0),
            parent=self._splash, pos=(0, 0, 0.08),
        )
        DirectLabel(
            text=sub,
            text_fg=TEXT_D, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._splash, pos=(0, 0, -0.06),
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

        # Full-screen backdrop so the 3D world doesn't show through.
        root = DirectFrame(
            frameColor=DARKER,
            frameSize=(-3, 3, -3, 3),
        )
        self._login_ui = root

        # Card centered on the backdrop.
        root = DirectFrame(
            frameColor=DARK,
            frameSize=(-0.54, 0.54, -0.46, 0.46),
            parent=self._login_ui,
        )

        DirectLabel(
            text="PhoenixHill",
            text_fg=TEXT, text_scale=0.072,
            frameColor=(0, 0, 0, 0),
            parent=root, pos=(0, 0, 0.30),
        )
        DirectLabel(
            text="Username",
            text_fg=TEXT, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=root, pos=(-0.20, 0, 0.175),
        )
        self._u_entry = DirectEntry(
            text_fg=TEXT, text_scale=0.040,
            frameColor=MED,
            width=16, numLines=1,
            parent=root, pos=(-0.38, 0, 0.10),
            initialText="",
            focus=1,
        )
        DirectLabel(
            text="Password",
            text_fg=TEXT, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=root, pos=(-0.20, 0, 0.005),
        )
        self._p_entry = DirectEntry(
            text_fg=TEXT, text_scale=0.040,
            frameColor=MED,
            width=16, numLines=1,
            parent=root, pos=(-0.38, 0, -0.07),
            initialText="",
            obscured=1,
            command=self._on_enter_pressed,
        )
        self._login_status = DirectLabel(
            text="",
            text_fg=RED, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=root, pos=(0, 0, -0.17),
        )
        DirectButton(
            text="Log In",
            text_fg=TEXT, text_scale=0.042,
            frameColor=SEL,
            frameSize=(-0.155, 0.155, -0.038, 0.038),
            parent=root, pos=(-0.19, 0, -0.27),
            command=self._do_login, relief=1,
        )
        DirectButton(
            text="Sign Up",
            text_fg=TEXT, text_scale=0.042,
            frameColor=BTN,
            frameSize=(-0.155, 0.155, -0.038, 0.038),
            parent=root, pos=(0.19, 0, -0.27),
            command=self._do_register, relief=1,
        )

    def _on_enter_pressed(self, _text):
        self._do_login()

    def _set_status(self, msg, color=None):
        if color is None:
            color = RED
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
        self._set_status("Logging in…", TEXT_D)
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
        self._set_status("Registering…", TEXT_D)
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
        self._join_splash = DirectFrame(frameColor=DARKER, frameSize=(-3, 3, -3, 3))
        DirectLabel(
            text="PhoenixHill",
            text_fg=TEXT, text_scale=0.090,
            frameColor=(0, 0, 0, 0),
            parent=self._join_splash, pos=(0, 0, 0.08),
        )
        self._join_status_lbl = DirectLabel(
            text="Finding a server…",
            text_fg=TEXT_D, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=self._join_splash, pos=(0, 0, -0.06),
        )
        DirectButton(
            text="Browse servers instead",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=BTN,
            frameSize=(-0.22, 0.22, -0.030, 0.030),
            parent=self._join_splash, pos=(0, 0, -0.20),
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
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        # Full-screen backdrop
        bg = DirectFrame(frameColor=DARKER, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # Centered card
        card = DirectFrame(
            frameColor=DARK,
            frameSize=(-0.78, 0.78, -0.62, 0.60),
            parent=bg,
        )

        DirectLabel(
            text="PhoenixHill",
            text_fg=TEXT, text_scale=0.078,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.46),
        )
        DirectLabel(
            text=f"Welcome, {self._session_username}",
            text_fg=TEXT_D, text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.34),
        )
        DirectLabel(
            text="My Builds",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.44, 0, 0.24),
        )

        # Build list area (populated after fetch)
        self._build_list_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-0.74, 0.74, -0.36, 0),
            parent=card, pos=(0, 0, 0.22),
        )
        self._build_list_status = DirectLabel(
            text="Loading…",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=self._build_list_frame, pos=(0, 0, -0.06),
        )

        # Bottom buttons
        DirectButton(
            text="< Play",
            text_fg=TEXT, text_scale=0.038,
            frameColor=(0.14, 0.42, 0.22, 1.0),
            frameSize=(-0.18, 0.18, -0.036, 0.036),
            parent=card, pos=(0, 0, -0.40),
            command=self._build_browse_screen, relief=1,
        )
        DirectButton(
            text="New Build",
            text_fg=TEXT, text_scale=0.044,
            frameColor=SEL,
            frameSize=(-0.18, 0.18, -0.042, 0.042),
            parent=card, pos=(-0.22, 0, -0.52),
            command=self._enter_studio, relief=1,
        )
        DirectButton(
            text="Log Out",
            text_fg=TEXT_D, text_scale=0.038,
            frameColor=BTN,
            frameSize=(-0.14, 0.14, -0.036, 0.036),
            parent=card, pos=(0.22, 0, -0.52),
            command=self._do_logout, relief=1,
        )

        # Fetch builds in background
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
                text="No saves yet" if not err else f"Error: {err}",
                text_fg=TEXT_D, text_scale=0.034,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, -0.06),
            )
            return task.done

        ROW_H = 0.072
        MED_L = (0.17, 0.19, 0.26, 1.0)
        PUB_C = (0.14, 0.42, 0.22, 1.0)
        for i, build in enumerate(builds[:5]):
            y = -(i + 0.5) * ROW_H
            is_pub = bool(build.get("published", 0))
            DirectFrame(
                frameColor=MED_L,
                frameSize=(-0.74, 0.74, -ROW_H / 2, ROW_H / 2),
                parent=frame, pos=(0, 0, y),
            )
            name = build["name"]
            if len(name) > 16:
                name = name[:14] + "…"
            ts = datetime.datetime.fromtimestamp(build["updated_at"]).strftime("%b %d")
            DirectLabel(
                text=f"{name}  {ts}",
                text_fg=TEXT, text_scale=0.028,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-0.70, 0, y - 0.010),
            )
            DirectButton(
                text="Settings",
                text_fg=TEXT, text_scale=0.022,
                frameColor=(0.22, 0.22, 0.34, 1.0),
                frameSize=(-0.058, 0.058, -0.022, 0.022),
                parent=frame, pos=(0.12, 0, y),
                command=self._open_game_settings,
                extraArgs=[build["id"], build["name"]], relief=1,
            )
            DirectButton(
                text="Unpub" if is_pub else "Pub",
                text_fg=TEXT, text_scale=0.022,
                frameColor=PUB_C if is_pub else BTN,
                frameSize=(-0.050, 0.050, -0.022, 0.022),
                parent=frame, pos=(0.30, 0, y),
                command=self._on_toggle_publish,
                extraArgs=[build["id"], not is_pub], relief=1,
            )
            DirectButton(
                text="Load",
                text_fg=TEXT, text_scale=0.022,
                frameColor=SEL,
                frameSize=(-0.050, 0.050, -0.022, 0.022),
                parent=frame, pos=(0.46, 0, y),
                command=self._on_load_build,
                extraArgs=[build["id"]], relief=1,
            )
            DirectButton(
                text="Del",
                text_fg=TEXT, text_scale=0.022,
                frameColor=(0.45, 0.14, 0.14, 1.0),
                frameSize=(-0.044, 0.044, -0.022, 0.022),
                parent=frame, pos=(0.60, 0, y),
                command=self._on_delete_build,
                extraArgs=[build["id"]], relief=1,
            )
        return task.done

    def _open_game_settings(self, build_id, build_name):
        """Open the game settings popup for thumbnail + description."""
        existing = getattr(self, "_settings_popup", None)
        if existing:
            try:
                existing.destroy()
            except Exception:
                pass
        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.80),
            frameSize=(-3, 3, -3, 3),
            sortOrder=80,
        )
        self._settings_popup = overlay
        card = DirectFrame(
            frameColor=DARK,
            frameSize=(-0.72, 0.72, -0.52, 0.52),
            parent=overlay, sortOrder=81,
        )
        DirectLabel(
            text=f"Game Settings — {build_name[:22]}",
            text_fg=TEXT, text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.40),
        )
        # Description label + entry
        DirectLabel(
            text="Description",
            text_fg=TEXT_D, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.48, 0, 0.24),
        )
        desc_entry = DirectEntry(
            text_fg=TEXT, text_scale=0.030,
            frameColor=MED,
            width=28, numLines=1,
            parent=card, pos=(-0.68, 0, 0.16),
            initialText="",
        )
        # Thumbnail path label + entry
        DirectLabel(
            text="Thumbnail path (PNG/JPG, 1920×1080)",
            text_fg=TEXT_D, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.28, 0, 0.04),
        )
        thumb_entry = DirectEntry(
            text_fg=TEXT, text_scale=0.028,
            frameColor=MED,
            width=30, numLines=1,
            parent=card, pos=(-0.68, 0, -0.04),
            initialText="",
        )
        DirectLabel(
            text="Paste the full file path to your image.",
            text_fg=TEXT_D, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.14),
        )
        self._settings_status = DirectLabel(
            text="",
            text_fg=GREEN, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.24),
        )
        # Load existing settings in background
        def _load():
            res, _ = auth_client.get_game_settings(self._session_token, build_id)
            if res:
                def _apply(task, r=res):
                    if desc_entry and not desc_entry.isEmpty():
                        desc_entry.set(r.get("description", ""))
                    return task.done
                self.taskMgr.doMethodLater(0, _apply, "_applySettings", appendTask=True)
        threading.Thread(target=_load, daemon=True).start()

        def _save():
            desc_text  = desc_entry.get().strip()
            thumb_path = thumb_entry.get().strip()
            thumb_b64  = ""
            if thumb_path:
                try:
                    import base64
                    with open(thumb_path, "rb") as f:
                        thumb_b64 = base64.b64encode(f.read()).decode()
                except Exception as e:
                    lbl = self._settings_status
                    if lbl and not lbl.isEmpty():
                        lbl["text"] = f"Image error: {e}"
                        lbl["text_fg"] = RED
                    return
            lbl = self._settings_status
            if lbl and not lbl.isEmpty():
                lbl["text"] = "Saving…"
                lbl["text_fg"] = TEXT_D
            def worker():
                res, err = auth_client.put_game_settings(
                    self._session_token, build_id, thumb_b64, desc_text)
                def _done(task, ok=(res is not None), err=err):
                    l = getattr(self, "_settings_status", None)
                    if l and not l.isEmpty():
                        l["text"] = "Saved!" if ok else f"Error: {err}"
                        l["text_fg"] = GREEN if ok else RED
                    return task.done
                self.taskMgr.doMethodLater(0, _done, "_settingsDone", appendTask=True)
            threading.Thread(target=worker, daemon=True).start()

        DirectButton(
            text="Save",
            text_fg=TEXT, text_scale=0.036,
            frameColor=SEL,
            frameSize=(-0.14, 0.14, -0.036, 0.036),
            parent=card, pos=(-0.22, 0, -0.38),
            command=_save, relief=1,
        )
        DirectButton(
            text="Cancel",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=BTN,
            frameSize=(-0.12, 0.12, -0.034, 0.034),
            parent=card, pos=(0.24, 0, -0.38),
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

    # ── Browse screen ──────────────────────────────────────────────────────

    def _build_browse_screen(self):
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
        DirectLabel(
            text="PhoenixHill",
            text_fg=_RS_WHITE, text_scale=0.044,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(-1.84, 0, -0.018),
        )
        for i, (tab_text, tab_cmd) in enumerate([
            ("Games",  self._build_browse_screen),
            ("Avatar", self._build_avatar_screen),
            ("Build",  self._build_main_menu),
        ]):
            is_active = (i == 0)
            DirectButton(
                text=tab_text,
                text_fg=_RS_WHITE if is_active else _RS_GRAY,
                text_scale=0.034,
                frameColor=_RS_ORANGE if is_active else (0, 0, 0, 0),
                frameSize=(-0.10, 0.10, -0.052, 0.052),
                parent=nav, pos=(-0.88 + i * 0.34, 0, -0.008),
                relief=1 if is_active else 0,
                command=tab_cmd,
            )
        DirectLabel(
            text=self._session_username or "",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.52, 0, -0.014),
        )
        DirectButton(
            text="Log Out",
            text_fg=_RS_WHITE, text_scale=0.026,
            frameColor=_RS_BORDER,
            frameSize=(-0.082, 0.082, -0.026, 0.026),
            parent=nav, pos=(1.84, 0, -0.014),
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
            text="◄",
            text_fg=_RS_WHITE, text_scale=0.038,
            frameColor=_RS_NAV,
            frameSize=(-0.052, 0.052, -0.034, 0.034),
            parent=bg, pos=(-0.20, 0, -0.913),
            relief=1, command=self._browse_prev_page,
        )
        self._page_lbl = DirectLabel(
            text="Page 1",
            text_fg=_RS_GRAY, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=bg, pos=(0, 0, -0.913),
        )
        self._next_page_btn = DirectButton(
            text="►",
            text_fg=_RS_WHITE, text_scale=0.038,
            frameColor=_RS_NAV,
            frameSize=(-0.052, 0.052, -0.034, 0.034),
            parent=bg, pos=(0.20, 0, -0.913),
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
                short  = (name[:12] + "…") if len(name) > 14 else name

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
                    text=short,
                    text_fg=_RS_WHITE, text_scale=0.026,
                    text_align=TextNode.ALeft,
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
                # Online count dot
                count_col = _RS_GREEN if online else (_RS_GRAY[0], _RS_GRAY[1], _RS_GRAY[2], 0.5)
                DirectLabel(
                    text=f"● {online}" if online else "●",
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
        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=60,
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
            text="✕",
            text_fg=_RS_WHITE, text_scale=0.036,
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
            text="▶  Play",
            text_fg=_RS_WHITE, text_scale=0.040,
            frameColor=_RS_ORANGE,
            frameSize=(-TH_W/2, TH_W/2, -0.054, 0.054),
            parent=card, pos=(TH_CX, 0, PLAY_Y),
            relief=1,
            command=self._popup_play,
            extraArgs=[build["id"]],
        )
        DirectButton(
            text="Play Solo",
            text_fg=_RS_GRAY, text_scale=0.028,
            frameColor=_RS_BORDER,
            frameSize=(-TH_W/4, TH_W/4, -0.030, 0.030),
            parent=card, pos=(TH_CX, 0, PLAY_Y - 0.100),
            relief=1,
            command=self._popup_play_solo,
            extraArgs=[build["id"]],
        )

        # Right column — info
        RX = 0.16
        title = build["name"]
        if len(title) > 24:
            title = title[:22] + "…"
        DirectLabel(
            text=title,
            text_fg=_RS_WHITE, text_scale=0.044,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(RX, 0, HH - 0.14),
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
            desc_short = (desc[:80] + "…") if len(desc) > 80 else desc
            DirectLabel(
                text=desc_short,
                text_fg=_RS_GRAY, text_scale=0.024,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(RX, 0, HH - 0.32 - len(info_rows) * 0.12 - 0.06),
            )

    def _apply_thumbnail_texture(self, frame_np, b64_data):
        """Decode a base64 image and apply it as a texture to a DirectFrame NodePath."""
        try:
            import base64, tempfile, os
            from panda3d.core import Filename
            raw = base64.b64decode(b64_data)
            suffix = ".jpg" if raw[:3] == b'\xff\xd8\xff' else ".png"
            tmp = tempfile.mktemp(suffix=suffix)
            with open(tmp, "wb") as f:
                f.write(raw)
            tex = self.loader.loadTexture(Filename.fromOsSpecific(tmp))
            try:
                os.remove(tmp)
            except Exception:
                pass
            if tex:
                frame_np.setTexture(tex, 1)
                frame_np["frameColor"] = (1, 1, 1, 1)
        except Exception as e:
            print(f"[THUMB] load error: {e}")

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
