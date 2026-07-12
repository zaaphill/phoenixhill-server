import json
import os
import sys

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
        self._nav_av_update_colors()

    # ── Avatar screen ──────────────────────────────────────────────────────

    def _build_avatar_screen(self, items_filter="tshirt"):
        self._cleanup_avatar_items_tab()
        if self._main_menu_ui:
            self._main_menu_ui.destroy()

        self._avatar_colors       = self.load_avatar_colors()
        self._avatar_selected     = "head"
        self._avatar_btns         = {}
        if not hasattr(self, "_equipped_tshirt_id"):
            self._equipped_tshirt_id = None
        if not hasattr(self, "_equipped_hat_id"):
            self._equipped_hat_id = None
        if not hasattr(self, "_equipped_shirt_id"):
            self._equipped_shirt_id = None
        if not hasattr(self, "_equipped_pants_id"):
            self._equipped_pants_id = None

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
            frameSize=(-2.5, 2.5, -0.076, 0.090),
            parent=bg, pos=(0, 0, 0.908),
        )
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        _lt = None
        try:
            _lt = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(_base_dir, 'PiePlex logo.png')))
        except Exception:
            pass
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
            is_active = (i == 1)
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
                    os.path.join(_base_dir, _nav_icons[i])))
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
            text=getattr(self, "_session_username", "") or "",
            text_fg=_RS_GRAY, text_scale=0.040,
            frameColor=(0, 0, 0, 0),
            parent=nav, pos=(1.07, 0, 0.005),
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

        # ── Content area ──────────────────────────────────────────────────
        self._build_avatar_items_content(bg, items_filter=items_filter)
        _sbar_cache = {}
        for _sif in ["hat.png", "face.png", "shirt.png", "pantss.png", "t shirt.png", "colors.png"]:
            try:
                _st = self.loader.loadTexture(Filename.fromOsSpecific(os.path.join(_base_dir, _sif)))
                if _st:
                    _sbar_cache[_sif] = _st
            except Exception:
                pass
        self._build_avatar_sidebar(bg, items_filter, _sbar_cache)

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
        btn = (self._avatar_btns or {}).get(part)
        if btn and not btn.isEmpty():
            btn["frameColor"] = color
        self.save_avatar_colors(self._avatar_colors)
        self.apply_avatar_colors()
        self._nav_avatar_tex = 'UNSET'  # invalidate cached topbar thumbnail
        token = getattr(self, "_session_token", None)
        if token:
            import threading, auth_client
            colors_copy = {k: list(v) for k, v in self._avatar_colors.items()}
            threading.Thread(
                target=lambda: auth_client.put_avatar(token, colors_copy),
                daemon=True,
            ).start()

    # ── Sidebar + category switching ───────────────────────────────────────

    def _build_avatar_sidebar(self, parent, current_filter="tshirt", icon_cache=None):
        from panda3d.core import CardMaker
        _PANEL_BG  = (0.62, 0.58, 0.78, 1.0)
        _SEL_COL   = (0.44, 0.32, 0.64, 1.0)
        _NORM_COL  = (0.55, 0.46, 0.72, 1.0)
        _TEXT_H    = (0.12, 0.08, 0.28, 1.0)
        _base_dir  = os.path.dirname(os.path.abspath(__file__))
        _CATS = [
            ("Hats",     "hat",     "hat.png"),
            ("Faces",    "face",    "face.png"),
            ("Shirts",   "shirt",   "shirt.png"),
            ("Pants",    "pants",   "pantss.png"),
            ("T-Shirts", "tshirt",  "t shirt.png"),
            ("Colors",   "colors",  "colors.png"),
        ]
        _BTN_H = 0.21
        _GAP   = 0.017
        _n     = len(_CATS)
        _total = _n * _BTN_H + (_n - 1) * _GAP
        _start_z = (-0.82 + 0.68) / 2 + _total / 2 - _BTN_H / 2
        sidebar = DirectFrame(
            frameColor=_PANEL_BG,
            frameSize=(-0.16, 0.16, -0.82, 0.68),
            parent=parent, pos=(1.14, 0, -0.08),
        )
        self._avatar_sidebar_frame = sidebar
        self._avatar_sidebar_buttons = {}
        for i, (label, cat, icon_file) in enumerate(_CATS):
            is_sel = (cat == current_filter)
            bz = _start_z - i * (_BTN_H + _GAP)
            btn = DirectButton(
                text="",
                frameColor=_SEL_COL if is_sel else _NORM_COL,
                frameSize=(-0.14, 0.14, -_BTN_H/2, _BTN_H/2),
                parent=sidebar, pos=(0, 0, bz),
                relief=1,
                command=self._switch_avatar_category,
                extraArgs=[cat],
            )
            self._avatar_sidebar_buttons[cat] = btn
            has_icon = False
            if icon_file:
                _it = (icon_cache or {}).get(icon_file)
                if not _it:
                    try:
                        _it = self.loader.loadTexture(Filename.fromOsSpecific(
                            os.path.join(_base_dir, icon_file)))
                    except Exception:
                        _it = None
                if _it:
                    _cm = CardMaker('sb_icon')
                    _cm.setFrame(-0.046, 0.046, -0.046, 0.046)
                    _np = btn.attachNewNode(_cm.generate())
                    _np.setTexture(_it, 1)
                    _np.setTransparency(TransparencyAttrib.MAlpha)
                    _np.setPos(0, 0, 0.040)
                    _np.setLightOff()
                    _np.setShaderOff()
                    _np.setBin('gui-popup', 5)
                    _np.setDepthWrite(False)
                    has_icon = True
            DirectLabel(
                text=label, text_fg=_TEXT_H, text_scale=0.021,
                frameColor=(0, 0, 0, 0),
                parent=btn, pos=(0, 0, -0.072 if has_icon else 0.0),
            )

    def _switch_avatar_category(self, cat):
        _SEL_COL  = (0.44, 0.32, 0.64, 1.0)
        _NORM_COL = (0.55, 0.46, 0.72, 1.0)
        for k, btn in (getattr(self, '_avatar_sidebar_buttons', None) or {}).items():
            if btn and not btn.isEmpty():
                btn['frameColor'] = _SEL_COL if k == cat else _NORM_COL
        parent = getattr(self, "_avatar_screen_parent", None)
        if cat == "colors":
            # Invalidate prebuilt rig so colors changes are reflected on return
            self._avatar_rig_prebuilt = False
            # Tear down 3D preview and items panel
            self._cleanup_avatar_items_tab()
            old_bg = getattr(self, "_avatar_items_bg", None)
            if old_bg and not old_bg.isEmpty():
                old_bg.destroy()
            self._avatar_items_bg = None
            # Destroy old colors view if any (colors→colors shouldn't happen but guard)
            old_col = getattr(self, "_avatar_colors_bg", None)
            if old_col and not old_col.isEmpty():
                old_col.destroy()
            self._avatar_colors_bg = None
            if parent and not parent.isEmpty():
                self._build_avatar_colors_content(parent)
        else:
            # Destroy colors view
            old_col = getattr(self, "_avatar_colors_bg", None)
            if old_col and not old_col.isEmpty():
                old_col.destroy()
            self._avatar_colors_bg = None
            self._avatar_btns = {}
            self._avatar_items_filter = cat
            if parent and not parent.isEmpty():
                if getattr(self, '_avatar_preview_card', None) is None:
                    # preview card destroyed (came from colors or first open), rebuild
                    self._build_avatar_items_content(parent, cat)
                else:
                    # preview card already shown, just swap the items panel
                    self._build_avatar_items_panel(parent, cat)

    def _build_avatar_colors_content(self, parent):
        # Transparent full-screen container so destroying it removes all char+palette buttons
        colors_bg = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-3, 3, -3, 3),
            parent=parent,
        )
        self._avatar_colors_bg = colors_bg
        self._avatar_btns = {}
        # Original 2D flat char + palette at original screen positions
        self._build_avatar_char(colors_bg, x_off=-0.28, z_off=-0.08)
        self._build_avatar_palette(colors_bg, left=0.16, top=0.20, sw=0.082, sh=0.078, pad=0.007)

    # ── Items tab content (3D preview + empty list) ────────────────────────

    def _ensure_avatar_preview_rig(self):
        """Build the offscreen preview rig if not already live. Safe to call multiple times."""
        if getattr(self, '_avatar_rig_prebuilt', False):
            root = getattr(self, '_avatar_preview_root', None)
            if root and not root.isEmpty():
                return
            self._avatar_rig_prebuilt = False  # stale reference, rebuild
        PMASK = BitMask32.bit(5)
        preview_root = self.render.attachNewNode("avatar_preview_root")
        preview_root.setPos(0, 2000, 0)
        self._avatar_preview_root = preview_root
        colors = getattr(self, "_avatar_colors", {}) or {}
        self._build_preview_rig(preview_root, colors, PMASK)
        alight = AmbientLight("preview_ambient")
        alight.setColor(LColor(0.22, 0.22, 0.25, 1))
        preview_root.setLight(preview_root.attachNewNode(alight))
        dlight = DirectionalLight("preview_key")
        dlight.setColor(LColor(0.50, 0.50, 0.52, 1))
        dlnp = preview_root.attachNewNode(dlight)
        dlnp.setHpr(20, 15, 0)
        preview_root.setLight(dlnp)
        fill = DirectionalLight("preview_fill")
        fill.setColor(LColor(0.16, 0.16, 0.18, 1))
        flnp = preview_root.attachNewNode(fill)
        flnp.setHpr(200, -50, 0)
        preview_root.setLight(flnp)
        pivot = preview_root.attachNewNode("avatar_preview_pivot")
        pivot.setPos(0, 0, 2)
        self._avatar_cam_pivot = pivot
        buf = self.win.makeTextureBuffer("avatar_preview", 400, 480)
        buf.setClearColor(LColor(0.78, 0.75, 0.88, 1.0))
        buf.setClearColorActive(True)
        self._avatar_buf = buf
        _camNode = Camera("avatar_preview_cam")
        _lens = PerspectiveLens()
        _lens.setFov(32, 46)
        _lens.setNearFar(0.1, 1000)
        _camNode.setLens(_lens)
        _camNode.setCameraMask(PMASK)
        cam_np = pivot.attachNewNode(_camNode)
        cam_np.setPos(0, -9.5, 0)
        cam_np.lookAt(preview_root, Point3(0, 0, 3))
        _dr = buf.makeDisplayRegion()
        _dr.setSort(10)
        _dr.setCamera(cam_np)
        self._avatar_cam_np = cam_np
        orig_mask = self.camNode.getCameraMask()
        self._avatar_saved_cam_mask = orig_mask
        self.camNode.setCameraMask(orig_mask & ~PMASK)
        self._avatar_rig_prebuilt = True

    def _avatar_start_prefetch(self):
        """Kick off background fetch (owned items + catalog) and schedule rig pre-build after login."""
        token = getattr(self, '_session_token', None)
        if not token:
            return
        import threading as _thr, auth_client as _ac
        def _fetch():
            try:
                result, _ = _ac.get_owned_items(token)
                self._avatar_items_full_cache = (result or {}).get("items", [])
            except Exception:
                pass
            try:
                result, _ = _ac.list_shop_items()
                self._shop_items_full_cache = (result or {}).get("items", [])
            except Exception:
                pass
        _thr.Thread(target=_fetch, daemon=True).start()
        self.taskMgr.doMethodLater(0.5, self._avatar_prebuild_rig_task, '_avatarPrebuildRig')

    def _avatar_prebuild_rig_task(self, task):
        try:
            if not getattr(self, '_avatar_colors', None):
                self._avatar_colors = self.load_avatar_colors()
            self._ensure_avatar_preview_rig()
        except Exception as e:
            print(f"[AVATAR_PREBUILD] {e}", flush=True)
        return task.done

    def _build_avatar_items_content(self, parent, items_filter="tshirt"):
        self._avatar_items_filter = items_filter
        self._avatar_screen_parent = parent
        CARD_W = 0.50
        CARD_H = 0.60
        CARD_X = -0.75
        CARD_Z = -0.10

        self._ensure_avatar_preview_rig()

        # ── Texture card ───────────────────────────────────────────────────
        tex = self._avatar_buf.getTexture()
        preview_card = DirectFrame(
            frameTexture=tex,
            frameColor=(1, 1, 1, 1),
            frameSize=(-CARD_W, CARD_W, -CARD_H, CARD_H),
            parent=parent, pos=(CARD_X, 0, CARD_Z),
        )
        preview_card.setTransparency(False)
        self._avatar_preview_card = preview_card

        drag_lbl = DirectLabel(
            text="Drag to rotate",
            text_fg=(0.40, 0.35, 0.55, 1), text_scale=0.022,
            frameColor=(0, 0, 0, 0),
            parent=parent,
            pos=(CARD_X, 0, CARD_Z - CARD_H - 0.038),
        )
        self._avatar_drag_lbl = drag_lbl

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

        self._build_avatar_items_panel(parent, items_filter)

    def _build_avatar_items_panel(self, parent, items_filter="tshirt"):
        # Destroy any previous items panel before rebuilding
        old_bg = getattr(self, "_avatar_items_bg", None)
        if old_bg and not old_bg.isEmpty():
            old_bg.destroy()
        self._avatar_items_bg = None

        _PANEL_BG  = (0.68, 0.65, 0.82, 1.0)
        _PANEL_DIV = (0.50, 0.40, 0.68, 1.0)
        _TEXT_H    = (0.12, 0.08, 0.28, 1.0)
        _TEXT_M    = (0.22, 0.15, 0.40, 1.0)
        _TEXT_D    = (0.32, 0.22, 0.50, 1.0)

        items_bg = DirectFrame(
            frameColor=_PANEL_BG,
            frameSize=(-0.57, 0.57, -0.82, 0.68),
            parent=parent, pos=(0.38, 0, -0.08),
        )
        self._avatar_items_loading_lbl = DirectLabel(
            text="Loading...", text_fg=_TEXT_M, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=items_bg, pos=(0, 0, 0.46),
        )
        self._avatar_items_bg = items_bg
        self._avatar_items_panel_colors = (_TEXT_H, _TEXT_M, _TEXT_D, _PANEL_BG, _PANEL_DIV)

        token = getattr(self, "_session_token", None)
        if token:
            import threading as _thr, auth_client as _ac
            equipped_tshirt_id = getattr(self, "_equipped_tshirt_id", None)
            equipped_hat_id    = getattr(self, "_equipped_hat_id",    None)
            equipped_shirt_id  = getattr(self, "_equipped_shirt_id",  None)
            equipped_pants_id  = getattr(self, "_equipped_pants_id",  None)
            cur_filter         = items_filter
            def _fetch(eid_t=equipped_tshirt_id, eid_h=equipped_hat_id,
                       eid_s=equipped_shirt_id, eid_p=equipped_pants_id, flt=cur_filter):
                import base64 as _b64
                cache = getattr(self, '_avatar_items_full_cache', None)
                if cache is not None:
                    all_owned = cache
                else:
                    result, _ = _ac.get_owned_items(token)
                    all_owned = (result or {}).get("items", [])
                    self._avatar_items_full_cache = all_owned
                if flt == "hat":
                    owned_items = [it for it in all_owned if "|HATDATA|" in (it.get("image_data") or "")]
                elif flt == "shirt":
                    owned_items = [it for it in all_owned if "|SHIRTDATA|" in (it.get("image_data") or "")]
                elif flt == "pants":
                    owned_items = [it for it in all_owned if "|PANTSDATA|" in (it.get("image_data") or "")]
                elif flt == "face":
                    owned_items = [it for it in all_owned if "|FACEDATA|" in (it.get("image_data") or "")]
                else:
                    owned_items = [it for it in all_owned
                                   if "|HATDATA|"    not in (it.get("image_data") or "")
                                   and "|SHIRTDATA|" not in (it.get("image_data") or "")
                                   and "|PANTSDATA|" not in (it.get("image_data") or "")
                                   and "|FACEDATA|"  not in (it.get("image_data") or "")]

                preview_b64 = None
                if eid_t:
                    for it in all_owned:
                        if it.get("id") == eid_t:
                            img = it.get("image_data") or ""
                            preview_b64 = img if "|HATDATA|" not in img else None
                            break
                    if not preview_b64:
                        full, _ = _ac.get_shop_item(eid_t)
                        if full:
                            img = full.get("image_data") or ""
                            preview_b64 = img if "|HATDATA|" not in img else None

                preview_hat_data = None
                if eid_h:
                    for it in all_owned:
                        if it.get("id") == eid_h:
                            img = it.get("image_data") or ""
                            if "|HATDATA|" in img:
                                try:
                                    preview_hat_data = _b64.b64decode(
                                        img.split("|HATDATA|", 1)[1]).decode()
                                except Exception:
                                    pass
                            break
                    if not preview_hat_data:
                        full, _ = _ac.get_shop_item(eid_h)
                        if full:
                            img = full.get("image_data") or ""
                            if "|HATDATA|" in img:
                                try:
                                    preview_hat_data = _b64.b64decode(
                                        img.split("|HATDATA|", 1)[1]).decode()
                                except Exception:
                                    pass

                preview_shirt_b64 = None
                if eid_s:
                    for it in all_owned:
                        if it.get("id") == eid_s and "|SHIRTDATA|" in (it.get("image_data") or ""):
                            img = it.get("image_data") or ""
                            preview_shirt_b64 = img.split("|SHIRTDATA|")[0]
                            break
                    if not preview_shirt_b64:
                        full, _ = _ac.get_shop_item(eid_s)
                        if full:
                            img = full.get("image_data") or ""
                            if "|SHIRTDATA|" in img:
                                preview_shirt_b64 = img.split("|SHIRTDATA|")[0]

                preview_pants_b64 = getattr(self, "_equipped_pants_b64", None)
                if not preview_pants_b64 and eid_p:
                    for it in all_owned:
                        if it.get("id") == eid_p and "|PANTSDATA|" in (it.get("image_data") or ""):
                            img = it.get("image_data") or ""
                            preview_pants_b64 = img.split("|PANTSDATA|")[0]
                            break
                    if not preview_pants_b64:
                        full, _ = _ac.get_shop_item(eid_p)
                        if full:
                            img = full.get("image_data") or ""
                            if "|PANTSDATA|" in img:
                                preview_pants_b64 = img.split("|PANTSDATA|")[0]

                def _populate(task, items=owned_items, b64=preview_b64, hd=preview_hat_data,
                              sb64=preview_shirt_b64, pb64=preview_pants_b64):
                    self._populate_avatar_items(items)
                    if b64:
                        self._preview_apply_tshirt(b64)
                    if hd:
                        self._preview_apply_hat(hd)
                    if sb64:
                        self._preview_apply_shirt(sb64)
                    if pb64:
                        self._preview_apply_pants(pb64)
                    return task.done
                self.taskMgr.doMethodLater(0, _populate, "_populateAvatarItems", appendTask=True)
            _thr.Thread(target=_fetch, daemon=True).start()
        else:
            lbl = getattr(self, "_avatar_items_loading_lbl", None)
            if lbl and not lbl.isEmpty():
                lbl["text"] = "Not logged in."

    def _switch_avatar_items_filter(self, new_filter):
        self._switch_avatar_category(new_filter)

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

        # Pre-render thumbnails for the first page only; other pages load lazily on navigation.
        self._avatar_all_items = items
        self._avatar_items_page = 0
        cur_filter = getattr(self, '_avatar_items_filter', 'tshirt')
        PAGE_SIZE = 6
        thumb_textures = self._make_thumb_textures(items[:PAGE_SIZE], cur_filter)
        self._avatar_thumb_textures = thumb_textures

        # Grid sub-frame (replaced on each page turn)
        self._avatar_items_grid_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-0.56, 0.56, -0.64, 0.62),
            parent=items_bg,
        )

        # Pagination: < | Page X/Y | >
        self._avatar_items_prev_btn = DirectButton(
            text="<",
            text_fg=_TEXT_H, text_scale=0.038,
            frameColor=_PANEL_DIV,
            frameSize=(-0.090, 0.090, -0.038, 0.038),
            parent=items_bg, pos=(-0.30, 0, -0.72),
            relief=1,
            command=self._avatar_items_goto_page,
            extraArgs=[-1],
        )
        self._avatar_items_page_lbl = DirectLabel(
            text="Page 1/1",
            text_fg=_TEXT_H, text_scale=0.030,
            frameColor=(0, 0, 0, 0),
            parent=items_bg, pos=(0, 0, -0.72),
        )
        self._avatar_items_next_btn = DirectButton(
            text=">",
            text_fg=_TEXT_H, text_scale=0.038,
            frameColor=_PANEL_DIV,
            frameSize=(-0.090, 0.090, -0.038, 0.038),
            parent=items_bg, pos=(0.30, 0, -0.72),
            relief=1,
            command=self._avatar_items_goto_page,
            extraArgs=[+1],
        )
        self._draw_avatar_items_page(0)

    def _draw_avatar_items_page(self, page):
        items_bg = getattr(self, '_avatar_items_bg', None)
        if not items_bg or items_bg.isEmpty():
            return
        _TEXT_H, _TEXT_M, _TEXT_D, _PANEL_BG, _PANEL_DIV = self._avatar_items_panel_colors

        all_items = getattr(self, '_avatar_all_items', [])
        thumb_textures = getattr(self, '_avatar_thumb_textures', {})
        PAGE_SIZE = 6
        max_page = max(0, (len(all_items) - 1) // PAGE_SIZE)
        page = max(0, min(page, max_page))
        self._avatar_items_page = page

        # Rebuild grid sub-frame
        gf = getattr(self, '_avatar_items_grid_frame', None)
        if gf and not gf.isEmpty():
            gf.destroy()
        grid_frame = DirectFrame(
            frameColor=(0, 0, 0, 0),
            frameSize=(-0.56, 0.56, -0.64, 0.62),
            parent=items_bg,
        )
        self._avatar_items_grid_frame = grid_frame

        cur_filter  = getattr(self, '_avatar_items_filter', 'tshirt')

        # Lazy-generate thumbnails for any items on this page that aren't cached yet
        page_items = all_items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        missing = [it for it in page_items if it.get("id") not in thumb_textures]
        if missing:
            new_tex = self._make_thumb_textures(missing, cur_filter)
            thumb_textures.update(new_tex)
            self._avatar_thumb_textures = thumb_textures

        if cur_filter == "hat":
            equipped_id = getattr(self, "_equipped_hat_id", None)
        elif cur_filter == "shirt":
            equipped_id = getattr(self, "_equipped_shirt_id", None)
        elif cur_filter == "pants":
            equipped_id = getattr(self, "_equipped_pants_id", None)
        elif cur_filter == "face":
            equipped_id = getattr(self, "_equipped_face_id", None)
        else:
            equipped_id = getattr(self, "_equipped_tshirt_id", None)
        COLS = 3; CARD_W = 0.335; CARD_H = 0.335; NAME_H = 0.115
        GAP_X = 0.022; GAP_Y = 0.028; TOTAL_H = CARD_H + NAME_H
        start_x = -(COLS * CARD_W + (COLS - 1) * GAP_X) / 2 + CARD_W / 2
        start_z = 0.40
        _EQ_COL   = (0.38, 0.26, 0.58, 1.0)
        _NORM_COL = (0.52, 0.44, 0.70, 1.0)
        self._avatar_item_btns = {}

        for i, item in enumerate(all_items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]):
            col = i % COLS
            row = i // COLS
            cx  = start_x + col * (CARD_W + GAP_X)
            cz  = start_z - row * (TOTAL_H + GAP_Y)
            item_id = item.get("id")
            name    = item.get("name", "")
            creator = item.get("username", "")
            is_eq   = (item_id == equipped_id)
            card = DirectButton(
                frameColor=_EQ_COL if is_eq else _NORM_COL,
                frameSize=(-CARD_W / 2, CARD_W / 2, -TOTAL_H / 2, TOTAL_H / 2),
                parent=grid_frame, pos=(cx, 0, cz),
                relief=1,
                command=self._on_avatar_item_equip,
                extraArgs=[item],
            )
            thumb = DirectFrame(
                frameColor=(0.48, 0.38, 0.66, 1.0),
                frameSize=(-CARD_W / 2, CARD_W / 2, -CARD_H / 2, CARD_H / 2),
                parent=card, pos=(0, 0, NAME_H / 2),
            )
            rtt = thumb_textures.get(item_id)
            if rtt:
                thumb["frameTexture"] = rtt
                thumb["frameColor"]   = (1, 1, 1, 1)
            short = (name[:13] + "…") if len(name) > 14 else name
            DirectLabel(
                text=short, text_fg=_TEXT_H, text_scale=0.026,
                frameColor=(0, 0, 0, 0),
                parent=card, pos=(0, 0, -TOTAL_H / 2 + NAME_H * 0.72),
            )
            if creator:
                short_c = (creator[:13] + "…") if len(creator) > 14 else creator
                DirectLabel(
                    text=f"by {short_c}", text_fg=_TEXT_D, text_scale=0.020,
                    frameColor=(0, 0, 0, 0),
                    parent=card, pos=(0, 0, -TOTAL_H / 2 + NAME_H * 0.22),
                )
            self._avatar_item_btns[item_id] = card

        # Bob-only: "Upload Face" button visible when on the Face tab
        if cur_filter == "face" and getattr(self, '_session_username', None) == "bob":
            DirectButton(
                text="+ Upload Face",
                text_fg=_TEXT_H, text_scale=0.022,
                frameColor=(0.38, 0.26, 0.56, 1.0),
                frameSize=(-0.14, 0.14, -0.024, 0.024),
                parent=items_bg, pos=(0, 0, -0.44),
                relief=1,
                command=self._show_upload_face_dialog,
            )

        # Update page label and dim unavailable pagination buttons
        page_lbl = getattr(self, '_avatar_items_page_lbl', None)
        if page_lbl and not page_lbl.isEmpty():
            page_lbl['text'] = f"Page {page + 1}/{max_page + 1}"
        prev_btn = getattr(self, '_avatar_items_prev_btn', None)
        next_btn = getattr(self, '_avatar_items_next_btn', None)
        _DIM = (0.40, 0.35, 0.52, 1.0)
        if prev_btn and not prev_btn.isEmpty():
            prev_btn['frameColor'] = _PANEL_DIV if page > 0 else _DIM
        if next_btn and not next_btn.isEmpty():
            next_btn['frameColor'] = _PANEL_DIV if page < max_page else _DIM

    def _make_thumb_textures(self, items, cur_filter):
        """Generate Texture objects for a list of items based on current filter."""
        import base64 as _b64
        from panda3d.core import PNMImage, StringStream, Texture
        result = {}
        if cur_filter in ("tshirt", "shirt", "pants"):
            filtered = [it for it in items if it.get("image_data")]
            try:
                result = self._render_shop_thumbnails(filtered, buf_w=256, buf_h=256)
            except Exception:
                pass
        elif cur_filter == "face":
            for it in items:
                iid  = it.get("id")
                idat = it.get("image_data") or ""
                if "|FACEDATA|" in idat:
                    idat = idat.split("|FACEDATA|")[0]
                if iid and idat:
                    try:
                        raw  = _b64.b64decode(idat)
                        face = PNMImage()
                        if face.read(StringStream(raw), "face.png"):
                            w, h = face.getXSize(), face.getYSize()
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
                    except Exception:
                        pass
        else:  # hat
            for it in items:
                iid  = it.get("id")
                idat = it.get("image_data") or ""
                if "|HATDATA|" in idat:
                    idat = idat.split("|HATDATA|")[0]
                if iid and idat:
                    try:
                        raw = _b64.b64decode(idat)
                        ss  = StringStream(raw)
                        pnm = PNMImage()
                        if pnm.read(ss):
                            tex = Texture()
                            tex.load(pnm)
                            tex.setMagfilter(Texture.FTLinear)
                            tex.setMinfilter(Texture.FTLinear)
                            result[iid] = tex
                    except Exception:
                        pass
        return result

    def _avatar_items_goto_page(self, delta):
        page = getattr(self, '_avatar_items_page', 0) + delta
        self._draw_avatar_items_page(page)

    def _on_avatar_item_equip(self, item):
        import threading as _thr, auth_client as _ac
        idat     = item.get("image_data") or ""
        is_hat   = "|HATDATA|"   in idat
        is_shirt = "|SHIRTDATA|" in idat
        is_pants = "|PANTSDATA|" in idat
        is_face  = "|FACEDATA|"  in idat
        print(f"[EQUIP] item={item.get('id')} is_hat={is_hat} is_shirt={is_shirt} is_pants={is_pants} is_face={is_face} idat_len={len(idat)}", flush=True)

        if is_hat:
            self._on_avatar_hat_equip(item, _ac, _thr)
        elif is_shirt:
            self._on_avatar_shirt_equip(item, _ac, _thr)
        elif is_pants:
            self._on_avatar_pants_equip(item, _ac, _thr)
        elif is_face:
            self._on_avatar_face_equip(item, _ac, _thr)
        else:
            self._on_avatar_tshirt_equip(item, _ac, _thr)

    def _on_avatar_face_equip(self, item, _ac, _thr):
        import base64 as _b64
        item_id     = item.get("id")
        idat        = item.get("image_data") or ""
        equipped_id = getattr(self, "_equipped_face_id", None)
        token       = getattr(self, "_session_token", None)

        if item_id == equipped_id:
            # Un-equip: restore default face
            self._equipped_face_id = None
            if hasattr(self, "remove_face"):
                self.remove_face()
            if token:
                _thr.Thread(
                    target=lambda: _ac.equip_face(token, None), daemon=True).start()
            self._broadcast_face_equip(None)
        else:
            # Equip: decode the 3 frames from |FACEDATA| payload
            self._equipped_face_id = item_id
            if "|FACEDATA|" in idat:
                frames_part = idat.split("|FACEDATA|", 1)[1]
                frames_b64  = [f for f in frames_part.split(",") if f]
                if hasattr(self, "apply_face"):
                    self.apply_face(frames_b64)
                self._broadcast_face_equip(item_id, frames_b64)
            if token:
                _thr.Thread(
                    target=lambda: _ac.equip_face(token, item_id), daemon=True).start()

        # Refresh grid to show new equipped state
        page = getattr(self, '_avatar_items_page', 0)
        self._draw_avatar_items_page(page)

    def _broadcast_face_equip(self, item_id, frames_b64=None):
        ws   = getattr(self, "_ws", None)
        loop = getattr(self, "_mp_loop", None)
        if not ws or not loop or loop.is_closed():
            return
        import asyncio, json
        payload = {"type": "equip_face", "item_id": item_id,
                   "frames": frames_b64 or []}
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(payload)), loop)
        except Exception as e:
            print(f"[MP] face broadcast error: {e}")

    def _on_avatar_tshirt_equip(self, item, _ac, _thr):
        item_id    = item.get("id")
        image_b64  = item.get("image_data", "")
        equipped_id = getattr(self, "_equipped_tshirt_id", None)
        token       = getattr(self, "_session_token", None)

        if item_id == equipped_id:
            self._equipped_tshirt_id = None
            if hasattr(self, "remove_tshirt"):
                self.remove_tshirt()
            self._preview_apply_tshirt(None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_tshirt(token, None), daemon=True).start()
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
            self._equipped_tshirt_id = item_id
            if image_b64:
                if hasattr(self, "apply_tshirt"):
                    self.apply_tshirt(image_b64)
                self._preview_apply_tshirt(image_b64)
            else:
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
            if token:
                _thr.Thread(target=lambda: _ac.equip_tshirt(token, item_id), daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_tshirt", "item_id": item_id})), loop)
                except Exception:
                    pass

        self._refresh_avatar_item_highlights()

    def _on_avatar_shirt_equip(self, item, _ac, _thr):
        item_id    = item.get("id")
        raw_img    = item.get("image_data") or ""
        image_b64  = raw_img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in raw_img else raw_img
        equipped_id = getattr(self, "_equipped_shirt_id", None)
        token       = getattr(self, "_session_token", None)

        if item_id == equipped_id:
            self._equipped_shirt_id = None
            if hasattr(self, "remove_shirt"): self.remove_shirt()
            self._preview_apply_shirt(None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_shirt(token, None), daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_shirt", "item_id": None})), loop)
                except Exception:
                    pass
        else:
            self._equipped_shirt_id = item_id
            if image_b64:
                if hasattr(self, "apply_shirt"): self.apply_shirt(image_b64)
                self._preview_apply_shirt(image_b64)
            else:
                def _fetch_shirt(iid=item_id):
                    full, _ = _ac.get_shop_item(iid)
                    if full and full.get("image_data"):
                        img = full["image_data"]
                        b64 = img.split("|SHIRTDATA|")[0] if "|SHIRTDATA|" in img else img
                        def _apply(task, _b=b64):
                            if hasattr(self, "apply_shirt"): self.apply_shirt(_b)
                            self._preview_apply_shirt(_b)
                            return task.done
                        self.taskMgr.doMethodLater(0, _apply, "_applyShirtLocal", appendTask=True)
                _thr.Thread(target=_fetch_shirt, daemon=True).start()
            if token:
                def _do_equip_shirt(t=token, iid=item_id):
                    result, err = _ac.equip_shirt(t, iid)
                    print(f"[SHIRT_DBG] equip_shirt PUT result={result} err={err}", flush=True)
                _thr.Thread(target=_do_equip_shirt, daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_shirt", "item_id": item_id})), loop)
                except Exception:
                    pass

        self._refresh_avatar_item_highlights()

    def _on_avatar_pants_equip(self, item, _ac, _thr):
        item_id    = item.get("id")
        raw_img    = item.get("image_data") or ""
        image_b64  = raw_img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in raw_img else raw_img
        equipped_id = getattr(self, "_equipped_pants_id", None)
        token       = getattr(self, "_session_token", None)

        if item_id == equipped_id:
            self._equipped_pants_id  = None
            self._equipped_pants_b64 = None
            if hasattr(self, "remove_pants"): self.remove_pants()
            self._preview_apply_pants(None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_pants(token, None), daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_pants", "item_id": None})), loop)
                except Exception:
                    pass
        else:
            self._equipped_pants_id = item_id
            if image_b64:
                self._equipped_pants_b64 = image_b64
                if hasattr(self, "apply_pants"): self.apply_pants(image_b64)
                self._preview_apply_pants(image_b64)
            else:
                def _fetch_pants(iid=item_id):
                    full, _ = _ac.get_shop_item(iid)
                    if full and full.get("image_data"):
                        img = full["image_data"]
                        b64 = img.split("|PANTSDATA|")[0] if "|PANTSDATA|" in img else img
                        def _apply(task, _b=b64):
                            self._equipped_pants_b64 = _b
                            if hasattr(self, "apply_pants"): self.apply_pants(_b)
                            self._preview_apply_pants(_b)
                            return task.done
                        self.taskMgr.doMethodLater(0, _apply, "_applyPantsLocal", appendTask=True)
                _thr.Thread(target=_fetch_pants, daemon=True).start()
            if token:
                def _do_equip_pants(t=token, iid=item_id):
                    result, err = _ac.equip_pants(t, iid)
                    print(f"[PANTS_DBG] equip_pants PUT result={result} err={err}", flush=True)
                _thr.Thread(target=_do_equip_pants, daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_pants", "item_id": item_id})), loop)
                except Exception:
                    pass

        self._refresh_avatar_item_highlights()

    def _preview_apply_pants(self, image_b64):
        """Apply pants to the avatar preview rig."""
        for n in getattr(self, '_avatar_preview_pants_nodes', []):
            if n and not n.isEmpty(): n.removeNode()
        self._avatar_preview_pants_nodes = []
        if not image_b64:
            return
        root   = getattr(self, '_avatar_preview_rig_root', None)
        pmask  = getattr(self, '_avatar_preview_rig_pmask', None)
        ll_piv = getattr(self, '_avatar_preview_ll_piv', None)
        rl_piv = getattr(self, '_avatar_preview_rl_piv', None)
        if not root or root.isEmpty():
            return
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib
            from character import CharacterMixin

            raw = base64.b64decode(image_b64)
            ss  = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss): return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)

            R = CharacterMixin._PANTS_REGIONS

            def attach(parent, reg_map, w, d, h, pos):
                if parent is None or parent.isEmpty(): return None
                node = CharacterMixin._make_shirt_box_geom(w, d, h, reg_map,
                    template_w=CharacterMixin._PANTS_TEMPLATE_W,
                    template_h=CharacterMixin._PANTS_TEMPLATE_H)
                np = parent.attachNewNode(node)
                np.setPos(*pos); np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setDepthOffset(1); np.setTransparency(TransparencyAttrib.MAlpha)
                if pmask: np.show(pmask)
                return np

            # Preview camera at -Y: swap front/back and left/right
            nodes = [n for n in [
                attach(root, {
                    'front': R['torso_back'],  'back':  R['torso_front'],
                    'left':  R['torso_right'], 'right': R['torso_left'],
                    'top':   R['torso_up'],    'bottom':R['torso_down'],
                }, 2, 1, 2, (-1, -0.5, 2)),
                attach(rl_piv, {
                    'front': R['rleg_back'],  'back':  R['rleg_front'],
                    'left':  R['rleg_right'], 'right': R['rleg_left'],
                    'top':   R['rleg_up'],    'bottom':R['rleg_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
                attach(ll_piv, {
                    'front': R['lleg_back'],  'back':  R['lleg_front'],
                    'left':  R['lleg_right'], 'right': R['lleg_left'],
                    'top':   R['lleg_up'],    'bottom':R['lleg_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
            ] if n is not None]
            self._avatar_preview_pants_nodes = nodes
        except Exception as e:
            print(f"[PREVIEW_PANTS] {e}", flush=True)

    def _on_avatar_hat_equip(self, item, _ac, _thr):
        item_id     = item.get("id")
        equipped_id = getattr(self, "_equipped_hat_id", None)
        token       = getattr(self, "_session_token", None)
        print(f"[HAT_EQUIP] called: item_id={item_id} equipped_id={equipped_id}", flush=True)

        if item_id == equipped_id:
            self._equipped_hat_id = None
            if hasattr(self, "remove_hat"):
                self.remove_hat()
            self._preview_apply_hat(None)
            if token:
                _thr.Thread(target=lambda: _ac.equip_hat(token, None), daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_hat", "item_id": None})), loop)
                except Exception:
                    pass
        else:
            self._equipped_hat_id = item_id
            if token:
                _thr.Thread(target=lambda: _ac.equip_hat(token, item_id), daemon=True).start()
            ws   = getattr(self, "_ws", None)
            loop = getattr(self, "_mp_loop", None)
            if ws and loop and not loop.is_closed():
                import asyncio, json
                try:
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "equip_hat", "item_id": item_id})), loop)
                except Exception:
                    pass

            # Extract hat_data from image_data — embedded at upload time, no extra fetch needed
            import base64 as _b64, json as _json
            img = item.get("image_data") or ""
            hat_data_json = None
            if "|HATDATA|" in img:
                try:
                    hat_data_json = _b64.b64decode(img.split("|HATDATA|", 1)[1]).decode()
                    print(f"[HAT_EQUIP] hat_data_json extracted, length={len(hat_data_json)}", flush=True)
                except Exception as e:
                    print(f"[HAT_EQUIP] decode error: {e}", flush=True)
            else:
                print(f"[HAT_EQUIP] no |HATDATA| in image_data (len={len(img)})", flush=True)

            if hat_data_json:
                def _apply_now(task, _hd=hat_data_json):
                    print(f"[HAT_EQUIP] _apply_now task running", flush=True)
                    if hasattr(self, "apply_hat"):
                        self.apply_hat(_hd)
                    self._preview_apply_hat(_hd)
                    return task.done
                self.taskMgr.doMethodLater(0, _apply_now, "_applyHatLocal", appendTask=True)
            else:
                # Fallback: fetch full item in case hat_data wasn't in the list response
                def _fetch_and_apply(iid=item_id):
                    full, _ = _ac.get_shop_item(iid)
                    if not full:
                        return
                    fi = full.get("image_data") or ""
                    if "|HATDATA|" in fi:
                        try:
                            hd = _b64.b64decode(fi.split("|HATDATA|", 1)[1]).decode()
                            def _apply(task, _hd=hd):
                                if hasattr(self, "apply_hat"): self.apply_hat(_hd)
                                self._preview_apply_hat(_hd)
                                return task.done
                            self.taskMgr.doMethodLater(0, _apply, "_applyHatFetch", appendTask=True)
                        except Exception as e:
                            print(f"[HAT_EQUIP] fetch decode: {e}", flush=True)
                _thr.Thread(target=_fetch_and_apply, daemon=True).start()

        self._refresh_avatar_item_highlights()

    def _refresh_avatar_item_highlights(self):
        cur_filter  = getattr(self, '_avatar_items_filter', 'tshirt')
        if cur_filter == "hat":
            new_equipped = getattr(self, "_equipped_hat_id", None)
        elif cur_filter == "shirt":
            new_equipped = getattr(self, "_equipped_shirt_id", None)
        elif cur_filter == "pants":
            new_equipped = getattr(self, "_equipped_pants_id", None)
        else:
            new_equipped = getattr(self, "_equipped_tshirt_id", None)
        btns = getattr(self, "_avatar_item_btns", {})
        for bid, card in btns.items():
            if card and not card.isEmpty():
                is_eq = (bid == new_equipped)
                card["frameColor"] = (0.38, 0.26, 0.58, 1.0) if is_eq else (0.52, 0.44, 0.70, 1.0)

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
            np.setDepthOffset(3)  # tshirt on top
            np.show(pmask)
            self._avatar_preview_tshirt_anchor = anchor
            self._avatar_preview_tshirt_np     = np
        except Exception as e:
            print(f"[PREVIEW_TSHIRT] {e}", flush=True)

    def _preview_apply_hat(self, hat_data_json):
        """Add or replace the hat model on the avatar preview rig."""
        print(f"[PREVIEW_HAT] called, has_data={bool(hat_data_json)}", flush=True)
        n = getattr(self, '_avatar_preview_hat_model', None)
        if n and not n.isEmpty():
            n.removeNode()
        self._avatar_preview_hat_model = None
        if not hat_data_json:
            return
        root  = getattr(self, '_avatar_preview_rig_root', None)
        pmask = getattr(self, '_avatar_preview_rig_pmask', BitMask32.allOn())
        print(f"[PREVIEW_HAT] root={root}, root_empty={root.isEmpty() if root else 'N/A'}, pmask={pmask}", flush=True)
        if not root or root.isEmpty():
            return
        import json as _json, base64, tempfile, os as _os2, shutil
        from panda3d.core import Filename
        tmp_dir = None
        try:
            data = _json.loads(hat_data_json)
            tmp_dir = tempfile.mkdtemp(prefix="phx_prevhat_")
            obj_tmp = _os2.path.join(tmp_dir, "hat.obj")
            with open(obj_tmp, 'wb') as f:
                f.write(base64.b64decode(data["obj_b64"]))
            mtl_b64  = data.get("mtl_b64")
            mtl_name = data.get("mtl_name") or "hat.mtl"
            if mtl_b64:
                with open(_os2.path.join(tmp_dir, mtl_name), 'wb') as f:
                    f.write(base64.b64decode(mtl_b64))
            hat_model = self.loader.loadModel(Filename.fromOsSpecific(obj_tmp))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir = None
            if not hat_model:
                print("[PREVIEW_HAT] loadModel returned None", flush=True)
                return
            tex_b64 = data.get("texture_b64")
            if tex_b64:
                from panda3d.core import PNMImage, StringStream, Texture
                raw = base64.b64decode(tex_b64)
                ss  = StringStream(raw)
                pnm = PNMImage()
                if pnm.read(ss):
                    tex = Texture()
                    tex.load(pnm)
                    hat_model.setTexture(tex, 1)
            bs = data.get("brick_scale", [2, 2, 2])
            ms = data.get("model_scale", [1, 1, 1])
            world_scale = [bs[i] * ms[i] for i in range(3)]
            hat_model.reparentTo(root)
            hat_model.setScale(*world_scale)
            h0, p0, r0 = data.get("model_hpr", [0, 0, -90])
            # Preview character's front faces -Y (H=180°), same as in-game.
            # Add 180° to match the heading offset the follow task applies.
            hat_model.setHpr(h0 + 180, p0, r0)
            z_off = float(data.get("z_offset", 0.0))
            x_off = float(data.get("x_offset", 0.0))
            y_off = float(data.get("y_offset", 0.0))
            hat_model.setPos(x_off, y_off, 4.55 + 0.55 + z_off)
            hat_model.setShaderOff()
            hat_model.setTwoSided(True)
            # Force hat and all its child geometry nodes visible to the preview camera
            hat_model.showThrough(pmask)
            for _child in hat_model.findAllMatches("**"):
                _child.showThrough(pmask)
            self._avatar_preview_hat_model = hat_model
            print(f"[PREVIEW_HAT] placed z={hat_model.getPos().z:.2f} scale={hat_model.getScale()}", flush=True)
        except Exception as e:
            import traceback
            print(f"[PREVIEW_HAT] {e}", flush=True)
            traceback.print_exc()
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _preview_apply_shirt(self, image_b64):
        """Crop a shirt template and apply face cards to the avatar preview rig."""
        for n in getattr(self, '_avatar_preview_shirt_nodes', []):
            if n and not n.isEmpty(): n.removeNode()
        self._avatar_preview_shirt_nodes = []
        if not image_b64:
            return
        root   = getattr(self, '_avatar_preview_rig_root', None)
        pmask  = getattr(self, '_avatar_preview_rig_pmask', None)
        la_piv = getattr(self, '_avatar_preview_la_piv', None)
        ra_piv = getattr(self, '_avatar_preview_ra_piv', None)
        if not root or root.isEmpty():
            return
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib
            from character import CharacterMixin

            raw = base64.b64decode(image_b64)
            ss  = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)

            R = CharacterMixin._SHIRT_REGIONS
            nodes = []

            def attach(parent, reg_map, w, d, h, pos):
                if parent is None or parent.isEmpty():
                    return None
                node = CharacterMixin._make_shirt_box_geom(w, d, h, reg_map)
                np = parent.attachNewNode(node)
                np.setPos(*pos)
                np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setDepthOffset(2)  # shirt above pants (pants=1, shirt=2, tshirt=3)
                np.setTransparency(TransparencyAttrib.MAlpha)
                if pmask: np.show(pmask)
                return np

            # Preview camera is at Y=-8, so -Y face is toward camera.
            # Swap front↔back and left↔right so the shirt shows correctly.
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
            self._avatar_preview_shirt_nodes = nodes
        except Exception as e:
            print(f"[PREVIEW_SHIRT] {e}", flush=True)

    def _build_preview_rig(self, root, colors, pmask):
        """Build a completely fresh avatar rig under root — no copyTo, no inherited state."""
        self._avatar_preview_rig_root  = root
        self._avatar_preview_rig_pmask = pmask
        self._avatar_preview_tshirt_anchor = None
        self._avatar_preview_tshirt_np     = None
        self._avatar_preview_hat_model     = None

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
        self._avatar_preview_la_piv = la_piv

        ra_piv = root.attachNewNode("ra_piv")
        ra_piv.setPos(cx + 1.5, cy, top_z)
        box(ra_piv, (1, 1, 2), (-0.5, -0.5, -2), "right_arm")
        self._avatar_preview_ra_piv = ra_piv

        ll_piv = root.attachNewNode("ll_piv")
        ll_piv.setPos(cx - 0.5, cy, bot_z)
        box(ll_piv, (1, 1, 2), (-0.5, -0.5, -2), "left_leg")
        self._avatar_preview_ll_piv = ll_piv

        rl_piv = root.attachNewNode("rl_piv")
        rl_piv.setPos(cx + 0.5, cy, bot_z)
        box(rl_piv, (1, 1, 2), (-0.5, -0.5, -2), "right_leg")
        self._avatar_preview_rl_piv = rl_piv

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
        prebuilt = getattr(self, '_avatar_rig_prebuilt', False)
        # Destroy the 2D GUI cards that display the 3D preview (always)
        for attr in ('_avatar_preview_card', '_avatar_drag_lbl'):
            node = getattr(self, attr, None)
            if node and not node.isEmpty():
                node.destroy()
            setattr(self, attr, None)
        if prebuilt:
            # Rig persists across tab opens — only UI cards were destroyed above
            return
        # Full teardown when rig is not prebuilt (e.g. coming from colors)
        saved = getattr(self, '_avatar_saved_cam_mask', None)
        if saved is not None:
            self.camNode.setCameraMask(saved)
        self._avatar_saved_cam_mask = None
        buf = getattr(self, '_avatar_buf', None)
        if buf:
            self.graphicsEngine.removeWindow(buf)
        self._avatar_buf = None
        for n in getattr(self, '_avatar_preview_shirt_nodes', []):
            if n and not n.isEmpty(): n.removeNode()
        self._avatar_preview_shirt_nodes = []
        for attr in ('_avatar_cam_np', '_avatar_cam_pivot',
                     '_avatar_char_copy', '_avatar_preview_root',
                     '_avatar_preview_tshirt_anchor', '_avatar_preview_tshirt_np',
                     '_avatar_preview_hat_model', '_avatar_preview_rig_root',
                     '_avatar_preview_la_piv', '_avatar_preview_ra_piv'):
            node = getattr(self, attr, None)
            if node and not node.isEmpty():
                node.removeNode()
            setattr(self, attr, None)
