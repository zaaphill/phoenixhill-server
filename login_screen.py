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

    def _start_server(self):
        # If a working server is already running, check it has the latest API.
        result, _ = auth_client.browse_published()
        if result is not None:
            rooms_result, _ = auth_client.get_rooms()
            if rooms_result is not None:
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
        if cfg["local"]:
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

    def _verify_token_async(self, token, username):
        def worker():
            result, _ = auth_client.verify(token)
            if result and result.get("ok"):
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
        self._build_main_menu()
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
            text_fg=TEXT_D, text_scale=0.036,
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
            text_fg=TEXT_D, text_scale=0.036,
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
            text="Register",
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
        if self._login_ui:
            self._login_ui.destroy()
            self._login_ui = None
        self._build_main_menu()
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
        PUB_C = (0.14, 0.42, 0.22, 1.0)   # green-ish when published
        for i, build in enumerate(builds[:5]):
            y = -(i + 0.5) * ROW_H
            is_pub = bool(build.get("published", 0))
            DirectFrame(
                frameColor=MED_L,
                frameSize=(-0.74, 0.74, -ROW_H / 2, ROW_H / 2),
                parent=frame, pos=(0, 0, y),
            )
            name = build["name"]
            if len(name) > 18:
                name = name[:16] + "…"
            ts = datetime.datetime.fromtimestamp(build["updated_at"]).strftime("%b %d")
            DirectLabel(
                text=f"{name}  {ts}",
                text_fg=TEXT, text_scale=0.028,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-0.70, 0, y - 0.010),
            )
            # Publish / Unpublish toggle
            DirectButton(
                text="Unpub" if is_pub else "Pub",
                text_fg=TEXT, text_scale=0.026,
                frameColor=PUB_C if is_pub else BTN,
                frameSize=(-0.056, 0.056, -0.022, 0.022),
                parent=frame, pos=(0.30, 0, y),
                command=self._on_toggle_publish,
                extraArgs=[build["id"], not is_pub], relief=1,
            )
            DirectButton(
                text="Load",
                text_fg=TEXT, text_scale=0.026,
                frameColor=SEL,
                frameSize=(-0.060, 0.060, -0.022, 0.022),
                parent=frame, pos=(0.48, 0, y),
                command=self._on_load_build,
                extraArgs=[build["id"]], relief=1,
            )
            DirectButton(
                text="Del",
                text_fg=TEXT, text_scale=0.026,
                frameColor=(0.45, 0.14, 0.14, 1.0),
                frameSize=(-0.048, 0.048, -0.022, 0.022),
                parent=frame, pos=(0.63, 0, y),
                command=self._on_delete_build,
                extraArgs=[build["id"]], relief=1,
            )
        return task.done

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

        bg = DirectFrame(frameColor=DARKER, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        card = DirectFrame(
            frameColor=DARK,
            frameSize=(-0.78, 0.78, -0.62, 0.60),
            parent=bg,
        )
        DirectLabel(
            text="PhoenixHill",
            text_fg=TEXT, text_scale=0.070,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.46),
        )
        DirectLabel(
            text=f"Logged in as {self._session_username}",
            text_fg=TEXT_D, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.34),
        )
        DirectButton(
            text="Refresh",
            text_fg=TEXT_D, text_scale=0.030,
            frameColor=BTN,
            frameSize=(-0.090, 0.090, -0.026, 0.026),
            parent=card, pos=(0.64, 0, 0.34),
            command=self._build_browse_screen, relief=1,
        )
        self._browse_list_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-0.74, 0.74, -0.40, 0),
            parent=card, pos=(0, 0, 0.28),
        )
        DirectLabel(
            text="Loading…",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=self._browse_list_frame, pos=(0, 0, -0.06),
        )

        # Bottom nav
        DirectButton(
            text="My Builds",
            text_fg=TEXT, text_scale=0.038,
            frameColor=BTN,
            frameSize=(-0.16, 0.16, -0.036, 0.036),
            parent=card, pos=(-0.44, 0, -0.50),
            command=self._build_main_menu, relief=1,
        )
        DirectButton(
            text="New Build",
            text_fg=TEXT, text_scale=0.038,
            frameColor=SEL,
            frameSize=(-0.16, 0.16, -0.036, 0.036),
            parent=card, pos=(0, 0, -0.50),
            command=self._enter_studio, relief=1,
        )
        DirectButton(
            text="Log Out",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=BTN,
            frameSize=(-0.14, 0.14, -0.032, 0.032),
            parent=card, pos=(0.44, 0, -0.50),
            command=self._do_logout, relief=1,
        )

        threading.Thread(target=self._fetch_browse_thread, daemon=True).start()
        self.taskMgr.doMethodLater(6, self._browse_auto_refresh, "_browseAutoRefresh",
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
        frame = self._browse_list_frame
        for child in frame.getChildren():
            child.removeNode()

        if not builds:
            DirectLabel(
                text="No published builds yet." if not err else f"Error: {err}",
                text_fg=TEXT_D, text_scale=0.034,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0, 0, -0.06),
            )
            return task.done

        ROW_H = 0.078
        MED_L = (0.17, 0.19, 0.26, 1.0)
        LIVE  = (0.20, 0.55, 0.28, 1.0)   # green tint for rows with players
        for i, build in enumerate(builds[:5]):
            online = build.get("online", 0)
            y = -(i + 0.5) * ROW_H
            DirectFrame(
                frameColor=LIVE if online else MED_L,
                frameSize=(-0.74, 0.74, -ROW_H / 2, ROW_H / 2),
                parent=frame, pos=(0, 0, y),
            )
            name = build["name"]
            if len(name) > 20:
                name = name[:18] + "…"
            DirectLabel(
                text=name,
                text_fg=TEXT, text_scale=0.030,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-0.70, 0, y + 0.004),
            )
            DirectLabel(
                text=f"by {build['username']}",
                text_fg=TEXT_D, text_scale=0.026,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(-0.70, 0, y - 0.024),
            )
            # Player count badge
            count_text = f"{online} online" if online else "empty"
            count_color = (0.55, 1.0, 0.65, 1) if online else (0.45, 0.47, 0.55, 1)
            DirectLabel(
                text=count_text,
                text_fg=count_color, text_scale=0.026,
                text_align=TextNode.ARight,
                frameColor=(0, 0, 0, 0),
                parent=frame, pos=(0.42, 0, y),
            )
            DirectButton(
                text="Play",
                text_fg=TEXT, text_scale=0.030,
                frameColor=(0.14, 0.42, 0.22, 1.0),
                frameSize=(-0.070, 0.070, -0.026, 0.026),
                parent=frame, pos=(0.60, 0, y),
                command=self._on_play_published,
                extraArgs=[build["id"]], relief=1,
            )
        return task.done

    def _on_play_published(self, build_id):
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
        self.stop_multiplayer()
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
