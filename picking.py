from panda3d.core import (
    CardMaker, TransparencyAttrib, CollisionNode, CollisionBox,
    BitMask32, Point3, Vec3, LineSegs, NodePath,
)
from direct.task import Task

BLUE = (0.20, 0.45, 0.95, 0.95)


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
        elif self.is_move_mode:
            for e in entries:
                np = e.getIntoNodePath().getParent()
                if np.hasTag("handle"):
                    self.start_drag(np, np.getTag("handle_axis"))
                    return

        # Brick click — unified selection, mode determines which handles appear.
        # Use the canonical wrapper from self.bricks so identity comparisons
        # in _refresh_hierarchy (brick is self.selected_brick) stay correct.
        for e in entries:
            np = e.getIntoNodePath()
            while not np.isEmpty() and np != self.render:
                if np in self.bricks:
                    canonical = next(b for b in self.bricks if b == np)
                    self.select_brick(canonical)
                    return
                np = np.getParent()
        self.clear_selection()

    def on_mouse1_up(self):
        self.dragging = False
        self.scale_dragging = False
        self.drag_handle = None

    # ── Brick selection ───────────────────────────────────────────────────

    def select_brick(self, brick):
        """Select a brick and show the gizmo matching the current active mode.

        Move mode  → move handles
        Scale mode → scale handles
        No mode    → green outline only, no handles
        """
        if brick is self.selected_brick:
            return
        self.clear_selection()
        self.selected_brick = brick
        self._create_selection_outline(brick)
        if self.is_move_mode:
            self.create_move_handles()
        elif self.is_scale_mode:
            self.create_scale_handles()
        self._show_inspector(brick)

    def clear_selection(self):
        if self.selected_brick:
            for h in self.move_handles:
                h['node'].removeNode()
            self.move_handles.clear()
            for h in self.scale_handles:
                h['node'].removeNode()
            self.scale_handles.clear()
            self._remove_selection_outline()
            self.selected_brick = None
            self._hide_inspector()
        self.dragging = False
        self.scale_dragging = False
        self.drag_handle = None

    # ── Selection outline ─────────────────────────────────────────────────

    def _create_selection_outline(self, brick):
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
        self._update_selection_outline(brick)

    def _update_selection_outline(self, brick):
        if not getattr(self, '_sel_outline', None):
            return
        try:
            if self._sel_outline.isEmpty():
                return
        except Exception:
            return
        box = self.get_brick_collision_box(brick)
        m = 0.15
        self._sel_outline.setPos(box['center'].x, box['center'].y, box['center'].z)
        self._sel_outline.setScale(
            box['half_width']  + m,
            box['half_depth']  + m,
            box['half_height'] + m,
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
        if not self.selected_brick:
            return
        visual = self.brick_hitbox_visuals.get(self.selected_brick)
        try:
            min_b, max_b = (visual.getTightBounds(self.render)
                            if visual and not visual.isEmpty()
                            else self.selected_brick.getTightBounds(self.render))
        except Exception:
            min_b, max_b = self.selected_brick.getTightBounds(self.render)

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
        cm.setFrame(-0.12, 0.12, -0.12, 0.12)
        hnp = self.render.attachNewNode(cm.generate())
        hnp.setPos(pos)
        hnp.setColor(*color)
        hnp.setTransparency(TransparencyAttrib.MAlpha)
        hnp.setBillboardPointEye()
        cnode = CollisionNode(f"{name}_col")
        cnode.addSolid(CollisionBox(Point3(0, 0, 0), 0.2, 0.2, 0.2))
        cnode.setIntoCollideMask(BitMask32.bit(1))
        cnode.setFromCollideMask(BitMask32.allOff())
        hnp.attachNewNode(cnode)
        return hnp

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
        brick  = self.selected_brick
        ss     = self.scale_drag_start_scale   # Vec3 — brick scale at drag start
        sp     = self.scale_drag_start_pos     # Vec3 — brick pos at drag start
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

        # Each face handle owns one axis.  Positive delta always means "grow".
        # For the negative-direction handles the face that moves is the origin
        # face, so we also slide the brick's position to keep the opposite face
        # stationary.
        if axkey == 'x':
            new_bx      = max(min_sz, ss.x + delta)
            actual_grow = new_bx - ss.x
            brick.setScale(new_bx, ss.y, ss.z)
            if axis.x < 0:   # left face: move origin left
                brick.setPos(sp.x - actual_grow, sp.y, sp.z)

        elif axkey == 'y':
            new_by      = max(min_sz, ss.y + delta)
            actual_grow = new_by - ss.y
            brick.setScale(ss.x, new_by, ss.z)
            if axis.y < 0:   # front face: move origin forward
                brick.setPos(sp.x, sp.y - actual_grow, sp.z)

        else:  # 'z'
            new_bz      = max(min_sz, ss.z + delta)
            actual_grow = new_bz - ss.z
            brick.setScale(ss.x, ss.y, new_bz)
            if axis.z < 0:   # bottom face: move origin down
                brick.setPos(sp.x, sp.y, sp.z - actual_grow)

        # Sync the visual; collision auto-updates because cnode is parented to brick.
        if brick in self.brick_hitbox_visuals:
            self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])

    # ── Update task ───────────────────────────────────────────────────────

    def updateHandlesTask(self, task):
        if self.selected_brick:
            # Move handles: follow visual bounds
            if self.move_handles:
                visual = self.brick_hitbox_visuals.get(self.selected_brick)
                try:
                    min_b, max_b = (visual.getTightBounds(self.render)
                                    if visual and not visual.isEmpty()
                                    else self.selected_brick.getTightBounds(self.render))
                except Exception:
                    min_b, max_b = self.selected_brick.getTightBounds(self.render)
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

            # Scale handles: follow collision box
            if self.scale_handles:
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

            # Selection outline
            self._update_selection_outline(self.selected_brick)

        if self.dragging and self.drag_handle and self.selected_brick:
            self.update_drag()
        if self.scale_dragging and self.drag_handle and self.selected_brick:
            self.update_scale_drag()
        return Task.cont

    # ── Move dragging ─────────────────────────────────────────────────────

    def start_drag(self, handle_np, axis_str):
        ax = [float(v) for v in axis_str.split(",")]
        self.dragging = True
        self.drag_handle = {'node': handle_np, 'axis': Vec3(*ax)}
        self.drag_start_brick_pos = self.selected_brick.getPos(self.render)
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
            new_pos = self.drag_start_brick_pos + Vec3(0, 0, cur.z - self.drag_start_mouse_world.z)
            self.selected_brick.setPos(new_pos)
        else:
            cur = self._mouse_world_point_at_z(self.drag_start_brick_pos.z)
            if not cur:
                return
            axis_xy = Vec3(axis.x, axis.y, 0)
            new_pos = self.drag_start_brick_pos + axis_xy.normalized() * (cur - self.drag_start_mouse_world).dot(axis_xy)
            self.selected_brick.setPos(new_pos)
        if self.selected_brick in self.brick_hitbox_visuals:
            self.update_brick_hitbox_visual_scale(
                self.selected_brick, self.brick_hitbox_visuals[self.selected_brick])

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
