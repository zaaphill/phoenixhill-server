import json
import os

from direct.gui.DirectGui import DirectFrame, DirectButton, DirectLabel
from direct.task import Task
from panda3d.core import (
    TextNode, TransparencyAttrib, Filename,
    Camera, PerspectiveLens, NodePath, Point3,
    LColor, MouseButton, BitMask32,
    AmbientLight, DirectionalLight, CardMaker,
)

_USER_DATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PhoenixHill")

DARK   = (0.11, 0.12, 0.17, 0.97)
DARKER = (0.07, 0.08, 0.11, 1.0)
BTN    = (0.19, 0.21, 0.29, 1.0)
SEL    = (0.18, 0.38, 0.72, 1.0)
TEXT   = (0.88, 0.90, 0.95, 1.0)
TEXT_D = (0.54, 0.57, 0.65, 1.0)

_DEFAULTS = {
    "head":      (244/255, 204/255,  67/255, 1),
    "torso":     ( 23/255, 107/255, 170/255, 1),
    "left_arm":  (244/255, 204/255,  67/255, 1),
    "right_arm": (244/255, 204/255,  67/255, 1),
    "left_leg":  (165/255, 188/255,  80/255, 1),
    "right_leg": (165/255, 188/255,  80/255, 1),
}

# 8 × 8 = 64 colour swatches
_PALETTE = [
    # Row 1 — greens / yellows / reds / purples / blues / teals
    (0.64, 0.74, 0.26, 1), (0.93, 0.82, 0.14, 1), (0.96, 0.64, 0.15, 1), (0.72, 0.18, 0.14, 1),
    (0.44, 0.13, 0.44, 1), (0.14, 0.21, 0.51, 1), (0.06, 0.57, 0.62, 1), (0.15, 0.49, 0.19, 1),
    # Row 2 — greyscale
    (1.00, 1.00, 1.00, 1), (0.90, 0.90, 0.90, 1), (0.75, 0.75, 0.75, 1), (0.60, 0.60, 0.60, 1),
    (0.45, 0.45, 0.45, 1), (0.30, 0.30, 0.30, 1), (0.17, 0.17, 0.17, 1), (0.06, 0.06, 0.06, 1),
    # Row 3 — muted / earthy
    (0.44, 0.55, 0.30, 1), (0.71, 0.55, 0.28, 1), (0.76, 0.50, 0.38, 1), (0.55, 0.33, 0.26, 1),
    (0.42, 0.33, 0.38, 1), (0.38, 0.40, 0.52, 1), (0.32, 0.55, 0.55, 1), (0.35, 0.52, 0.38, 1),
    # Row 4 — pastels
    (0.86, 0.94, 0.73, 1), (0.98, 0.95, 0.76, 1), (0.99, 0.82, 0.63, 1), (0.91, 0.63, 0.65, 1),
    (0.83, 0.70, 0.84, 1), (0.73, 0.77, 0.90, 1), (0.72, 0.90, 0.93, 1), (0.73, 0.93, 0.79, 1),
    # Row 5 — skin tones
    (0.96, 0.87, 0.72, 1), (0.95, 0.76, 0.57, 1), (0.87, 0.63, 0.43, 1), (0.75, 0.50, 0.31, 1),
    (0.62, 0.37, 0.22, 1), (0.86, 0.47, 0.47, 1), (0.94, 0.60, 0.53, 1), (0.96, 0.76, 0.65, 1),
    # Row 6 — vivid / bright
    (0.67, 0.84, 0.18, 1), (0.97, 0.92, 0.11, 1), (0.97, 0.55, 0.00, 1), (0.91, 0.09, 0.08, 1),
    (0.90, 0.07, 0.49, 1), (0.09, 0.15, 0.87, 1), (0.02, 0.87, 0.93, 1), (0.07, 0.86, 0.07, 1),
    # Row 7 — deep / saturated
    (0.44, 0.35, 0.23, 1), (0.63, 0.42, 0.26, 1), (0.73, 0.44, 0.41, 1), (0.55, 0.20, 0.54, 1),
    (0.36, 0.17, 0.60, 1), (0.12, 0.29, 0.72, 1), (0.05, 0.47, 0.82, 1), (0.07, 0.44, 0.23, 1),
    # Row 8 — darkest
    (0.28, 0.18, 0.12, 1), (0.48, 0.30, 0.16, 1), (0.65, 0.37, 0.29, 1), (0.48, 0.12, 0.47, 1),
    (0.27, 0.09, 0.47, 1), (0.06, 0.17, 0.55, 1), (0.02, 0.32, 0.60, 1), (0.05, 0.27, 0.16, 1),
]

