from direct.gui.DirectGui import (
    DirectButton, DirectFrame, DirectLabel,
)
from panda3d.core import WindowProperties, TextNode, Point3
from direct.task import Task
from avatar import _PALETTE as _AV_PALETTE

# ── Theme ──────────────────────────────────────────────────────────────────
DARK    = (0.11, 0.12, 0.17, 0.97)
DARKER  = (0.07, 0.08, 0.11, 1.0)
ITEM_BG = (0.16, 0.17, 0.23, 1.0)   # slightly lighter than DARK — makes rows visible
MED     = (0.17, 0.19, 0.26, 1.0)
BTN     = (0.19, 0.21, 0.29, 1.0)
SEL     = (0.18, 0.38, 0.72, 1.0)
TEXT    = (0.88, 0.90, 0.95, 1.0)
TEXT_D  = (0.54, 0.57, 0.65, 1.0)

# ── Layout ─────────────────────────────────────────────────────────────────
PW       = 0.50     # right-panel width (a2dTopRight-relative units)
TH       = 0.09     # top-bar height
IH       = 0.066    # hierarchy row height
MAX_VIS  = 11       # visible hierarchy rows
LIST_TOP = -0.075
LIST_BOT = LIST_TOP - MAX_VIS * IH   # -0.801
DIV_Z    = LIST_BOT - 0.018          # -0.819
INS_Z    = DIV_Z    - 0.075          # -0.894


