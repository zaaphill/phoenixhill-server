from panda3d.core import (
    CardMaker, TransparencyAttrib, CollisionNode, CollisionBox, CollisionSphere,
    BitMask32, Point3, Vec3, LineSegs, NodePath, KeyboardButton,
    GeomVertexFormat, GeomVertexData, GeomVertexWriter,
    Geom, GeomTriangles, GeomNode, Quat,
)
import math
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
                    self.start_rotate_drag(e.getIntoNodePath(),
                                           np.getTag("rotate_axis"),
                                           np.getTag("rotate_key"))
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
                        self._grid_update(b)
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
                        self._grid_update(b)
                self.create_scale_handles()
            self._push_undo(undo_scale)

        if was_rotate_dragging and self.rotate_drag_start_hpr:
            all_hpr = dict(self.rotate_drag_start_hpr)
            all_pos = dict(getattr(self, 'rotate_drag_start_pos', {}))
            def undo_rotate(hprs=all_hpr, poss=all_pos):
                for b, hpr in hprs.items():
                    if b in self.bricks:
                        b.setHpr(hpr)
                        if b in poss:
                            b.setPos(poss[b])
                        if b in self.brick_hitbox_visuals:
                            self.update_brick_hitbox_visual_scale(b, self.brick_hitbox_visuals[b])
                        self._grid_update(b)
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

    def _brick_world_aabb(self, brick):
        """Return (min_pt, max_pt) for a single brick using its transform matrix."""
        mat = brick.getMat()
        corners = [
            mat.xformPoint(Point3(x, y, z))
            for x in (0, 1) for y in (0, 1) for z in (0, 1)
        ]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        return Point3(min(xs), min(ys), min(zs)), Point3(max(xs), max(ys), max(zs))

    def _get_combined_bounds(self):
        """Return (min_point, max_point) enclosing all selected bricks."""
        all_min = all_max = None
        for brick in self.selected_bricks:
            try:
                if brick.isEmpty():
                    continue
            except Exception:
                continue
            min_b, max_b = self._brick_world_aabb(brick)
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
        m = 0.15
        if len(self.selected_bricks) == 1:
            # Single brick: oriented bounding box — outline rotates with the brick.
            brick = self.selected_bricks[0]
            s = brick.getScale()
            self._sel_outline.setPos(brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5)))
            self._sel_outline.setHpr(brick.getHpr())
            self._sel_outline.setScale(abs(s.x)/2 + m, abs(s.y)/2 + m, abs(s.z)/2 + m)
        else:
            # Multiple bricks: axis-aligned bounding box.
            min_b, max_b = self._get_combined_bounds()
            if min_b is None:
                return
            cx = (min_b.x + max_b.x) / 2
            cy = (min_b.y + max_b.y) / 2
            cz = (min_b.z + max_b.z) / 2
            self._sel_outline.setPos(cx, cy, cz)
            self._sel_outline.setHpr(0, 0, 0)
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

    def _move_handle_positions(self, brick):
        mat = brick.getMat()
        s   = brick.getScale()
        mg  = max(abs(s.x), abs(s.y), abs(s.z)) * 0.05 + 0.12
        wc  = Vec3(mat.xformPoint(Point3(0.5, 0.5, 0.5)))
        lx  = Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized()
        ly  = Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized()
        lz  = Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized()
        hx, hy, hz = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5
        return [
            wc + lx*(hx+mg), wc - lx*(hx+mg),
            wc + ly*(hy+mg), wc - ly*(hy+mg),
            wc + lz*(hz+mg), wc - lz*(hz+mg),
        ]

    def create_move_handles(self):
        if not self.selected_bricks:
            return

        brick = self.selected_brick or self.selected_bricks[0]
        positions = self._move_handle_positions(brick)

        defs = [
            (positions[0], 'x+', (1,0,0,0.95)),
            (positions[1], 'x-', (1,0,0,0.95)),
            (positions[2], 'y+', (0,1,0,0.95)),
            (positions[3], 'y-', (0,1,0,0.95)),
            (positions[4], 'z+', (0,0,1,0.95)),
            (positions[5], 'z-', (0,0,1,0.95)),
        ]
        for idx, (pos, axis_key, col) in enumerate(defs):
            hnp = self._make_handle(f"handle_{idx}", pos, col)
            hnp.setTag("handle", "1")
            hnp.setTag("handle_axis", axis_key)
            self.move_handles.append({'node': hnp, 'axis': axis_key})

    # ── Scale handles ─────────────────────────────────────────────────────

    def create_scale_handles(self):
        for h in self.scale_handles:
            h['node'].removeNode()
        self.scale_handles.clear()
        if not self.selected_brick:
            return

        brick = self.selected_brick
        mat   = brick.getMat()
        s     = brick.getScale()
        mg    = max(abs(s.x), abs(s.y), abs(s.z)) * 0.05 + 0.12
        wc    = Vec3(mat.xformPoint(Point3(0.5, 0.5, 0.5)))
        lx    = Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized()
        ly    = Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized()
        lz    = Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized()
        hx, hy, hz = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5

        defs = [
            (wc + lx*(hx+mg),  lx, 'x'),
            (wc - lx*(hx+mg), -lx, 'x'),
            (wc + ly*(hy+mg),  ly, 'y'),
            (wc - ly*(hy+mg), -ly, 'y'),
            (wc + lz*(hz+mg),  lz, 'z'),
            (wc - lz*(hz+mg), -lz, 'z'),
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

    def _make_sphere_geom(self, name, color, radius, lat=8, lon=12):
        fmt   = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData(name, fmt, Geom.UHStatic)
        vw = GeomVertexWriter(vdata, 'vertex')
        nw = GeomVertexWriter(vdata, 'normal')
        cw = GeomVertexWriter(vdata, 'color')
        r, g, b, a = color
        for i in range(lat + 1):
            phi = math.pi * (-0.5 + i / lat)
            z   = math.sin(phi) * radius
            cr  = math.cos(phi) * radius
            for j in range(lon + 1):
                theta = 2 * math.pi * j / lon
                x = cr * math.cos(theta)
                y = cr * math.sin(theta)
                n = Vec3(x, y, z).normalized()
                vw.addData3(x, y, z)
                nw.addData3(n.x, n.y, n.z)
                cw.addData4(r, g, b, a)
        tris = GeomTriangles(Geom.UHStatic)
        for i in range(lat):
            for j in range(lon):
                v0 = i * (lon + 1) + j
                tris.addVertices(v0, v0 + (lon + 1), v0 + 1)
                tris.addVertices(v0 + 1, v0 + (lon + 1), v0 + (lon + 2))
        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode(name)
        node.addGeom(geom)
        return node

    def create_rotate_handles(self):
        for h in self.rotate_handles:
            h['node'].removeNode()
        self.rotate_handles.clear()
        if not self.selected_brick:
            return

        c        = self.selected_brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
        s        = self.selected_brick.getScale()
        hpr      = self.selected_brick.getHpr()
        hw, hd, hh = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5

        # Each ring encircles only the two axes perpendicular to its rotation axis.
        # axis Z (H/green): encircles XY  →  radius from hw, hd
        # axis X (P/red):   encircles YZ  →  radius from hd, hh
        # axis Y (R/blue):  encircles XZ  →  radius from hw, hh
        rings = [
            (Vec3(0, 0, 1), (0.12, 0.82, 0.22, 1), 'h', max(hw, hd) + 1.5),
            (Vec3(1, 0, 0), (0.90, 0.18, 0.18, 1), 'p', max(hd, hh) + 1.5),
            (Vec3(0, 1, 0), (0.15, 0.45, 0.95, 1), 'r', max(hw, hh) + 1.5),
        ]

        for axis, color, rot_key, radius in rings:
            sphere_r = max(0.30, radius * 0.14)
            ax    = axis.normalized()
            t     = Vec3(1, 0, 0) if abs(ax.x) < 0.9 else Vec3(0, 1, 0)
            perp1 = ax.cross(t).normalized()
            perp2 = ax.cross(perp1).normalized()

            # Ring node inherits brick's HPR so it rotates with the part
            ring_np = self.render.attachNewNode(f"rotate_ring_{rot_key}")
            ring_np.setPos(c)
            ring_np.setHpr(hpr)
            ring_np.setTwoSided(True)

            # Thin circle line
            r, g, b, a = color
            ls = LineSegs(f"ring_line_{rot_key}")
            ls.setColor(r, g, b, a)
            ls.setThickness(2.5)
            CIRCLE_SEGS = 64
            for i in range(CIRCLE_SEGS + 1):
                ang = 2 * math.pi * i / CIRCLE_SEGS
                pt  = perp1 * math.cos(ang) * radius + perp2 * math.sin(ang) * radius
                if i == 0:
                    ls.moveTo(pt.x, pt.y, pt.z)
                else:
                    ls.drawTo(pt.x, pt.y, pt.z)
            line_np = ring_np.attachNewNode(ls.create())
            line_np.setShaderOff()
            line_np.setLightOff()

            # 4 clickable sphere handles — offset 45° so no two rings share a position
            axis_str = f"{axis.x},{axis.y},{axis.z}"
            for i in range(4):
                ang  = math.pi * 0.25 + math.pi * 0.5 * i
                spt  = perp1 * math.cos(ang) * radius + perp2 * math.sin(ang) * radius
                name = f"ring_{rot_key}_col_{i}"

                sph_node = self._make_sphere_geom(f"sph_{name}", color, sphere_r)
                snp = ring_np.attachNewNode(sph_node)
                snp.setPos(spt)
                snp.setShaderOff()
                snp.setLightOff()
                snp.setTag("rotate_handle", "1")
                snp.setTag("rotate_axis",   axis_str)
                snp.setTag("rotate_key",    rot_key)

                cnode = CollisionNode(name)
                cnode.addSolid(CollisionSphere(0, 0, 0, sphere_r * 1.3))
                cnode.setIntoCollideMask(BitMask32.bit(1))
                cnode.setFromCollideMask(BitMask32.allOff())
                snp.attachNewNode(cnode)

            self.rotate_handles.append({'node': ring_np, 'axis': axis, 'key': rot_key})

    # ── Rotate dragging ───────────────────────────────────────────────────

    def _world_to_screen(self, world_pt):
        p = self.camera.getRelativePoint(self.render, world_pt)
        screen = Point3()
        if self.camNode.getLens().project(p, screen):
            return (screen.x, screen.y)
        return None

    def start_rotate_drag(self, handle_np, axis_str, rot_key):
        ax = [float(v) for v in axis_str.split(",")]
        self.rotate_dragging    = True
        self.rotate_drag_handle = {'node': handle_np, 'axis': Vec3(*ax), 'key': rot_key}
        self.rotate_drag_start_hpr    = {b: Vec3(b.getHpr()) for b in self.selected_bricks}
        self.rotate_drag_start_quats  = {b: Quat(b.getQuat()) for b in self.selected_bricks}
        self.rotate_drag_start_pos    = {b: Vec3(b.getPos()) for b in self.selected_bricks}
        self.rotate_drag_start_center = {
            b: Vec3(b.getMat().xformPoint(Point3(0.5, 0.5, 0.5)))
            for b in self.selected_bricks
        }
        # Group centroid — all bricks orbit this point together
        all_centers = list(self.rotate_drag_start_center.values())
        if all_centers:
            self.rotate_group_center = Vec3(
                sum(c.x for c in all_centers) / len(all_centers),
                sum(c.y for c in all_centers) / len(all_centers),
                sum(c.z for c in all_centers) / len(all_centers),
            )
        else:
            self.rotate_group_center = Vec3(0, 0, 0)
        # Store world-space direction of each ring axis directly from the brick's
        # transform matrix — no Euler-order ambiguity, correct for any HPR.
        if self.selected_brick:
            mat = self.selected_brick.getMat()
            self.rotate_drag_axes = {
                'h': Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized(),
                'p': Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized(),
                'r': Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized(),
            }
        else:
            self.rotate_drag_axes = {'h': Vec3(0,0,1), 'p': Vec3(1,0,0), 'r': Vec3(0,1,0)}
        # Screen-space pivot for circular drag — use group centroid so the
        # angle feels natural relative to the whole selection.
        self.rotate_ring_world_center = self.rotate_group_center
        if self.mouseWatcherNode.hasMouse():
            m  = self.mouseWatcherNode.getMouse()
            sc = self._world_to_screen(self.rotate_ring_world_center)
            if sc:
                self.rotate_drag_start_angle = math.atan2(m.getY() - sc[1], m.getX() - sc[0])
            else:
                self.rotate_drag_start_angle = 0.0
        else:
            self.rotate_drag_start_angle = 0.0

    def update_rotate_drag(self):
        if not self.rotate_drag_handle or not self.rotate_drag_start_hpr:
            return
        if not self.mouseWatcherNode.hasMouse():
            return
        m       = self.mouseWatcherNode.getMouse()
        rot_key = self.rotate_drag_handle['key']

        # Compute delta from mouse angle around the ring's screen-space center
        raw_delta = 0.0
        world_center = getattr(self, 'rotate_ring_world_center', None)
        if world_center:
            sc = self._world_to_screen(world_center)
            if sc:
                dx = m.getX() - sc[0]
                dy = m.getY() - sc[1]
                if abs(dx) > 0.005 or abs(dy) > 0.005:
                    current_angle = math.atan2(dy, dx)
                    raw_delta = math.degrees(current_angle - self.rotate_drag_start_angle)
                    raw_delta = (raw_delta + 180) % 360 - 180

        delta = round(raw_delta / 5) * 5

        # World-space ring axis frozen at drag-start from the brick's transform
        # matrix, so each ring rotates the brick around its own visual axis.
        axes      = getattr(self, 'rotate_drag_axes', {'h': Vec3(0,0,1), 'p': Vec3(1,0,0), 'r': Vec3(0,1,0)})
        ring_axis = axes[rot_key]
        # Dynamic sign: CCW screen drag = positive rotation when axis faces the camera
        # (right-hand rule).  This keeps each ring consistent after the brick is rotated —
        # e.g. the blue ring pitched onto the world-Z axis behaves like the green ring did
        # when the brick was flat.
        cam_pos = self.camera.getPos(self.render)
        wc      = Vec3(getattr(self, 'rotate_ring_world_center', Vec3(0,0,0)))
        to_cam  = cam_pos - wc
        if to_cam.lengthSquared() > 1e-6:
            to_cam.normalize()
            sign = 1.0 if ring_axis.dot(to_cam) >= 0 else -1.0
        else:
            sign = 1.0
        signed_delta = delta * sign

        delta_q = Quat()
        delta_q.setFromAxisAngle(signed_delta, ring_axis.normalized())

        group_center = getattr(self, 'rotate_group_center', None)
        for brick, start_hpr in self.rotate_drag_start_hpr.items():
            if brick not in self.bricks:
                continue
            start_pos = self.rotate_drag_start_pos.get(brick, Vec3(brick.getPos()))

            # All bricks orbit the group centroid so the selection rotates as one unit.
            bq = self.rotate_drag_start_quats.get(brick, Quat())
            brick.setPos(start_pos)
            brick.setQuat(bq)
            pivot_pos = group_center if group_center else self.rotate_drag_start_center.get(brick)
            if pivot_pos:
                _piv = self.render.attachNewNode("_rot_pivot")
                _piv.setPos(pivot_pos)
                brick.wrtReparentTo(_piv)        # brick keeps world transform
                _piv.setQuat(delta_q)             # pivot carries the rotation
                brick.wrtReparentTo(self.render)  # fold pivot rotation into brick
                _piv.removeNode()

            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])
            self._grid_update(brick)

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
        # Also capture each brick's local axes so position compensation works after rotation.
        self.scale_drag_start_all = {
            b: (Vec3(b.getScale()), Vec3(b.getPos()))
            for b in self.selected_bricks
        }
        self.scale_drag_local_axes = {
            b: (
                Vec3(b.getMat().xformVec(Vec3(1, 0, 0))).normalized(),
                Vec3(b.getMat().xformVec(Vec3(0, 1, 0))).normalized(),
                Vec3(b.getMat().xformVec(Vec3(0, 0, 1))).normalized(),
            )
            for b in self.selected_bricks
        }

        # Fix a world-space reference point for the drag planes.
        self.scale_drag_center = Vec3(brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5)))
        self.scale_drag_start_mouse = self._mouse_world_point_on_axis_plane(Vec3(*ax), self.scale_drag_center)

    def update_scale_drag(self):
        if not self.selected_brick or not self.drag_handle:
            return
        if not self.scale_drag_start_mouse:
            return

        axis   = self.drag_handle['axis']
        axkey  = self.drag_handle['key']
        min_sz = 0.5

        # Compute how far the mouse has moved along the handle's outward axis.
        cur = self._mouse_world_point_on_axis_plane(axis, self.scale_drag_center)
        if not cur:
            return
        delta = (cur - self.scale_drag_start_mouse).dot(axis)

        # Apply the same delta to every selected brick using each brick's own start state.
        bricks_to_update = self.scale_drag_start_all if self.scale_drag_start_all else {
            self.selected_brick: (self.scale_drag_start_scale, self.scale_drag_start_pos)
        }
        for brick, (ss, sp) in bricks_to_update.items():
            if brick not in self.bricks:
                continue
            lx, ly, lz = self.scale_drag_local_axes.get(brick, (Vec3(1,0,0), Vec3(0,1,0), Vec3(0,0,1)))
            if axkey == 'x':
                new_bx      = max(min_sz, ss.x + delta)
                actual_grow = new_bx - ss.x
                brick.setScale(new_bx, ss.y, ss.z)
                if axis.dot(lx) < 0:
                    brick.setPos(sp - lx * actual_grow)

            elif axkey == 'y':
                new_by      = max(min_sz, ss.y + delta)
                actual_grow = new_by - ss.y
                brick.setScale(ss.x, new_by, ss.z)
                if axis.dot(ly) < 0:
                    brick.setPos(sp - ly * actual_grow)

            else:  # 'z'
                new_bz      = max(min_sz, ss.z + delta)
                actual_grow = new_bz - ss.z
                brick.setScale(ss.x, ss.y, new_bz)
                if axis.dot(lz) < 0:
                    brick.setPos(sp - lz * actual_grow)

            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])
            self._grid_update(brick)

    # ── Update task ───────────────────────────────────────────────────────

    def updateHandlesTask(self, task):
        if self.selected_bricks:
            # Compute distance-based scale so handles keep a constant apparent size.
            h_scale = 1.0
            if self.selected_brick:
                cam_pos = self.camera.getPos(self.render)
                brick_center = Vec3(self.selected_brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5)))
                dist    = (cam_pos - brick_center).length()
                h_scale = max(0.5, dist / 15.0)

            # Move handles: follow primary brick's rotated face centers
            if self.move_handles and self.selected_brick:
                for h, pos in zip(self.move_handles, self._move_handle_positions(self.selected_brick)):
                    h['node'].setPos(pos)
                    h['node'].setScale(h_scale)

            # Scale handles: follow primary brick's actual rotated face centers
            if self.scale_handles and self.selected_brick:
                brick = self.selected_brick
                mat   = brick.getMat()
                s     = brick.getScale()
                mg    = max(abs(s.x), abs(s.y), abs(s.z)) * 0.05 + 0.12
                wc    = Vec3(mat.xformPoint(Point3(0.5, 0.5, 0.5)))
                lx    = Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized()
                ly    = Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized()
                lz    = Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized()
                hx, hy, hz = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5
                positions = [
                    wc + lx*(hx+mg), wc - lx*(hx+mg),
                    wc + ly*(hy+mg), wc - ly*(hy+mg),
                    wc + lz*(hz+mg), wc - lz*(hz+mg),
                ]
                for h, pos in zip(self.scale_handles, positions):
                    h['node'].setPos(pos)
                    h['node'].setScale(h_scale)

            # Rotate ring handles: re-center and re-orient on brick each frame
            if self.rotate_handles and self.selected_brick:
                c   = self.selected_brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                hpr = self.selected_brick.getHpr()
                for h in self.rotate_handles:
                    h['node'].setPos(c)
                    h['node'].setHpr(hpr)

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
        self.dragging = True
        brick = self.selected_brick
        mat   = brick.getMat()
        sign  = 1.0 if axis_str.endswith('+') else -1.0
        key   = axis_str[0]
        if key == 'x':
            local_dir = Vec3(mat.xformVec(Vec3(sign, 0, 0))).normalized()
        elif key == 'y':
            local_dir = Vec3(mat.xformVec(Vec3(0, sign, 0))).normalized()
        else:
            local_dir = Vec3(mat.xformVec(Vec3(0, 0, sign))).normalized()
        self.drag_handle = {'node': handle_np, 'axis': local_dir}
        self.drag_start_brick_positions = {b: Vec3(b.getPos(self.render)) for b in self.selected_bricks}
        self.drag_start_brick_pos = Vec3(self.selected_brick.getPos(self.render))
        self.drag_start_mouse_world = self._mouse_world_point_on_axis_plane(local_dir, self.drag_start_brick_pos)

    def update_drag(self):
        local_dir = self.drag_handle['axis']
        cur = self._mouse_world_point_on_axis_plane(local_dir, self.drag_start_brick_pos)
        if not cur:
            return
        # Project raw 3D mouse movement onto the brick's local axis direction
        delta = local_dir * (cur - self.drag_start_mouse_world).dot(local_dir)
        for brick, start_pos in self.drag_start_brick_positions.items():
            brick.setPos(start_pos + delta)
            if brick in self.brick_hitbox_visuals:
                self.update_brick_hitbox_visual_scale(brick, self.brick_hitbox_visuals[brick])
            self._grid_update(brick)

    # ── Mouse raycasting ──────────────────────────────────────────────────

    def _mouse_world_point_on_axis_plane(self, axis_dir, plane_point):
        """Intersect mouse ray with the plane that contains axis_dir and best faces the camera.
        This keeps cursor-to-handle movement 1:1 regardless of brick rotation."""
        if not self.update_picker_ray():
            return None
        mpos = self.mouseWatcherNode.getMouse()
        near, far = Point3(), Point3()
        if not self.cam.node().getLens().extrude(mpos, near, far):
            return None
        near_w = self.render.getRelativePoint(self.camera, near)
        far_w  = self.render.getRelativePoint(self.camera, far)
        ray_d  = (far_w - near_w)
        if ray_d.lengthSquared() == 0:
            return None
        ray_d.normalize()
        # Plane normal = camera-forward minus its component along the drag axis.
        # This gives the plane that contains the axis and faces the camera most directly.
        cam_fwd = Vec3(self.camera.getQuat(self.render).getForward())
        a = Vec3(axis_dir).normalized()
        n = cam_fwd - a * cam_fwd.dot(a)
        if n.lengthSquared() < 1e-6:
            cam_up = Vec3(self.camera.getQuat(self.render).getUp())
            n = cam_up - a * cam_up.dot(a)
        if n.lengthSquared() < 1e-6:
            return None
        n.normalize()
        denom = ray_d.dot(n)
        if abs(denom) < 1e-6:
            return None
        t = (Vec3(plane_point) - near_w).dot(n) / denom
        if t < 0:
            return None
        return near_w + ray_d * t

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