_PARTS_LAYOUT = [
    ("head",      -0.420,  0.210, 0.070, 0.070),
    ("torso",     -0.420,  0.000, 0.140, 0.140),
    ("left_arm",  -0.630,  0.000, 0.070, 0.140),
    ("right_arm", -0.210,  0.000, 0.070, 0.140),
    ("left_leg",  -0.490, -0.280, 0.070, 0.140),
    ("right_leg", -0.350, -0.280, 0.070, 0.140),
]


class AvatarMixin:

    # ── Persistence ────────────────────────────────────────────────────────

    def _avatar_file_path(self, username=None):
        name = username or getattr(self, "_session_username", None) or "_default"
        return os.path.join(_USER_DATA, f"avatar_{name}.json")

    def load_avatar_colors(self, username=None):
        colors = dict(_DEFAULTS)
        path = self._avatar_file_path(username)
        try:
            with open(path) as f:
                data = json.load(f)
            for part in _DEFAULTS:
                if part in data and len(data[part]) == 4:
                    colors[part] = tuple(float(v) for v in data[part])
            print(f"[AVATAR_LOAD] username={username or getattr(self,'_session_username',None)} path={path} colors={colors}", flush=True)
        except Exception as e:
            print(f"[AVATAR_LOAD] username={username or getattr(self,'_session_username',None)} path={path} FILE_MISSING_OR_ERROR={e} returning_defaults", flush=True)
        return colors

    def save_avatar_colors(self, colors, username=None):
        path = self._avatar_file_path(username)
        try:
            os.makedirs(_USER_DATA, exist_ok=True)
            with open(path, "w") as f:
                json.dump({k: list(v) for k, v in colors.items()}, f)
            print(f"[AVATAR_SAVE] username={username or getattr(self,'_session_username',None)} path={path} colors={colors}", flush=True)
        except Exception as e:
            print(f"[AVATAR_SAVE] FAILED path={path} error={e}", flush=True)

    def apply_avatar_colors(self):
        colors = self.load_avatar_colors()
        for part in _DEFAULTS:
            node = getattr(self, part, None)
            exists = node is not None
            if exists:
                node.setColor(*colors[part])
            print(f"[SETCOLOR_LOCAL] part={part} rgba={colors[part]} node_exists={exists}", flush=True)

    # ── Avatar screen ──────────────────────────────────────────────────────

    def _build_avatar_screen(self, subtab="items"):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        self._avatar_colors       = self.load_avatar_colors()
        self._avatar_selected     = "head"
        self._avatar_btns         = {}
        if not hasattr(self, "_equipped_tshirt_id"):
            self._equipped_tshirt_id = None

        _RS_BG     = (0.78, 0.75, 0.88, 1.0)
        _RS_NAV    = (0.55, 0.45, 0.76, 1.0)
        _RS_SUBNAV = (0.62, 0.52, 0.80, 1.0)
        _RS_ORANGE = (0.58, 0.18, 0.82, 1.0)
        _RS_WHITE  = (0.00, 0.00, 0.00, 1.0)
        _RS_GRAY   = (0.00, 0.00, 0.00, 1.0)
        _RS_BORDER = (0.48, 0.38, 0.66, 1.0)

        bg = DirectFrame(frameColor=_RS_BG, frameSize=(-3, 3, -3, 3))
        self._main_menu_ui = bg

        # ── Top nav bar (Avatar tab active) ───────────────────────────────
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
            is_active = (i == 1)
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
            text=getattr(self, "_session_username", "") or "",
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

        # ── Sub-nav: Colors / Items ────────────────────────────────────────
        DirectFrame(
            frameColor=_RS_SUBNAV,
            frameSize=(-3, 3, -0.040, 0.040),
            parent=bg, pos=(0, 0, 0.760),
        )
        for i, (label, tab) in enumerate([("Items", "items"), ("Colors", "colors")]):
            is_active = (tab == subtab)
            DirectButton(
                text=label,
                text_fg=_RS_WHITE,
                text_scale=0.028,
                frameColor=_RS_ORANGE if is_active else (0.48, 0.38, 0.66, 1.0),
                frameSize=(-0.095, 0.095, -0.028, 0.028),
                parent=bg,
                pos=(-0.12 + i * 0.24, 0, 0.756),
                relief=1,
                command=self._build_avatar_screen,
                extraArgs=[tab],
            )

        # ── Content area ──────────────────────────────────────────────────
        if subtab == "colors":
            self._build_avatar_char(bg, x_off=-0.28, z_off=-0.08)
            self._build_avatar_palette(bg, left=0.16, top=0.20, sw=0.082, sh=0.078, pad=0.007)
        else:
            self._build_avatar_items_content(bg)

    # ── Colors tab content (2D clickable char + palette) ──────────────────

    def _build_avatar_char(self, parent, x_off=0.0, z_off=0.0):
        for key, cx, cz, hw, hh in _PARTS_LAYOUT:
            btn = DirectButton(
                frameColor=self._avatar_colors[key],
                frameSize=(-hw, hw, -hh, hh),
                parent=parent, pos=(cx + x_off, 0, cz + z_off),
                relief=1, sortOrder=10,
                command=self._avatar_select,
                extraArgs=[key],
            )
            self._avatar_btns[key] = btn

    def _build_avatar_palette(self, parent, left=0.055, top=0.420,
                              sw=0.072, sh=0.068, pad=0.006):
        COLS = 8
        for i, color in enumerate(_PALETTE):
            col = i % COLS
            row = i // COLS
            x = left + col * (sw + pad) + sw / 2
            z = top  - row * (sh + pad)
            DirectButton(
                frameColor=color,
                frameSize=(-sw / 2, sw / 2, -sh / 2, sh / 2),
                parent=parent, pos=(x, 0, z),
                relief=1,
                command=self._avatar_pick,
                extraArgs=[color],
            )

    def _avatar_select(self, part):
        self._avatar_selected = part
        btn = self._avatar_btns.get(part)
        if btn:
            from direct.interval.IntervalGlobal import Sequence, LerpScaleInterval
            Sequence(
                LerpScaleInterval(btn, 0.06, 0.88),
                LerpScaleInterval(btn, 0.10, 1.00),
            ).start()

    def _avatar_pick(self, color):
        part = self._avatar_selected
        self._avatar_colors[part] = color
        btn = self._avatar_btns[part]
        btn["frameColor"] = color
        self.save_avatar_colors(self._avatar_colors)
        self.apply_avatar_colors()
        token = getattr(self, "_session_token", None)
        if token:
            import threading, auth_client
            colors_copy = {k: list(v) for k, v in self._avatar_colors.items()}
            threading.Thread(
                target=lambda: auth_client.put_avatar(token, colors_copy),
                daemon=True,
            ).start()

    # ── Items tab content (3D preview + empty list) ────────────────────────

    def _build_avatar_items_content(self, parent):
        CARD_W = 0.50
        CARD_H = 0.60
        CARD_X = -0.75
        CARD_Z = -0.10
        PMASK  = BitMask32.bit(5)

        # ── Preview root anchored in render (cull traverser finds it) ─────
        preview_root = self.render.attachNewNode("avatar_preview_root")
        preview_root.setPos(0, 2000, 0)
        self._avatar_preview_root = preview_root

        # ── Fresh preview rig — NO copyTo, zero inherited state ────────────
        colors = getattr(self, "_avatar_colors", {}) or {}
        self._build_preview_rig(preview_root, colors, PMASK)

        # ── Lighting ───────────────────────────────────────────────────────
        # Soft ambient so no face goes fully black
        alight = AmbientLight("preview_ambient")
        alight.setColor(LColor(0.22, 0.22, 0.25, 1))
        preview_root.setLight(preview_root.attachNewNode(alight))

        # Key light from the camera-side (H=0 shines in +Y = toward character front)
        dlight = DirectionalLight("preview_key")
        dlight.setColor(LColor(0.50, 0.50, 0.52, 1))
        dlnp = preview_root.attachNewNode(dlight)
        dlnp.setHpr(20, 15, 0)
        preview_root.setLight(dlnp)

        # Rim light from above-back to give depth
        fill = DirectionalLight("preview_fill")
        fill.setColor(LColor(0.16, 0.16, 0.18, 1))
        flnp = preview_root.attachNewNode(fill)
        flnp.setHpr(200, -50, 0)
        preview_root.setLight(flnp)

        # ── Camera pivot (at character mid-height) ─────────────────────────
        pivot = preview_root.attachNewNode("avatar_preview_pivot")
        pivot.setPos(0, 0, 2)
        self._avatar_cam_pivot = pivot

        # ── Buffer ─────────────────────────────────────────────────────────
        # Buffer aspect must match card display aspect (CARD_W*2 / CARD_H*2 = 0.833)
        # so no stretch occurs when frameTexture fills the card.
        buf = self.win.makeTextureBuffer("avatar_preview", 400, 480)
        buf.setClearColor(LColor(0.78, 0.75, 0.88, 1.0))
        buf.setClearColorActive(True)
        self._avatar_buf = buf

        # ── Camera (officially supported RTT path) ─────────────────────────
        cam_np = self.makeCamera(buf)
        cam_np.reparentTo(pivot)
        cam_np.setPos(0, -8, 0)
        cam_np.lookAt(preview_root, Point3(0, 0, 3))
        lens = cam_np.node().getLens()
        # Must set aspect explicitly — makeCamera may use main-window aspect by default.
        # setFov(h) then derives vFOV from the given aspect.
        lens.setAspectRatio(CARD_W / CARD_H)   # 0.833 = buffer 400/480
        lens.setFov(32)                         # hFOV 32° → vFOV ≈ 38°
        lens.setNearFar(0.1, 1000)
        cam_np.node().setCameraMask(PMASK)
        self._avatar_cam_np = cam_np

        # ── Exclude PMASK from main camera ─────────────────────────────────
        orig_mask = self.camNode.getCameraMask()
        self._avatar_saved_cam_mask = orig_mask
        self.camNode.setCameraMask(orig_mask & ~PMASK)

        # ── Texture card ───────────────────────────────────────────────────
        tex = buf.getTexture()
        preview_card = DirectFrame(
            frameTexture=tex,
            frameColor=(1, 1, 1, 1),
            frameSize=(-CARD_W, CARD_W, -CARD_H, CARD_H),
            parent=parent, pos=(CARD_X, 0, CARD_Z),
        )
        preview_card.setTransparency(False)

        DirectLabel(
            text="Drag to rotate",
            text_fg=(0.40, 0.35, 0.55, 1), text_scale=0.022,
            frameColor=(0, 0, 0, 0),
            parent=parent,
            pos=(CARD_X, 0, CARD_Z - CARD_H - 0.038),
        )

        # ── Drag-to-rotate task ────────────────────────────────────────────
        self._avatar_drag_active = False
        self._avatar_drag_last_x = 0.0

        def _drag_task(task):
            if getattr(self, '_avatar_buf', None) is None:
                return Task.done
            dt = globalClock.getDt()

            # Animate face sprite at 4 fps
            face_spr = getattr(self, '_avatar_preview_face_sprite', None)
            face_txs = getattr(self, '_face_textures', [])
            if face_spr and face_txs:
                self._avatar_preview_face_t += dt
                if self._avatar_preview_face_t >= 0.25:
                    self._avatar_preview_face_t -= 0.25
                    self._avatar_preview_face_frame = (
                        self._avatar_preview_face_frame + 1) % len(face_txs)
                    face_spr.setTexture(face_txs[self._avatar_preview_face_frame])

            mwn = self.mouseWatcherNode
            if not mwn.hasMouse():
                self._avatar_drag_active = False
                return Task.cont
            m = mwn.getMouse()
            pressed = mwn.isButtonDown(MouseButton.one())
            if pressed:
                if not self._avatar_drag_active:
                    # Only start a drag when the click begins inside the card
                    ar = self.getAspectRatio()
                    in_card = (
                        (CARD_X - CARD_W) < m.x * ar < (CARD_X + CARD_W) and
                        (CARD_Z - CARD_H) < m.y       < (CARD_Z + CARD_H)
                    )
                    if in_card:
                        self._avatar_drag_active = True
                        self._avatar_drag_last_x = m.x
                else:
                    # Continue rotating wherever the mouse is
                    dx = m.x - self._avatar_drag_last_x
                    p = getattr(self, '_avatar_cam_pivot', None)
                    if p and not p.isEmpty():
                        p.setH(p.getH() - dx * 200)
                    self._avatar_drag_last_x = m.x
            else:
                self._avatar_drag_active = False
            return Task.cont

        self.taskMgr.add(_drag_task, "_avatarItemsDrag")

        # ── Items list panel (purple theme) ────────────────────────────────
        _PANEL_BG  = (0.68, 0.65, 0.82, 1.0)
        _PANEL_DIV = (0.50, 0.40, 0.68, 1.0)
        _TEXT_H    = (0.12, 0.08, 0.28, 1.0)
        _TEXT_M    = (0.22, 0.15, 0.40, 1.0)
        _TEXT_D    = (0.32, 0.22, 0.50, 1.0)

        items_bg = DirectFrame(
            frameColor=_PANEL_BG,
            frameSize=(-0.72, 0.72, -0.75, 0.68),
            parent=parent, pos=(0.55, 0, -0.08),
        )
        DirectLabel(
            text="Items", text_fg=_TEXT_H, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=items_bg, pos=(0, 0, 0.56),
        )
        DirectFrame(
            frameColor=_PANEL_DIV,
            frameSize=(-0.64, 0.64, -0.002, 0.002),
            parent=items_bg, pos=(0, 0, 0.44),
        )
        self._avatar_items_loading_lbl = DirectLabel(
            text="Loading...", text_fg=_TEXT_M, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=items_bg, pos=(0, 0, 0.20),
        )
        self._avatar_items_bg = items_bg
        self._avatar_items_panel_colors = (_TEXT_H, _TEXT_M, _TEXT_D, _PANEL_BG, _PANEL_DIV)

        token = getattr(self, "_session_token", None)
        if token:
            import threading as _thr, auth_client as _ac
            equipped_id = getattr(self, "_equipped_tshirt_id", None)
            def _fetch(eid=equipped_id):
                result, _ = _ac.get_owned_items(token)
                owned_items = (result or {}).get("items", [])
                # If a T-shirt is already equipped, fetch its image for the preview
                preview_b64 = None
                if eid:
                    for it in owned_items:
                        if it.get("id") == eid and it.get("image_data"):
                            preview_b64 = it["image_data"]
                            break
                    if not preview_b64:
                        full, _ = _ac.get_shop_item(eid)
                        if full:
                            preview_b64 = full.get("image_data")
                def _populate(task, items=owned_items, b64=preview_b64):
                    self._populate_avatar_items(items)
                    if b64:
                        self._preview_apply_tshirt(b64)
                    return task.done
                self.taskMgr.doMethodLater(0, _populate, "_populateAvatarItems", appendTask=True)
            _thr.Thread(target=_fetch, daemon=True).start()
        else:
            lbl = getattr(self, "_avatar_items_loading_lbl", None)
            if lbl and not lbl.isEmpty():
                lbl["text"] = "Not logged in."

    def _populate_avatar_items(self, items):
        lbl = getattr(self, "_avatar_items_loading_lbl", None)
        if lbl and not lbl.isEmpty():
            lbl.destroy()
        self._avatar_items_loading_lbl = None
        items_bg = getattr(self, "_avatar_items_bg", None)
        if not items_bg or items_bg.isEmpty():
            return
        _TEXT_H, _TEXT_M, _TEXT_D, _PANEL_BG, _PANEL_DIV = self._avatar_items_panel_colors

        if not items:
            DirectLabel(
                text="No items", text_fg=_TEXT_M, text_scale=0.032,
                frameColor=(0, 0, 0, 0),
                parent=items_bg, pos=(0, 0, 0.06),
            )
            DirectLabel(
                text="Items you collect from\nthe shop will appear here.",
                text_fg=_TEXT_D, text_scale=0.026,
                frameColor=(0, 0, 0, 0),
                parent=items_bg, pos=(0, 0, -0.12),
            )
            return

        equipped_id = getattr(self, "_equipped_tshirt_id", None)
        ROW_H = 0.110
        self._avatar_item_btns = {}

        for i, item in enumerate(items[:6]):
            y = 0.34 - i * ROW_H
            item_id = item.get("id")
            name = item.get("name", "")

            # Swatch
            DirectFrame(
                frameColor=(0.48, 0.38, 0.66, 1.0),
                frameSize=(-0.044, 0.044, -0.036, 0.036),
                parent=items_bg, pos=(-0.60, 0, y),
            )
            # Name
            DirectLabel(
                text=(name[:16] + "...") if len(name) > 18 else name,
                text_fg=_TEXT_H, text_scale=0.026,
                text_align=TextNode.ALeft,
                frameColor=(0, 0, 0, 0),
                parent=items_bg, pos=(-0.50, 0, y + 0.006),
            )
            # Equip / Unequip button
            is_equipped = (item_id == equipped_id)
            btn_text = "Unequip" if is_equipped else "Equip"
            btn_col  = (0.38, 0.26, 0.58, 1.0) if is_equipped else (0.58, 0.18, 0.82, 1.0)
            btn = DirectButton(
                text=btn_text,
                text_fg=(1, 1, 1, 1), text_scale=0.022,
                frameColor=btn_col,
                frameSize=(-0.090, 0.090, -0.028, 0.028),
                parent=items_bg, pos=(0.54, 0, y),
                relief=1,
                command=self._on_avatar_item_equip,
                extraArgs=[item],
            )
            self._avatar_item_btns[item_id] = btn

    def _on_avatar_item_equip(self, item):
        import threading as _thr, auth_client as _ac
        item_id = item.get("id")
        image_b64 = item.get("image_data", "")
        equipped_id = getattr(self, "_equipped_tshirt_id", None)

        if item_id == equipped_id:
            # Unequip
            self._equipped_tshirt_id = None
            if hasattr(self, "remove_tshirt"):
                self.remove_tshirt()
            self._preview_apply_tshirt(None)
            token = getattr(self, "_session_token", None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_tshirt(token, None), daemon=True).start()
            # Broadcast unequip via WS
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_tshirt", "item_id": None})), loop)
                except Exception:
                    pass
        else:
            # Equip
            self._equipped_tshirt_id = item_id
            if image_b64:
                if hasattr(self, "apply_tshirt"):
                    self.apply_tshirt(image_b64)
                self._preview_apply_tshirt(image_b64)
            else:
                # Fetch image data then apply to both in-game and preview
                def _fetch_and_apply(iid=item_id):
                    full, _ = _ac.get_shop_item(iid)
                    if full and full.get("image_data"):
                        def _apply(task, b64=full["image_data"]):
                            if hasattr(self, "apply_tshirt"):
                                self.apply_tshirt(b64)
                            self._preview_apply_tshirt(b64)
                            return task.done
                        self.taskMgr.doMethodLater(0, _apply, "_applyTshirtLocal", appendTask=True)
                _thr.Thread(target=_fetch_and_apply, daemon=True).start()
            token = getattr(self, "_session_token", None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_tshirt(token, item_id), daemon=True).start()
            # Broadcast equip via WS
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_tshirt", "item_id": item_id})), loop)
                except Exception:
                    pass

        # Refresh button labels
        btns = getattr(self, "_avatar_item_btns", {})
        new_equipped = getattr(self, "_equipped_tshirt_id", None)
        for bid, btn in btns.items():
            if btn and not btn.isEmpty():
                is_eq = (bid == new_equipped)
                btn["text"] = "Unequip" if is_eq else "Equip"
                btn["frameColor"] = (0.38, 0.26, 0.58, 1.0) if is_eq else (0.58, 0.18, 0.82, 1.0)

    def _preview_apply_tshirt(self, image_b64):
        """Add or replace the T-shirt card on the avatar preview rig."""
        from panda3d.core import CardMaker, TransparencyAttrib, Filename, BitMask32
        for attr in ('_avatar_preview_tshirt_anchor', '_avatar_preview_tshirt_np'):
            n = getattr(self, attr, None)
            if n and not n.isEmpty():
                n.removeNode()
            setattr(self, attr, None)
        if not image_b64:
            return
        root  = getattr(self, '_avatar_preview_rig_root', None)
        pmask = getattr(self, '_avatar_preview_rig_pmask', BitMask32.allOn())
        if not root or root.isEmpty():
            return
        try:
            import base64, tempfile, os as _os2
            raw = base64.b64decode(image_b64)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                tf.write(raw); tmp = tf.name
            tex = self.loader.loadTexture(Filename.fromOsSpecific(tmp))
            _os2.unlink(tmp)
            if not tex:
                return
            cm = CardMaker('preview_tshirt')
            cm.setFrame(-1, 1, 0, 2)
            anchor = root.attachNewNode("preview_tshirt_anchor")
            anchor.setPos(0, -0.51, 2)   # -Y side faces the preview camera at Y=-8
            np = anchor.attachNewNode(cm.generate())
            np.setTexture(tex)
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setLightOff()
            np.setShaderOff()
            np.setDepthWrite(False)
            np.setDepthOffset(1)
            np.show(pmask)
            self._avatar_preview_tshirt_anchor = anchor
            self._avatar_preview_tshirt_np     = np
        except Exception as e:
            print(f"[PREVIEW_TSHIRT] {e}", flush=True)

    def _build_preview_rig(self, root, colors, pmask):
        """Build a completely fresh avatar rig under root — no copyTo, no inherited state."""
        self._avatar_preview_rig_root  = root
        self._avatar_preview_rig_pmask = pmask
        self._avatar_preview_tshirt_anchor = None
        self._avatar_preview_tshirt_np     = None

        def box(parent, scale, pos, color_key):
            m = self.loader.loadModel("models/box")
            m.reparentTo(parent)
            m.setScale(*scale)
            m.setPos(*pos)
            m.setColor(*colors.get(color_key, _DEFAULTS[color_key]))
            m.setTextureOff(1)
            m.show(pmask)
            return m

        torso = box(root, (2, 1, 2), (-1, -0.5, 2), "torso")

        cx, cy = 0.0, 0.0    # torso center x/y
        top_z  = 4.0         # torso top z
        bot_z  = 2.0         # torso bottom z

        la_piv = root.attachNewNode("la_piv")
        la_piv.setPos(cx - 1.5, cy, top_z)
        box(la_piv, (1, 1, 2), (-0.5, -0.5, -2), "left_arm")

        ra_piv = root.attachNewNode("ra_piv")
        ra_piv.setPos(cx + 1.5, cy, top_z)
        box(ra_piv, (1, 1, 2), (-0.5, -0.5, -2), "right_arm")

        ll_piv = root.attachNewNode("ll_piv")
        ll_piv.setPos(cx - 0.5, cy, bot_z)
        box(ll_piv, (1, 1, 2), (-0.5, -0.5, -2), "left_leg")

        rl_piv = root.attachNewNode("rl_piv")
        rl_piv.setPos(cx + 0.5, cy, bot_z)
        box(rl_piv, (1, 1, 2), (-0.5, -0.5, -2), "right_leg")

        head = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        head.reparentTo(root)
        head.setColor(*colors.get("head", _DEFAULTS["head"]))
        head.setTwoSided(True)
        head.setTextureOff(1)
        head.setPos(cx, cy, top_z + 0.55)
        head.show(pmask)

        # Face sprite — placed on the -Y side of the head (toward the preview camera)
        face_textures = getattr(self, '_face_textures', [])
        self._avatar_preview_face_sprite = None
        if face_textures:
            face_cm = CardMaker('preview_face')
            face_cm.setFrame(-0.70, 0.70, -0.55, 0.55)
            face_anchor = root.attachNewNode("preview_face_anchor")
            face_anchor.setPos(cx, cy - 0.72, top_z + 0.55)
            face_sprite = face_anchor.attachNewNode(face_cm.generate())
            face_sprite.setTransparency(TransparencyAttrib.MAlpha)
            face_sprite.setTwoSided(False)
            face_sprite.setColor(1, 1, 1, 1)
            face_sprite.setLightOff()
            face_sprite.setShaderOff()
            face_sprite.setDepthWrite(False)
            face_sprite.setTexture(face_textures[0])
            face_sprite.show(pmask)
            self._avatar_preview_face_sprite = face_sprite
            self._avatar_preview_face_frame = 0
            self._avatar_preview_face_t     = 0.0

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _cleanup_avatar_items_tab(self):
        self.taskMgr.remove("_avatarItemsDrag")
        saved = getattr(self, '_avatar_saved_cam_mask', None)
        if saved is not None:
            self.camNode.setCameraMask(saved)
        self._avatar_saved_cam_mask = None
        buf = getattr(self, '_avatar_buf', None)
        if buf:
            self.graphicsEngine.removeWindow(buf)
        self._avatar_buf = None
        for attr in ('_avatar_cam_np', '_avatar_cam_pivot',
                     '_avatar_char_copy', '_avatar_preview_root',
                     '_avatar_preview_tshirt_anchor', '_avatar_preview_tshirt_np',
                     '_avatar_preview_rig_root'):
            node = getattr(self, attr, None)
            if node and not node.isEmpty():
                node.removeNode()
            setattr(self, attr, None)
