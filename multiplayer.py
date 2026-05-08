import asyncio
import json
import queue
import threading
import time
from math import sin, pi

from direct.gui.DirectGui import DirectFrame, DirectEntry, DirectLabel, DirectButton
from direct.task import Task
from panda3d.core import TextNode

import config as _cfg_mod

_COLORS = [
    (0.85, 0.25, 0.25, 1),
    (0.25, 0.55, 0.90, 1),
    (0.90, 0.75, 0.15, 1),
    (0.30, 0.80, 0.35, 1),
    (0.85, 0.50, 0.15, 1),
    (0.65, 0.25, 0.90, 1),
]

_MAX_SWING  = 30.0
_WALK_SPEED = 10.0
_LERP       = 18.0   # interpolation factor — higher = snappier catch-up
_MAX_CHAT   = 8      # chat lines shown
_CHAT_PNL_W = 0.88   # chat panel width (units in aspect2d)
_CHAT_PNL_H = 0.36   # chat message area height
_INPUT_H    = 0.058  # chat input bar height
_LB_W       = 0.32   # leaderboard panel width


class MultiplayerMixin:

    def start_multiplayer(self, build_id, token):
        print("[MP] start_multiplayer requested")

        # Always fully stop the old session first, regardless of its state.
        try:
            self.stop_multiplayer()
        except Exception as e:
            print("[MP] stop before restart failed:", e)

        print(f"[MP] joining new build {build_id}")

        # Remove stale remote player models from the scene before starting fresh.
        for pid in list(getattr(self, "_remote_players", {}).keys()):
            self._remove_remote_player(pid)

        gen = getattr(self, "_mp_generation", 0) + 1
        self._mp_generation     = gen
        self._mp_build_id       = build_id
        self._remote_players    = {}          # clear on join transition
        self._mp_queue          = queue.Queue()
        self._mp_connected      = True
        self._mp_joined         = False
        self._ws                = None
        self._mp_recv_ok        = False
        self._disconnect_popup  = None
        self._mp_loop           = asyncio.new_event_loop()
        self._chat_input_active = False
        self._mp_task           = None
        print(f"[MP] start_multiplayer build_id={build_id} gen={gen}")
        t = threading.Thread(
            target=self._run_mp_loop,
            args=(build_id, token, gen),
            daemon=True,
        )
        t.start()
        self._mp_thread = t
        self._mp_task = self.taskMgr.add(self._mp_update_task, "mpUpdateTask")
        self._setup_chat_ui()
        self.accept("/", self._open_chat_input)

    def stop_multiplayer(self):
        print("[MP] stopping old multiplayer session")

        # Clear networking state — never clears _remote_players here.
        self._mp_connected = False
        self._mp_joined    = False
        self._mp_recv_ok   = False
        self._mp_build_id  = None

        # Close old websocket explicitly.
        ws   = getattr(self, "_ws",      None)
        loop = getattr(self, "_mp_loop", None)
        if ws and loop and not loop.is_closed():
            async def _close_ws(w):
                try:
                    await w.close(code=1000)
                except Exception:
                    pass
            asyncio.run_coroutine_threadsafe(_close_ws(ws), loop)
            print("[MP] old websocket closed")
        self._ws = None

        # Always remove the task by name so no zombie survives into next session.
        try:
            self.taskMgr.remove("mpUpdateTask")
            print("[MP] removed mpUpdateTask")
        except Exception:
            pass
        self._mp_task = None

        self._teardown_chat_ui()
        self._teardown_leaderboard()
        self.ignore("/")

    # ── Background asyncio thread ──────────────────────────────────────────

    def _run_mp_loop(self, build_id, token, gen):
        asyncio.set_event_loop(self._mp_loop)
        try:
            self._mp_loop.run_until_complete(self._mp_main(build_id, token, gen))
        finally:
            self._mp_loop.close()

    async def _mp_main(self, build_id, token, gen):
        try:
            import websockets as ws_lib
        except ImportError:
            print("[MP] websockets not installed")
            return
        ws_base = _cfg_mod.get()["ws"]
        uri = f"{ws_base}/ws/{build_id}?token={token}"

        retry = 0
        while self._mp_connected and self._mp_generation == gen:
            print(f"[MP] connecting -> {uri}")
            self._mp_recv_ok = False
            try:
                async with ws_lib.connect(uri, ping_interval=None) as ws:
                    self._ws = ws
                    print("[MP] WebSocket connected OK")
                    self._mp_queue.put_nowait({"type": "_connected"})
                    await asyncio.gather(
                        self._mp_recv(ws),
                        self._mp_send(ws),
                    )
            except Exception as e:
                print(f"[MP] connection error: {e}")
                if not self._mp_connected or self._mp_generation != gen:
                    break
                self._mp_queue.put_nowait({"type": "_reconnecting"})
            finally:
                self._ws = None
            if not self._mp_connected or self._mp_generation != gen:
                break
            # Only reset the retry counter if we actually received data this session.
            if self._mp_recv_ok:
                retry = 0
            retry += 1
            if retry > 8:
                self._mp_queue.put_nowait({"type": "_error", "msg": "Could not reconnect to server"})
                break
            wait = 0.5 if retry == 1 else min(2 ** (retry - 1), 30)
            print(f"[MP] reconnecting in {wait}s (attempt {retry})")
            elapsed = 0.0
            while elapsed < wait and self._mp_connected and self._mp_generation == gen:
                chunk = min(0.1, wait - elapsed)
                await asyncio.sleep(chunk)
                elapsed += chunk
        # Only clear the flag if we're still the current session (don't kill a newer session)
        if self._mp_generation == gen:
            self._mp_connected = False

    async def _mp_recv(self, ws):
        received_any = False
        got_kicked   = False
        try:
            async for raw in ws:
                if not received_any:
                    self._mp_recv_ok = True
                received_any = True
                try:
                    msg = json.loads(raw)
                    if msg.get("type") not in ("move",):
                        print(f"[MP] recv type={msg.get('type')}")
                    if msg.get("type") == "kicked":
                        got_kicked = True
                    self._mp_queue.put_nowait(msg)
                except Exception as e:
                    print(f"[MP] recv parse error: {e}")
        except Exception as e:
            code = getattr(getattr(e, "rcvd", None), "code", None)
            if code in (4008, 4009) or got_kicked:
                # Server kicked us — stop retry loop regardless of close code
                self._mp_connected = False
            else:
                print(f"[MP] recv loop ended: {e}")
                if not received_any:
                    self._mp_queue.put_nowait({
                        "type": "_error",
                        "msg": "Server rejected connection — try logging out and back in",
                    })

    async def _mp_send(self, ws):
        last_pos = None
        last_sent = time.monotonic()
        last_idle_log = 0
        try:
            while self._mp_connected:
                try:
                    char = getattr(self, "character", None)
                    if char:
                        pos = char.getPos()
                        h   = char.getH()
                        cur = (round(float(pos.x), 2), round(float(pos.y), 2),
                               round(float(pos.z), 2), round(float(h), 1))
                        if cur != last_pos:
                            await ws.send(json.dumps({
                                "type": "move",
                                "x": cur[0], "y": cur[1], "z": cur[2], "h": cur[3],
                            }))
                            last_pos      = cur
                            last_sent     = time.monotonic()
                            last_idle_log = 0
                        else:
                            idle = time.monotonic() - last_sent
                            if idle >= 25.0:
                                await ws.send(json.dumps({"type": "ping"}))
                                last_sent     = time.monotonic()
                                last_idle_log = 0
                            elif idle - last_idle_log >= 5.0:
                                last_idle_log = idle
                                print(f"[MP] idle for {idle:.0f}s (server kicks at 35s)", flush=True)
                except Exception as e:
                    print(f"[MP] send error: {e}")
                    break
                await asyncio.sleep(0.05)   # 20 Hz poll
        finally:
            # Always send a clean close frame when the send loop exits,
            # whether from _mp_connected=False (window close / menu) or a send error.
            try:
                await ws.close()
            except Exception:
                pass

    # ── Panda3D main-thread task ───────────────────────────────────────────

    def _mp_update_task(self, task):
        if getattr(self, "_mp_task", None) is None:
            return task.done

        dt = globalClock.getDt()

        # Drain incoming message queue
        q = getattr(self, "_mp_queue", None)
        if q:
            while True:
                try:
                    self._handle_mp_msg(q.get_nowait())
                except queue.Empty:
                    break

        t = min(1.0, _LERP * dt)

        for d in list(getattr(self, "_remote_players", {}).values()):
            tp = d.get("target_pos")
            if tp is None:
                continue

            # Smooth position interpolation
            ip = d.get("interp_pos", tp)
            nx = ip[0] + (tp[0] - ip[0]) * t
            ny = ip[1] + (tp[1] - ip[1]) * t
            nz = ip[2] + (tp[2] - ip[2]) * t
            d["interp_pos"] = (nx, ny, nz)

            # Smooth heading — take shortest arc
            th  = d.get("target_h", 0.0)
            ih  = d.get("interp_h", th)
            diff = ((th - ih + 180) % 360) - 180
            nh  = ih + diff * t
            d["interp_h"] = nh

            try:
                d["root"].setPos(nx, ny, nz)
                d["root"].setH(nh)
                d["label"].setPos(nx, ny, nz + 5.8)
            except Exception:
                pass

            # Clear is_moving if no position update arrived in the last 0.25s
            if d.get("is_moving") and time.monotonic() - d.get("last_move_time", 0) > 0.25:
                d["is_moving"] = False

            # Walking animation
            if d.get("is_moving"):
                d["walk_angle"] += _WALK_SPEED * dt
                wa = d["walk_angle"]
                try:
                    d["la_piv"].setP( sin(wa)      * _MAX_SWING)
                    d["ra_piv"].setP( sin(wa + pi)  * _MAX_SWING)
                    d["ll_piv"].setP( sin(wa + pi)  * _MAX_SWING)
                    d["rl_piv"].setP( sin(wa)       * _MAX_SWING)
                except Exception:
                    pass
            else:
                s = min(1.0, 12.0 * dt)
                try:
                    d["la_piv"].setP(d["la_piv"].getP() * (1 - s))
                    d["ra_piv"].setP(d["ra_piv"].getP() * (1 - s))
                    d["ll_piv"].setP(d["ll_piv"].getP() * (1 - s))
                    d["rl_piv"].setP(d["rl_piv"].getP() * (1 - s))
                except Exception:
                    pass

        return Task.cont

    def _handle_mp_msg(self, msg):
        t = msg.get("type")
        if t == "_connected":
            self._show_toast("Multiplayer connected", (0.40, 0.88, 0.52, 1))
            self._update_leaderboard()
            return
        if t == "_reconnecting":
            self._show_toast("Connection lost, reconnecting...", (1.0, 0.85, 0.30, 1), duration=3.0)
            for pid in list(self._remote_players.keys()):
                self._remove_remote_player(pid)
            self._remote_players = {}
            self._update_leaderboard()
            return
        if t == "_error":
            err_text = msg.get('msg', '')
            print(f"[MP] ERROR: {err_text}")
            self._show_toast(f"MP: {err_text}"[:60], (1.0, 0.40, 0.40, 1), duration=6.0)
            return
        if t == "kicked":
            reason = msg.get("reason")
            text = ("You were disconnected\ndue to inactivity."
                    if reason == "inactivity"
                    else "Another session connected\nwith your account.")
            def _do_kick(task, text=text):
                self.stop_multiplayer()
                self._show_disconnect_popup(text)
                return task.done
            self.taskMgr.doMethodLater(0, _do_kick, "_kickedCleanup", appendTask=True)
            return
        if t == "state":
            print(f"[MP] state: {len(msg.get('players', {}))} other players")
            for pid, d in msg.get("players", {}).items():
                self._add_remote_player(pid, d.get("username", pid))
                self._update_remote_player(pid, d)
            self._update_leaderboard()
        elif t == "joined":
            print(f"[MP] joined: {msg['player_id']} ({msg.get('username')})")
            self._add_remote_player(msg["player_id"], msg.get("username", ""))
            self._update_leaderboard()
        elif t == "left":
            print(f"[MP] left: {msg['player_id']}")
            self._remove_remote_player(msg["player_id"])
            self._update_leaderboard()
        elif t == "move":
            pid = msg.get("player_id")
            if pid and pid in self._remote_players:
                self._update_remote_player(pid, msg)
        elif t == "chat":
            self._add_chat_message(msg.get("username", "?"), msg.get("text", ""))

    # ── Disconnect popup ─────────────────────────────────────────────────

    def _show_disconnect_popup(self, message):
        if getattr(self, "_disconnect_popup", None):
            return
        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.82),
            frameSize=(-3, 3, -3, 3),
            sortOrder=100,
        )
        self._disconnect_popup = overlay
        card = DirectFrame(
            frameColor=(0.11, 0.12, 0.17, 0.97),
            frameSize=(-0.60, 0.60, -0.22, 0.22),
            parent=overlay,
        )
        DirectLabel(
            text=message,
            text_fg=(0.88, 0.90, 0.95, 1),
            text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=card,
            pos=(0, 0, 0.07),
        )
        def _on_ok():
            p = getattr(self, "_disconnect_popup", None)
            if p:
                try:
                    p.destroy()
                except Exception:
                    pass
                self._disconnect_popup = None
            self._return_to_menu()
        DirectButton(
            text="OK",
            text_fg=(0.88, 0.90, 0.95, 1),
            text_scale=0.042,
            frameColor=(0.18, 0.38, 0.72, 1),
            frameSize=(-0.12, 0.12, -0.038, 0.038),
            parent=card,
            pos=(0, 0, -0.10),
            command=_on_ok,
            relief=1,
        )

    # ── Remote player model ───────────────────────────────────────────────

    def _make_box(self, parent, scale, pos, color):
        box = self.loader.loadModel("models/box")
        box.reparentTo(parent)
        box.setScale(*scale)
        box.setPos(*pos)
        box.setColor(*color)
        box.setTextureOff(1)
        return box

    def _add_remote_player(self, pid, username):
        if pid in self._remote_players:
            return
        # Ignore ghost entries for our own account (zombie from a previous session
        # that hasn't been evicted by the server's ping timeout yet).
        if username and username == getattr(self, "_session_username", None):
            return
        r, g, b, a = _COLORS[len(self._remote_players) % len(_COLORS)]
        skin  = (r * 0.95, g * 0.85, b * 0.55, a)
        leg_c = (r * 0.60, g * 0.75, b * 0.35, a)
        print(f"[MP] adding remote player pid={pid} username={username!r}")

        root = self.render.attachNewNode(f"remote_{pid}")
        root.setPos(0, 0, -9999)

        self._make_box(root, (2, 1, 2), (-1, -0.5, 2), (r, g, b, a))  # torso

        la_piv = root.attachNewNode("la_piv")
        la_piv.setPos(-1.5, 0, 4)
        self._make_box(la_piv, (1, 1, 2), (-0.5, -0.5, -2), skin)

        ra_piv = root.attachNewNode("ra_piv")
        ra_piv.setPos(1.5, 0, 4)
        self._make_box(ra_piv, (1, 1, 2), (-0.5, -0.5, -2), skin)

        ll_piv = root.attachNewNode("ll_piv")
        ll_piv.setPos(-0.5, 0, 2)
        self._make_box(ll_piv, (1, 1, 2), (-0.5, -0.5, -2), leg_c)

        rl_piv = root.attachNewNode("rl_piv")
        rl_piv.setPos(0.5, 0, 2)
        self._make_box(rl_piv, (1, 1, 2), (-0.5, -0.5, -2), leg_c)

        head = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        head.reparentTo(root)
        head.setColor(*skin)
        head.setTwoSided(True)
        head.setTextureOff(1)
        head.setPos(0, 0, 4.55)

        tn = TextNode("mpname")
        tn.setText(username or pid)
        tn.setAlign(TextNode.ACenter)
        label = self.render.attachNewNode(tn)
        label.setScale(0.38)
        label.setLightOff()
        label.setShaderOff()
        label.setDepthWrite(False)
        label.setBillboardPointEye()
        label.setPos(0, 0, -9999)

        self._remote_players[pid] = {
            "root": root, "label": label,
            "la_piv": la_piv, "ra_piv": ra_piv,
            "ll_piv": ll_piv, "rl_piv": rl_piv,
            "username": username,
            "walk_angle": 0.0, "is_moving": False,
            "last_pos": None, "last_move_time": 0.0,
            "target_pos": None, "target_h": 0.0,
            "interp_pos": None, "interp_h": 0.0,
        }

    def _remove_remote_player(self, pid):
        d = self._remote_players.pop(pid, None)
        if d:
            try:
                d["root"].removeNode()
                d["label"].removeNode()
            except Exception:
                pass

    def _update_remote_player(self, pid, data):
        d = self._remote_players.get(pid)
        if not d:
            return
        x = float(data.get("x", 0.0))
        y = float(data.get("y", 0.0))
        z = float(data.get("z", 0.0))
        h = float(data.get("h", 0.0))
        lp = d["last_pos"]
        d["is_moving"] = lp is not None and (abs(x - lp[0]) > 0.01 or abs(y - lp[1]) > 0.01)
        if d["is_moving"]:
            d["last_move_time"] = time.monotonic()
        d["last_pos"]   = (x, y, z)
        d["target_pos"] = (x, y, z)
        d["target_h"]   = h
        # First update: snap directly so the player doesn't slide in from -9999
        if d["interp_pos"] is None:
            d["interp_pos"] = (x, y, z)
            d["interp_h"]   = h
            try:
                d["root"].setPos(x, y, z)
                d["root"].setH(h)
                d["label"].setPos(x, y, z + 5.8)
            except Exception:
                pass

    # ── Leaderboard (top right) ───────────────────────────────────────────

    def _update_leaderboard(self):
        lb = getattr(self, "_lb_panel", None)
        if lb:
            try:
                lb.destroy()
            except Exception:
                pass
        self._lb_panel = None

        local   = getattr(self, "_session_username", "You")
        remotes = [d.get("username", "") or pid
                   for pid, d in getattr(self, "_remote_players", {}).items()]
        players = [local] + remotes

        row_h   = 0.040
        title_h = 0.048
        pad     = 0.014
        h       = title_h + len(players) * row_h + pad

        self._lb_panel = DirectFrame(
            frameColor=(0, 0, 0, 0.55),
            frameSize=(-_LB_W, 0, -h, 0),
            parent=base.a2dTopRight,
            pos=(-0.04, 0, -0.04),
            sortOrder=55,
        )
        DirectLabel(
            text="Players",
            text_fg=(1, 1, 1, 0.65),
            text_scale=0.032,
            text_align=TextNode.ACenter,
            frameColor=(0, 0, 0, 0),
            parent=self._lb_panel,
            pos=(-_LB_W * 0.5, 0, -0.030),
        )
        for i, name in enumerate(players):
            color   = (0.95, 0.85, 0.30, 1) if i == 0 else (0.88, 0.90, 0.95, 1)
            display = f"{name}  (You)" if i == 0 else name
            DirectLabel(
                text=display,
                text_fg=color,
                text_scale=0.030,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=self._lb_panel,
                pos=(-_LB_W + 0.014, 0, -(title_h + i * row_h + 0.010)),
            )

    def _teardown_leaderboard(self):
        lb = getattr(self, "_lb_panel", None)
        if lb:
            try:
                lb.destroy()
            except Exception:
                pass
        self._lb_panel = None

    # ── Chat ──────────────────────────────────────────────────────────────

    def _setup_chat_ui(self):
        self._chat_messages     = []
        self._chat_input_active = False
        self._chat_visible      = True

        # Toggle button — always visible, top left
        self._chat_toggle_btn = DirectButton(
            text="Chat",
            text_fg=(1, 1, 1, 0.9),
            text_scale=0.030,
            frameColor=(0, 0, 0, 0.62),
            frameSize=(0, 0.14, -0.044, 0),
            parent=base.a2dTopLeft,
            pos=(0.04, 0, -0.04),
            sortOrder=55,
            relief=1,
            command=self._toggle_chat,
        )

        # Message panel (just below toggle button)
        self._chat_panel = DirectFrame(
            frameColor=(0, 0, 0, 0.50),
            frameSize=(0, _CHAT_PNL_W, -_CHAT_PNL_H, 0),
            parent=base.a2dTopLeft,
            pos=(0.04, 0, -0.092),
            sortOrder=50,
        )
        DirectLabel(
            text="Chat '/?' or '/help' for a list of chat commands.",
            text_fg=(1, 1, 1, 0.50),
            text_scale=0.026,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=self._chat_panel,
            pos=(0.014, 0, -0.030),
        )
        self._chat_labels = []
        for i in range(_MAX_CHAT):
            lbl = DirectLabel(
                text="",
                text_fg=(1, 1, 1, 0.92),
                text_scale=0.030,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=self._chat_panel,
                pos=(0.014, 0, -0.068 - i * 0.036),
            )
            self._chat_labels.append(lbl)

        # Input bar (permanently visible below the message panel)
        _panel_bot = -0.092 - _CHAT_PNL_H
        self._chat_input_frame = DirectFrame(
            frameColor=(0, 0, 0, 0.68),
            frameSize=(0, _CHAT_PNL_W, -_INPUT_H, 0),
            parent=base.a2dTopLeft,
            pos=(0.04, 0, _panel_bot),
            sortOrder=51,
        )
        self._chat_placeholder = DirectLabel(
            text='To chat click here or press "/" key',
            text_fg=(1, 1, 1, 0.38),
            text_scale=0.028,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=self._chat_input_frame,
            pos=(0.015, 0, -0.032),
        )
        self._chat_entry = DirectEntry(
            text_fg=(1, 1, 1, 1),
            text_scale=0.033,
            frameColor=(0, 0, 0, 0),
            width=24,
            numLines=1,
            parent=self._chat_input_frame,
            pos=(0.012, 0, -0.036),
            command=self._on_chat_submit,
        )
        self._chat_entry.hide()

    def _teardown_chat_ui(self):
        for attr in ("_chat_toggle_btn", "_chat_panel", "_chat_input_frame"):
            node = getattr(self, attr, None)
            if node:
                try:
                    node.destroy()
                except Exception:
                    pass
            setattr(self, attr, None)
        self._chat_labels       = []
        self._chat_messages     = []
        self._chat_input_active = False
        self._chat_placeholder  = None

    def _toggle_chat(self):
        self._chat_visible = not getattr(self, "_chat_visible", True)
        panel = getattr(self, "_chat_panel", None)
        inp   = getattr(self, "_chat_input_frame", None)
        if self._chat_visible:
            if panel: panel.show()
            if inp:   inp.show()
        else:
            if panel: panel.hide()
            if inp:   inp.hide()
            self._close_chat_input()

    def _open_chat_input(self):
        if not getattr(self, "_chat_visible", True):
            self._chat_visible = True
            p = getattr(self, "_chat_panel", None)
            i = getattr(self, "_chat_input_frame", None)
            if p: p.show()
            if i: i.show()
        if getattr(self, "_chat_input_active", False):
            return
        self._chat_input_active = True
        ph = getattr(self, "_chat_placeholder", None)
        if ph: ph.hide()
        self._chat_entry.show()
        self._chat_entry.set("")
        self._chat_entry["focus"] = 1

    def _close_chat_input(self):
        self._chat_input_active = False
        self._chat_entry.hide()
        self._chat_entry["focus"] = 0
        ph = getattr(self, "_chat_placeholder", None)
        if ph: ph.show()

    def _on_chat_submit(self, text):
        self._chat_entry.set("")
        text = text.strip()
        self._close_chat_input()
        if not text:
            return
        ws   = getattr(self, "_ws",      None)
        loop = getattr(self, "_mp_loop", None)
        if ws and loop and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({"type": "chat", "text": text[:200]})),
                loop,
            )
        username = getattr(self, "_session_username", "You")
        self._add_chat_message(username, text)

    def _add_chat_message(self, username, text):
        if not hasattr(self, "_chat_messages"):
            return
        line = f"{username}: {text}"
        self._chat_messages.append(line)
        if len(self._chat_messages) > _MAX_CHAT:
            self._chat_messages = self._chat_messages[-_MAX_CHAT:]
        for i, lbl in enumerate(self._chat_labels):
            if i < len(self._chat_messages):
                raw = self._chat_messages[i]
                lbl["text"] = (raw[:44] + "…") if len(raw) > 44 else raw
            else:
                lbl["text"] = ""
