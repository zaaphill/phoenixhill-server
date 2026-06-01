import asyncio
import json
import queue
import threading
import time
from math import sin, pi

from direct.gui.DirectGui import DirectFrame, DirectEntry, DirectLabel, DirectButton, DGG
from direct.task import Task
from panda3d.core import TextNode, CardMaker, TransparencyAttrib, MouseButton

import config as _cfg_mod

_MAX_SWING  = 30.0
_WALK_SPEED = 10.0
_LERP       = 18.0   # interpolation factor — higher = snappier catch-up
_CHAT_LINES = 10     # visible line slots in the panel
_CHAT_WRAP  = 42     # chars per visual line (pre-wrap before display)
_LINE_SPACE = 0.040  # vertical gap between chat lines
_CHAT_PNL_W = 0.88   # chat panel width (units in aspect2d)
_CHAT_PNL_H = 0.44   # message area height
_INPUT_H    = 0.052  # chat input bar height (1 line)
_INPUT_LINE = 0.040  # extra height added per wrapped line
_LB_W       = 0.32   # leaderboard panel width
_CHAT_TOP   = -0.10  # z from a2dTopLeft — sits just below the toolbar (TH=0.09)
# Toolbar-button style constants (must match ui.py BTN / TEXT / TH)
_TB_COLOR   = (0.19, 0.21, 0.29, 1.0)
_TB_TEXT    = (0.88, 0.90, 0.95, 1.0)
_TB_BZ      = -0.045  # -TH/2 = vertical centre of the top bar


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
        # Announce avatar colors immediately so other players see them right away.
        try:
            colors = self.load_avatar_colors()
            payload = {"type": "avatar_colors", "colors": {k: list(v) for k, v in colors.items()}}
            print(f"[AVATAR_MSG_SEND] payload={payload}", flush=True)
            await ws.send(json.dumps(payload))
        except Exception as e:
            print(f"[MP] failed to send avatar colors: {e}")
        equipped = getattr(self, '_equipped_tshirt_id', None)
        if equipped:
            try:
                await ws.send(json.dumps({"type": "equip_tshirt", "item_id": equipped}))
            except Exception as e:
                print(f"[MP] failed to send equip_tshirt: {e}")
        equipped_shirt = getattr(self, '_equipped_shirt_id', None)
        if equipped_shirt:
            try:
                await ws.send(json.dumps({"type": "equip_shirt", "item_id": equipped_shirt}))
            except Exception as e:
                print(f"[MP] failed to send equip_shirt: {e}")
        equipped_pants = getattr(self, '_equipped_pants_id', None)
        if equipped_pants:
            try:
                await ws.send(json.dumps({"type": "equip_pants", "item_id": equipped_pants}))
            except Exception as e:
                print(f"[MP] failed to send equip_pants: {e}")

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

            face_np = d.get("face_np")
            face_textures = getattr(self, '_face_textures', [])
            if face_np and len(face_textures) >= 2:
                d["face_anim_t"] += dt
                if d["face_anim_t"] >= 0.25:
                    d["face_anim_t"] -= 0.25
                    d["face_frame"] = (d["face_frame"] + 1) % len(face_textures)
                    try:
                        face_np.setTexture(face_textures[d["face_frame"]], 2)
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
            players = msg.get("players", {})
            colors_in_state = {pid: bool(d.get("colors")) for pid, d in players.items()}
            print(f"[WS_RECV] type=state player_count={len(players)} colors_present={colors_in_state}", flush=True)
            for pid, d in players.items():
                self._add_remote_player(pid, d.get("username", pid), d.get("colors"),
                                        tshirt_id=d.get("tshirt_id"), hat_id=d.get("hat_id"),
                                        shirt_id=d.get("shirt_id"), pants_id=d.get("pants_id"))
                self._update_remote_player(pid, d)
            self._update_leaderboard()
        elif t == "joined":
            print(f"[WS_RECV] type=joined pid={msg.get('player_id')} username={msg.get('username')!r} colors={msg.get('colors')}", flush=True)
            self._add_remote_player(msg["player_id"], msg.get("username", ""), msg.get("colors"),
                                    tshirt_id=msg.get("tshirt_id"), hat_id=msg.get("hat_id"),
                                    shirt_id=msg.get("shirt_id"), pants_id=msg.get("pants_id"))
            self._update_leaderboard()
            self._broadcast_my_colors()
        elif t == "left":
            print(f"[MP] left: {msg['player_id']}")
            self._remove_remote_player(msg["player_id"])
            self._update_leaderboard()
        elif t == "move":
            pid = msg.get("player_id")
            if pid and pid in self._remote_players:
                self._update_remote_player(pid, msg)
        elif t == "avatar_colors":
            pid = msg.get("player_id")
            print(f"[WS_RECV] type=avatar_colors pid={pid} pid_known={pid in self._remote_players} colors={msg.get('colors')}", flush=True)
            if pid and pid in self._remote_players:
                self._apply_colors_to_remote_player(pid, msg.get("colors", {}))
        elif t == "chat":
            self._add_chat_message(msg.get("username", "?"), msg.get("text", ""))
        elif t == "equip_tshirt":
            pid = msg.get("player_id")
            item_id = msg.get("item_id")
            if pid and pid in self._remote_players:
                if item_id:
                    threading.Thread(
                        target=self._fetch_and_apply_remote_tshirt,
                        args=(pid, item_id), daemon=True,
                    ).start()
                else:
                    self._apply_tshirt_to_remote(pid, None)
        elif t == "equip_hat":
            pid     = msg.get("player_id")
            item_id = msg.get("item_id")
            if pid and pid in self._remote_players:
                self._remote_players[pid]["hat_id"] = item_id
                if item_id:
                    threading.Thread(
                        target=self._fetch_and_apply_remote_hat,
                        args=(pid, item_id), daemon=True,
                    ).start()
                else:
                    self._apply_hat_to_remote(pid, None)
        elif t == "equip_shirt":
            pid     = msg.get("player_id")
            item_id = msg.get("item_id")
            if pid and pid in self._remote_players:
                self._remote_players[pid]["shirt_id"] = item_id
                if item_id:
                    threading.Thread(
                        target=self._fetch_and_apply_remote_shirt,
                        args=(pid, item_id), daemon=True,
                    ).start()
                else:
                    self._apply_shirt_to_remote(pid, None)
        elif t == "equip_pants":
            pid     = msg.get("player_id")
            item_id = msg.get("item_id")
            if pid and pid in self._remote_players:
                self._remote_players[pid]["pants_id"] = item_id
                if item_id:
                    threading.Thread(
                        target=self._fetch_and_apply_remote_pants,
                        args=(pid, item_id), daemon=True,
                    ).start()
                else:
                    self._apply_pants_to_remote(pid, None)

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

    def _add_remote_player(self, pid, username, colors=None, tshirt_id=None, hat_id=None, shirt_id=None, pants_id=None):
        if pid in self._remote_players:
            return
        # Ignore ghost entries for our own account (zombie from a previous session
        # that hasn't been evicted by the server's ping timeout yet).
        if username and username == getattr(self, "_session_username", None):
            return
        print(f"[REMOTE_BUILD] pid={pid} username={username!r} colors_arg={colors}", flush=True)

        _D_HEAD  = (244/255, 204/255,  67/255, 1)
        _D_TORSO = ( 23/255, 107/255, 170/255, 1)
        _D_LEG   = (165/255, 188/255,  80/255, 1)

        def _col(key, fallback):
            if colors and isinstance(colors, dict):
                v = colors.get(key)
                if v and len(v) == 4:
                    return tuple(float(x) for x in v)
            return fallback

        torso_c = _col("torso",     _D_TORSO)
        la_c    = _col("left_arm",  _D_HEAD)
        ra_c    = _col("right_arm", _D_HEAD)
        head_c  = _col("head",      _D_HEAD)
        ll_c    = _col("left_leg",  _D_LEG)
        rl_c    = _col("right_leg", _D_LEG)

        root = self.render.attachNewNode(f"remote_{pid}")
        root.setPos(0, 0, -9999)

        torso_node = self._make_box(root, (2, 1, 2), (-1, -0.5, 2), torso_c)

        la_piv = root.attachNewNode("la_piv")
        la_piv.setPos(-1.5, 0, 4)
        la_node = self._make_box(la_piv, (1, 1, 2), (-0.5, -0.5, -2), la_c)

        ra_piv = root.attachNewNode("ra_piv")
        ra_piv.setPos(1.5, 0, 4)
        ra_node = self._make_box(ra_piv, (1, 1, 2), (-0.5, -0.5, -2), ra_c)

        ll_piv = root.attachNewNode("ll_piv")
        ll_piv.setPos(-0.5, 0, 2)
        ll_node = self._make_box(ll_piv, (1, 1, 2), (-0.5, -0.5, -2), ll_c)

        rl_piv = root.attachNewNode("rl_piv")
        rl_piv.setPos(0.5, 0, 2)
        rl_node = self._make_box(rl_piv, (1, 1, 2), (-0.5, -0.5, -2), rl_c)

        head_node = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        head_node.reparentTo(root)
        head_node.setColor(*head_c)
        head_node.setTwoSided(True)
        head_node.setTextureOff(1)
        head_node.setPos(0, 0, 4.55)

        face_np = None
        face_textures = getattr(self, '_face_textures', [])
        if face_textures:
            _cm = CardMaker('face')
            _cm.setFrame(-0.70, 0.70, -0.55, 0.55)
            _face_anchor = root.attachNewNode("face_anchor")
            _face_anchor.setPos(0, 0.72, 4.55)
            face_np = _face_anchor.attachNewNode(_cm.generate())
            face_np.setTransparency(TransparencyAttrib.MAlpha)
            face_np.setTwoSided(False)
            face_np.setColor(1, 1, 1, 1)
            face_np.setLightOff()
            face_np.setShaderOff()
            face_np.setDepthWrite(False)
            face_np.setH(180)
            face_np.setTexture(face_textures[0])

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
            "torso_node": torso_node, "la_node": la_node, "ra_node": ra_node,
            "ll_node": ll_node, "rl_node": rl_node, "head_node": head_node,
            "username": username,
            "walk_angle": 0.0, "is_moving": False,
            "last_pos": None, "last_move_time": 0.0,
            "target_pos": None, "target_h": 0.0,
            "interp_pos": None, "interp_h": 0.0,
            "face_np": face_np, "face_frame": 0, "face_anim_t": 0.0,
            "tshirt_anchor": None, "tshirt_np": None,
            "hat_id": hat_id, "hat_model": None,
            "shirt_id": shirt_id, "shirt_nodes": [],
            "pants_id": pants_id, "pants_nodes": [],
        }
        if tshirt_id:
            threading.Thread(
                target=self._fetch_and_apply_remote_tshirt,
                args=(pid, tshirt_id), daemon=True,
            ).start()
        if hat_id:
            threading.Thread(
                target=self._fetch_and_apply_remote_hat,
                args=(pid, hat_id), daemon=True,
            ).start()
        if shirt_id:
            threading.Thread(
                target=self._fetch_and_apply_remote_shirt,
                args=(pid, shirt_id), daemon=True,
            ).start()
        if pants_id:
            threading.Thread(
                target=self._fetch_and_apply_remote_pants,
                args=(pid, pants_id), daemon=True,
            ).start()
        for _nk, _ck in [("torso_node","torso"),("la_node","left_arm"),("ra_node","right_arm"),
                          ("ll_node","left_leg"),("rl_node","right_leg"),("head_node","head")]:
            _n = self._remote_players[pid].get(_nk)
            try:
                _actual = tuple(round(float(x), 3) for x in _n.getColor()) if _n else None
            except Exception:
                _actual = "ERROR"
            print(f"[REMOTE_BUILD_PART] pid={pid} part={_ck} actual_color={_actual}", flush=True)

    def _remove_remote_player(self, pid):
        d = self._remote_players.pop(pid, None)
        if d:
            try:
                d["root"].removeNode()
                d["label"].removeNode()
            except Exception:
                pass
            d["tshirt_anchor"] = None
            d["tshirt_np"] = None
            hat = d.get("hat_model")
            if hat and not hat.isEmpty():
                hat.removeNode()
            d["hat_model"] = None
            for n in d.get("shirt_nodes", []):
                if n and not n.isEmpty():
                    n.removeNode()
            d["shirt_nodes"] = []
            for n in d.get("pants_nodes", []):
                if n and not n.isEmpty():
                    n.removeNode()
            d["pants_nodes"] = []

    def _fetch_and_apply_remote_tshirt(self, pid, item_id):
        if not hasattr(self, '_tshirt_cache'):
            self._tshirt_cache = {}
        image_b64 = self._tshirt_cache.get(item_id)
        if not image_b64:
            import auth_client
            result, _ = auth_client.get_shop_item(item_id)
            if result and result.get("image_data"):
                image_b64 = result["image_data"]
                self._tshirt_cache[item_id] = image_b64
        if image_b64:
            self.taskMgr.doMethodLater(
                0, self._apply_remote_tshirt_task, f"_applyTshirt_{pid}",
                extraArgs=[pid, image_b64], appendTask=True,
            )

    def _apply_remote_tshirt_task(self, pid, image_b64, task):
        self._apply_tshirt_to_remote(pid, image_b64)
        return task.done

    def _apply_tshirt_to_remote(self, pid, image_b64):
        d = self._remote_players.get(pid)
        if not d:
            return
        # Remove old
        for attr in ('tshirt_np', 'tshirt_anchor'):
            n = d.get(attr)
            if n and not n.isEmpty():
                n.removeNode()
            d[attr] = None
        if not image_b64:
            return
        try:
            import base64 as _b64, tempfile, os as _os
            from panda3d.core import CardMaker, TransparencyAttrib, Filename
            raw = _b64.b64decode(image_b64)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                tf.write(raw)
                tmp = tf.name
            tex = self.loader.loadTexture(Filename.fromOsSpecific(tmp))
            _os.unlink(tmp)
            if not tex:
                return
            root = d["root"]
            cm = CardMaker('rtshirt')
            cm.setFrame(-1, 1, 0, 2)
            anchor = root.attachNewNode("tshirt_anchor")
            anchor.setPos(0, 0.51, 2)
            np = anchor.attachNewNode(cm.generate())
            np.setH(180)
            np.setTexture(tex)
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setLightOff()
            np.setShaderOff()
            np.setDepthWrite(False)
            np.setDepthOffset(1)
            d["tshirt_anchor"] = anchor
            d["tshirt_np"] = np
        except Exception as e:
            print(f"[TSHIRT_REMOTE] apply failed for {pid}: {e}", flush=True)

    def _fetch_and_apply_remote_hat(self, pid, item_id):
        if not hasattr(self, '_hat_cache'):
            self._hat_cache = {}
        hat_data_json = self._hat_cache.get(item_id)
        if not hat_data_json:
            import auth_client, base64 as _b64
            result, _ = auth_client.get_shop_item(item_id)
            if result:
                img = result.get("image_data") or ""
                if "|HATDATA|" in img:
                    try:
                        hat_data_json = _b64.b64decode(img.split("|HATDATA|", 1)[1]).decode()
                        self._hat_cache[item_id] = hat_data_json
                    except Exception as e:
                        print(f"[HAT_REMOTE] decode: {e}", flush=True)
        if hat_data_json:
            self.taskMgr.doMethodLater(
                0, self._apply_hat_to_remote_task, f"_applyHat_{pid}",
                extraArgs=[pid, hat_data_json], appendTask=True,
            )

    def _apply_hat_to_remote_task(self, pid, hat_data_json, task):
        self._apply_hat_to_remote(pid, hat_data_json)
        return task.done

    def _apply_hat_to_remote(self, pid, hat_data_json):
        d = self._remote_players.get(pid)
        if not d:
            return
        # Remove existing hat
        old = d.get("hat_model")
        if old and not old.isEmpty():
            old.removeNode()
        d["hat_model"] = None
        if not hat_data_json:
            return
        try:
            import json as _json, base64, tempfile, os as _os, shutil
            from panda3d.core import Filename
            data = _json.loads(hat_data_json)
            tmp_dir = tempfile.mkdtemp(prefix="phx_rhat_")
            obj_tmp = _os.path.join(tmp_dir, "hat.obj")
            with open(obj_tmp, 'wb') as f:
                f.write(base64.b64decode(data["obj_b64"]))
            mtl_b64  = data.get("mtl_b64")
            mtl_name = data.get("mtl_name") or "hat.mtl"
            if mtl_b64:
                with open(_os.path.join(tmp_dir, mtl_name), 'wb') as f:
                    f.write(base64.b64decode(mtl_b64))
            hat_m = self.loader.loadModel(Filename.fromOsSpecific(obj_tmp))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if not hat_m:
                return
            hat_m.setR(-90)
            tex_b64 = data.get("texture_b64")
            if tex_b64:
                raw = base64.b64decode(tex_b64)
                tex_tmp = _os.path.join(tempfile.gettempdir(), f"phx_rhat_{pid}.png")
                with open(tex_tmp, 'wb') as f:
                    f.write(raw)
                tex = self.loader.loadTexture(Filename.fromOsSpecific(tex_tmp))
                try: _os.unlink(tex_tmp)
                except Exception: pass
                if tex:
                    hat_m.setTexture(tex, 1)
            bs = data.get("brick_scale", [2, 2, 2])
            ms = data.get("model_scale", [1, 1, 1])
            hat_m.setScale(bs[0]*ms[0], bs[1]*ms[1], bs[2]*ms[2])
            hat_m.setHpr(*data.get("model_hpr", [0, 0, -90]))
            z_off = float(data.get("z_offset", 0.0))
            # Parent to remote player's root — moves/rotates with the player automatically
            hat_m.reparentTo(d["root"])
            hat_m.setPos(0, 0, 4.55 + 0.55 + z_off)
            hat_m.setShaderOff()
            hat_m.setTwoSided(True)
            d["hat_model"] = hat_m
        except Exception as e:
            print(f"[HAT_REMOTE] apply failed for {pid}: {e}", flush=True)

    def _fetch_and_apply_remote_shirt(self, pid, item_id):
        if not hasattr(self, '_shirt_cache'):
            self._shirt_cache = {}
        image_b64 = self._shirt_cache.get(item_id)
        if not image_b64:
            import auth_client
            result, _ = auth_client.get_shop_item(item_id)
            if result and result.get("image_data"):
                img = result["image_data"]
                image_b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                self._shirt_cache[item_id] = image_b64
        if image_b64:
            self.taskMgr.doMethodLater(
                0, self._apply_remote_shirt_task, f"_applyShirt_{pid}",
                extraArgs=[pid, image_b64], appendTask=True,
            )

    def _apply_remote_shirt_task(self, pid, image_b64, task):
        self._apply_shirt_to_remote(pid, image_b64)
        return task.done

    def _apply_shirt_to_remote(self, pid, image_b64):
        d = self._remote_players.get(pid)
        if not d:
            return
        for n in d.get("shirt_nodes", []):
            if n and not n.isEmpty():
                n.removeNode()
        d["shirt_nodes"] = []
        if not image_b64:
            return
        try:
            import base64 as _b64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib
            from character import CharacterMixin
            raw = _b64.b64decode(image_b64)
            ss = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            R = CharacterMixin._SHIRT_REGIONS
            root = d["root"]

            def attach(parent, reg_map, w, dp, h, pos):
                node = CharacterMixin._make_shirt_box_geom(w, dp, h, reg_map)
                np = parent.attachNewNode(node)
                np.setPos(*pos)
                np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setTransparency(TransparencyAttrib.MAlpha)
                return np

            ra_piv = d["ra_piv"]
            la_piv = d["la_piv"]
            nodes = [
                attach(root, {'front': R['torso_front'], 'back': R['torso_back'],
                              'left': R['torso_left'],  'right': R['torso_right'],
                              'top':  R['torso_up'],    'bottom': R['torso_down']},
                       2, 1, 2, (-1, -0.5, 2)),
                attach(ra_piv, {'front': R['rarm_front'], 'back': R['rarm_back'],
                                'left': R['rarm_left'],   'right': R['rarm_right'],
                                'top':  R['rarm_up'],     'bottom': R['rarm_down']},
                       1, 1, 2, (-0.5, -0.5, -2)),
                attach(la_piv, {'front': R['larm_front'], 'back': R['larm_back'],
                                'left': R['larm_left'],   'right': R['larm_right'],
                                'top':  R['larm_up'],     'bottom': R['larm_down']},
                       1, 1, 2, (-0.5, -0.5, -2)),
            ]
            d["shirt_nodes"] = nodes
        except Exception as e:
            print(f"[SHIRT_REMOTE] apply failed for {pid}: {e}", flush=True)

    def _fetch_and_apply_remote_pants(self, pid, item_id):
        if not hasattr(self, '_pants_cache'):
            self._pants_cache = {}
        image_b64 = self._pants_cache.get(item_id)
        if not image_b64:
            import auth_client
            result, _ = auth_client.get_shop_item(item_id)
            if result and result.get("image_data"):
                img = result["image_data"]
                image_b64 = img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in img else img
                self._pants_cache[item_id] = image_b64
        if image_b64:
            self.taskMgr.doMethodLater(
                0, self._apply_remote_pants_task, f"_applyPants_{pid}",
                extraArgs=[pid, image_b64], appendTask=True,
            )

    def _apply_remote_pants_task(self, pid, image_b64, task):
        self._apply_pants_to_remote(pid, image_b64)
        return task.done

    def _apply_pants_to_remote(self, pid, image_b64):
        d = self._remote_players.get(pid)
        if not d:
            return
        for n in d.get("pants_nodes", []):
            if n and not n.isEmpty():
                n.removeNode()
        d["pants_nodes"] = []
        if not image_b64:
            return
        try:
            import base64 as _b64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib
            from character import CharacterMixin
            raw = _b64.b64decode(image_b64)
            ss = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            R  = CharacterMixin._PANTS_REGIONS
            TW = CharacterMixin._PANTS_TEMPLATE_W
            TH = CharacterMixin._PANTS_TEMPLATE_H
            root   = d["root"]
            ll_piv = d["ll_piv"]
            rl_piv = d["rl_piv"]

            def attach(parent, reg_map, w, dp, h, pos):
                node = CharacterMixin._make_shirt_box_geom(w, dp, h, reg_map,
                    template_w=TW, template_h=TH)
                np = parent.attachNewNode(node)
                np.setPos(*pos); np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setTransparency(TransparencyAttrib.MAlpha)
                return np

            nodes = [
                attach(root, {'front': R['torso_front'], 'back': R['torso_back'],
                              'left': R['torso_left'],  'right': R['torso_right'],
                              'top':  R['torso_up'],    'bottom': R['torso_down']},
                       2, 1, 2, (-1, -0.5, 2)),
                attach(rl_piv, {'front': R['rleg_front'], 'back': R['rleg_back'],
                                'left': R['rleg_left'],  'right': R['rleg_right'],
                                'top':  R['rleg_up'],    'bottom': R['rleg_down']},
                       1, 1, 2, (-0.5, -0.5, -2)),
                attach(ll_piv, {'front': R['lleg_front'], 'back': R['lleg_back'],
                                'left': R['lleg_left'],  'right': R['lleg_right'],
                                'top':  R['lleg_up'],    'bottom': R['lleg_down']},
                       1, 1, 2, (-0.5, -0.5, -2)),
            ]
            d["pants_nodes"] = nodes
        except Exception as e:
            print(f"[PANTS_REMOTE] apply failed for {pid}: {e}", flush=True)

    def _apply_colors_to_remote_player(self, pid, colors):
        d = self._remote_players.get(pid)
        print(f"[REMOTE_APPLY] pid={pid} d_exists={d is not None} colors={colors}", flush=True)
        if not d or not colors:
            return
        mapping = [
            ("torso_node", "torso"),
            ("la_node",    "left_arm"),
            ("ra_node",    "right_arm"),
            ("ll_node",    "left_leg"),
            ("rl_node",    "right_leg"),
            ("head_node",  "head"),
        ]
        for node_key, color_key in mapping:
            node = d.get(node_key)
            v = colors.get(color_key)
            if node and v and len(v) == 4:
                try:
                    before = node.getColor()
                    node.setColor(float(v[0]), float(v[1]), float(v[2]), float(v[3]))
                    after = node.getColor()
                    print(f"[REMOTE_APPLY] part={color_key} before={tuple(round(x,3) for x in before)} after={tuple(round(x,3) for x in after)}", flush=True)
                except Exception as e:
                    print(f"[REMOTE_APPLY] part={color_key} FAILED: {e}", flush=True)
            else:
                print(f"[REMOTE_APPLY] part={color_key} SKIP node_exists={node is not None} v={v}", flush=True)

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
            pos=(-0.04, 0, -0.12),
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

    def _broadcast_my_colors(self):
        """Send our avatar colors over the websocket so other players can update us."""
        ws   = getattr(self, "_ws", None)
        loop = getattr(self, "_mp_loop", None)
        if not ws or not loop or loop.is_closed():
            print(f"[BROADCAST_COLORS] SKIP ws={ws is not None} loop_ok={loop is not None and not loop.is_closed()}", flush=True)
            return
        try:
            colors = self.load_avatar_colors()
            print(f"[BROADCAST_COLORS] sending colors={colors}", flush=True)
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({
                    "type": "avatar_colors",
                    "colors": {k: list(v) for k, v in colors.items()},
                })),
                loop,
            )
        except Exception as e:
            print(f"[MP] broadcast colors error: {e}")
        equipped = getattr(self, '_equipped_tshirt_id', None)
        if equipped:
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send(json.dumps({"type": "equip_tshirt", "item_id": equipped})),
                    loop,
                )
            except Exception as e:
                print(f"[MP] broadcast equip_tshirt error: {e}")
        equipped_shirt = getattr(self, '_equipped_shirt_id', None)
        if equipped_shirt:
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send(json.dumps({"type": "equip_shirt", "item_id": equipped_shirt})),
                    loop,
                )
            except Exception as e:
                print(f"[MP] broadcast equip_shirt error: {e}")
        equipped_pants = getattr(self, '_equipped_pants_id', None)
        if equipped_pants:
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send(json.dumps({"type": "equip_pants", "item_id": equipped_pants})),
                    loop,
                )
            except Exception as e:
                print(f"[MP] broadcast equip_pants error: {e}")

    # ── Chat ──────────────────────────────────────────────────────────────

    def _setup_chat_ui(self):
        self._chat_messages     = []
        self._chat_input_active = False
        self._chat_visible      = True

        # Chat toggle button lives in the top toolbar (same style as Menu/Edit).
        # Placed at x=0.195, between Menu and the Edit button.
        self._chat_toggle_btn = DirectButton(
            text="Chat",
            text_fg=_TB_TEXT,
            text_scale=0.040,
            frameColor=_TB_COLOR,
            frameSize=(-0.055, 0.055, -0.032, 0.032),
            parent=self._top_bg,
            pos=(0.195, 0, _TB_BZ),
            relief=1,
            command=self._toggle_chat,
        )

        # Message area — just below the toolbar
        self._chat_panel = DirectFrame(
            frameColor=(0, 0, 0, 0.50),
            frameSize=(0, _CHAT_PNL_W, -_CHAT_PNL_H, 0),
            parent=base.a2dTopLeft,
            pos=(0.04, 0, _CHAT_TOP),
            sortOrder=50,
        )
        self._chat_lines  = []   # flat list of pre-wrapped display lines
        self._chat_labels = []
        for i in range(_CHAT_LINES):
            # i=0 → bottom (newest), i=_CHAT_LINES-1 → top (oldest)
            z = -_CHAT_PNL_H + 0.030 + i * _LINE_SPACE
            lbl = DirectLabel(
                text="",
                text_fg=(1, 1, 1, 0.92),
                text_scale=0.030,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=self._chat_panel,
                pos=(0.014, 0, z),
            )
            self._chat_labels.append(lbl)

        # Input bar — click anywhere on it to start typing
        self._chat_input_frame = DirectFrame(
            frameColor=(0, 0, 0, 0.68),
            frameSize=(0, _CHAT_PNL_W, -_INPUT_H, 0),
            parent=base.a2dTopLeft,
            pos=(0.04, 0, _CHAT_TOP - _CHAT_PNL_H),
            sortOrder=51,
            state=DGG.NORMAL,
        )
        self._chat_placeholder = DirectLabel(
            text='To chat click here or press "/" key',
            text_fg=(1, 1, 1, 0.38),
            text_scale=0.028,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=self._chat_input_frame,
            pos=(0.015, 0, -0.033),
        )
        self._chat_entry = DirectEntry(
            text_fg=(1, 1, 1, 1),
            text_scale=0.033,
            frameColor=(0, 0, 0, 0),
            width=26,
            numLines=3,
            parent=self._chat_input_frame,
            pos=(0.012, 0, -0.033),
            command=self._on_chat_submit,
        )
        self._chat_entry.hide()
        self._chat_input_frame.bind(DGG.B1PRESS, lambda e: self._open_chat_input())

    def _teardown_chat_ui(self):
        for attr in ("_chat_toggle_btn", "_chat_panel", "_chat_input_frame"):
            node = getattr(self, attr, None)
            if node:
                try:
                    node.destroy()
                except Exception:
                    pass
            setattr(self, attr, None)
        self._chat_lines        = []
        self._chat_labels       = []
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

    def _chat_resize_task(self, task):
        import textwrap
        entry = getattr(self, "_chat_entry", None)
        frame = getattr(self, "_chat_input_frame", None)
        if entry is None or frame is None:
            return Task.done

        # Auto-resize height based on wrapped line count
        raw = entry.get()
        lines = textwrap.wrap(raw, _CHAT_WRAP) if raw else []
        n = max(1, len(lines))
        new_h = _INPUT_H + (n - 1) * _INPUT_LINE
        frame["frameSize"] = (0, _CHAT_PNL_W, -new_h, 0)

        # Click-outside detection (avoids touching accept("mouse1") which would
        # overwrite the editor's picker handler registered in game.py)
        mwn = base.mouseWatcherNode
        pressed = mwn.isButtonDown(MouseButton.one())
        if pressed and not getattr(self, "_chat_m1_was_down", True):
            if not self._is_mouse_over_chat_input():
                self._close_chat_input()
                return Task.done
        self._chat_m1_was_down = pressed

        return Task.cont

    def _is_mouse_over_chat_input(self):
        if not base.mouseWatcherNode.hasMouse():
            return True
        m  = base.mouseWatcherNode.getMouse()
        ar = base.getAspectRatio()
        x0 = (-ar + 0.04) / ar
        x1 = x0 + _CHAT_PNL_W / ar
        z1 = 1.0 + _CHAT_TOP - _CHAT_PNL_H
        frame = getattr(self, "_chat_input_frame", None)
        h  = (-frame["frameSize"][2]) if frame else _INPUT_H
        z0 = z1 - h
        return x0 <= m.x <= x1 and z0 <= m.y <= z1

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
        self._chat_m1_was_down  = True  # ignore the click that opened the input
        ph = getattr(self, "_chat_placeholder", None)
        if ph: ph.hide()
        self._chat_entry.show()
        self._chat_entry.set("")
        self._chat_entry["focus"] = 1
        self.taskMgr.add(self._chat_resize_task, "_chatResize")

    def _close_chat_input(self):
        self._chat_input_active = False
        self.taskMgr.remove("_chatResize")
        frame = getattr(self, "_chat_input_frame", None)
        if frame:
            frame["frameSize"] = (0, _CHAT_PNL_W, -_INPUT_H, 0)
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
                ws.send(json.dumps({"type": "chat", "text": text[:400]})),
                loop,
            )
        username = getattr(self, "_session_username", "You")
        self._add_chat_message(username, text)

    def _add_chat_message(self, username, text):
        if not hasattr(self, "_chat_lines"):
            return
        import textwrap
        line = f"{username}: {text}"
        self._chat_lines.extend(textwrap.wrap(line, _CHAT_WRAP) or [line])
        if len(self._chat_lines) > _CHAT_LINES * 6:
            self._chat_lines = self._chat_lines[-(_CHAT_LINES * 4):]
        visible = self._chat_lines[-_CHAT_LINES:]
        for i, lbl in enumerate(self._chat_labels):
            # label[0] = bottom = newest; label[-1] = top = oldest
            rev = len(visible) - 1 - i
            lbl["text"] = visible[rev] if rev >= 0 else ""
