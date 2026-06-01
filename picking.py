from panda3d.core import (
    CardMaker, TransparencyAttrib, CollisionNode, CollisionBox,
    BitMask32, Point3, Vec3, LineSegs, NodePath, KeyboardButton,
)
from direct.task import Task

BLUE  = (0.20, 0.45, 0.95, 0.95)
GREEN = (0.10, 0.80, 0.20, 0.95)


class PickingMixin:
    def update_picker_ray(self):
        if not self.mouseWatcherNode.hasMouse():
            return False
        mpos = self.mouseWatcherNode.getMouse()
        self.pickerRay.setFromLens(self.camNode, mpos.getX(), mpos.getY())
        return True

    def pick_collisions(self):
        self.pq.clearEntries()
        self.picker.traverse(self.render)
        entries = [self.pq.getEntry(i) for i in range(self.pq.getNumEntries())]
        cam_pos = self.camera.getPos(self.render)
        entries.sort(key=lambda e: (e.getSurfacePoint(self.render) - cam_pos).lengthSquared())
        return entries

    # ── Mouse events ──────────────────────────────────────────────────────

    def on_mouse1_down(self):
        if self.is_playtest:
            return
        if not self.update_picker_ray():
            return
        entries = self.pick_collisions()

        # Active-mode handles take priority over brick selection.
        if self.is_scale_mode:
            for e in entries:
                np = e.getIntoNodePath().getParent()
                if np.hasTag("scale_handle"):
                    self.start_scale_drag(np, np.getTag("scale_axis"), np.getTag("scale_key"))
                    return
        elif self.is_rotate_mode:
            for e in entries:
                np = e.getIntoNodePath().getParent()
                if np.hasTag("rotate_handle"):
                    self.start_rotate_drag(np, np.getTag("rotate_axis"), np.getTag("rotate_key"))
                    return
        elif self.is_move_mode:
            for e in entries:
                np = e.getIntoNodePath().getParent()
                if np.hasTag("handle"):
                    self.start_drag(np, np.getTag("handle_axis"))
                    return

        # Brick click — unified selection, mode determines which handles appear.
        # Use the canonical wrapper from self.bricks so identity comparisons
        # in _refresh_hierarchy (brick in self.selected_bricks) stay correct.
        shift_held = (self.mouseWatcherNode.isButtonDown(KeyboardButton.lshift()) or
                      self.mouseWatcherNode.isButtonDown(KeyboardButton.rshift()))
        for e in entries:
            np = e.getIntoNodePath()
            while not np.isEmpty() and np != self.render:
                if np in self.bricks:
                    canonical = next(b for b in self.bricks if b == np)
                    if shift_held:
                        self._toggle_brick_selection(canonical)
                    else:
                        self.select_brick(canonical)
                    return
                np = np.getParent()
        if not shift_held:
            self.clear_selection()

    def on_mouse1_up(self):
        was_dragging        = self.dragging
        was_scale_dragging  = self.scale_dragging
        was_rotate_dragging = self.rotate_dragging
        self.dragging        = False
        self.scale_dragging  = False
        self.rotate_dragging = False
        self.drag_handle     = None

        if was_dragging and self.drag_start_brick_positions:
            start_positions = dict(self.drag_start_brick_positions)
            def undo_move(sp=start_positions):
                for b, pos in sp.items():
                    if b in self.bricks:
                        b.setPos(pos)
                        if b in self.brick_hitbox_visuals:
                            self.update_brick_hitbox_visual_scale(
                                b, self.brick_hitbox_visuals[b])
            self._push_undo(undo_move)

        if was_scale_dragging and self.scale_drag_start_all:
            all_starts = dict(self.scale_drag_start_all)
            def undo_scale(starts=all_starts):
                for b, (s, p) in starts.items():
                    if b in self.bricks:
                        b.setScale(s)
                        b.setPos(p)
                        if b in self.brick_hitbox_visuals:
                            self.update_brick_hitbox_visual_scale(
                                b, self.brick_hitbox_visuals[b])
                self.create_scale_handles()
            self._push_undo(undo_scale)

        if was_rotate_dragging and self.rotate_drag_start_hpr:
            all_starts = dict(self.rotate_drag_start_hpr)
            def undo_rotate(starts=all_starts):
                for b, hpr in starts.items():
                    if b in self.bricks:
                        b.setHpr(hpr)
                self.create_rotate_handles()
            self._push_undo(undo_rotate)

    # ── Brick selection ───────────────────────────────────────────────────

    def select_brick(self, brick):
        """Select a single brick, replacing any existing selection."""
        if len(self.selected_bricks) == 1 and self.selected_bricks[0] is brick:
            return
        self.clear_selection()
        self.selected_brick  = brick
        self.selected_bricks = [brick]
        self._create_selection_outline()
        if self.is_move_mode:
            self.create_move_handles()
        elif self.is_scale_mode:
            self.create_scale_handles()
        elif self.is_rotate_mode:
            self.create_rotate_handles()
        self._show_inspector(brick)

    def _toggle_brick_selection(self, brick):
        """Add brick to selection or remove it if already selected (shift-click)."""
        if brick in self.selected_bricks:
            self.selected_bricks.remove(brick)
            if not self.selected_bricks:
                self.clear_selection()
                return
            self.selected_brick = self.selected_bricks[-1]
        else:
            self.selected_bricks.append(brick)
            self.selected_brick = brick
        self._remove_selection_outline()
        self._create_selection_outline()
        if self.is_move_mode:
            for h in self.move_handles:
                h['node'].removeNode()
            self.move_handles.clear()
            self.create_move_handles()
        if len(self.selected_bricks) == 1:
            self._show_inspector(self.selected_bricks[0])
        else:
            self._show_inspector_multi(len(self.selected_bricks))
        self._refresh_hierarchy()

    def clear_selection(self):
        if self.selected_bricks:
            for h in self.move_handles:
                h['node'].removeNode()
            self.move_handles.clear()
            for h in self.scale_handles:
                h['node'].removeNode()
            self.scale_handles.clear()
            for h in self.rotate_handles:
                h['node'].removeNode()
            self.rotate_handles.clear()
            self._remove_selection_outline()
            self.selected_bricks = []
            self.selected_brick  = None
            self._hide_inspector()
        self.dragging = False
        self.scale_dragging = False
        self.drag_handle = None

    # ── Selection outline ─────────────────────────────────────────────────

    def _get_combined_bounds(self):
        """Return (min_point, max_point) enclosing all selected bricks."""
        all_min = all_max = None
        for brick in self.selected_bricks:
            try:
                if brick.isEmpty():
                    continue
            except Exception:
                continue
            visual = self.brick_hitbox_visuals.get(brick)
            try:
                if visual and not visual.isEmpty():
                    min_b, max_b = visual.getTightBounds(self.render)
                else:
                    min_b, max_b = brick.getTightBounds(self.render)
            except Exception:
                try:
                    min_b, max_b = brick.getTightBounds(self.render)
                except Exception:
                    continue
            if all_min is None:
                all_min = Point3(min_b)
                all_max = Point3(max_b)
            else:
                all_min = Point3(min(all_min.x, min_b.x),
                                 min(all_min.y, min_b.y),
                                 min(all_min.z, min_b.z))
                all_max = Point3(max(all_max.x, max_b.x),
                                 max(all_max.y, max_b.y),
                                 max(all_max.z, max_b.z))
        return all_min, all_max

    def _create_selection_outline(self):
        self._remove_selection_outline()
        ls = LineSegs("sel_outline")
        ls.setColor(0.1, 0.95, 0.2, 1.0)
        ls.setThickness(3.0)
        c = [
            (-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
            (-1,-1, 1),(1,-1, 1),(1,1, 1),(-1,1, 1),
        ]
        for i, j in [(0,1),(1,2),(2,3),(3,0),
                     (4,5),(5,6),(6,7),(7,4),
                     (0,4),(1,5),(2,6),(3,7)]:
            ls.moveTo(*c[i])
            ls.drawTo(*c[j])
        self._sel_outline = NodePath(ls.create())
        self._sel_outline.reparentTo(self.render)
        self._sel_outline.setLightOff()
        self._sel_outline.setShaderOff()
        self._sel_outline.setBin("transparent", 5)
        self._sel_outline.setDepthWrite(False)
        self._update_selection_outline()

    def _update_selection_outline(self):
        if not getattr(self, '_sel_outline', None):
            return
        try:
            if self._sel_outline.isEmpty():
                return
        except Exception:
            return
        # Purge any bricks whose NodePath has been destroyed.
        live = []
        for b in self.selected_bricks:
            try:
                if not b.isEmpty():
                    live.append(b)
            except Exception:
                pass
        if len(live) != len(self.selected_bricks):
            self.selected_bricks = live
            self.selected_brick = live[-1] if live else None
            if not live:
                self.clear_selection()
                return
        min_b, max_b = self._get_combined_bounds()
        if min_b is None:
            return
        cx = (min_b.x + max_b.x) / 2
        cy = (min_b.y + max_b.y) / 2
        cz = (min_b.z + max_b.z) / 2
        m  = 0.15
        self._sel_outline.setPos(cx, cy, cz)
        self._sel_outline.setScale(
            (max_b.x - min_b.x) / 2 + m,
            (max_b.y - min_b.y) / 2 + m,
            (max_b.z - min_b.z) / 2 + m,
        )

    def _remove_selection_outline(self):
        outline = getattr(self, '_sel_outline', None)
        if outline is not None:
            try:
                if not outline.isEmpty():
                    outline.removeNode()
            except Exception:
                pass
        self._sel_outline = None

    # ── Move handles ──────────────────────────────────────────────────────

    def create_move_handles(self):
        if not self.selected_bricks:
            return
        min_b, max_b = self._get_combined_bounds()
        if min_b is None:
            return
        cx = (min_b.x + max_b.x) / 2
        cy = (min_b.y + max_b.y) / 2
        cz = (min_b.z + max_b.z) / 2
        mg = max(max_b.x - min_b.x, max_b.y - min_b.y, max_b.z - min_b.z) * 0.05 + 0.12

        defs = [
            ((max_b.x+mg, cy, cz), Vec3( 1,0,0), (1,0,0,0.95)),
            ((min_b.x-mg, cy, cz), Vec3(-1,0,0), (1,0,0,0.95)),
            ((cx, max_b.y+mg, cz), Vec3(0, 1,0), (0,1,0,0.95)),
            ((cx, min_b.y-mg, cz), Vec3(0,-1,0), (0,1,0,0.95)),
            ((cx, cy, max_b.z+mg), Vec3(0,0, 1), (0,0,1,0.95)),
            ((cx, cy, min_b.z-mg), Vec3(0,0,-1), (0,0,1,0.95)),
        ]
        for idx, (pos, axis, col) in enumerate(defs):
            hnp = self._make_handle(f"handle_{idx}", pos, col)
            hnp.setTag("handle", "1")
            hnp.setTag("handle_axis", f"{axis.x},{axis.y},{axis.z}")
            self.move_handles.append({'node': hnp, 'axis': axis})

    # ── Scale handles ─────────────────────────────────────────────────────

    def create_scale_handles(self):
        for h in self.scale_handles:
            h['node'].removeNode()
        self.scale_handles.clear()
        if not self.selected_brick:
            return

        box = self.get_brick_collision_box(self.selected_brick)
        cx, cy, cz = box['center'].x, box['center'].y, box['center'].z
        hw, hd, hh = box['half_width'], box['half_depth'], box['half_height']
        mg = max(hw, hd, hh) * 0.05 + 0.12

        # key is the axis name ('x', 'y', 'z'); axis is the outward direction.
        defs = [
            ((cx+hw+mg, cy, cz), Vec3( 1, 0, 0), 'x'),
            ((cx-hw-mg, cy, cz), Vec3(-1, 0, 0), 'x'),
            ((cx, cy+hd+mg, cz), Vec3(0,  1, 0), 'y'),
            ((cx, cy-hd-mg, cz), Vec3(0, -1, 0), 'y'),
            ((cx, cy, cz+hh+mg), Vec3(0, 0,  1), 'z'),
            ((cx, cy, cz-hh-mg), Vec3(0, 0, -1), 'z'),
        ]
        for idx, (pos, axis, key) in enumerate(defs):
            hnp = self._make_handle(f"scale_handle_{idx}", pos, BLUE)
            hnp.setTag("scale_handle", "1")
            hnp.setTag("scale_axis",   f"{axis.x},{axis.y},{axis.z}")
            hnp.setTag("scale_key",    key)
            self.scale_handles.append({'node': hnp, 'axis': axis, 'key': key})

    def _make_handle(self, name, pos, color):
        cm = CardMaker(name)
        cm.setFrame(-0.2, 0.2, -0.2, 0.2)
        hnp = self.render.attachNewNode(cm.generate())
        hnp.setPos(pos)
        hnp.setColor(*color)
        hnp.setTransparency(TransparencyAttrib.MAlpha)
        hnp.setBillboardPointEye()
        cnode = CollisionNode(f"{name}_col")
        cnode.addSolid(CollisionBox(Point3(0, 0, 0), 0.35, 0.35, 0.35))
        cnode.setIntoCollideMask(BitMask32.bit(1))
        cnode.setFromCollideMask(BitMask32.allOff())
        hnp.attachNewNode(cnode)
        return hnp

    # ── Rotate handles ────────────────────────────────────────────────────

    def create_rotate_handles(self):
        for h in self.rotate_handles:
            h['node'].removeNode()
        self.rotate_handles.clear()
        if not self.selected_brick:
            return
        box = self.get_brick_collision_box(self.selected_brick)
        cx, cy, cz = box['center'].x, box['center'].y, box['center'].z
        hw, hd, hh = box['half_width'], box['half_depth'], box['half_height']
        mg = max(hw, hd, hh) * 0.05 + 0.28

        # top/bottom → heading (H, around Z); left/right → pitch (P); front/back → roll (R)
        defs = [
            ((cx,      cy,      cz+hh+mg), Vec3(0, 0,  1), 'h'),
            ((cx,      cy,      cz-hh-mg), Vec3(0, 0, -1), 'h'),
            ((cx+hw+mg,cy,      cz      ), Vec3( 1, 0, 0), 'p'),
            ((cx-hw-mg,cy,      cz      ), Vec3(-1, 0, 0), 'p'),
            ((cx,      cy+hd+mg,cz      ), Vec3(0,  1, 0), 'r'),
            ((cx,      cy-hd-mg,cz      ), Vec3(0, -1, 0), 'r'),
        ]
        for idx, (pos, axis, rot_key) in enumerate(defs):
            hnp = self._make_handle(f"rotate_handle_{idx}", pos, GREEN)
            hnp.setTag("rotate_handle", "1")
            hnp.setTag("rotate_axis",   f"{axis.x},{axis.y},{axis.z}")
            hnp.setTag("rotate_key",    rot_key)
            self.rotate_handles.append({'node': hnp, 'axis': axis, 'key': rot_key})

    # ── Rotate dragging ───────────────────────────────────────────────────

    def start_rotate_drag(self, handle_np, axis_str, rot_key):
        ax = [float(v) for v in axis_str.split(",")]
        self.rotate_dragging    = True
        self.rotate_drag_handle = {'node': handle_np, 'axis': Vec3(*ax), 'key': rot_key}
        self.rotate_drag_start_hpr = {b: Vec3(b.getHpr()) for b in self.selected_bricks}
        if self.mouseWatcherNode.hasMouse():
            m = self.mouseWatcherNode.getMouse()
            self.rotate_drag_start_mpos = (m.getX(), m.getY())
        else:
            self.rotate_drag_start_mpos = (0.0, 0.0)

    def update_rotate_drag(self):
        if not self.rotate_drag_handle or not self.rotate_drag_start_hpr:
            return
        if not self.mouseWatcherNode.hasMouse():
            return
        m  = self.mouseWatcherNode.getMouse()
        dx = m.getX() - self.rotate_drag_start_mpos[0]
        dy = m.getY() - self.rotate_drag_start_mpos[1]
        SENS = 270.0  # degrees per screen-width of drag
        rot_key = self.rotate_drag_handle['key']
        # H (yaw): drag left/right;  P (pitch): drag up/down;  R (roll): drag left/right
        if rot_key == 'p':
            delta = dy * SENS
        else:
            delta = dx * SENS
        # Snap to 5-degree grid
        delta = round(delta / 5) * 5
        for brick, start_hpr in self.rotate_drag_start_hpr.items():
            if brick not in self.bricks:
                continue
            if rot_key == 'h':
                brick.setHpr(start_hpr.x + delta, start_hpr.y, start_hpr.z)
            elif rot_key == 'p':
                brick.setHpr(start_hpr.x, start_hpr.y + delta, start_hpr.z)
            else:
                brick.setHpr(start_hpr.x, start_hpr.y, start_hpr.z + delta)
            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])

    # ── Scale dragging ────────────────────────────────────────────────────

    def start_scale_drag(self, handle_np, axis_str, scale_key):
        ax = [float(v) for v in axis_str.split(",")]
        axis = Vec3(*ax)
        self.scale_dragging = True
        self.drag_handle = {'node': handle_np, 'axis': axis, 'key': scale_key}

        brick = self.selected_brick
        s = brick.getScale()
        self.scale_drag_start_scale = Vec3(s.x, s.y, s.z)
        self.scale_drag_start_pos   = Vec3(brick.getPos())

        # Record start state for every selected brick (supports multi-select).
        self.scale_drag_start_all = {
            b: (Vec3(b.getScale()), Vec3(b.getPos()))
            for b in self.selected_bricks
        }

        # Fix a world-space reference point for the drag planes.
        box = self.get_brick_collision_box(brick)
        self.scale_drag_center = Vec3(box['center'])
        if abs(ax[2]) > 0.5:
            self.scale_drag_start_mouse = self._mouse_world_point_at_vertical_plane(self.scale_drag_center)
        else:
            self.scale_drag_start_mouse = self._mouse_world_point_at_z(self.scale_drag_center.z)

    def update_scale_drag(self):
        if not self.selected_brick or not self.drag_handle:
            return
        if not self.scale_drag_start_mouse:
            return

        axis   = self.drag_handle['axis']
        axkey  = self.drag_handle['key']
        min_sz = 0.5

        # Compute how far the mouse has moved along the handle's outward axis.
        if abs(axis.z) > 0.5:
            cur = self._mouse_world_point_at_vertical_plane(self.scale_drag_center)
            if not cur:
                return
            delta = (cur.z - self.scale_drag_start_mouse.z) * axis.z
        else:
            cur = self._mouse_world_point_at_z(self.scale_drag_center.z)
            if not cur:
                return
            delta = (cur - self.scale_drag_start_mouse).dot(Vec3(axis.x, axis.y, 0))

        # Apply the same delta to every selected brick using each brick's own start state.
        bricks_to_update = self.scale_drag_start_all if self.scale_drag_start_all else {
            self.selected_brick: (self.scale_drag_start_scale, self.scale_drag_start_pos)
        }
        for brick, (ss, sp) in bricks_to_update.items():
            if brick not in self.bricks:
                continue
            if axkey == 'x':
                new_bx      = max(min_sz, ss.x + delta)
                actual_grow = new_bx - ss.x
                brick.setScale(new_bx, ss.y, ss.z)
                if axis.x < 0:
                    brick.setPos(sp.x - actual_grow, sp.y, sp.z)

            elif axkey == 'y':
                new_by      = max(min_sz, ss.y + delta)
                actual_grow = new_by - ss.y
                brick.setScale(ss.x, new_by, ss.z)
                if axis.y < 0:
                    brick.setPos(sp.x, sp.y - actual_grow, sp.z)

            else:  # 'z'
                new_bz      = max(min_sz, ss.z + delta)
                actual_grow = new_bz - ss.z
                brick.setScale(ss.x, ss.y, new_bz)
                if axis.z < 0:
                    brick.setPos(sp.x, sp.y, sp.z - actual_grow)

            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])

    # ── Update task ───────────────────────────────────────────────────────

    def updateHandlesTask(self, task):
        if self.selected_bricks:
            # Move handles: follow combined visual bounds
            if self.move_handles:
                min_b, max_b = self._get_combined_bounds()
                if min_b is not None:
                    cx = (min_b.x + max_b.x) / 2
                    cy = (min_b.y + max_b.y) / 2
                    cz = (min_b.z + max_b.z) / 2
                    mg = max(max_b.x-min_b.x, max_b.y-min_b.y, max_b.z-min_b.z)*0.05+0.12
                    positions = [
                        (max_b.x+mg, cy, cz), (min_b.x-mg, cy, cz),
                        (cx, max_b.y+mg, cz), (cx, min_b.y-mg, cz),
                        (cx, cy, max_b.z+mg), (cx, cy, min_b.z-mg),
                    ]
                    for h, pos in zip(self.move_handles, positions):
                        h['node'].setPos(pos)

            # Scale handles: follow primary brick's collision box
            if self.scale_handles and self.selected_brick:
                box = self.get_brick_collision_box(self.selected_brick)
                cx, cy, cz = box['center'].x, box['center'].y, box['center'].z
                hw, hd, hh = box['half_width'], box['half_depth'], box['half_height']
                mg = max(hw, hd, hh)*0.05+0.12
                positions = [
                    (cx+hw+mg, cy, cz), (cx-hw-mg, cy, cz),
                    (cx, cy+hd+mg, cz), (cx, cy-hd-mg, cz),
                    (cx, cy, cz+hh+mg), (cx, cy, cz-hh-mg),
                ]
                for h, pos in zip(self.scale_handles, positions):
                    h['node'].setPos(pos)

            # Rotate handles: same layout as scale but track brick's AABB
            if self.rotate_handles and self.selected_brick:
                box = self.get_brick_collision_box(self.selected_brick)
                cx, cy, cz = box['center'].x, box['center'].y, box['center'].z
                hw, hd, hh = box['half_width'], box['half_depth'], box['half_height']
                mg = max(hw, hd, hh)*0.05+0.28
                positions = [
                    (cx, cy, cz+hh+mg), (cx, cy, cz-hh-mg),
                    (cx+hw+mg, cy, cz), (cx-hw-mg, cy, cz),
                    (cx, cy+hd+mg, cz), (cx, cy-hd-mg, cz),
                ]
                for h, pos in zip(self.rotate_handles, positions):
                    h['node'].setPos(pos)

            self._update_selection_outline()

        if self.dragging and self.drag_handle and self.selected_bricks:
            self.update_drag()
        if self.scale_dragging and self.drag_handle and self.selected_brick:
            self.update_scale_drag()
        if self.rotate_dragging and self.rotate_drag_handle and self.selected_brick:
            self.update_rotate_drag()
        return Task.cont

    # ── Move dragging ─────────────────────────────────────────────────────

    def start_drag(self, handle_np, axis_str):
        ax = [float(v) for v in axis_str.split(",")]
        self.dragging = True
        self.drag_handle = {'node': handle_np, 'axis': Vec3(*ax)}
        # Record starting positions for all selected bricks
        self.drag_start_brick_positions = {b: Vec3(b.getPos(self.render)) for b in self.selected_bricks}
        # Use primary brick as the reference point for drag plane
        self.drag_start_brick_pos = Vec3(self.selected_brick.getPos(self.render))
        if abs(ax[2]) > 0.5:
            self.drag_start_mouse_world = self._mouse_world_point_at_vertical_plane(self.drag_start_brick_pos)
        else:
            self.drag_start_mouse_world = self._mouse_world_point_at_z(self.drag_start_brick_pos.z)

    def update_drag(self):
        axis = self.drag_handle['axis']
        if abs(axis.z) > 0.5:
            cur = self._mouse_world_point_at_vertical_plane(self.drag_start_brick_pos)
            if not cur:
                return
            delta = Vec3(0, 0, cur.z - self.drag_start_mouse_world.z)
        else:
            cur = self._mouse_world_point_at_z(self.drag_start_brick_pos.z)
            if not cur:
                return
            axis_xy = Vec3(axis.x, axis.y, 0)
            d = axis_xy.normalized() * (cur - self.drag_start_mouse_world).dot(axis_xy)
            delta = Vec3(d.x, d.y, 0)
        for brick, start_pos in self.drag_start_brick_positions.items():
            brick.setPos(start_pos + delta)
            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])

    # ── Mouse raycasting ──────────────────────────────────────────────────

    def _mouse_world_point_at_vertical_plane(self, plane_point):
        if not self.update_picker_ray():
            return None
        mpos = self.mouseWatcherNode.getMouse()
        near, far = Point3(), Point3()
        if not self.cam.node().getLens().extrude(mpos, near, far):
            return None
        near_w = self.render.getRelativePoint(self.camera, near)
        far_w  = self.render.getRelativePoint(self.camera, far)
        d = far_w - near_w
        if d.lengthSquared() == 0:
            return None
        d.normalize()
        fwd = self.camera.getQuat().getForward()
        n = Vec3(fwd.x, fwd.y, 0)
        if n.lengthSquared() < 0.001:
            n = Vec3(0, 1, 0)
        n.normalize()
        denom = d.dot(n)
        if abs(denom) < 1e-6:
            return None
        t = (plane_point - near_w).dot(n) / denom
        if t < 0:
            return None
        return near_w + d * t

    def _mouse_world_point_at_z(self, z):
        if not self.update_picker_ray():
            return None
        mpos = self.mouseWatcherNode.getMouse()
        near, far = Point3(), Point3()
        if not self.cam.node().getLens().extrude(mpos, near, far):
            return None
        near_w = self.render.getRelativePoint(self.camera, near)
        far_w  = self.render.getRelativePoint(self.camera, far)
        d = far_w - near_w
        if d.lengthSquared() == 0 or abs(d.z) < 1e-6:
            return None
        d.normalize()
        t = (z - near_w.z) / d.z
        if t < 0:
            return None
        return near_w + d * t