class UIMixin:

    # ── Entry points called from game.py ───────────────────────────────────

    def setup_scale_controls(self):
        pass

    def setup_color_controls(self):
        pass

    def setup_ui(self):
        self._brick_counter = 0
        self._h_bricks      = []
        self._h_btns        = {}
        self._brick_names   = {}
        self._scroll_off    = 0
        self.ui_elements    = []   # manually tracked for UIDebugMixin

        self._build_top_bar()
        self._build_panel()
        self._build_inspector()
        self.taskMgr.add(self._status_task, "uiStatusTask")
        self.accept("arrow_left",  self._hat_flip, ["left"])
        self.accept("arrow_right", self._hat_flip, ["right"])
        self.accept("arrow_up",    self._hat_flip, ["up"])
        self.accept("arrow_down",  self._hat_flip, ["down"])
        self._hat_adj_held = set()
        for _k in ("k", "l", "p", "o", "y", "u"):
            self.accept(_k,        self._hat_adj_held.add,     [_k])
            self.accept(_k+"-up",  self._hat_adj_held.discard, [_k])
        self.accept("r", self._hat_rotate_backwards)

    # ── Top bar ────────────────────────────────────────────────────────────

    def _build_top_bar(self):
        # Anchored to the top-left corner so buttons never shift when the
        # window is resized or the aspect ratio changes.
        ar = base.getAspectRatio()
        self._top_bg = DirectFrame(
            frameSize=(0, 2 * ar, -TH, 0),
            frameColor=DARKER,
            parent=base.a2dTopLeft,
            pos=(0, 0, 0),
        )
        kw = dict(parent=self._top_bg, text_fg=TEXT, text_scale=0.040,
                  frameColor=BTN, relief=1)

        BZ = -TH / 2   # vertical center of the bar in top-bar local space
        # Positions with 0.015 gap between neighbours.
        # Menu(0.110w) | [Chat added by multiplayer at 0.195] | Edit(0.150w) |
        # +Brick(0.150w) | Move(0.120w) | Scale(0.120w) | Export(0.130w) |
        # Import(0.130w) | Save(0.110w)
        self.menu_button = DirectButton(
            text="Menu",
            frameSize=(-0.055, 0.055, -0.032, 0.032),
            pos=(0.070, 0, BZ),
            command=self._return_to_menu,
            **kw,
        )
        self.exit_button = DirectButton(
            text="Edit",
            frameSize=(-0.075, 0.075, -0.032, 0.032),
            pos=(0.340, 0, BZ),
            command=self.toggle_mode,
            **kw,
        )
        self.insert_brick_button = DirectButton(
            text="+ Brick",
            frameSize=(-0.075, 0.075, -0.032, 0.032),
            pos=(0.505, 0, BZ),
            command=self.insert_brick,
            **kw,
        )
        self.move_button = DirectButton(
            text="Move",
            frameSize=(-0.060, 0.060, -0.032, 0.032),
            pos=(0.655, 0, BZ),
            command=self.toggle_move_mode,
            **kw,
        )
        self.scale_button = DirectButton(
            text="Scale",
            frameSize=(-0.060, 0.060, -0.032, 0.032),
            pos=(0.790, 0, BZ),
            command=self.toggle_scale_mode,
            **kw,
        )
        self.rotate_button = DirectButton(
            text="Rotate",
            frameSize=(-0.066, 0.066, -0.032, 0.032),
            pos=(0.930, 0, BZ),
            command=self.toggle_rotate_mode,
            **kw,
        )
        self.export_button = DirectButton(
            text="Export",
            frameSize=(-0.065, 0.065, -0.032, 0.032),
            pos=(1.075, 0, BZ),
            command=self.export_build,
            **kw,
        )
        self.import_button = DirectButton(
            text="Import",
            frameSize=(-0.065, 0.065, -0.032, 0.032),
            pos=(1.220, 0, BZ),
            command=self.import_build,
            **kw,
        )
        self.cloud_save_button = DirectButton(
            text="Save",
            frameSize=(-0.055, 0.055, -0.032, 0.032),
            pos=(1.355, 0, BZ),
            command=self.cloud_save_build,
            **kw,
        )
        self.hat_config_button = DirectButton(
            text="Hat Config",
            frameSize=(-0.085, 0.085, -0.032, 0.032),
            pos=(1.530, 0, BZ),
            command=self._open_hat_obj,
            **kw,
        )
        # Status label anchored to the top-right corner, always just left of
        # the panel regardless of window width.
        self._status_lbl = DirectLabel(
            text="",
            text_fg=TEXT_D, text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            parent=base.a2dTopRight,
            pos=(-PW - 0.05, 0, -TH / 2 + 0.01),
            text_align=TextNode.ARight,
        )
        self.accept("window-event", self._on_window_event)

        # Editor-only buttons hidden at start (play mode is default)
        for w in (self.insert_brick_button, self.move_button,
                  self.scale_button, self.rotate_button, self.export_button,
                  self.import_button, self.cloud_save_button, self.hat_config_button):
            w.hide()

        self.ui_elements += [
            self._top_bg, self.menu_button, self.exit_button,
            self.insert_brick_button, self.move_button, self.scale_button,
            self.export_button, self.import_button, self._status_lbl,
        ]

    # ── Right panel shell ──────────────────────────────────────────────────

    def _build_panel(self):
        self._panel = DirectFrame(
            frameSize=(-PW, 0, -2.0, 0),
            frameColor=DARK,
            parent=base.a2dTopRight,
            pos=(0, 0, 0),
        )
        _hier_lbl = DirectLabel(
            text="Hierarchy",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=DARKER,
            frameSize=(-PW / 2, PW / 2, -0.028, 0.028),
            parent=self._panel,
            pos=(-PW / 2, 0, -0.032),
        )
        self._list_root = DirectFrame(
            frameSize=(-PW, 0, -MAX_VIS * IH, 0),
            frameColor=(0, 0, 0, 0),
            parent=self._panel,
            pos=(0, 0, LIST_TOP),
        )

        _divider = DirectFrame(
            frameSize=(-PW, 0, -0.002, 0.002),
            frameColor=MED,
            parent=self._panel,
            pos=(0, 0, DIV_Z),
        )
        _ins_lbl = DirectLabel(
            text="Inspector",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=DARKER,
            frameSize=(-PW / 2, PW / 2, -0.028, 0.028),
            parent=self._panel,
            pos=(-PW / 2, 0, INS_Z - 0.028),
        )
        # Panel hidden during play mode (default start state)
        self._panel.hide()

        self.ui_elements += [
            self._panel, _hier_lbl, self._list_root,
            _divider, _ins_lbl,
        ]

    # ── Inspector content ──────────────────────────────────────────────────

    def _build_inspector(self):
        self._ins = DirectFrame(
            frameSize=(-PW, 0, -0.80, 0),
            frameColor=(0, 0, 0, 0),
            parent=self._panel,
            pos=(0, 0, INS_Z - 0.072),
        )
        self._ins_none = DirectLabel(
            text="No brick selected",
            text_fg=TEXT_D, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW / 2, 0, -0.065),
        )
        self.selected_brick_label = DirectLabel(
            text="",
            text_fg=TEXT_D, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW / 2, 0, -0.042),
        )

        # Color section
        _color_lbl = DirectLabel(
            text="Color",
            text_fg=TEXT_D, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW + 0.05, 0, -0.072),
        )
        palette = _AV_PALETTE
        cols = 8
        cw, gap = 0.052, 0.005
        sx, sz  = -PW + 0.04, -0.100
        _palette_btns = []
        for i, col in enumerate(palette):
            r, c = divmod(i, cols)
            _pbtn = DirectButton(
                frameColor=col,
                frameSize=(-cw / 2, cw / 2, -cw / 2, cw / 2),
                pos=(sx + c * (cw + gap), 0, sz - r * (cw + gap)),
                parent=self._ins,
                command=self.apply_color_to_selected_brick,
                extraArgs=[col],
                relief=1,
            )
            _palette_btns.append(_pbtn)
        num_rows = (len(palette) + cols - 1) // cols

        # Texture section
        z_tex = sz - (num_rows - 1) * (cw + gap) - 0.056
        _texture_lbl = DirectLabel(
            text="Texture",
            text_fg=TEXT_D, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW + 0.05, 0, z_tex),
        )
        z_tex_btns = z_tex - 0.042
        _plastic_btn = DirectButton(
            text="Plastic", text_fg=TEXT, text_scale=0.020,
            frameColor=MED,
            frameSize=(-0.055, 0.055, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 - 0.165, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['plastic'],
        )
        _grass_btn = DirectButton(
            text="Grass", text_fg=TEXT, text_scale=0.020,
            frameColor=MED,
            frameSize=(-0.055, 0.055, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 - 0.055, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['grass'],
        )
        _wood_btn = DirectButton(
            text="Wood", text_fg=TEXT, text_scale=0.020,
            frameColor=MED,
            frameSize=(-0.055, 0.055, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 + 0.055, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['wood'],
        )
        _stone_btn = DirectButton(
            text="Stone", text_fg=TEXT, text_scale=0.020,
            frameColor=MED,
            frameSize=(-0.055, 0.055, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 + 0.165, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['stone'],
        )

        # Spawn Point section
        z_sp = z_tex_btns - 0.052
        _sp_lbl = DirectLabel(
            text="Type",
            text_fg=TEXT_D, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW + 0.05, 0, z_sp),
        )
        self._spawn_btn = DirectButton(
            text="Spawn Point: OFF",
            text_fg=TEXT, text_scale=0.022,
            frameColor=MED,
            frameSize=(-0.130, 0.130, -0.020, 0.020),
            parent=self._ins,
            pos=(-PW / 2, 0, z_sp - 0.038),
            command=self._toggle_spawn_point,
        )
        self._kill_btn = DirectButton(
            text="Kill Brick: OFF",
            text_fg=TEXT, text_scale=0.022,
            frameColor=MED,
            frameSize=(-0.130, 0.130, -0.020, 0.020),
            parent=self._ins,
            pos=(-PW / 2, 0, z_sp - 0.076),
            command=self._toggle_kill_brick,
        )
        self._nocol_btn = DirectButton(
            text="No Collision: OFF",
            text_fg=TEXT, text_scale=0.022,
            frameColor=MED,
            frameSize=(-0.130, 0.130, -0.020, 0.020),
            parent=self._ins,
            pos=(-PW / 2, 0, z_sp - 0.114),
            command=self._toggle_no_collision,
        )

        self._hat_tex_btn = DirectButton(
            text="Hat Texture",
            text_fg=TEXT, text_scale=0.022,
            frameColor=MED,
            frameSize=(-0.130, 0.130, -0.020, 0.020),
            parent=self._ins,
            pos=(-PW / 2, 0, z_sp - 0.160),
            command=self._upload_hat_texture,
        )
        self._hat_tex_btn.hide()

        self._hat_upload_btn = DirectButton(
            text="Upload Hat",
            text_fg=TEXT, text_scale=0.022,
            frameColor=(0.20, 0.44, 0.24, 1.0),
            frameSize=(-0.130, 0.130, -0.020, 0.020),
            parent=self._ins,
            pos=(-PW / 2, 0, z_sp - 0.208),
            command=self._show_upload_hat_dialog,
        )
        self._hat_upload_btn.hide()

        self._ins.hide()

        self.ui_elements += [
            self._ins, self._ins_none, self.selected_brick_label,
            _color_lbl,
            _texture_lbl, _plastic_btn, _grass_btn, _wood_btn, _stone_btn,
            _sp_lbl, self._spawn_btn, self._kill_btn, self._nocol_btn,
            self._hat_tex_btn, self._hat_upload_btn,
        ] + _palette_btns

    # ── Inspector visibility ───────────────────────────────────────────────

    def _show_inspector(self, brick):
        pos = brick.getPos()
        self.selected_brick_label['text'] = (
            f"({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f})"
        )
        self._ins_none.hide()
        self._ins.show()
        self._refresh_spawn_btn()
        self._refresh_kill_btn()
        self._refresh_nocol_btn()
        self._refresh_hierarchy()
        is_hat = (brick is getattr(self, '_hat_brick', None))
        is_bob = (getattr(self, '_session_username', None) == "bob")
        hat_btn = getattr(self, '_hat_tex_btn', None)
        if hat_btn:
            if is_hat and is_bob: hat_btn.show()
            else:                 hat_btn.hide()
        upload_btn = getattr(self, '_hat_upload_btn', None)
        if upload_btn:
            if is_hat and is_bob: upload_btn.show()
            else:                 upload_btn.hide()

    def _refresh_spawn_btn(self):
        btn = getattr(self, '_spawn_btn', None)
        if not btn or btn.isEmpty():
            return
        brick = getattr(self, 'selected_brick', None)
        if brick is None:
            btn['text'] = "Spawn Point: OFF"
            btn['frameColor'] = MED
            return
        is_sp = brick in getattr(self, 'brick_spawn_points', set())
        btn['text']       = "Spawn Point: ON" if is_sp else "Spawn Point: OFF"
        btn['frameColor'] = (0.18, 0.62, 0.34, 1.0) if is_sp else MED

    def _toggle_spawn_point(self):
        brick = getattr(self, 'selected_brick', None)
        if brick is None or getattr(self, 'is_playtest', False):
            return
        sp = getattr(self, 'brick_spawn_points', set())
        if brick in sp:
            sp.discard(brick)
        else:
            sp.add(brick)
            getattr(self, 'brick_kill_bricks', set()).discard(brick)
            self._refresh_kill_btn()
        self._refresh_spawn_btn()

    def _refresh_kill_btn(self):
        btn = getattr(self, '_kill_btn', None)
        if not btn or btn.isEmpty():
            return
        brick = getattr(self, 'selected_brick', None)
        if brick is None:
            btn['text'] = "Kill Brick: OFF"
            btn['frameColor'] = MED
            return
        is_kill = brick in getattr(self, 'brick_kill_bricks', set())
        btn['text']       = "Kill Brick: ON" if is_kill else "Kill Brick: OFF"
        btn['frameColor'] = (0.72, 0.12, 0.12, 1.0) if is_kill else MED

    def _toggle_kill_brick(self):
        brick = getattr(self, 'selected_brick', None)
        if brick is None or getattr(self, 'is_playtest', False):
            return
        kb = getattr(self, 'brick_kill_bricks', set())
        if brick in kb:
            kb.discard(brick)
        else:
            kb.add(brick)
            getattr(self, 'brick_spawn_points', set()).discard(brick)
            self._refresh_spawn_btn()
        self._refresh_kill_btn()

    def _refresh_nocol_btn(self):
        btn = getattr(self, '_nocol_btn', None)
        if not btn or btn.isEmpty():
            return
        brick = getattr(self, 'selected_brick', None)
        if brick is None:
            btn['text'] = "No Collision: OFF"
            btn['frameColor'] = MED
            return
        is_nc = brick in getattr(self, 'brick_no_collision', set())
        btn['text']       = "No Collision: ON" if is_nc else "No Collision: OFF"
        btn['frameColor'] = (0.20, 0.55, 0.80, 1.0) if is_nc else MED

    def _toggle_no_collision(self):
        brick = getattr(self, 'selected_brick', None)
        if brick is None or getattr(self, 'is_playtest', False):
            return
        nc = getattr(self, 'brick_no_collision', set())
        if brick in nc:
            nc.discard(brick)
        else:
            nc.add(brick)
        self.update_brick_collision(brick)
        self._refresh_nocol_btn()

    def _show_inspector_multi(self, count):
        self.selected_brick_label['text'] = f"{count} bricks selected"
        self._ins_none.hide()
        self._ins.show()
        self._refresh_hierarchy()
        for attr in ('_hat_tex_btn', '_hat_upload_btn'):
            btn = getattr(self, attr, None)
            if btn: btn.hide()

    def _hide_inspector(self):
        self._ins.hide()
        self._ins_none.show()
        self.selected_brick_label['text'] = ""
        self._refresh_hierarchy()
        self._refresh_spawn_btn()
        for attr in ('_hat_tex_btn', '_hat_upload_btn'):
            btn = getattr(self, attr, None)
            if btn: btn.hide()

    # ── Hierarchy ──────────────────────────────────────────────────────────

    def add_hierarchy_entry(self, brick, name=None):
        if name is None:
            self._brick_counter += 1
            name = f"Brick {self._brick_counter}"
        self._h_bricks.append(brick)
        self._brick_names[brick] = name
        self._refresh_hierarchy()

    def remove_hierarchy_entry(self, brick):
        if brick in self._h_bricks:
            self._h_bricks.remove(brick)
        btn = self._h_btns.pop(brick, None)
        if btn:
            btn.destroy()
        self._brick_names.pop(brick, None)
        n = len(self._h_bricks)
        self._scroll_off = max(0, min(self._scroll_off, n - MAX_VIS))
        self._refresh_hierarchy()

    def _refresh_hierarchy(self):
        for btn in list(self._h_btns.values()):
            btn.destroy()
        self._h_btns.clear()

        visible = self._h_bricks[self._scroll_off: self._scroll_off + MAX_VIS]
        for i, brick in enumerate(visible):
            name  = self._brick_names.get(brick, "Brick ?")
            sel   = (brick in self.selected_bricks)
            btn = DirectButton(
                text=name,
                text_fg=TEXT if sel else TEXT_D,
                text_pos=(-PW + 0.04, 0),
                text_align=TextNode.ALeft,
                text_scale=0.034,
                frameColor=SEL if sel else ITEM_BG,
                frameSize=(-PW, 0, -IH / 2, IH / 2),
                parent=self._list_root,
                pos=(0, 0, -(i + 0.5) * IH),
                command=self._on_hierarchy_click,
                extraArgs=[brick],
                relief=1,
                suppressKeys=False,
                suppressMouse=False,
            )
            self._h_btns[brick] = btn

    def _on_hierarchy_click(self, brick):
        if self.is_playtest:
            return
        from panda3d.core import KeyboardButton
        shift_held = (self.mouseWatcherNode.isButtonDown(KeyboardButton.lshift()) or
                      self.mouseWatcherNode.isButtonDown(KeyboardButton.rshift()))
        if shift_held:
            self._toggle_brick_selection(brick)
        else:
            self.select_brick(brick)

    def _scroll_up(self):
        self._scroll_off = max(0, self._scroll_off - 1)
        self._refresh_hierarchy()

    def _scroll_down(self):
        max_off = max(0, len(self._h_bricks) - MAX_VIS)
        self._scroll_off = min(max_off, self._scroll_off + 1)
        self._refresh_hierarchy()

    # ── Status task ────────────────────────────────────────────────────────

    def _status_task(self, task):
        fps = globalClock.getAverageFrameRate()
        self._status_lbl['text'] = f"{len(self.bricks)} Bricks  |  {fps:.0f} FPS"
        return Task.cont

    # ── Color / scale logic ────────────────────────────────────────────────

    def apply_color_to_selected_brick(self, color):
        if not self.selected_bricks:
            return
        old_colors = {b: self.brick_colors.get(b, (0.5, 0.5, 0.5, 0.7))
                      for b in self.selected_bricks}
        for brick in self.selected_bricks:
            self.apply_color_to_brick(brick, color)
        def undo(oc=old_colors):
            for b, c in oc.items():
                if b in self.bricks:
                    self.apply_color_to_brick(b, c)
        self._push_undo(undo)

    def apply_color_to_brick(self, brick, color):
        self.brick_colors[brick] = color
        if brick in self.brick_grass_shells:
            shell = self.brick_grass_shells[brick]
            if shell and not shell.isEmpty():
                from panda3d.core import Vec4
                shell.setShaderInput('brickColor', Vec4(*color))
            self.brick_grass_color[brick] = color
            return
        if brick in self.brick_wood_shells:
            shell = self.brick_wood_shells[brick]
            if shell and not shell.isEmpty():
                from panda3d.core import Vec4
                shell.setShaderInput('brickColor', Vec4(*color))
            self.brick_wood_color[brick] = color
            return
        if brick in self.brick_stone_shells:
            shell = self.brick_stone_shells[brick]
            if shell and not shell.isEmpty():
                from panda3d.core import Vec4
                shell.setShaderInput('brickColor', Vec4(*color))
            self.brick_stone_color[brick] = color
            return
        if brick in self.brick_hitbox_visuals:
            try:
                self.brick_hitbox_visuals[brick].setColor(*color)
            except Exception:
                pass
        try:
            brick.setColor(*color)
            if getattr(self, '_hat_brick', None) is not brick:
                brick.hide()
        except Exception:
            pass

    def reset_brick_color(self):
        if not self.selected_bricks:
            return
        old_colors = {b: self.brick_colors.get(b, (0.5, 0.5, 0.5, 0.7))
                      for b in self.selected_bricks}
        for brick in self.selected_bricks:
            if brick in self.brick_grass_shells:
                self.apply_color_to_brick(brick, (0.15, 0.49, 0.19, 1.0))
            elif brick in self.brick_wood_shells:
                self.apply_color_to_brick(brick, (0.80, 0.60, 0.35, 1.0))
            elif brick in self.brick_stone_shells:
                self.apply_color_to_brick(brick, (0.75, 0.72, 0.68, 1.0))
            else:
                self.apply_color_to_brick(brick, (0.5, 0.5, 0.5, 0.7))
        def undo(oc=old_colors):
            for b, c in oc.items():
                if b in self.bricks:
                    self.apply_color_to_brick(b, c)
        self._push_undo(undo)

    def apply_texture_to_selected_brick(self, texture_name):
        if not self.selected_bricks:
            return
        old_state = {}
        for brick in self.selected_bricks:
            if brick in self.brick_grass_shells:
                old_state[brick] = ('grass', self.brick_grass_color.get(brick, (0.15, 0.49, 0.19, 1.0)))
            elif brick in self.brick_wood_shells:
                old_state[brick] = ('wood', self.brick_wood_color.get(brick, (0.80, 0.60, 0.35, 1.0)))
            elif brick in self.brick_stone_shells:
                old_state[brick] = ('stone', self.brick_stone_color.get(brick, (0.75, 0.72, 0.68, 1.0)))
            else:
                old_state[brick] = ('plastic', self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7)))
        for brick in self.selected_bricks:
            self.apply_texture_to_brick(brick, texture_name)
        def undo(os=old_state):
            for b, (tex, col) in os.items():
                if b in self.bricks:
                    self.apply_texture_to_brick(b, tex)
                    self.apply_color_to_brick(b, col)
        self._push_undo(undo)

    def apply_texture_to_brick(self, brick, texture_name):
        if texture_name == 'plastic':
            shell = self.brick_grass_shells.pop(brick, None)
            if shell and not shell.isEmpty():
                shell.removeNode()
            self.brick_grass_color.pop(brick, None)
            wshell = self.brick_wood_shells.pop(brick, None)
            if wshell and not wshell.isEmpty():
                wshell.removeNode()
            self.brick_wood_color.pop(brick, None)
            sshell = self.brick_stone_shells.pop(brick, None)
            if sshell and not sshell.isEmpty():
                sshell.removeNode()
            self.brick_stone_color.pop(brick, None)
            self.brick_last_scale.pop(brick, None)
            self.brick_last_pos.pop(brick, None)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.show()
        elif texture_name == 'grass':
            wshell = self.brick_wood_shells.pop(brick, None)
            if wshell and not wshell.isEmpty():
                wshell.removeNode()
            self.brick_wood_color.pop(brick, None)
            sshell = self.brick_stone_shells.pop(brick, None)
            if sshell and not sshell.isEmpty():
                sshell.removeNode()
            self.brick_stone_color.pop(brick, None)
            self.brick_grass_color[brick] = self.brick_colors.get(brick, (0.15, 0.49, 0.19, 1.0))
            self._rebuild_grass_shell(brick)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.hide()
        elif texture_name == 'wood':
            shell = self.brick_grass_shells.pop(brick, None)
            if shell and not shell.isEmpty():
                shell.removeNode()
            self.brick_grass_color.pop(brick, None)
            sshell = self.brick_stone_shells.pop(brick, None)
            if sshell and not sshell.isEmpty():
                sshell.removeNode()
            self.brick_stone_color.pop(brick, None)
            self.brick_wood_color[brick] = self.brick_colors.get(brick, (0.80, 0.60, 0.35, 1.0))
            self._rebuild_wood_shell(brick)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.hide()
        elif texture_name == 'stone':
            shell = self.brick_grass_shells.pop(brick, None)
            if shell and not shell.isEmpty():
                shell.removeNode()
            self.brick_grass_color.pop(brick, None)
            wshell = self.brick_wood_shells.pop(brick, None)
            if wshell and not wshell.isEmpty():
                wshell.removeNode()
            self.brick_wood_color.pop(brick, None)
            self.brick_stone_color[brick] = self.brick_colors.get(brick, (0.75, 0.72, 0.68, 1.0))
            self._rebuild_stone_shell(brick)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.hide()

    def reset_brick_scaling(self):
        if not self.selected_bricks:
            return
        for brick in self.selected_bricks:
            default = self.brick_default_scale.get(brick)
            if default:
                brick.setScale(default)
            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(
                    brick, self.brick_hitbox_visuals[brick])
        self.create_scale_handles()

    def close_scale_controls(self):
        self.is_scale_mode = False
        self.clear_selection()

    def _open_hat_obj(self):
        import tkinter as _tk
        from tkinter import filedialog as _fd
        _root = _tk.Tk()
        _root.withdraw()
        _root.attributes('-topmost', True)
        path = _fd.askopenfilename(
            title="Import Hat (.obj)",
            filetypes=[("OBJ files", "*.obj"), ("All files", "*.*")],
        )
        _root.destroy()
        if path:
            self._load_hat_for_editor(path)

    def _load_hat_for_editor(self, path):
        from panda3d.core import Filename, NodePath, Vec3, TransparencyAttrib

        # Remove previous hat brick if it's still in the scene
        existing = getattr(self, '_hat_brick', None)
        if existing and not existing.isEmpty():
            if existing in self.selected_bricks:
                self.selected_bricks.remove(existing)
            if self.selected_brick is existing:
                self.selected_brick = None
            self._destroy_brick(existing)
        self._hat_brick = None

        try:
            hat_model = self.loader.loadModel(Filename.fromOsSpecific(path))
        except Exception as _e:
            return
        if not hat_model:
            return

        # Fix OBJ Y-up → Panda3D Z-up: rotate -90° around X axis (roll)
        hat_model.setR(-90)

        # Create the hat anchor (empty NodePath, registered in the brick system
        # so it can be selected, moved, and scaled in the editor)
        hat_brick = NodePath("hat_brick")
        hat_brick.reparentTo(self.render)
        hat_brick.setScale(2, 2, 2)
        if not self.is_playtest:
            fwd = self.camera.getQuat().getForward()
            hat_brick.setPos(self.camera.getPos() + fwd * 5)
        else:
            cp = self.character.getPos()
            hat_brick.setPos(cp.x, cp.y, cp.z + 4)

        # Parent hat model to anchor; position at center of the unit-space brick
        hat_model.reparentTo(hat_brick)
        hat_model.setPos(0.5, 0.5, 0.5)
        # Fixed-function pipeline: auto-shader + setTwoSided causes black patches
        # at certain angles because the auto-shader doesn't flip normals for back
        # faces. Fixed-function has built-in two-sided lighting that does.
        hat_model.setShaderOff()
        hat_model.setTwoSided(True)

        # Semi-transparent bounding box — visible in editor for selection feedback,
        # faint enough not to obscure the hat mesh itself
        hat_vis = self.create_solid_box(
            self.brick_base_width, self.brick_base_depth, self.brick_base_height,
            (0.3, 0.5, 1.0, 0.12),
        )
        hat_vis.reparentTo(self.render)
        hat_vis.setTransparency(TransparencyAttrib.MAlpha)

        # Register in the brick system (skip _grid_add so the character
        # doesn't physically collide with the hat brick)
        self.brick_hitbox_visuals[hat_brick] = hat_vis
        self.brick_default_scale[hat_brick]  = Vec3(hat_brick.getScale())
        self.brick_colors[hat_brick]         = (1, 1, 1, 1)
        self.update_brick_hitbox_visual_scale(hat_brick, hat_vis)
        self.update_brick_collision(hat_brick)
        self.bricks.append(hat_brick)
        self.add_hierarchy_entry(hat_brick, "Hat")

        self._hat_brick       = hat_brick
        self._hat_model       = hat_model
        self._hat_vis         = hat_vis
        self._hat_obj_path    = path
        self._hat_texture_path = None
        # Reset position offsets so each new hat starts fresh
        self._hat_z_offset = 0.0
        self._hat_x_offset = 0.0
        self._hat_y_offset = 0.0
        self._hat_saved_hpr = (0.0, 0.0, -90.0)

    def _hat_flip(self, direction):
        """Rotate the hat model 90° in the given direction (editor only)."""
        if self.is_playtest:
            return
        hat_brick = getattr(self, '_hat_brick', None)
        hat_model = getattr(self, '_hat_model', None)
        if not hat_brick or hat_brick.isEmpty():
            return
        if self.selected_brick is not hat_brick:
            return
        if not hat_model or hat_model.isEmpty():
            return
        if direction == "left":
            hat_model.setH(hat_model.getH() + 90)
        elif direction == "right":
            hat_model.setH(hat_model.getH() - 90)
        elif direction == "up":
            hat_model.setP(hat_model.getP() - 90)
        elif direction == "down":
            hat_model.setP(hat_model.getP() + 90)

    def _hat_rotate_backwards(self):
        """R: spin hat 180° around the heading axis — wearing it backwards."""
        hat_model = getattr(self, '_hat_model', None)
        if not hat_model or hat_model.isEmpty():
            return
        if self.is_playtest:
            h, p, r = getattr(self, '_hat_saved_hpr', (0.0, 0.0, -90.0))
            self._hat_saved_hpr = ((h + 180) % 360, p, r)
        else:
            hat_model.setH(hat_model.getH() + 180)

    def _apply_hat_mode(self):
        """In play mode reparent hat_model directly under render (bypassing
        character.setShaderOff) and track the head with a per-frame task.
        In editor mode restore the model to its hat_brick anchor."""
        hat_brick = getattr(self, '_hat_brick', None)
        hat_model = getattr(self, '_hat_model', None)
        hat_vis   = getattr(self, '_hat_vis', None)

        self.taskMgr.remove("_hatFollowTask")

        if not hat_brick or hat_brick.isEmpty():
            return
        if not hat_model or hat_model.isEmpty():
            return

        if self.is_playtest:
            # Save local transform (hat_brick has no rotation → local == world)
            self._hat_saved_hpr   = (hat_model.getH(), hat_model.getP(), hat_model.getR())
            self._hat_saved_scale = hat_model.getScale()
            # World scale = hat_brick.scale × hat_model.local_scale
            bs = hat_brick.getScale()
            ls = self._hat_saved_scale
            self._hat_world_scale = (bs.x * ls.x, bs.y * ls.y, bs.z * ls.z)
            # Reparent directly to render — completely outside the
            # character subtree that has setShaderOff, so textures show
            hat_model.reparentTo(self.render)
            hat_model.setScale(*self._hat_world_scale)
            hat_model.setHpr(*self._hat_saved_hpr)
            if hat_vis and not hat_vis.isEmpty():
                hat_vis.hide()
            self.taskMgr.add(self._hat_follow_task, "_hatFollowTask")
        else:
            # Restore to hat_brick with original local transform
            hat_model.reparentTo(hat_brick)
            hat_model.setPos(0.5, 0.5, 0.5)
            hpr   = getattr(self, '_hat_saved_hpr',   None)
            scale = getattr(self, '_hat_saved_scale', None)
            if hpr   is not None: hat_model.setHpr(*hpr)
            if scale is not None: hat_model.setScale(scale)
            hat_model.setShaderOff()
            if hat_vis and not hat_vis.isEmpty():
                hat_vis.show()
                self.update_brick_hitbox_visual_scale(hat_brick, hat_vis)

    def _hat_follow_task(self, task):
        from direct.task import Task
        hat_model = getattr(self, '_hat_model', None)
        if not hat_model or hat_model.isEmpty():
            return Task.done
        held = getattr(self, '_hat_adj_held', set())
        if held:
            _sp = 1.5 * globalClock.getDt()
            if "k" in held: self._hat_z_offset = getattr(self, '_hat_z_offset', 0.0) + _sp
            if "l" in held: self._hat_z_offset = getattr(self, '_hat_z_offset', 0.0) - _sp
            if "o" in held: self._hat_x_offset = getattr(self, '_hat_x_offset', 0.0) + _sp
            if "p" in held: self._hat_x_offset = getattr(self, '_hat_x_offset', 0.0) - _sp
            if "y" in held: self._hat_y_offset = getattr(self, '_hat_y_offset', 0.0) + _sp
            if "u" in held: self._hat_y_offset = getattr(self, '_hat_y_offset', 0.0) - _sp
        head_pos = self.head.getPos(self.render)
        z_adj    = getattr(self, '_hat_z_offset', 0.0)
        x_adj    = getattr(self, '_hat_x_offset', 0.0)
        y_adj    = getattr(self, '_hat_y_offset', 0.0)
        hat_model.setPos(head_pos.x + x_adj, head_pos.y + y_adj, head_pos.z + 0.55 + z_adj)
        h, p, r  = getattr(self, '_hat_saved_hpr', (0.0, 0.0, -90.0))
        hat_model.setHpr(self.character.getH() + h, p, r)
        return Task.cont


    def _upload_hat_texture(self):
        """Open a file dialog to pick an image and apply it to the hat model."""
        hat_model = getattr(self, '_hat_model', None)
        if not hat_model or hat_model.isEmpty():
            return
        import tkinter as _tk
        from tkinter import filedialog as _fd
        from panda3d.core import Filename
        _root = _tk.Tk()
        _root.withdraw()
        _root.attributes('-topmost', True)
        path = _fd.askopenfilename(
            title="Hat Texture",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tga *.webp"),
                ("All files", "*.*"),
            ],
        )
        _root.destroy()
        if not path:
            return
        try:
            from panda3d.core import PNMImage, StringStream, Texture as _Tex
            import io as _io
            tex = None
            try:
                from PIL import Image as _PIL
                img = _PIL.open(path).convert("RGB")
                buf = _io.BytesIO()
                img.save(buf, format="PNG")
                ss  = StringStream(buf.getvalue())
                pnm = PNMImage()
                if pnm.read(ss):
                    tex = _Tex()
                    tex.load(pnm)
            except ImportError:
                tex = self.loader.loadTexture(Filename.fromOsSpecific(path))
            if tex:
                hat_model.setTexture(tex, 1)
                self._hat_texture_path = path
        except Exception:
            pass

    def _show_upload_hat_dialog(self):
        hat_brick = getattr(self, '_hat_brick', None)
        hat_model = getattr(self, '_hat_model', None)
        obj_path  = getattr(self, '_hat_obj_path', None)
        token     = getattr(self, '_session_token', None)
        if not hat_brick or hat_brick.isEmpty() or not hat_model or not obj_path or not token:
            return

        existing = getattr(self, '_hat_upload_popup', None)
        if existing:
            try: existing.destroy()
            except Exception: pass

        from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectButton, DirectEntry
        from panda3d.core import TextNode

        DARK2  = (0.10, 0.11, 0.16, 0.96)
        MED2   = (0.17, 0.19, 0.26, 1.0)
        BTN2   = (0.20, 0.44, 0.24, 1.0)
        CAN2   = (0.30, 0.30, 0.40, 1.0)
        TEXT2  = (0.88, 0.90, 0.95, 1.0)
        GRAY2  = (0.54, 0.57, 0.65, 1.0)
        RED2   = (0.90, 0.30, 0.30, 1.0)
        GREEN2 = (0.40, 0.88, 0.50, 1.0)

        overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.75),
            frameSize=(-3, 3, -3, 3),
            sortOrder=500, state='normal',
        )
        self._hat_upload_popup = overlay

        card = DirectFrame(
            frameColor=DARK2,
            frameSize=(-0.55, 0.55, -0.38, 0.38),
            parent=overlay, sortOrder=501,
        )

        DirectLabel(
            text="Upload Hat to Shop",
            text_fg=TEXT2, text_scale=0.034,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, 0.28),
        )

        DirectLabel(
            text="Name",
            text_fg=GRAY2, text_scale=0.024,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.50, 0, 0.14),
        )
        name_bg = DirectFrame(
            frameColor=MED2,
            frameSize=(-0.48, 0.48, -0.030, 0.030),
            parent=card, pos=(0, 0, 0.085),
        )
        name_entry = DirectEntry(
            text_fg=TEXT2, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            width=36, numLines=1,
            parent=name_bg, pos=(-0.46, 0, -0.010),
        )

        DirectLabel(
            text="Description",
            text_fg=GRAY2, text_scale=0.024,
            text_align=TextNode.ALeft,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(-0.50, 0, -0.02),
        )
        desc_bg = DirectFrame(
            frameColor=MED2,
            frameSize=(-0.48, 0.48, -0.030, 0.030),
            parent=card, pos=(0, 0, -0.075),
        )
        desc_entry = DirectEntry(
            text_fg=TEXT2, text_scale=0.026,
            frameColor=(0, 0, 0, 0),
            width=36, numLines=1,
            parent=desc_bg, pos=(-0.46, 0, -0.010),
        )

        status_lbl = DirectLabel(
            text="",
            text_fg=GREEN2, text_scale=0.024,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.19),
        )

        _zv = getattr(self, '_hat_z_offset', 0.0)
        _xv = getattr(self, '_hat_x_offset', 0.0)
        _yv = getattr(self, '_hat_y_offset', 0.0)
        _any_offset = (_zv != 0.0 or _xv != 0.0 or _yv != 0.0)
        _pos_text  = f"Pos  Z:{_zv:+.2f}  X:{_xv:+.2f}  Y:{_yv:+.2f}"
        _pos_color = (0.55, 0.85, 0.55, 1) if _any_offset else (0.85, 0.55, 0.35, 1)
        if not _any_offset:
            _pos_text = "No position set - enter Play to adjust"
        DirectLabel(
            text=_pos_text,
            text_fg=_pos_color, text_scale=0.020,
            frameColor=(0, 0, 0, 0),
            parent=card, pos=(0, 0, -0.14),
        )

        def _cancel():
            p = getattr(self, '_hat_upload_popup', None)
            if p:
                try: p.destroy()
                except Exception: pass
            self._hat_upload_popup = None

        def _publish():
            import threading as _thr
            item_name = name_entry.get().strip()
            if not item_name:
                status_lbl['text'] = "Enter a name."
                status_lbl['text_fg'] = RED2
                return
            item_desc = desc_entry.get().strip()
            status_lbl['text'] = "Packaging..."
            status_lbl['text_fg'] = GRAY2

            # Guard: hat_brick/hat_model may have been removed since dialog opened
            if hat_brick.isEmpty() or hat_model.isEmpty():
                status_lbl['text'] = "Hat was removed — reload it first."
                status_lbl['text_fg'] = RED2
                return

            # Read all Panda3D NodePath values NOW on the main thread —
            # accessing them inside a background thread causes the assertion crash.
            bs = hat_brick.getScale()
            ms = hat_model.getScale()
            hpr_now = getattr(self, '_hat_saved_hpr', None)
            if hpr_now is None:
                hpr_now = (hat_model.getH(), hat_model.getP(), hat_model.getR())
            brick_scale_v = [bs.x, bs.y, bs.z]
            model_scale_v = [ms.x, ms.y, ms.z]
            model_hpr_v   = list(hpr_now)
            z_offset_v    = getattr(self, '_hat_z_offset', 0.0)
            x_offset_v    = getattr(self, '_hat_x_offset', 0.0)
            y_offset_v    = getattr(self, '_hat_y_offset', 0.0)
            tex_path_v    = getattr(self, '_hat_texture_path', None)
            def worker(bsv=brick_scale_v, msv=model_scale_v, hprv=model_hpr_v,
                       zov=z_offset_v, xov=x_offset_v, yov=y_offset_v, tpv=tex_path_v):
                import base64, tempfile, json as _json, os as _os, re as _re
                from panda3d.core import PNMImage, Filename as _Fn, BitMask32
                from panda3d.core import Camera, PerspectiveLens
                try:
                    # -- OBJ bytes ------------------------------------------------
                    with open(obj_path, 'rb') as fh:
                        obj_raw = fh.read()
                    obj_b64 = base64.b64encode(obj_raw).decode()

                    # -- MTL file (materials) — look for mtllib line in OBJ -------
                    mtl_b64  = None
                    mtl_name = None
                    try:
                        obj_text = obj_raw.decode('utf-8', errors='replace')
                        m = _re.search(r'^mtllib\s+(.+)$', obj_text, _re.MULTILINE)
                        if m:
                            mtl_name = m.group(1).strip()
                            mtl_path = _os.path.join(_os.path.dirname(obj_path), mtl_name)
                            if _os.path.exists(mtl_path):
                                with open(mtl_path, 'rb') as fh:
                                    mtl_b64 = base64.b64encode(fh.read()).decode()
                    except Exception:
                        pass

                    # -- Texture bytes (if any) -----------------------------------
                    tex_b64 = None
                    if tpv and _os.path.exists(tpv):
                        try:
                            from PIL import Image as _PILImg
                            import io as _io
                            _pil = _PILImg.open(tpv).convert("RGB")
                            if _pil.width > 512 or _pil.height > 512:
                                _pil = _pil.resize((512, 512), _PILImg.LANCZOS)
                            _buf = _io.BytesIO()
                            _pil.save(_buf, format="PNG")
                            tex_b64 = base64.b64encode(_buf.getvalue()).decode()
                        except Exception:
                            pass

                    # -- Transform metadata (plain Python values, no NodePath) ----
                    hat_data = _json.dumps({
                        "obj_b64":     obj_b64,
                        "mtl_b64":     mtl_b64,
                        "mtl_name":    mtl_name,
                        "texture_b64": tex_b64,
                        "brick_scale": bsv,
                        "model_scale": msv,
                        "model_hpr":   hprv,
                        "z_offset":    zov,
                        "x_offset":    xov,
                        "y_offset":    yov,
                    })
                except Exception as e:
                    def _err(task, msg=str(e)):
                        status_lbl['text'] = f"Pack error: {msg[:40]}"
                        status_lbl['text_fg'] = RED2
                        return task.done
                    self.taskMgr.doMethodLater(0, _err, "_hatUploadErr", appendTask=True)
                    return

                # -- Thumbnail: avatar rig + hat, same framing as T-shirt thumbs ----
                def _do_thumb_and_upload(task):
                    thumb_b64 = ""
                    try:
                        from panda3d.core import (
                            Filename as _Fn2, LColor, Point3,
                            AmbientLight as _AL, DirectionalLight as _DL, Vec3,
                        )
                        PMASK  = BitMask32.bit(8)
                        BUF_W  = BUF_H = 512
                        RIG_Z  = -2.0   # calibrated: avatar sits lower so hat is visible
                        DIST   = 11.0   # calibrated zoom
                        CAM_Z  = 3.3    # same as T-shirt thumbnails

                        _GREY  = (0.72, 0.72, 0.72, 1)
                        _DCOL  = {k: _GREY for k in ("head","torso","left_arm","right_arm","left_leg","right_leg")}
                        colors = _DCOL

                        rig = self.render.attachNewNode("hat_thumb_rig")
                        rig.setPos(0, 5000, RIG_Z)

                        def _box(parent, sc, pos, col):
                            m = self.loader.loadModel("models/box")
                            m.reparentTo(parent); m.setScale(*sc); m.setPos(*pos)
                            m.setColor(*col); m.setTextureOff(1); m.show(PMASK)
                        _box(rig,(2,1,2),(-1,-0.5,2),   colors.get("torso",     _DCOL["torso"]))
                        la=rig.attachNewNode("la"); la.setPos(-1.5,0,4)
                        _box(la,(1,1,2),(-0.5,-0.5,-2), colors.get("left_arm",  _DCOL["left_arm"]))
                        ra=rig.attachNewNode("ra"); ra.setPos(1.5,0,4)
                        _box(ra,(1,1,2),(-0.5,-0.5,-2), colors.get("right_arm", _DCOL["right_arm"]))
                        ll=rig.attachNewNode("ll"); ll.setPos(-0.5,0,2)
                        _box(ll,(1,1,2),(-0.5,-0.5,-2), colors.get("left_leg",  _DCOL["left_leg"]))
                        rl=rig.attachNewNode("rl"); rl.setPos(0.5,0,2)
                        _box(rl,(1,1,2),(-0.5,-0.5,-2), colors.get("right_leg", _DCOL["right_leg"]))
                        head = self.create_cylinder(radius=0.7, height=1.1, segments=16)
                        head.reparentTo(rig); head.setColor(*colors.get("head",_DCOL["head"]))
                        head.setTwoSided(True); head.setTextureOff(1)
                        head.setPos(0,0,4.55); head.show(PMASK)

                        # Hat model on top of head
                        hat_m = self.loader.loadModel(_Fn2.fromOsSpecific(obj_path))
                        if hat_m:
                            hat_m.setR(-90)
                            hat_m.setScale(*[bsv[i]*msv[i] for i in range(3)])
                            hat_m.setHpr(*hprv)
                            tp2 = getattr(self, '_hat_texture_path', None)
                            if tp2:
                                import os as _os3, io as _io2
                                if _os3.path.exists(tp2):
                                    try:
                                        from PIL import Image as _PILt
                                        from panda3d.core import PNMImage as _PNMt, StringStream as _SSt, Texture as _Tt
                                        _pi = _PILt.open(tp2).convert("RGB")
                                        _bb = _io2.BytesIO()
                                        _pi.save(_bb, format="PNG")
                                        _ss = _SSt(_bb.getvalue())
                                        _pnm = _PNMt()
                                        if _pnm.read(_ss):
                                            t2 = _Tt(); t2.load(_pnm)
                                            hat_m.setTexture(t2, 1)
                                    except Exception:
                                        t2 = self.loader.loadTexture(_Fn2.fromOsSpecific(tp2))
                                        if t2: hat_m.setTexture(t2, 1)
                            hat_m.reparentTo(rig)
                            hat_m.setPos(xov, yov, 4.55 + 0.55 + zov)
                            hat_m.setShaderOff(); hat_m.setTwoSided(True)
                            hat_m.show(PMASK)

                        al = _AL("ht_al"); al.setColor(LColor(0.22,0.22,0.25,1))
                        rig.setLight(rig.attachNewNode(al))
                        dl = _DL("ht_dl"); dl.setColor(LColor(0.50,0.50,0.52,1))
                        dlnp = rig.attachNewNode(dl); dlnp.setHpr(20,15,0); rig.setLight(dlnp)

                        buf = self.win.makeTextureBuffer("hat_thumb", BUF_W, BUF_H)
                        buf.setClearColor(LColor(0.78,0.75,0.88,1.0))  # same as tshirt
                        buf.setClearColorActive(True)
                        _cn = Camera("hat_thumb_cam")
                        _lens = PerspectiveLens()
                        _lens.setFov(32); _lens.setAspectRatio(1.0); _lens.setNearFar(0.1,10000)
                        _cn.setLens(_lens); _cn.setCameraMask(PMASK)
                        cam_np = self.render.attachNewNode(_cn)
                        cam_np.setPos(0, 5000 - DIST, CAM_Z)
                        cam_np.lookAt(Point3(0, 5000, CAM_Z))
                        _dr = buf.makeDisplayRegion(); _dr.setSort(10); _dr.setCamera(cam_np)
                        orig_mask = self.camNode.getCameraMask()
                        self.camNode.setCameraMask(orig_mask & ~PMASK)
                        # Hide everything in the scene from the thumbnail camera,
                        # then force only the rig visible — prevents the live
                        # character/face/shirt from bleeding into the thumbnail.
                        self.render.hide(PMASK)
                        rig.showThrough(PMASK)

                        self.graphicsEngine.renderFrame()
                        rtex = buf.getTexture()
                        self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
                        pnm = PNMImage()
                        if rtex.store(pnm):
                            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                                tmp2 = tf.name
                            pnm.write(_Fn2.fromOsSpecific(tmp2))
                            with open(tmp2, 'rb') as fh:
                                thumb_b64 = base64.b64encode(fh.read()).decode()
                            import os as _os2; _os2.unlink(tmp2)

                        self.render.show(PMASK)
                        self.graphicsEngine.removeWindow(buf)
                        cam_np.removeNode(); rig.removeNode()
                        self.camNode.setCameraMask(orig_mask)
                    except Exception:
                        pass

                    import threading as _thr2, auth_client as _ac
                    def _upload():
                        # Embed hat_data inside image_data so no server schema changes
                        # are required. The Render server stores image_data as-is.
                        # Format: <thumb_b64>|HATDATA|<base64(hat_data_json)>
                        hat_data_encoded = base64.b64encode(hat_data.encode()).decode()
                        combined = thumb_b64 + "|HATDATA|" + hat_data_encoded
                        result, err = _ac.upload_shop_item(
                            token, item_name, item_desc, 0, combined,
                            category="hat", hat_data="")
                        def _done(task, ok=(result is not None), err=err):
                            if ok:
                                status_lbl['text'] = "Published!"
                                status_lbl['text_fg'] = GREEN2
                            else:
                                status_lbl['text'] = f"Error: {(err or '')[:40]}"
                                status_lbl['text_fg'] = RED2
                            return task.done
                        self.taskMgr.doMethodLater(0, _done, "_hatUploadDone", appendTask=True)
                    _thr2.Thread(target=_upload, daemon=True).start()
                    return task.done

                self.taskMgr.doMethodLater(0, _do_thumb_and_upload, "_hatThumbUpload", appendTask=True)

            def _set_packaging(task):
                status_lbl['text'] = "Packaging..."
                status_lbl['text_fg'] = GRAY2
                import threading as _thr3
                _thr3.Thread(target=worker, daemon=True).start()
                return task.done
            self.taskMgr.doMethodLater(0, _set_packaging, "_hatPackage", appendTask=True)

        DirectButton(
            text="Publish",
            text_fg=TEXT2, text_scale=0.028,
            frameColor=BTN2,
            frameSize=(-0.13, 0.13, -0.032, 0.032),
            parent=card, pos=(-0.18, 0, -0.29),
            relief=1, command=_publish,
        )
        DirectButton(
            text="Cancel",
            text_fg=GRAY2, text_scale=0.026,
            frameColor=CAN2,
            frameSize=(-0.10, 0.10, -0.028, 0.028),
            parent=card, pos=(0.26, 0, -0.29),
            relief=1, command=_cancel,
        )

    def _hat_thumbnail_debug_REMOVED(self):
        from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectButton
        from panda3d.core import (
            BitMask32, Camera, PerspectiveLens, PNMImage,
            LColor, Point3, AmbientLight, DirectionalLight,
            Filename, Vec3,
        )
        from direct.task import Task

        # Close any existing debug window
        existing = getattr(self, '_hat_dbg_overlay', None)
        if existing:
            try: existing.destroy()
            except Exception: pass
        self.taskMgr.remove("_hatDbgTask")
        for k in ('arrow_up', 'arrow_down', 'arrow_left', 'arrow_right'):
            self.ignore(k)

        # Adjustable params — same defaults as _render_shop_thumbnails
        self._hat_dbg_rig_z  =  0.0   # rig Z offset: negative = avatar lower in frame
        self._hat_dbg_dist   = 12.0   # camera distance (same default as tshirt thumbs)
        self._hat_dbg_dirty  = True

        PMASK = BitMask32.bit(11)
        BUF_W = BUF_H = 300

        # ── Build avatar rig at a parked world position ────────────────────
        _DEFAULTS_COL = {
            "head":      (244/255, 204/255,  67/255, 1),
            "torso":     ( 23/255, 107/255, 170/255, 1),
            "left_arm":  (244/255, 204/255,  67/255, 1),
            "right_arm": (244/255, 204/255,  67/255, 1),
            "left_leg":  (165/255, 188/255,  80/255, 1),
            "right_leg": (165/255, 188/255,  80/255, 1),
        }
        colors = getattr(self, '_avatar_colors', None) or _DEFAULTS_COL

        rig = self.render.attachNewNode("hatdbg_rig")
        rig.setPos(0, 7000, 0)

        def _box(parent, scale, pos, col):
            m = self.loader.loadModel("models/box")
            m.reparentTo(parent); m.setScale(*scale); m.setPos(*pos)
            m.setColor(*col); m.setTextureOff(1); m.show(PMASK); return m

        _box(rig, (2,1,2), (-1,-0.5,2), colors.get("torso", _DEFAULTS_COL["torso"]))
        la = rig.attachNewNode("la"); la.setPos(-1.5,0,4)
        _box(la,(1,1,2),(-0.5,-0.5,-2), colors.get("left_arm",  _DEFAULTS_COL["left_arm"]))
        ra = rig.attachNewNode("ra"); ra.setPos(1.5,0,4)
        _box(ra,(1,1,2),(-0.5,-0.5,-2), colors.get("right_arm", _DEFAULTS_COL["right_arm"]))
        ll = rig.attachNewNode("ll"); ll.setPos(-0.5,0,2)
        _box(ll,(1,1,2),(-0.5,-0.5,-2), colors.get("left_leg",  _DEFAULTS_COL["left_leg"]))
        rl = rig.attachNewNode("rl"); rl.setPos(0.5,0,2)
        _box(rl,(1,1,2),(-0.5,-0.5,-2), colors.get("right_leg", _DEFAULTS_COL["right_leg"]))

        head_cyl = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        head_cyl.reparentTo(rig)
        head_cyl.setColor(*colors.get("head", _DEFAULTS_COL["head"]))
        head_cyl.setTwoSided(True); head_cyl.setTextureOff(1)
        head_cyl.setPos(0,0,4.55); head_cyl.show(PMASK)

        # Load hat model onto rig head
        hat_copy = self.loader.loadModel(Filename.fromOsSpecific(obj_path))
        if hat_copy:
            hat_copy.setR(-90)
            if hat_brick and not hat_brick.isEmpty():
                bs = hat_brick.getScale()
                ms = hat_model.getScale() if hat_model and not hat_model.isEmpty() else Vec3(1,1,1)
                hat_copy.setScale(bs.x*ms.x, bs.y*ms.y, bs.z*ms.z)
                hpr = getattr(self, '_hat_saved_hpr', None) or (hat_model.getH(), hat_model.getP(), hat_model.getR())
                hat_copy.setHpr(*hpr)
                z_off = getattr(self, '_hat_z_offset', 0.0)
                x_off = getattr(self, '_hat_x_offset', 0.0)
                y_off = getattr(self, '_hat_y_offset', 0.0)
            else:
                hat_copy.setScale(2,2,2); z_off = 0.0; x_off = 0.0; y_off = 0.0
            # Apply texture if one was uploaded
            tex_p = getattr(self, '_hat_texture_path', None)
            if tex_p and __import__('os').path.exists(tex_p):
                tex = self.loader.loadTexture(Filename.fromOsSpecific(tex_p))
                if tex:
                    hat_copy.setTexture(tex, 1)
            hat_copy.reparentTo(rig)
            hat_copy.setPos(x_off, y_off, 4.55 + 0.55 + z_off)
            hat_copy.setShaderOff(); hat_copy.setTwoSided(True)
            hat_copy.show(PMASK)

        # Lighting for rig
        al = AmbientLight("hdbg_al"); al.setColor(LColor(0.22,0.22,0.25,1))
        rig.setLight(rig.attachNewNode(al))
        dl = DirectionalLight("hdbg_dl"); dl.setColor(LColor(0.50,0.50,0.52,1))
        dlnp = rig.attachNewNode(dl); dlnp.setHpr(20,15,0); rig.setLight(dlnp)

        # ── Offscreen buffer + camera ─────────────────────────────────────
        buf = self.win.makeTextureBuffer("hatdbg_buf", BUF_W, BUF_H)
        buf.setClearColor(LColor(0.78,0.75,0.88,1.0)); buf.setClearColorActive(True)

        cam_node = Camera("hatdbg_cam")
        lens = PerspectiveLens(); lens.setFov(32); lens.setAspectRatio(1.0); lens.setNearFar(0.1,10000)
        cam_node.setLens(lens); cam_node.setCameraMask(PMASK)
        cam_np = self.render.attachNewNode(cam_node)
        _dr = buf.makeDisplayRegion(); _dr.setSort(10); _dr.setCamera(cam_np)
        orig_mask = self.camNode.getCameraMask()
        self.camNode.setCameraMask(orig_mask & ~PMASK)

        self._hat_dbg_rig     = rig
        self._hat_dbg_cam_np  = cam_np
        self._hat_dbg_buf     = buf
        self._hat_dbg_orig_mask = orig_mask

        def _update_camera():
            # Identical to _render_shop_thumbnails: FOV=32, cam_z=3.3, dist=12 default.
            # Only rig_z and dist are adjustable — camera is always centered at X=0.
            rz   = self._hat_dbg_rig_z
            dist = self._hat_dbg_dist
            rig.setPos(0, 7000, rz)
            cam_np.setPos(0, 7000 - dist, 3.3)
            cam_np.lookAt(Point3(0, 7000, 3.3))

        # ── Overlay UI ────────────────────────────────────────────────────
        overlay = DirectFrame(
            frameColor=(0,0,0,0.88), frameSize=(-3,3,-3,3),
            sortOrder=600, state='normal',
        )
        self._hat_dbg_overlay = overlay

        preview_card = DirectFrame(
            frameColor=(1,1,1,1),
            frameSize=(-0.55,0.55,-0.55,0.55),
            parent=overlay, pos=(-0.7, 0, 0),
        )
        preview_card.setTransparency(False)

        coords_lbl = DirectLabel(
            text="rig_z: 0.0 | dist: 12.0",
            text_fg=(0.9,0.95,1,1), text_scale=0.032,
            frameColor=(0,0,0,0),
            parent=overlay, pos=(0.55, 0, 0.65),
        )
        DirectLabel(
            text="UP/DOWN: move avatar up/down  |  +/-: zoom",
            text_fg=(0.7,0.75,0.85,1), text_scale=0.026,
            frameColor=(0,0,0,0),
            parent=overlay, pos=(0.55, 0, 0.55),
        )

        def _close_dbg():
            self.taskMgr.remove("_hatDbgTask")
            for k in ('arrow_up','arrow_down','=','+','-'):
                self.ignore(k)
            buf2 = getattr(self, '_hat_dbg_buf', None)
            if buf2: self.graphicsEngine.removeWindow(buf2)
            np2 = getattr(self, '_hat_dbg_cam_np', None)
            if np2 and not np2.isEmpty(): np2.removeNode()
            rig2 = getattr(self, '_hat_dbg_rig', None)
            if rig2 and not rig2.isEmpty(): rig2.removeNode()
            orig = getattr(self, '_hat_dbg_orig_mask', None)
            if orig is not None: self.camNode.setCameraMask(orig)
            self._hat_dbg_buf = self._hat_dbg_cam_np = self._hat_dbg_rig = None
            ov = getattr(self, '_hat_dbg_overlay', None)
            if ov:
                try: ov.destroy()
                except Exception: pass
            self._hat_dbg_overlay = None
            # Restore all four hat-flip arrow bindings
            for direction in ("left", "right", "up", "down"):
                self.accept(f"arrow_{direction}", self._hat_flip, [direction])

        DirectButton(
            text="Close",
            text_fg=(1,1,1,1), text_scale=0.030,
            frameColor=(0.55,0.18,0.18,1),
            frameSize=(-0.12,0.12,-0.036,0.036),
            parent=overlay, pos=(0.55, 0, -0.65),
            relief=1, command=_close_dbg,
        )

        # Arrow key handlers
        def _step_z_up():
            self._hat_dbg_rig_z += 1.0; self._hat_dbg_dirty = True
        def _step_z_dn():
            self._hat_dbg_rig_z -= 1.0; self._hat_dbg_dirty = True
        def _zoom_in():
            self._hat_dbg_dist = max(2, self._hat_dbg_dist - 1.0)
            self._hat_dbg_dirty = True
        def _zoom_out():
            self._hat_dbg_dist += 1.0; self._hat_dbg_dirty = True

        # Override hat-flip bindings temporarily
        self.ignore("arrow_left"); self.ignore("arrow_right")
        self.ignore("arrow_up");   self.ignore("arrow_down")
        self.accept("arrow_up",   _step_z_up)
        self.accept("arrow_down", _step_z_dn)
        self.accept("=",          _zoom_in)
        self.accept("+",          _zoom_in)
        self.accept("-",          _zoom_out)

        # ── Render task ───────────────────────────────────────────────────
        def _dbg_task(task):
            if not getattr(self, '_hat_dbg_dirty', False):
                return Task.cont
            self._hat_dbg_dirty = False
            _update_camera()
            self.graphicsEngine.renderFrame()
            rtex = buf.getTexture()
            self.graphicsEngine.extractTextureData(rtex, self.win.getGsg())
            pnm = PNMImage()
            if rtex.store(pnm):
                from panda3d.core import Texture
                tex = Texture(); tex.load(pnm)
                tex.setMinfilter(Texture.FTLinear)
                tex.setMagfilter(Texture.FTLinear)
                preview_card["frameTexture"] = tex
                preview_card["frameColor"]   = (1,1,1,1)
            coords_lbl["text"] = (
                f"rig_z: {self._hat_dbg_rig_z:.1f}  |  dist: {self._hat_dbg_dist:.1f}"
            )
            return Task.cont

        self.taskMgr.add(_dbg_task, "_hatDbgTask")
        self._hat_dbg_dirty = True   # trigger first render

    def _on_window_event(self, window):
        # Only the background bar width needs updating; buttons and status
        # label are edge-anchored and reposition automatically.
        ar = base.getAspectRatio()
        self._top_bg['frameSize'] = (0, 2 * ar, -TH, 0)

    def _mouse_is_over_hierarchy(self):
        # win.getPointer(0) relies on WM_MOUSEMOVE which DirectGUI consumes, so it
        # returns stale data. Call GetCursorPos+ScreenToClient via ctypes instead —
        # the OS always knows where the cursor is regardless of event capture state.
        try:
            import ctypes
            class _PT(ctypes.Structure):
                _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
            pt = _PT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            hwnd = base.win.getWindowHandle().getIntHandle()
            ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt))
            win_w = base.win.getXSize()
            win_h = base.win.getYSize()
            if win_w <= 0 or win_h <= 0:
                return False
            ar = base.getAspectRatio()
            # Pixel → render2d: x ∈ [-ar, ar], z ∈ [-1 (bottom), 1 (top)]
            mx = (pt.x / win_w * 2 - 1) * ar
            mz = -(pt.y / win_h * 2 - 1)
            # _list_root in render2d: x ∈ [ar-PW, ar], z ∈ [1+LIST_BOT, 1+LIST_TOP]
            return (ar - PW <= mx <= ar and 1.0 + LIST_BOT <= mz <= 1.0 + LIST_TOP)
        except Exception:
            return False

    def _on_wheel(self, direction):
        if self.is_playtest:
            self.zoom_camera(direction)
        elif self._mouse_is_over_hierarchy():
            if direction > 0:
                self._scroll_up()
            else:
                self._scroll_down()
        else:
            self.zoom_camera(direction)

    # ── Mode toggles ───────────────────────────────────────────────────────

    def toggle_scale_mode(self):
        self.is_scale_mode  = not self.is_scale_mode
        self.is_move_mode   = False
        self.is_rotate_mode = False
        self.move_button['text']   = "Move"
        self.rotate_button['text'] = "Rotate"
        for h in self.rotate_handles:
            h['node'].removeNode()
        self.rotate_handles.clear()
        if self.is_scale_mode:
            self.scale_button['text'] = "[Scale]"
            if self.selected_brick:
                for h in self.move_handles:
                    h['node'].removeNode()
                self.move_handles.clear()
                self.create_scale_handles()
        else:
            self.scale_button['text'] = "Scale"
            self.clear_selection()

    def toggle_rotate_mode(self):
        self.is_rotate_mode = not self.is_rotate_mode
        self.is_scale_mode  = False
        self.is_move_mode   = False
        self.scale_button['text'] = "Scale"
        self.move_button['text']  = "Move"
        for h in self.scale_handles:
            h['node'].removeNode()
        self.scale_handles.clear()
        for h in self.move_handles:
            h['node'].removeNode()
        self.move_handles.clear()
        if self.is_rotate_mode:
            self.rotate_button['text'] = "[Rotate]"
            if self.selected_brick:
                self.create_rotate_handles()
        else:
            self.rotate_button['text'] = "Rotate"
            for h in self.rotate_handles:
                h['node'].removeNode()
            self.rotate_handles.clear()

    def toggle_move_mode(self):
        self.is_move_mode   = not self.is_move_mode
        self.is_scale_mode  = False
        self.is_rotate_mode = False
        self.scale_button['text']  = "Scale"
        self.rotate_button['text'] = "Rotate"
        for h in self.rotate_handles:
            h['node'].removeNode()
        self.rotate_handles.clear()
        if self.is_move_mode:
            self.move_button['text'] = "[Move]"
            if self.selected_brick:
                for h in self.scale_handles:
                    h['node'].removeNode()
                self.scale_handles.clear()
                self.create_move_handles()
        else:
            self.move_button['text'] = "Move"
            self.clear_selection()

    def toggle_mode(self):
        if getattr(self, "_is_play_only", False):
            return
        self.is_playtest = not self.is_playtest
        if self.is_playtest:
            # Switched TO play mode — reset to neutral first so the overlap
            # fallback in spawn_unstuck doesn't anchor to the editor position
            self.character.setPos(0, 0, 50)
            self.spawn_unstuck()
            self.character.show()
            self.exit_button['text'] = "Edit"   # clicking will go to editor
            self._panel.hide()
            for w in (self.insert_brick_button, self.move_button,
                      self.scale_button, self.rotate_button, self.export_button,
                      self.import_button, self.cloud_save_button, self.hat_config_button):
                w.hide()
            self.clear_selection()
            self.is_move_mode   = False
            self.is_scale_mode  = False
            self.is_rotate_mode = False
            self.move_button['text']   = "Move"
            self.scale_button['text']  = "Scale"
            self.rotate_button['text'] = "Rotate"
            self.cam_distance = 20
            self.cam_angle.set(0, 20)
            self.camLens.setFov(getattr(self, '_settings_play_fov', 80))
            self._apply_hat_mode()
        else:
            # Switched TO editor mode
            if getattr(self, 'is_first_person', False):
                self._exit_first_person()
            self.character.hide()
            self.exit_button['text'] = "Play"   # clicking will go to play
            self._panel.show()
            for w in (self.insert_brick_button, self.move_button,
                      self.scale_button, self.rotate_button, self.export_button,
                      self.import_button, self.cloud_save_button):
                w.show()
            if getattr(self, '_session_username', None) == "bob":
                self.hat_config_button.show()
            self.shift_lock = False
            if self.is_rotating:
                self.is_rotating = False
            self._restore_cursor()
            self.camera.setPos(0, -30, 18)
            self.camera.lookAt(Point3(0, 0, 1))
            self.camLens.setFov(getattr(self, '_settings_play_fov', 80))
            self._apply_hat_mode()
