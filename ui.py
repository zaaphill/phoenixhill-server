from direct.gui.DirectGui import (
    DirectButton, DirectFrame, DirectLabel,
)
from panda3d.core import WindowProperties, TextNode, Point3
from direct.task import Task

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
        # Positions computed so every button has exactly 0.015 gap to its neighbour.
        # Menu(0.110w) | Edit(0.150w) | +Brick(0.150w) | Move(0.120w) |
        # Scale(0.120w) | Export(0.130w) | Import(0.130w) | Save(0.110w)
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
            pos=(0.215, 0, BZ),
            command=self.toggle_mode,
            **kw,
        )
        self.insert_brick_button = DirectButton(
            text="+ Brick",
            frameSize=(-0.075, 0.075, -0.032, 0.032),
            pos=(0.380, 0, BZ),
            command=self.insert_brick,
            **kw,
        )
        self.move_button = DirectButton(
            text="Move",
            frameSize=(-0.060, 0.060, -0.032, 0.032),
            pos=(0.530, 0, BZ),
            command=self.toggle_move_mode,
            **kw,
        )
        self.scale_button = DirectButton(
            text="Scale",
            frameSize=(-0.060, 0.060, -0.032, 0.032),
            pos=(0.665, 0, BZ),
            command=self.toggle_scale_mode,
            **kw,
        )
        self.export_button = DirectButton(
            text="Export",
            frameSize=(-0.065, 0.065, -0.032, 0.032),
            pos=(0.805, 0, BZ),
            command=self.export_build,
            **kw,
        )
        self.import_button = DirectButton(
            text="Import",
            frameSize=(-0.065, 0.065, -0.032, 0.032),
            pos=(0.950, 0, BZ),
            command=self.import_build,
            **kw,
        )
        self.cloud_save_button = DirectButton(
            text="Save",
            frameSize=(-0.055, 0.055, -0.032, 0.032),
            pos=(1.085, 0, BZ),
            command=self.cloud_save_build,
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
                  self.scale_button, self.export_button, self.import_button,
                  self.cloud_save_button):
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
        palette = [
            (1, 1, 1, 1),          (0.85, 0.85, 0.85, 1),
            (1, 0.15, 0.15, 1),    (0.15, 0.85, 0.15, 1),
            (0.15, 0.35, 1, 1),    (1, 1, 0.1, 1),
            (1, 0.1, 1, 1),        (0.1, 1, 1, 1),
            (0.55, 0.28, 0.08, 1), (0.55, 0.55, 0.55, 1),
            (0.22, 0.22, 0.22, 1), (0, 0, 0, 1),
            (0.42, 0.78, 0.28, 1),  # baseplate grass default
        ]
        cols = 6
        cw, gap = 0.054, 0.006
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
        num_rows     = (len(palette) + cols - 1) // cols
        reset_color_z = sz - (num_rows - 1) * (cw + gap) - 0.038
        _reset_color_btn = DirectButton(
            text="Reset Color", text_fg=TEXT, text_scale=0.028,
            frameColor=MED,
            frameSize=(-0.085, 0.085, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2, 0, reset_color_z),
            command=self.reset_brick_color,
        )

        # Texture section
        z_tex = reset_color_z - 0.055
        _texture_lbl = DirectLabel(
            text="Texture",
            text_fg=TEXT_D, text_scale=0.028,
            frameColor=(0, 0, 0, 0),
            parent=self._ins,
            pos=(-PW + 0.05, 0, z_tex),
        )
        z_tex_btns = z_tex - 0.042
        _plastic_btn = DirectButton(
            text="Plastic", text_fg=TEXT, text_scale=0.028,
            frameColor=MED,
            frameSize=(-0.082, 0.082, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 - 0.09, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['plastic'],
        )
        _grass_btn = DirectButton(
            text="Grass", text_fg=TEXT, text_scale=0.028,
            frameColor=MED,
            frameSize=(-0.082, 0.082, -0.018, 0.018),
            parent=self._ins,
            pos=(-PW / 2 + 0.09, 0, z_tex_btns),
            command=self.apply_texture_to_selected_brick,
            extraArgs=['grass'],
        )

        self._ins.hide()

        self.ui_elements += [
            self._ins, self._ins_none, self.selected_brick_label,
            _color_lbl, _reset_color_btn,
            _texture_lbl, _plastic_btn, _grass_btn,
        ] + _palette_btns

    # ── Inspector visibility ───────────────────────────────────────────────

    def _show_inspector(self, brick):
        pos = brick.getPos()
        self.selected_brick_label['text'] = (
            f"({pos.x:.1f}, {pos.y:.1f}, {pos.z:.1f})"
        )
        self._ins_none.hide()
        self._ins.show()
        self._refresh_hierarchy()

    def _hide_inspector(self):
        self._ins.hide()
        self._ins_none.show()
        self.selected_brick_label['text'] = ""
        self._refresh_hierarchy()

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
            sel   = (brick is self.selected_brick)
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
            )
            self._h_btns[brick] = btn

    def _on_hierarchy_click(self, brick):
        if self.is_playtest:
            return
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
        if self.selected_brick:
            self.apply_color_to_brick(self.selected_brick, color)

    def apply_color_to_brick(self, brick, color):
        self.brick_colors[brick] = color
        if brick in self.brick_grass_shells:
            shell = self.brick_grass_shells[brick]
            if shell and not shell.isEmpty():
                from panda3d.core import Vec4
                shell.setShaderInput('brickColor', Vec4(*color))
            self.brick_grass_color[brick] = color
            return
        if brick in self.brick_hitbox_visuals:
            try:
                self.brick_hitbox_visuals[brick].setColor(*color)
            except Exception:
                pass
        try:
            brick.setColor(*color)
            brick.hide()
        except Exception:
            pass

    def reset_brick_color(self):
        if not self.selected_brick:
            return
        if self.selected_brick in self.brick_grass_shells:
            self.apply_color_to_brick(self.selected_brick, (0.42, 0.78, 0.28, 1.0))
        else:
            self.apply_color_to_brick(self.selected_brick, (0.5, 0.5, 0.5, 0.7))

    def apply_texture_to_selected_brick(self, texture_name):
        if self.selected_brick:
            self.apply_texture_to_brick(self.selected_brick, texture_name)

    def apply_texture_to_brick(self, brick, texture_name):
        if texture_name == 'plastic':
            shell = self.brick_grass_shells.pop(brick, None)
            if shell and not shell.isEmpty():
                shell.removeNode()
            self.brick_grass_color.pop(brick, None)
            self.brick_last_scale.pop(brick, None)
            self.brick_last_pos.pop(brick, None)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.show()
        elif texture_name == 'grass':
            if brick not in self.brick_grass_color:
                self.brick_grass_color[brick] = (0.40, 0.80, 0.55, 1.0)
            self._rebuild_grass_shell(brick)
            visual = self.brick_hitbox_visuals.get(brick)
            if visual and not visual.isEmpty():
                visual.hide()

    def reset_brick_scaling(self):
        if not self.selected_brick:
            return
        default = self.brick_default_scale.get(self.selected_brick)
        if default:
            self.selected_brick.setScale(default)
        if self.selected_brick in self.brick_hitbox_visuals:
            self.update_brick_hitbox_visual_scale(
                self.selected_brick, self.brick_hitbox_visuals[self.selected_brick])
        self.create_scale_handles()

    def close_scale_controls(self):
        self.is_scale_mode = False
        self.clear_selection()

    def _on_window_event(self, window):
        # Only the background bar width needs updating; buttons and status
        # label are edge-anchored and reposition automatically.
        ar = base.getAspectRatio()
        self._top_bg['frameSize'] = (0, 2 * ar, -TH, 0)

    def _on_wheel(self, direction):
        if self.is_playtest:
            self.zoom_camera(direction)
        else:
            if direction > 0:
                self._scroll_up()
            else:
                self._scroll_down()

    # ── Mode toggles ───────────────────────────────────────────────────────

    def toggle_scale_mode(self):
        self.is_scale_mode = not self.is_scale_mode
        self.is_move_mode  = False
        self.move_button['text'] = "Move"
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

    def toggle_move_mode(self):
        self.is_move_mode  = not self.is_move_mode
        self.is_scale_mode = False
        self.scale_button['text'] = "Scale"
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
            # Switched TO play mode
            self.spawn_unstuck()
            self.character.show()
            self.exit_button['text'] = "Edit"   # clicking will go to editor
            self._panel.hide()
            for w in (self.insert_brick_button, self.move_button,
                      self.scale_button, self.export_button, self.import_button,
                      self.cloud_save_button):
                w.hide()
            self.clear_selection()
            self.is_move_mode  = False
            self.is_scale_mode = False
            self.move_button['text']  = "Move"
            self.scale_button['text'] = "Scale"
            self.cam_distance = 20
            self.cam_angle.set(0, 20)
            self.camLens.setFov(60)
        else:
            # Switched TO editor mode
            self.character.hide()
            self.exit_button['text'] = "Play"   # clicking will go to play
            self._panel.show()
            for w in (self.insert_brick_button, self.move_button,
                      self.scale_button, self.export_button, self.import_button,
                      self.cloud_save_button):
                w.show()
            self.shift_lock = False
            if self.is_rotating:
                self.is_rotating = False
            props = WindowProperties()
            props.setCursorHidden(False)
            self.win.requestProperties(props)
            self.camera.setPos(0, -30, 18)
            self.camera.lookAt(Point3(0, 0, 1))
            self.camLens.setFov(80)
