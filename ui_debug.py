import tkinter as tk
from direct.task import Task


class UIDebugMixin:
    """Developer tool: hold Ctrl to drag-reposition UI elements.

    Ctrl held
      - All widget commands are suspended (buttons won't fire).
      - Click and drag any widget to reposition it.
      - Releases snap to a 0.01-unit grid.

    Alt pressed while Ctrl held
      - Copies the last dragged widget's layout data to clipboard.

    Ctrl released
      - All commands restored; drag highlight cleared; normal mode resumes.
    """

    def setup_ui_debug(self):
        self._ctrl_held          = False
        self._drag_widget        = None
        self._drag_start_pos     = None   # widget pos (local to parent) at drag start
        self._drag_start_mouse   = None   # (mx, my) in aspect2d at drag start
        self._last_selected      = None   # last widget touched (for ALT copy)
        self._last_sel_color_bak = None
        self._saved_commands     = {}     # id(w) -> (w, cmd, extraArgs)
        self._drag_grid          = 0.01   # snap grid in aspect2d units

        self.accept("lcontrol",    self._ui_debug_on)
        self.accept("lcontrol-up", self._ui_debug_off)
        self.accept("lalt",        self._ui_debug_copy)

    # ── Mouse helpers ─────────────────────────────────────────────────────────

    def _ui_mouse_a2d(self):
        """Return current mouse position in aspect2d units, or None."""
        if not self.mouseWatcherNode.hasMouse():
            return None
        m  = self.mouseWatcherNode.getMouse()
        ar = self.getAspectRatio()
        return (m.x * ar, m.y)

    def _ui_find_widget(self):
        """AABB hit-test all registered widgets; return topmost hit or None."""
        pos = self._ui_mouse_a2d()
        if pos is None:
            return None
        mx, my = pos

        # Reverse iteration: last widget in the list is drawn on top.
        for widget in reversed(self.ui_elements):
            try:
                wp = widget.getPos(base.aspect2d)   # world pos in aspect2d space
                fs = widget['frameSize']             # (left, right, bottom, top)
                if (wp.x + fs[0] <= mx <= wp.x + fs[1] and
                        wp.z + fs[2] <= my <= wp.z + fs[3]):
                    return widget
            except Exception:
                pass
        return None

    @staticmethod
    def _snap(value, grid):
        if grid <= 0:
            return value
        return round(value / grid) * grid

    # ── Ctrl on / off ─────────────────────────────────────────────────────────

    def _ui_debug_on(self):
        self._ctrl_held = True
        self._saved_commands.clear()

        # Nullify every widget command so buttons don't fire while dragging.
        for widget in list(self.ui_elements):
            try:
                cmd = widget['command']
                try:
                    extra = list(widget['extraArgs'] or [])
                except Exception:
                    extra = []
                self._saved_commands[id(widget)] = (widget, cmd, extra)
                widget['command']   = None
                widget['extraArgs'] = []
            except Exception:
                pass  # widget has no command — fine, leave it

        # Take over mouse1 so 3D picking is suppressed and we detect drags.
        self.accept("mouse1",    self._ui_debug_mouse_down)
        self.accept("mouse1-up", self._ui_debug_mouse_up)
        self.taskMgr.add(self._ui_debug_drag_task, "uiDebugDragTask")
        print("[UIDebug] Ctrl held — drag mode active")

    def _ui_debug_off(self):
        self._ctrl_held = False

        self.taskMgr.remove("uiDebugDragTask")
        self._drag_widget      = None
        self._drag_start_pos   = None
        self._drag_start_mouse = None

        # Restore all widget commands.
        for _, (widget, cmd, extra) in self._saved_commands.items():
            try:
                widget['command']   = cmd
                widget['extraArgs'] = extra
            except Exception:
                pass
        self._saved_commands.clear()

        # Hand mouse1 back to the game.
        self.accept("mouse1",    self.on_mouse1_down)
        self.accept("mouse1-up", self.on_mouse1_up)

        self._ui_debug_clear_highlight()
        print("[UIDebug] Ctrl released — normal mode restored")

    # ── Drag ─────────────────────────────────────────────────────────────────

    def _ui_debug_mouse_down(self):
        widget = self._ui_find_widget()
        if widget is None:
            return

        self._ui_debug_clear_highlight()
        self._last_selected = widget
        try:
            self._last_sel_color_bak = widget['frameColor']
            widget['frameColor'] = (1.0, 0.75, 0.0, 0.95)   # yellow
        except Exception:
            self._last_sel_color_bak = None

        self._drag_widget      = widget
        self._drag_start_pos   = widget.getPos()              # local to parent
        self._drag_start_mouse = self._ui_mouse_a2d()
        print(f"[UIDebug] Dragging: {widget.getName()}")

    def _ui_debug_mouse_up(self):
        if self._drag_widget is not None:
            p = self._drag_widget.getPos()
            print(f"[UIDebug] Dropped at ({p.x:.4f}, {p.z:.4f})")
        self._drag_widget      = None
        self._drag_start_pos   = None
        self._drag_start_mouse = None

    def _ui_debug_drag_task(self, task):
        if self._drag_widget is None or self._drag_start_mouse is None:
            return Task.cont

        cur = self._ui_mouse_a2d()
        if cur is None:
            return Task.cont

        # Delta in aspect2d space equals delta in parent-local space because
        # all our GUI parents (aspect2d, a2dTopRight, …) share the same
        # orientation and scale — only their origin differs.
        dx = cur[0] - self._drag_start_mouse[0]
        dy = cur[1] - self._drag_start_mouse[1]

        new_x = self._snap(self._drag_start_pos.x + dx, self._drag_grid)
        new_z = self._snap(self._drag_start_pos.z + dy, self._drag_grid)
        self._drag_widget.setPos(new_x, self._drag_start_pos.y, new_z)
        return Task.cont

    # ── Highlight helpers ─────────────────────────────────────────────────────

    def _ui_debug_clear_highlight(self):
        if self._last_selected is not None and self._last_sel_color_bak is not None:
            try:
                self._last_selected['frameColor'] = self._last_sel_color_bak
            except Exception:
                pass
        self._last_selected      = None
        self._last_sel_color_bak = None

    # ── Alt → copy layout info to clipboard ──────────────────────────────────

    def _ui_debug_copy(self):
        if not self._ctrl_held:
            return
        w = self._last_selected
        if w is None:
            print("[UIDebug] No widget selected — nothing to copy")
            return
        try:
            pos   = w.getPos()
            name  = w.getName()
            par   = w.getParent()
            pname = par.getName() if (par and not par.isEmpty()) else "unknown"

            try:
                fs = w['frameSize']
                size_str = (f"  FrameSize = ({fs[0]:.4f}, {fs[1]:.4f}, "
                            f"{fs[2]:.4f}, {fs[3]:.4f})\n"
                            f"  Width = {fs[1]-fs[0]:.4f}, "
                            f"Height = {fs[3]-fs[2]:.4f}\n")
            except Exception:
                size_str = "  FrameSize = (unknown)\n"

            text = (
                f"UI_ELEMENT: {name}\n"
                f"  Position = ({pos.x:.4f}, {pos.z:.4f})\n"
                + size_str +
                f"  Parent = {pname}\n"
            )

            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
            print("[UIDebug] Copied to clipboard:\n" + text)
        except Exception as e:
            print(f"[UIDebug] Copy failed: {e}")
