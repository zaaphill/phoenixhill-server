from panda3d.core import (
    CollisionNode, CollisionBox, BitMask32, Point3, Vec3, Vec4,
    GeomVertexFormat, GeomVertexData, Geom,
    GeomVertexWriter, GeomTriangles, GeomNode, NodePath,
    Texture, Shader,
)
from direct.task import Task
import json
import math as _math
import tkinter as tk
from tkinter import filedialog
from pathlib import Path

_GRID_CELL = 25.0   # spatial grid cell size in game units
_DRAW_DIST = 1000.0  # bricks beyond this distance are hidden during playtest

# ── Grass detail shader ───────────────────────────────────────────────────────
# Converts the texture to a greyscale detail map and multiplies by brickColor,
# so any chosen color completely controls the hue while the texture stays visible.
_GRASS_VERT = """
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec2 p3d_MultiTexCoord0;
out vec2 uv;
out vec3 vNormal;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv      = p3d_MultiTexCoord0;
    vNormal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);
}
"""
_GRASS_FRAG = """
#version 140
uniform sampler2D p3d_Texture0;
uniform vec4 brickColor;
in vec2 uv;
in vec3 vNormal;
out vec4 fragColor;
void main() {
    vec3  tex    = texture(p3d_Texture0, uv).rgb;
    float lum    = dot(tex, vec3(0.299, 0.587, 0.114));
    float detail = lum * 2.0;   // mid-grey (0.5) -> 1.0, preserves exact brick color on average

    // Simple monochrome light factor so it never casts a colour tint.
    // Top face (normal up) -> 1.0, fully shadowed face -> 0.55.
    vec3  lightDir = normalize(vec3(0.21, -0.37, 0.90));
    float diff     = max(dot(normalize(vNormal), lightDir), 0.0);
    float light    = 0.55 + 0.45 * diff;

    fragColor = vec4(clamp(brickColor.rgb * detail * light, 0.0, 1.0), brickColor.a);
}
"""


class BrickMixin:
    def setup_collision_system(self):
        self._brick_grid  = {}   # (cx, cy) → set of bricks in that cell
        self._brick_cells = {}   # brick → frozenset of cells it occupies

        self.char_base_width = 2.0
        self.char_base_depth = 1.0
        self.char_base_height = 5.1

        self.char_hitbox_scale_left = 1.0
        self.char_hitbox_scale_right = 1.0
        self.char_hitbox_scale_front = 1.0
        self.char_hitbox_scale_back = 1.0
        self.char_hitbox_scale_top = 1.0
        self.char_hitbox_scale_bottom = 1.0

        self.char_hitbox_offset = Vec3(0.5, 0.1, 0.8)

        self.brick_base_width = 4.0
        self.brick_base_depth = 2.0
        self.brick_base_height = 1.0

        # Stores the creation-time scale of each brick so "Reset Scale" can restore it.
        self.brick_default_scale = {}

    def setup_visual_hitboxes(self):
        self.brick_hitbox_visuals = {}
        self.brick_grass_shells   = {}
        self.brick_grass_color    = {}
        self.brick_wood_shells    = {}
        self.brick_wood_color     = {}
        self.brick_stone_shells   = {}
        self.brick_stone_color    = {}
        self.brick_last_scale     = {}
        self.brick_last_pos       = {}
        self.brick_last_hpr       = {}
        self.brick_colors         = {}   # tracks current color for every brick
        self.brick_spawn_points   = set()
        self.brick_kill_bricks    = set()
        self.brick_no_collision   = set()
        self._grass_tex           = None
        self._grass_shader        = None
        self._wood_tex            = None
        self._wood_shader         = None
        self._stone_tex           = None
        self._stone_shader        = None
        self._was_playtest        = False
        self._face_culled_backup  = {}   # brick -> {vis, grass, wood, stone} original nodes
        if not hasattr(self, '_settings_render_distance'):
            self._settings_render_distance = 1000

    # ── Spatial grid ──────────────────────────────────────────────────────────

    def _grid_cells_for(self, brick):
        mat = brick.getMat()
        corners = [mat.xformPoint(Point3(x, y, z)) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        cx0, cx1 = int(min(xs) / _GRID_CELL), int(max(xs) / _GRID_CELL)
        cy0, cy1 = int(min(ys) / _GRID_CELL), int(max(ys) / _GRID_CELL)
        return frozenset(
            (cx, cy) for cx in range(cx0, cx1 + 1) for cy in range(cy0, cy1 + 1)
        )

    def _grid_add(self, brick):
        cells = self._grid_cells_for(brick)
        for c in cells:
            self._brick_grid.setdefault(c, set()).add(brick)
        self._brick_cells[brick] = cells

    def _grid_remove(self, brick):
        for c in self._brick_cells.pop(brick, ()):
            self._brick_grid.get(c, set()).discard(brick)

    def _grid_update(self, brick):
        self._grid_remove(brick)
        self._grid_add(brick)

    def _grid_nearby(self, pos, radius):
        cx0 = int((pos.x - radius) / _GRID_CELL)
        cx1 = int((pos.x + radius) / _GRID_CELL) + 1
        cy0 = int((pos.y - radius) / _GRID_CELL)
        cy1 = int((pos.y + radius) / _GRID_CELL) + 1
        result = set()
        for cx in range(cx0, cx1):
            for cy in range(cy0, cy1):
                result.update(self._brick_grid.get((cx, cy), ()))
        return result

    # ── Distance culling ──────────────────────────────────────────────────────

    def _cull_brick_visibility(self):
        cp = (self.character.getPos()
              if getattr(self, 'character', None) else self.camera.getPos())
        draw_dist = getattr(self, '_settings_render_distance', _DRAW_DIST)
        dd2 = draw_dist * draw_dist
        for brick in self.bricks:
            hpr = brick.getHpr()
            if abs(hpr.x) < 0.5 and abs(hpr.y) < 0.5 and abs(hpr.z) < 0.5:
                p  = brick.getPos()
                s  = brick.getScale()
                dx = max(p.x - cp.x, 0.0, cp.x - (p.x + s.x))
                dy = max(p.y - cp.y, 0.0, cp.y - (p.y + s.y))
                dz = max(p.z - cp.z, 0.0, cp.z - (p.z + s.z))
            else:
                mat     = brick.getMat()
                corners = [mat.xformPoint(Point3(x, y, z))
                           for x in (0, 1) for y in (0, 1) for z in (0, 1)]
                xs = [c.x for c in corners]; ys = [c.y for c in corners]; zs = [c.z for c in corners]
                dx = max(min(xs) - cp.x, 0.0, cp.x - max(xs))
                dy = max(min(ys) - cp.y, 0.0, cp.y - max(ys))
                dz = max(min(zs) - cp.z, 0.0, cp.z - max(zs))
            show = dx * dx + dy * dy + dz * dz <= dd2
            for d in (self.brick_hitbox_visuals,
                      self.brick_grass_shells, self.brick_wood_shells, self.brick_stone_shells):
                node = d.get(brick)
                if node and not node.isEmpty():
                    node.show() if show else node.hide()

    def _restore_all_brick_visibility(self):
        for d in (self.brick_hitbox_visuals,
                  self.brick_grass_shells, self.brick_wood_shells, self.brick_stone_shells):
            for node in d.values():
                if node and not node.isEmpty():
                    node.show()

    # ──────────────────────────────────────────────────────────────────────────

    def update_brick_collision(self, brick):
        """Create (or recreate) a collision node for the brick.

        The CollisionBox lives in the brick's local [0,1]^3 space.  Panda3D
        automatically applies the brick's setScale() to the solid at query
        time, so the collision always matches the brick's current world size
        with no manual math required.
        """
        if brick is None:
            return
        old = self.brick_collision_nodes.get(brick)
        if old and not old.isEmpty():
            old.removeNode()
        cnode = CollisionNode('brick_cnode')
        cnode.addSolid(CollisionBox(Point3(0.5, 0.5, 0.5), 0.5, 0.5, 0.5))
        cnode.setIntoCollideMask(BitMask32.bit(1))
        cnode.setFromCollideMask(BitMask32.allOff())
        self.brick_collision_nodes[brick] = brick.attachNewNode(cnode)

    def create_solid_box(self, width, depth, height, color, visible_faces=None):
        """Build a colored box geom.  visible_faces (set of 0-5) skips hidden faces:
        0=bottom(-Z) 1=top(+Z) 2=front(-Y) 3=back(+Y) 4=left(-X) 5=right(+X)"""
        vformat = GeomVertexFormat.get_v3n3c4()
        vdata   = GeomVertexData('solid_box', vformat, Geom.UH_static)
        vertex  = GeomVertexWriter(vdata, 'vertex')
        nw      = GeomVertexWriter(vdata, 'normal')
        cw      = GeomVertexWriter(vdata, 'color')
        tris    = GeomTriangles(Geom.UH_static)

        hw, hd, hh = width / 2.0, depth / 2.0, height / 2.0

        face_quads = [
            ([(-hw, hd,-hh),( hw, hd,-hh),( hw,-hd,-hh),(-hw,-hd,-hh)], ( 0, 0,-1)),  # 0 bottom -Z
            ([(-hw,-hd, hh),( hw,-hd, hh),( hw, hd, hh),(-hw, hd, hh)], ( 0, 0, 1)),  # 1 top +Z
            ([(-hw,-hd,-hh),( hw,-hd,-hh),( hw,-hd, hh),(-hw,-hd, hh)], ( 0,-1, 0)),  # 2 front -Y
            ([(-hw, hd, hh),( hw, hd, hh),( hw, hd,-hh),(-hw, hd,-hh)], ( 0, 1, 0)),  # 3 back +Y
            ([(-hw,-hd, hh),(-hw, hd, hh),(-hw, hd,-hh),(-hw,-hd,-hh)], (-1, 0, 0)),  # 4 left -X
            ([( hw,-hd,-hh),( hw, hd,-hh),( hw, hd, hh),( hw,-hd, hh)], ( 1, 0, 0)),  # 5 right +X
        ]

        for fi, (corners, normal) in enumerate(face_quads):
            if visible_faces is not None and fi not in visible_faces:
                continue
            base = vdata.getNumRows()
            for cx, cy, cz in corners:
                vertex.addData3(cx, cy, cz)
                nw.addData3(*normal)
                cw.addData4(*color)
            tris.addVertices(base, base + 1, base + 2)
            tris.addVertices(base, base + 2, base + 3)

        if vdata.getNumRows() == 0:
            vertex.addData3(0, 0, 0); nw.addData3(0, 0, 1); cw.addData4(0, 0, 0, 0)

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode('solid_box')
        node.addGeom(geom)
        np = NodePath(node)
        np.setTwoSided(True)
        np.setShaderOff()
        return np

    def update_brick_hitbox_visual_scale(self, brick, visual):
        s = brick.getScale()
        # models/box goes 0→1 in local space; its center is at local (0.5,0.5,0.5).
        # Using the full TRS matrix handles rotation correctly — pos+scale*0.5 only
        # works when HPR is zero (the brick pivots around its corner, not its center).
        world_center = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
        visual.setPos(world_center)
        visual.setHpr(brick.getHpr())
        visual.setScale(
            s.x / self.brick_base_width,
            s.y / self.brick_base_depth,
            s.z / self.brick_base_height,
        )

    def get_character_collision_box(self, pos):
        hw = (self.char_base_width / 2) * self.char_hitbox_scale_left
        hd = (self.char_base_depth / 2) * self.char_hitbox_scale_front
        hh = self.char_base_height / 2

        center = Vec3(
            pos.x,
            pos.y,
            pos.z + hh,
        )

        return {
            'center':      center,
            'half_width':  hw,
            'half_depth':  hd,
            'half_height': hh,
            'min_z':       pos.z,
            'max_z':       pos.z + self.char_base_height,
        }

    def get_brick_collision_box(self, brick):
        """Return the brick's axis-aligned collision box in world space.

        Derived purely from brick.getPos() and brick.getScale() — the single
        source of truth for brick size.
        """
        pos = brick.getPos()
        s   = brick.getScale()
        hw  = s.x * 0.5
        hd  = s.y * 0.5
        hh  = s.z * 0.5
        return {
            'center':      Vec3(pos.x + hw, pos.y + hd, pos.z + hh),
            'half_width':  hw,
            'half_depth':  hd,
            'half_height': hh,
            'min_z':       pos.z,
            'max_z':       pos.z + s.z,
        }

    def boxes_collide(self, box1, box2):
        return (
            abs(box1['center'].x - box2['center'].x) < (box1['half_width']  + box2['half_width'])  and
            abs(box1['center'].y - box2['center'].y) < (box1['half_depth']  + box2['half_depth'])  and
            abs(box1['center'].z - box2['center'].z) < (box1['half_height'] + box2['half_height'])
        )

    def _obb_aabb_collide(self, char_box, brick):
        """SAT test: character AABB vs oriented brick OBB. Tests 6 axes (3 AABB + 3 OBB face normals)."""
        mat    = brick.getMat()
        s      = brick.getScale()
        lx     = Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized()
        ly     = Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized()
        lz     = Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized()
        obb_c  = Vec3(mat.xformPoint(Point3(0.5, 0.5, 0.5)))
        ohx, ohy, ohz = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5
        aabb_c = char_box['center']
        ahx    = char_box['half_width']
        ahy    = char_box['half_depth']
        ahz    = char_box['half_height']
        diff   = obb_c - aabb_c
        # 3 world-axis separating axes (AABB face normals)
        for axis, ah in ((Vec3(1,0,0), ahx), (Vec3(0,1,0), ahy), (Vec3(0,0,1), ahz)):
            obb_proj = abs(lx.dot(axis))*ohx + abs(ly.dot(axis))*ohy + abs(lz.dot(axis))*ohz
            if abs(diff.dot(axis)) > ah + obb_proj:
                return False
        # 3 OBB-axis separating axes (brick face normals)
        for axis, oh in ((lx, ohx), (ly, ohy), (lz, ohz)):
            aabb_proj = ahx*abs(axis.x) + ahy*abs(axis.y) + ahz*abs(axis.z)
            if abs(diff.dot(axis)) > aabb_proj + oh:
                return False
        return True

    def _obb_aabb_push(self, char_box, brick):
        """Minimum-penetration push to move char_box out of brick's OBB.
        Returns a Vec3 push or None if not overlapping."""
        mat   = brick.getMat()
        s     = brick.getScale()
        lx    = Vec3(mat.xformVec(Vec3(1, 0, 0))).normalized()
        ly    = Vec3(mat.xformVec(Vec3(0, 1, 0))).normalized()
        lz    = Vec3(mat.xformVec(Vec3(0, 0, 1))).normalized()
        obb_c = Vec3(mat.xformPoint(Point3(0.5, 0.5, 0.5)))
        ohx, ohy, ohz = abs(s.x)*0.5, abs(s.y)*0.5, abs(s.z)*0.5
        aabb_c = char_box['center']
        ahx = char_box['half_width']
        ahy = char_box['half_depth']
        ahz = char_box['half_height']
        diff = obb_c - aabb_c

        min_ov = float('inf')
        best   = None
        for axis, ah, oh in (
            (Vec3(1,0,0), ahx, abs(lx.x)*ohx + abs(ly.x)*ohy + abs(lz.x)*ohz),
            (Vec3(0,1,0), ahy, abs(lx.y)*ohx + abs(ly.y)*ohy + abs(lz.y)*ohz),
            (Vec3(0,0,1), ahz, abs(lx.z)*ohx + abs(ly.z)*ohy + abs(lz.z)*ohz),
            (lx, ahx*abs(lx.x) + ahy*abs(lx.y) + ahz*abs(lx.z), ohx),
            (ly, ahx*abs(ly.x) + ahy*abs(ly.y) + ahz*abs(ly.z), ohy),
            (lz, ahx*abs(lz.x) + ahy*abs(lz.y) + ahz*abs(lz.z), ohz),
        ):
            d  = diff.dot(axis)
            ov = ah + oh - abs(d)
            if ov <= 0:
                return None  # separated on this axis
            if ov < min_ov:
                min_ov = ov
                best   = axis * (-1.0 if d >= 0 else 1.0)
        return best * min_ov if best else None

    def check_collision_at_position(self, pos):
        char_box = self.get_character_collision_box(pos)
        no_col = getattr(self, 'brick_no_collision', set())
        for brick in self._grid_nearby(pos, 15):
            if brick in no_col:
                continue
            hpr = brick.getHpr()
            if abs(hpr.x) < 0.5 and abs(hpr.y) < 0.5 and abs(hpr.z) < 0.5:
                brick_box = self.get_brick_collision_box(brick)
                if brick_box['max_z'] <= pos.z + 0.05:
                    continue
                if self.boxes_collide(char_box, brick_box):
                    return True
            else:
                mat = brick.getMat()
                corners = [mat.xformPoint(Point3(x, y, z)) for x in (0,1) for y in (0,1) for z in (0,1)]
                if max(c.z for c in corners) <= pos.z + 0.05:
                    continue
                # The surf_z "on surface" skip is only valid when the brick's local
                # up axis actually faces upward (slope/ramp).  For wall planks whose
                # local Z points sideways, _rotated_surface_z returns a side-face Z
                # that can falsely satisfy pos.z >= surf_z - 0.12, making the brick
                # invisible to collision.  Skip the surf_z check for those bricks.
                if mat.xformVec(Vec3(0, 0, 1)).z >= 0.3:
                    surf_z = self._rotated_surface_z(brick, char_box['center'].x, char_box['center'].y, clamp=True)
                    if surf_z is not None and pos.z >= surf_z - 0.12:
                        continue  # on or just below the top surface — not a wall
                if self._obb_aabb_collide(char_box, brick):
                    return True
        return False

    def _create_grass_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1, hidden_faces=None):
        """All 6 faces of a brick, textured with grass.
        cx/cy/cz = world-space centre; sx/sy/sz = world-space dimensions.
        Tile density is fixed so the texture never stretches when resized.
        """
        fmt   = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData('grass_base', fmt, Geom.UHStatic)
        vw    = GeomVertexWriter(vdata, 'vertex')
        nw    = GeomVertexWriter(vdata, 'normal')
        tw    = GeomVertexWriter(vdata, 'texcoord')
        tris  = GeomTriangles(Geom.UHStatic)

        def quad(pts, nx, ny, nz):
            b = vdata.getNumRows()
            for x, y, z, u, v in pts:
                vw.addData3(x, y, z); nw.addData3(nx, ny, nz); tw.addData2(u, v)
            tris.addVertices(b, b+1, b+2); tris.addVertices(b, b+2, b+3)

        x0, x1 = cx - sx/2, cx + sx/2
        y0, y1 = cy - sy/2, cy + sy/2
        z0, z1 = cz - sz/2, cz + sz/2

        # Fixed densities: 1 tile per 25 units across all faces so texture
        # scale is identical whether you're looking at the top or a side.
        ttx = sx / 25.0
        tty = sy / 25.0
        tsx = sx / 25.0
        tsy = sy / 25.0
        tsh = sz / 25.0

        hf = hidden_faces or set()
        if 1 not in hf:  # top (+Z)
            quad([(x0,y0,z1, 0,0),(x1,y0,z1, ttx,0),(x1,y1,z1, ttx,tty),(x0,y1,z1, 0,tty)],
                 0, 0, 1)
        if 0 not in hf:  # bottom (-Z)
            quad([(x0,y0,z0, 0,0),(x0,y1,z0, 0,tty),(x1,y1,z0, ttx,tty),(x1,y0,z0, ttx,0)],
                 0, 0, -1)
        if 3 not in hf:  # back (+Y)
            quad([(x0,y1,z0, 0,0),(x1,y1,z0, tsx,0),(x1,y1,z1, tsx,tsh),(x0,y1,z1, 0,tsh)],
                 0, 1, 0)
        if 2 not in hf:  # front (-Y)
            quad([(x1,y0,z0, 0,0),(x0,y0,z0, tsx,0),(x0,y0,z1, tsx,tsh),(x1,y0,z1, 0,tsh)],
                 0, -1, 0)
        if 5 not in hf:  # right (+X)
            quad([(x1,y1,z0, 0,0),(x1,y0,z0, tsy,0),(x1,y0,z1, tsy,tsh),(x1,y1,z1, 0,tsh)],
                 1, 0, 0)
        if 4 not in hf:  # left (-X)
            quad([(x0,y0,z0, 0,0),(x0,y1,z0, tsy,0),(x0,y1,z1, tsy,tsh),(x0,y0,z1, 0,tsh)],
                 -1, 0, 0)

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode('grass_baseplate')
        node.addGeom(geom)
        np = NodePath(node)
        np.setTwoSided(True)

        if self._grass_tex is None:
            self._grass_tex = self.loader.loadTexture(
                'textures/grass/Poliigon_GrassPatchyGround_4585_BaseColor.jpg')
            self._grass_tex.setWrapU(Texture.WMRepeat)
            self._grass_tex.setWrapV(Texture.WMRepeat)
            self._grass_tex.setMinfilter(Texture.FT_linear_mipmap_linear)
            self._grass_tex.setMagfilter(Texture.FT_linear)
            self._grass_tex.setAnisotropicDegree(16)
        if self._grass_shader is None:
            self._grass_shader = Shader.make(Shader.SL_GLSL, _GRASS_VERT, _GRASS_FRAG)
        np.setTexture(self._grass_tex)
        np.setShader(self._grass_shader)
        np.setDepthOffset(1)
        return np

    def _rebuild_grass_shell(self, brick):
        """Rebuild the grass shell to exactly match brick's current world bounds."""
        old = self.brick_grass_shells.get(brick)
        if old and not old.isEmpty():
            old.removeNode()
        s   = brick.getScale()
        p   = brick.getPos()
        h   = brick.getHpr()
        wc  = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
        # Geometry centered at origin so setHpr can rotate it correctly.
        grass = self._create_grass_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_grass_color.get(brick, (0.15, 0.49, 0.19, 1.0))
        grass.setShaderInput('brickColor', Vec4(*color))
        grass.reparentTo(self.render)
        grass.setPos(Vec3(wc))
        grass.setHpr(h)
        self.brick_grass_shells[brick] = grass
        self.brick_last_scale[brick]   = Vec3(s)
        self.brick_last_pos[brick]     = Vec3(p)
        self.brick_last_hpr[brick]     = Vec3(h)

    def _create_wood_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1, hidden_faces=None):
        fmt   = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData('wood_base', fmt, Geom.UHStatic)
        vw    = GeomVertexWriter(vdata, 'vertex')
        nw    = GeomVertexWriter(vdata, 'normal')
        tw    = GeomVertexWriter(vdata, 'texcoord')
        tris  = GeomTriangles(Geom.UHStatic)

        x0, x1 = cx - sx/2, cx + sx/2
        y0, y1 = cy - sy/2, cy + sy/2
        z0, z1 = cz - sz/2, cz + sz/2

        ttx = sx / 25.0
        tty = sy / 25.0
        ttz = sz / 25.0

        def quad(verts, normal, uvs):
            base = vdata.getNumRows()
            for v, u in zip(verts, uvs):
                vw.addData3(*v); nw.addData3(*normal); tw.addData2(*u)
            tris.addVertices(base, base+1, base+2)
            tris.addVertices(base, base+2, base+3)

        hf = hidden_faces or set()
        if 1 not in hf: quad([(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)], (0,0,1),  [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        if 0 not in hf: quad([(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)], (0,0,-1), [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        if 2 not in hf: quad([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)], (0,-1,0), [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        if 3 not in hf: quad([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)], (0,1,0),  [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        if 4 not in hf: quad([(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)], (-1,0,0), [(0,0),(tty,0),(tty,ttz),(0,ttz)])
        if 5 not in hf: quad([(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)], (1,0,0),  [(0,0),(tty,0),(tty,ttz),(0,ttz)])

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode('wood_shell')
        node.addGeom(geom)
        np = NodePath(node)
        np.setTwoSided(True)

        if self._wood_tex is None:
            self._wood_tex = self.loader.loadTexture(
                'textures/wood_table_worn_diff_4k.jpg')
            self._wood_tex.setWrapU(Texture.WMRepeat)
            self._wood_tex.setWrapV(Texture.WMRepeat)
            self._wood_tex.setMinfilter(Texture.FT_linear_mipmap_linear)
            self._wood_tex.setMagfilter(Texture.FT_linear)
            self._wood_tex.setAnisotropicDegree(16)
        if self._wood_shader is None:
            self._wood_shader = Shader.make(Shader.SL_GLSL, _GRASS_VERT, _GRASS_FRAG)
        np.setTexture(self._wood_tex)
        np.setShader(self._wood_shader)
        np.setDepthOffset(1)
        return np

    def _rebuild_wood_shell(self, brick):
        """Rebuild the wood shell to exactly match brick's current world bounds."""
        old = self.brick_wood_shells.get(brick)
        if old and not old.isEmpty():
            old.removeNode()
        s   = brick.getScale()
        p   = brick.getPos()
        h   = brick.getHpr()
        wc  = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
        wood = self._create_wood_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_wood_color.get(brick, (0.80, 0.60, 0.35, 1.0))
        wood.setShaderInput('brickColor', Vec4(*color))
        wood.reparentTo(self.render)
        wood.setPos(Vec3(wc))
        wood.setHpr(h)
        self.brick_wood_shells[brick] = wood
        self.brick_last_scale[brick]  = Vec3(s)
        self.brick_last_pos[brick]    = Vec3(p)
        self.brick_last_hpr[brick]    = Vec3(h)

    def _create_stone_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1, hidden_faces=None):
        fmt   = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData('stone_base', fmt, Geom.UHStatic)
        vw    = GeomVertexWriter(vdata, 'vertex')
        nw    = GeomVertexWriter(vdata, 'normal')
        tw    = GeomVertexWriter(vdata, 'texcoord')
        tris  = GeomTriangles(Geom.UHStatic)

        x0, x1 = cx - sx/2, cx + sx/2
        y0, y1 = cy - sy/2, cy + sy/2
        z0, z1 = cz - sz/2, cz + sz/2

        ttx = sx / 25.0
        tty = sy / 25.0
        ttz = sz / 25.0

        def quad(verts, normal, uvs):
            base = vdata.getNumRows()
            for v, u in zip(verts, uvs):
                vw.addData3(*v); nw.addData3(*normal); tw.addData2(*u)
            tris.addVertices(base, base+1, base+2)
            tris.addVertices(base, base+2, base+3)

        hf = hidden_faces or set()
        if 1 not in hf: quad([(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)], (0,0,1),  [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        if 0 not in hf: quad([(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)], (0,0,-1), [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        if 2 not in hf: quad([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)], (0,-1,0), [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        if 3 not in hf: quad([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)], (0,1,0),  [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        if 4 not in hf: quad([(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)], (-1,0,0), [(0,0),(tty,0),(tty,ttz),(0,ttz)])
        if 5 not in hf: quad([(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)], (1,0,0),  [(0,0),(tty,0),(tty,ttz),(0,ttz)])

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode('stone_shell')
        node.addGeom(geom)
        np = NodePath(node)
        np.setTwoSided(True)

        if self._stone_tex is None:
            self._stone_tex = self.loader.loadTexture(
                'textures/plastered_stone_wall_diff_4k.jpg')
            self._stone_tex.setWrapU(Texture.WMRepeat)
            self._stone_tex.setWrapV(Texture.WMRepeat)
            self._stone_tex.setMinfilter(Texture.FT_linear_mipmap_linear)
            self._stone_tex.setMagfilter(Texture.FT_linear)
            self._stone_tex.setAnisotropicDegree(16)
        if self._stone_shader is None:
            self._stone_shader = Shader.make(Shader.SL_GLSL, _GRASS_VERT, _GRASS_FRAG)
        np.setTexture(self._stone_tex)
        np.setShader(self._stone_shader)
        np.setDepthOffset(1)
        return np

    def _rebuild_stone_shell(self, brick):
        """Rebuild the stone shell to exactly match brick's current world bounds."""
        old = self.brick_stone_shells.get(brick)
        if old and not old.isEmpty():
            old.removeNode()
        s   = brick.getScale()
        p   = brick.getPos()
        h   = brick.getHpr()
        wc  = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
        stone = self._create_stone_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_stone_color.get(brick, (0.75, 0.72, 0.68, 1.0))
        stone.setShaderInput('brickColor', Vec4(*color))
        stone.reparentTo(self.render)
        stone.setPos(Vec3(wc))
        stone.setHpr(h)
        self.brick_stone_shells[brick] = stone
        self.brick_last_scale[brick]   = Vec3(s)
        self.brick_last_pos[brick]     = Vec3(p)
        self.brick_last_hpr[brick]     = Vec3(h)

    def create_baseplate(self):
        brick = self.loader.loadModel("models/box")
        brick.reparentTo(self.render)
        brick.setScale(50, 50, 1)
        brick.setPos(-25, -25, -0.5)
        brick.setTextureOff(1)
        brick.hide()

        # Solid-colour box kept as the hitbox_visual (editor overlay / selection)
        visual = self.create_solid_box(
            self.brick_base_width, self.brick_base_depth, self.brick_base_height,
            (0.13, 0.22, 0.10, 1.0),
        )
        visual.reparentTo(self.render)
        visual.hide()
        self.brick_hitbox_visuals[brick] = visual
        self.brick_default_scale[brick] = Vec3(brick.getScale())
        self.update_brick_hitbox_visual_scale(brick, visual)
        self.update_brick_collision(brick)

        # Textured grass shell: all 6 faces, rebuilt dynamically on resize
        self.brick_grass_color[brick] = (0.15, 0.49, 0.19, 1.0)
        self.brick_colors[brick]      = (0.15, 0.49, 0.19, 1.0)
        self._rebuild_grass_shell(brick)

        self.bricks.append(brick)
        self._grid_add(brick)
        self.add_hierarchy_entry(brick, name="Baseplate")

        # Default spawn point: flat 4×4×0.5 brick centered on the baseplate
        sp = self.loader.loadModel("models/box")
        sp.reparentTo(self.render)
        sp.setScale(4, 4, 0.5)
        sp.setPos(-2, -2, 0.5)   # sits on top of baseplate surface (z=0.5)
        sp.setTextureOff(1)
        sp.hide()
        sp_col = (0.65, 0.65, 0.65, 1.0)
        sp_visual = self.create_solid_box(
            self.brick_base_width, self.brick_base_depth, self.brick_base_height, sp_col)
        sp_visual.reparentTo(self.render)
        self.brick_hitbox_visuals[sp]  = sp_visual
        self.brick_default_scale[sp]   = Vec3(sp.getScale())
        self.brick_colors[sp]          = sp_col
        self.update_brick_hitbox_visual_scale(sp, sp_visual)
        self.update_brick_collision(sp)
        self.brick_spawn_points.add(sp)
        self.bricks.append(sp)
        self._grid_add(sp)
        self.create_brick_blob_shadow(sp)
        self.add_hierarchy_entry(sp, name="SpawnPoint")

    def _rotated_surface_z(self, brick, px, py, clamp=False):
        """World Z of whichever OBB face is topmost at world XY (px, py).

        Uses a ray-slab intersection so the result is correct for any brick
        rotation — flipped bricks, 90° pitched bricks, etc. all work because
        we find the first face a downward ray hits rather than hard-coding
        local z=1 as the walkable face.

        clamp=True snaps the footprint coordinates to [0,1] with a small margin
        so edge/base approaches return the edge surface rather than None.
        """
        from panda3d.core import LMatrix4
        mat = brick.getMat()
        inv = LMatrix4()
        inv.invertAffineFrom(mat)

        # Transform world downward ray into brick local space
        ro = inv.xformPoint(Point3(px, py, 10000))
        rd = inv.xformVec(Vec3(0, 0, -1))

        # Slab intersection with unit cube [0,1]^3
        # Track which axis/face the ray enters from so we know which two
        # coordinates are the "footprint" dimensions to clamp.
        t_enter  = -1e18
        t_exit   =  1e18
        enter_ax = -1    # axis index (0=x,1=y,2=z) of the entry face
        enter_v  =  0.0  # face value (0.0 or 1.0) along that axis

        for i, (rdi, roi) in enumerate(((rd.x, ro.x), (rd.y, ro.y), (rd.z, ro.z))):
            if abs(rdi) < 1e-8:
                if roi < 0.0 or roi > 1.0:
                    return None   # ray parallel to slab and outside
                continue
            t0 = (0.0 - roi) / rdi   # t at face = 0
            t1 = (1.0 - roi) / rdi   # t at face = 1
            if t0 < t1:
                t_lo, t_hi, v_lo = t0, t1, 0.0   # enters from face=0 side
            else:
                t_lo, t_hi, v_lo = t1, t0, 1.0   # enters from face=1 side
            if t_lo > t_enter:
                t_enter  = t_lo
                enter_ax = i
                enter_v  = v_lo
            t_exit = min(t_exit, t_hi)

        if t_enter > t_exit or t_exit < 0.0:
            return None

        t = t_enter if t_enter >= 0.0 else t_exit
        if t < 0.0:
            return None

        lhit = [ro.x + rd.x * t, ro.y + rd.y * t, ro.z + rd.z * t]

        if clamp:
            MARGIN = 0.18
            for j in range(3):
                if j == enter_ax:
                    continue   # depth axis — fixed by the face, not a footprint coord
                if not (-MARGIN <= lhit[j] <= 1.0 + MARGIN):
                    return None
                lhit[j] = max(0.0, min(1.0, lhit[j]))
            lhit[enter_ax] = enter_v   # snap to exact face boundary
        else:
            for j in range(3):
                if not (0.0 <= lhit[j] <= 1.0):
                    return None

        return mat.xformPoint(Point3(lhit[0], lhit[1], lhit[2])).z

    def get_ground_height_at_position(self, pos):
        highest_z = None
        char_box  = self.get_character_collision_box(pos)
        cx_char   = char_box['center'].x
        cy_char   = char_box['center'].y
        no_col    = getattr(self, 'brick_no_collision', set())

        for brick in self._grid_nearby(pos, 15):
            if brick in no_col:
                continue
            hpr = brick.getHpr()
            if abs(hpr.x) < 0.5 and abs(hpr.y) < 0.5 and abs(hpr.z) < 0.5:
                # Axis-aligned fast path
                brick_box = self.get_brick_collision_box(brick)
                brick_top = brick_box['max_z']
                if (brick_top <= char_box['min_z'] + 0.1 and
                        abs(cx_char - brick_box['center'].x) < (char_box['half_width'] + brick_box['half_width']) and
                        abs(cy_char - brick_box['center'].y) < (char_box['half_depth'] + brick_box['half_depth'])):
                    if highest_z is None or brick_top > highest_z:
                        highest_z = brick_top
            else:
                # Rotated brick: clamp=True so edges don't disappear mid-step.
                surf_z = self._rotated_surface_z(brick, cx_char, cy_char, clamp=True)
                if surf_z is not None and surf_z <= char_box['min_z'] + 0.1:
                    if highest_z is None or surf_z > highest_z:
                        highest_z = surf_z

        return highest_z

    def _slope_lift_z(self, desired_pos, current_pos):
        """If desired_pos is inside a rotated brick (slope), return the Z the
        character should be lifted to so they walk up the surface instead of
        getting stuck.  Returns None if no slope applies."""
        MAX_STEP = 1.2
        char_box = self.get_character_collision_box(desired_pos)
        cx, cy   = char_box['center'].x, char_box['center'].y
        best_z   = None
        no_col   = getattr(self, 'brick_no_collision', set())
        for brick in self._grid_nearby(desired_pos, 15):
            if brick in no_col:
                continue
            hpr = brick.getHpr()
            if abs(hpr.x) < 0.5 and abs(hpr.y) < 0.5 and abs(hpr.z) < 0.5:
                continue
            # Wall planks have a local Z axis pointing sideways — they are not
            # walkable slopes.  Slope-walking on them lifts the player up the wall.
            if brick.getMat().xformVec(Vec3(0, 0, 1)).z < 0.3:
                continue
            surf_z = self._rotated_surface_z(brick, cx, cy, clamp=True)
            if surf_z is None or surf_z < current_pos.z - 0.1:
                continue
            if surf_z > current_pos.z + 3.0:  # cap: prevent side-approach teleport
                continue
            # At seam boundaries the character may not yet OBB-overlap the next
            # brick, but if its surface is within step range we should still lift.
            if not self._obb_aabb_collide(char_box, brick) and surf_z > current_pos.z + MAX_STEP:
                continue
            if best_z is None or surf_z < best_z:
                best_z = surf_z
        if best_z is None:
            return None
        lifted_z = min(best_z, current_pos.z + MAX_STEP)

        # Scale horizontal movement so 3D speed matches the intended flat-ground speed.
        # Without this the character travels speed*dt horizontally AND climbs vertically,
        # making them noticeably faster on steep slopes.
        dz  = lifted_z - current_pos.z
        dx  = desired_pos.x - current_pos.x
        dy  = desired_pos.y - current_pos.y
        dxy = _math.sqrt(dx * dx + dy * dy)
        if dxy > 1e-6 and abs(dz) > 1e-6:
            dist_3d = _math.sqrt(dxy * dxy + dz * dz)
            scale   = dxy / dist_3d   # = cos(slope_angle)
            return Vec3(current_pos.x + dx * scale,
                        current_pos.y + dy * scale,
                        lifted_z)
        return Vec3(desired_pos.x, desired_pos.y, lifted_z)

    def resolve_movement(self, desired_pos):
        if not self.is_playtest:
            return desired_pos

        current_pos = self.character.getPos()
        MAX_STEP    = 1.2
        on_ground   = not self.is_jumping and self.vertical_speed <= 0

        if not self.check_collision_at_position(desired_pos):
            return desired_pos

        # Slope-walk: lift character onto rotated-brick surface instead of blocking.
        # Validate that the lifted position is actually collision-free before using it —
        # wall geometry can produce a surf_z that lands the player inside another brick.
        if on_ground:
            slope_pos = self._slope_lift_z(desired_pos, current_pos)
            if slope_pos is not None and not self.check_collision_at_position(slope_pos):
                return slope_pos

        # Step-up only when grounded — a jumping player must be stopped by walls,
        # not slipped through the top of them when current_z + MAX_STEP clears.
        if on_ground and not self.check_collision_at_position(
                Vec3(desired_pos.x, desired_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(desired_pos.x, desired_pos.y, current_pos.z)

        # Axis-by-axis sliding, each with a grounded step-up fallback.
        test_x = Vec3(desired_pos.x, current_pos.y, current_pos.z)
        if not self.check_collision_at_position(test_x):
            return test_x
        if on_ground:
            slope_pos = self._slope_lift_z(test_x, current_pos)
            if slope_pos is not None and not self.check_collision_at_position(slope_pos):
                return slope_pos
        if on_ground and not self.check_collision_at_position(
                Vec3(desired_pos.x, current_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(desired_pos.x, current_pos.y, current_pos.z)

        test_y = Vec3(current_pos.x, desired_pos.y, current_pos.z)
        if not self.check_collision_at_position(test_y):
            return test_y
        if on_ground:
            slope_pos = self._slope_lift_z(test_y, current_pos)
            if slope_pos is not None and not self.check_collision_at_position(slope_pos):
                return slope_pos
        if on_ground and not self.check_collision_at_position(
                Vec3(current_pos.x, desired_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(current_pos.x, desired_pos.y, current_pos.z)

        # Auto-hop: when fully blocked on the ground, check if the obstacle
        # is short enough to hop over.  Fires a gentle upward push so the
        # character clears slope seams and low ledges without the player
        # needing to press jump.
        if on_ground:
            # AUTO_H must stay close to the actual jump apex (~1.2 units) so
            # the hop only fires for obstacles the player can genuinely clear.
            # A high value (e.g. 2.5) triggers on gaps in tall/complex geometry
            # and launches the player into walls they can't actually hop over.
            AUTO_H = MAX_STEP + 0.2
            for hop_test in (
                Vec3(desired_pos.x, desired_pos.y, current_pos.z + AUTO_H),
                Vec3(desired_pos.x, current_pos.y, current_pos.z + AUTO_H),
                Vec3(current_pos.x, desired_pos.y, current_pos.z + AUTO_H),
            ):
                if not self.check_collision_at_position(hop_test):
                    self.is_jumping    = True
                    self.vertical_speed = 22.0   # gentle hop, clears ~1.2 units
                    break

        return current_pos

    def insert_brick(self):
        brick = self.loader.loadModel("models/box")
        brick.reparentTo(self.render)
        brick.setScale(5, 3, 1)
        brick.setPos(self.camera.getPos() + self.camera.getQuat().getForward() * 5)
        brick.setTextureOff(1)
        brick.hide()

        brick_hitbox_visual = self.create_solid_box(
            self.brick_base_width, self.brick_base_depth, self.brick_base_height,
            (0.5, 0.5, 0.5, 0.7),
        )
        brick_hitbox_visual.reparentTo(self.render)
        self.brick_hitbox_visuals[brick] = brick_hitbox_visual
        self.brick_default_scale[brick] = Vec3(brick.getScale())
        self.brick_colors[brick]        = (0.5, 0.5, 0.5, 0.7)
        self.update_brick_hitbox_visual_scale(brick, brick_hitbox_visual)
        self.update_brick_collision(brick)
        self.bricks.append(brick)
        self._grid_add(brick)
        self.create_brick_blob_shadow(brick)
        self.add_hierarchy_entry(brick)
        def undo(b=brick):
            if b in self.selected_bricks:
                self.selected_bricks.remove(b)
            if self.selected_brick is b:
                self.selected_brick = self.selected_bricks[-1] if self.selected_bricks else None
            self._destroy_brick(b)
            self._refresh_hierarchy()
        self._push_undo(undo)

    def export_build(self):
        try:
            root = tk.Tk()
            root.withdraw()
            fn = filedialog.asksaveasfilename(
                defaultextension='.json',
                filetypes=[('JSON files', '*.json')],
                initialdir=str(Path.home() / 'Downloads'),
            )
            root.destroy()
            if not fn:
                return

            out = {'bricks': []}
            for brick in self.bricks:
                pos   = list(brick.getPos())
                s     = brick.getScale()
                scale = [s.x, s.y, s.z]
                col   = list(self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7)))
                if brick in self.brick_grass_shells:
                    tex = 'grass'
                elif brick in self.brick_wood_shells:
                    tex = 'wood'
                elif brick in self.brick_stone_shells:
                    tex = 'stone'
                else:
                    tex = 'plastic'
                hpr = brick.getHpr()
                out['bricks'].append({
                    'pos': pos, 'scale': scale, 'color': col, 'texture': tex,
                    'hpr': [hpr.x, hpr.y, hpr.z],
                    'spawn_point':   brick in self.brick_spawn_points,
                    'kill_brick':    brick in self.brick_kill_bricks,
                    'no_collision':  brick in self.brick_no_collision,
                })

            with open(fn, 'w') as f:
                json.dump(out, f, indent=2)
            print('Exported build to', fn)
        except Exception as e:
            print('Export failed:', e)

    def get_build_data(self):
        """Return a serialisable dict representing the current scene."""
        bricks = []
        for brick in self.bricks:
            pos = list(brick.getPos())
            s   = brick.getScale()
            col = list(self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7)))
            if brick in self.brick_grass_shells:
                tex = 'grass'
            elif brick in self.brick_wood_shells:
                tex = 'wood'
            elif brick in self.brick_stone_shells:
                tex = 'stone'
            else:
                tex = 'plastic'
            hpr = brick.getHpr()
            bricks.append({
                'pos': pos, 'scale': [s.x, s.y, s.z], 'color': col, 'texture': tex,
                'hpr': [hpr.x, hpr.y, hpr.z],
                'spawn_point':  brick in self.brick_spawn_points,
                'kill_brick':   brick in self.brick_kill_bricks,
                'no_collision': brick in self.brick_no_collision,
            })
        return {'bricks': bricks}

    def _clear_all_bricks(self):
        # Discard any stashed face-cull backups so orphaned nodes don't leak
        for backup in getattr(self, "_face_culled_backup", {}).values():
            for node in backup.values():
                if node and not node.isEmpty():
                    node.removeNode()
        self._face_culled_backup = {}
        self._was_playtest = False  # prevent _exit_playtest_face_cull from running next frame

        self.clear_selection()
        for b in list(self.bricks):
            vis = self.brick_hitbox_visuals.pop(b, None)
            if vis and not vis.isEmpty():
                vis.removeNode()
            cnode = self.brick_collision_nodes.pop(b, None)
            if cnode and not cnode.isEmpty():
                cnode.removeNode()
            shell = self.brick_grass_shells.pop(b, None)
            if shell and not shell.isEmpty():
                shell.removeNode()
            wshell = self.brick_wood_shells.pop(b, None)
            if wshell and not wshell.isEmpty():
                wshell.removeNode()
            sshell = self.brick_stone_shells.pop(b, None)
            if sshell and not sshell.isEmpty():
                sshell.removeNode()
            self.brick_default_scale.pop(b, None)
            self.brick_grass_color.pop(b, None)
            self.brick_wood_color.pop(b, None)
            self.brick_stone_color.pop(b, None)
            self.brick_last_scale.pop(b, None)
            self.brick_last_pos.pop(b, None)
            self.brick_colors.pop(b, None)
            self.brick_spawn_points.discard(b)
            self.brick_kill_bricks.discard(b)
            self.brick_no_collision.discard(b)
            self.remove_brick_blob_shadow(b)
            self.remove_hierarchy_entry(b)
            if b and not b.isEmpty():
                b.removeNode()
        self.bricks.clear()
        self._brick_grid.clear()
        self._brick_cells.clear()
        self._brick_counter = 0

    def _load_bricks_from_data(self, data):
        """Clear the scene and load bricks from a data dict."""
        self._clear_all_bricks()
        for bd in data.get('bricks', []):
            self.create_brick_from_data(bd)

    def import_build(self):
        try:
            root = tk.Tk()
            root.withdraw()
            fn = filedialog.askopenfilename(
                filetypes=[('JSON files', '*.json')],
                initialdir=str(Path.home() / 'Downloads'),
            )
            root.destroy()
            if not fn:
                return
            with open(fn, 'r') as f:
                data = json.load(f)
            self._load_bricks_from_data(data)
            print('Imported build from', fn)
        except Exception as e:
            print('Import failed:', e)

    def create_brick_from_data(self, bd):
        brick = self.loader.loadModel('models/box')
        brick.reparentTo(self.render)
        s = bd.get('scale', [5, 3, 1])
        brick.setScale(s[0], s[1], s[2])
        p = bd.get('pos', [0, 0, 0])
        try:
            brick.setPos(Vec3(p[0], p[1], p[2]))
        except Exception:
            brick.setPos(0, 0, 0)
        hpr = bd.get('hpr', [0, 0, 0])
        try:
            brick.setHpr(Vec3(hpr[0], hpr[1], hpr[2]))
        except Exception:
            brick.setHpr(Vec3(0, 0, 0))
        brick.setTextureOff(1)
        brick.hide()

        color   = tuple(bd.get('color',   [0.5, 0.5, 0.5, 0.7]))
        texture = bd.get('texture', 'plastic')

        visual = self.create_solid_box(
            self.brick_base_width, self.brick_base_depth, self.brick_base_height, color
        )
        visual.reparentTo(self.render)
        self.brick_hitbox_visuals[brick] = visual
        self.brick_default_scale[brick]  = Vec3(brick.getScale())
        self.brick_colors[brick]         = color
        self.update_brick_hitbox_visual_scale(brick, visual)
        self.update_brick_collision(brick)
        self.bricks.append(brick)
        self._grid_add(brick)
        self.create_brick_blob_shadow(brick)
        self.add_hierarchy_entry(brick)

        if texture == 'grass':
            self.brick_grass_color[brick] = color
            self.apply_texture_to_brick(brick, 'grass')
        elif texture == 'wood':
            self.brick_wood_color[brick] = color
            self.apply_texture_to_brick(brick, 'wood')
        elif texture == 'stone':
            self.brick_stone_color[brick] = color
            self.apply_texture_to_brick(brick, 'stone')

        if bd.get('spawn_point'):
            self.brick_spawn_points.add(brick)
        if bd.get('kill_brick'):
            self.brick_kill_bricks.add(brick)
        if bd.get('no_collision'):
            self.brick_no_collision.add(brick)

        return brick

    def _push_undo(self, action):
        self._undo_stack.append(action)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _undo(self):
        if self._undo_stack and not self.is_playtest:
            self._undo_stack.pop()()

    def _destroy_brick(self, brick):
        """Remove a single brick from the scene without touching selection state."""
        vis = self.brick_hitbox_visuals.pop(brick, None)
        if vis and not vis.isEmpty():
            vis.removeNode()
        cnode = self.brick_collision_nodes.pop(brick, None)
        if cnode and not cnode.isEmpty():
            cnode.removeNode()
        shell = self.brick_grass_shells.pop(brick, None)
        if shell and not shell.isEmpty():
            shell.removeNode()
        wshell = self.brick_wood_shells.pop(brick, None)
        if wshell and not wshell.isEmpty():
            wshell.removeNode()
        sshell = self.brick_stone_shells.pop(brick, None)
        if sshell and not sshell.isEmpty():
            sshell.removeNode()
        self.brick_default_scale.pop(brick, None)
        self.brick_grass_color.pop(brick, None)
        self.brick_wood_color.pop(brick, None)
        self.brick_stone_color.pop(brick, None)
        self.brick_last_scale.pop(brick, None)
        self.brick_last_pos.pop(brick, None)
        self.brick_colors.pop(brick, None)
        self.brick_spawn_points.discard(brick)
        self.brick_kill_bricks.discard(brick)
        self.brick_no_collision.discard(brick)
        self._grid_remove(brick)
        self.remove_brick_blob_shadow(brick)
        self.remove_hierarchy_entry(brick)
        if brick in self.bricks:
            self.bricks.remove(brick)
        if not brick.isEmpty():
            brick.removeNode()

    def _delete_selection(self):
        if not self.selected_bricks or self.is_playtest:
            return
        # Snapshot brick data before destroying so undo can recreate them.
        snapshots = []
        for brick in self.selected_bricks:
            pos = brick.getPos()
            s   = brick.getScale()
            hpr = brick.getHpr()
            col = self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7))
            if brick in self.brick_grass_shells:   tex = 'grass'
            elif brick in self.brick_wood_shells:  tex = 'wood'
            elif brick in self.brick_stone_shells: tex = 'stone'
            else:                                  tex = 'plastic'
            snapshots.append({'pos': [pos.x, pos.y, pos.z],
                               'scale': [s.x, s.y, s.z],
                               'hpr': [hpr.x, hpr.y, hpr.z],
                               'color': list(col), 'texture': tex,
                               'spawn_point':  brick in self.brick_spawn_points,
                               'kill_brick':   brick in self.brick_kill_bricks,
                               'no_collision': brick in self.brick_no_collision})
        to_delete = list(self.selected_bricks)
        self.clear_selection()
        for brick in to_delete:
            self._destroy_brick(brick)
        def undo(snaps=snapshots):
            new_bricks = [self.create_brick_from_data(bd) for bd in snaps]
            self.clear_selection()
            self.selected_bricks = new_bricks
            self.selected_brick  = new_bricks[-1]
            self._create_selection_outline()
            if self.is_move_mode:
                self.create_move_handles()
            if len(new_bricks) == 1:
                self._show_inspector(new_bricks[0])
            else:
                self._show_inspector_multi(len(new_bricks))
            self._refresh_hierarchy()
        self._push_undo(undo)

    def _copy_selection(self):
        if not self.selected_bricks or self.is_playtest:
            return
        self._copy_clipboard = []
        for brick in self.selected_bricks:
            pos = brick.getPos()
            s   = brick.getScale()
            hpr = brick.getHpr()
            col = self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7))
            if brick in self.brick_grass_shells:   tex = 'grass'
            elif brick in self.brick_wood_shells:  tex = 'wood'
            elif brick in self.brick_stone_shells: tex = 'stone'
            else:                                  tex = 'plastic'
            self._copy_clipboard.append({
                'pos':     [pos.x, pos.y, pos.z],
                'scale':   [s.x, s.y, s.z],
                'hpr':     [hpr.x, hpr.y, hpr.z],
                'color':   list(col),
                'texture': tex,
                'spawn_point':  brick in self.brick_spawn_points,
                'kill_brick':   brick in self.brick_kill_bricks,
                'no_collision': brick in self.brick_no_collision,
            })

    def _paste_selection(self):
        if not self._copy_clipboard or self.is_playtest:
            return
        new_bricks = []
        for bd in self._copy_clipboard:
            new_bricks.append(self.create_brick_from_data(bd))

        # Select all pasted bricks
        self.clear_selection()
        self.selected_bricks = list(new_bricks)
        self.selected_brick  = new_bricks[-1]
        self._create_selection_outline()
        if self.is_move_mode:
            self.create_move_handles()
        if len(new_bricks) == 1:
            self._show_inspector(new_bricks[0])
        else:
            self._show_inspector_multi(len(new_bricks))
        self._refresh_hierarchy()
        # Paste pushes its own undo entry (overrides the per-brick ones added by create_brick_from_data)
        for _ in new_bricks:
            self._undo_stack.pop() if self._undo_stack else None
        def undo(nb=list(new_bricks)):
            self.clear_selection()
            for b in nb:
                self._destroy_brick(b)
            self._refresh_hierarchy()
        self._push_undo(undo)

    # ── Face culling ──────────────────────────────────────────────────────────

    def _get_brick_bounds_aa(self, brick):
        """World AABB for an axis-aligned brick, or None if rotated."""
        hpr = brick.getHpr()
        if abs(hpr.x) > 0.5 or abs(hpr.y) > 0.5 or abs(hpr.z) > 0.5:
            return None
        p = brick.getPos(); s = brick.getScale()
        return p.x, p.x + s.x, p.y, p.y + s.y, p.z, p.z + s.z

    def _compute_visible_faces(self, brick):
        """Return frozenset of face indices not fully occluded by a single neighbor.
        Indices: 0=bottom(-Z) 1=top(+Z) 2=front(-Y) 3=back(+Y) 4=left(-X) 5=right(+X)"""
        b = self._get_brick_bounds_aa(brick)
        if b is None:
            return frozenset(range(6))
        ax0, ax1, ay0, ay1, az0, az1 = b
        EPS = 0.05
        p = brick.getPos(); s = brick.getScale()
        center = Vec3(p.x + s.x * 0.5, p.y + s.y * 0.5, p.z + s.z * 0.5)
        radius = max(s.x, s.y, s.z) * 2 + _GRID_CELL
        visible = set(range(6))
        for nb in self._grid_nearby(center, radius):
            if nb is brick or not visible:
                continue
            nb_b = self._get_brick_bounds_aa(nb)
            if nb_b is None:
                continue
            bx0, bx1, by0, by1, bz0, bz1 = nb_b
            if 0 in visible and abs(bz1 - az0) < EPS and bx0 <= ax0 + EPS and bx1 >= ax1 - EPS and by0 <= ay0 + EPS and by1 >= ay1 - EPS:
                visible.discard(0)
            if 1 in visible and abs(bz0 - az1) < EPS and bx0 <= ax0 + EPS and bx1 >= ax1 - EPS and by0 <= ay0 + EPS and by1 >= ay1 - EPS:
                visible.discard(1)
            if 2 in visible and abs(by1 - ay0) < EPS and bx0 <= ax0 + EPS and bx1 >= ax1 - EPS and bz0 <= az0 + EPS and bz1 >= az1 - EPS:
                visible.discard(2)
            if 3 in visible and abs(by0 - ay1) < EPS and bx0 <= ax0 + EPS and bx1 >= ax1 - EPS and bz0 <= az0 + EPS and bz1 >= az1 - EPS:
                visible.discard(3)
            if 4 in visible and abs(bx1 - ax0) < EPS and by0 <= ay0 + EPS and by1 >= ay1 - EPS and bz0 <= az0 + EPS and bz1 >= az1 - EPS:
                visible.discard(4)
            if 5 in visible and abs(bx0 - ax1) < EPS and by0 <= ay0 + EPS and by1 >= ay1 - EPS and bz0 <= az0 + EPS and bz1 >= az1 - EPS:
                visible.discard(5)
        return frozenset(visible)

    def _enter_playtest_face_cull(self):
        self._face_culled_backup = {}
        for brick in self.bricks:
            visible = self._compute_visible_faces(brick)
            if len(visible) == 6:
                continue
            hidden = {i for i in range(6) if i not in visible}
            backup = {}

            # Solid-colour visual
            old_vis = self.brick_hitbox_visuals.get(brick)
            if old_vis and not old_vis.isEmpty():
                col = self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7))
                new_vis = self.create_solid_box(
                    self.brick_base_width, self.brick_base_depth, self.brick_base_height,
                    col, visible_faces=visible)
                new_vis.reparentTo(self.render)
                self.update_brick_hitbox_visual_scale(brick, new_vis)
                old_vis.stash()
                self.brick_hitbox_visuals[brick] = new_vis
                backup['vis'] = old_vis

            # Grass shell
            old_g = self.brick_grass_shells.get(brick)
            if old_g and not old_g.isEmpty():
                s = brick.getScale(); h = brick.getHpr()
                wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                new_g = self._create_grass_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z, hidden_faces=hidden)
                new_g.setShaderInput('brickColor', Vec4(*self.brick_grass_color.get(brick, (0.15, 0.49, 0.19, 1.0))))
                new_g.reparentTo(self.render); new_g.setPos(Vec3(wc)); new_g.setHpr(h)
                old_g.stash()
                self.brick_grass_shells[brick] = new_g
                backup['grass'] = old_g

            # Wood shell
            old_w = self.brick_wood_shells.get(brick)
            if old_w and not old_w.isEmpty():
                s = brick.getScale(); h = brick.getHpr()
                wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                new_w = self._create_wood_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z, hidden_faces=hidden)
                new_w.setShaderInput('brickColor', Vec4(*self.brick_wood_color.get(brick, (0.80, 0.60, 0.35, 1.0))))
                new_w.reparentTo(self.render); new_w.setPos(Vec3(wc)); new_w.setHpr(h)
                old_w.stash()
                self.brick_wood_shells[brick] = new_w
                backup['wood'] = old_w

            # Stone shell
            old_s = self.brick_stone_shells.get(brick)
            if old_s and not old_s.isEmpty():
                s = brick.getScale(); h = brick.getHpr()
                wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                new_s = self._create_stone_shell(cx=0, cy=0, cz=0, sx=s.x, sy=s.y, sz=s.z, hidden_faces=hidden)
                new_s.setShaderInput('brickColor', Vec4(*self.brick_stone_color.get(brick, (0.75, 0.72, 0.68, 1.0))))
                new_s.reparentTo(self.render); new_s.setPos(Vec3(wc)); new_s.setHpr(h)
                old_s.stash()
                self.brick_stone_shells[brick] = new_s
                backup['stone'] = old_s

            if backup:
                self._face_culled_backup[brick] = backup

    def _exit_playtest_face_cull(self):
        for brick, backup in self._face_culled_backup.items():
            if 'vis' in backup:
                cur = self.brick_hitbox_visuals.get(brick)
                if cur and not cur.isEmpty():
                    cur.removeNode()
                orig = backup['vis']
                orig.unstash()
                self.brick_hitbox_visuals[brick] = orig
            if 'grass' in backup:
                cur = self.brick_grass_shells.get(brick)
                if cur and not cur.isEmpty():
                    cur.removeNode()
                orig = backup['grass']
                orig.unstash()
                self.brick_grass_shells[brick] = orig
            if 'wood' in backup:
                cur = self.brick_wood_shells.get(brick)
                if cur and not cur.isEmpty():
                    cur.removeNode()
                orig = backup['wood']
                orig.unstash()
                self.brick_wood_shells[brick] = orig
            if 'stone' in backup:
                cur = self.brick_stone_shells.get(brick)
                if cur and not cur.isEmpty():
                    cur.removeNode()
                orig = backup['stone']
                orig.unstash()
                self.brick_stone_shells[brick] = orig
        self._face_culled_backup = {}

    def updateVisualHitboxes(self, task):
        if self.is_playtest and not self._was_playtest:
            self._enter_playtest_face_cull()
        if not self.is_playtest and self._was_playtest:
            self._exit_playtest_face_cull()
            self._restore_all_brick_visibility()
        self._was_playtest = self.is_playtest

        if self.is_playtest:
            # Bricks never move during playtest — skip all O(N) editor loops
            if task.frame % 20 == 0:
                self._cull_brick_visibility()
            return Task.cont

        # ── Editor mode only below this point ────────────────────────────────
        for brick, visual in self.brick_hitbox_visuals.items():
            if brick.isEmpty():
                continue
            self.update_brick_hitbox_visual_scale(brick, visual)
        for brick in list(self.brick_grass_shells.keys()):
            if brick.isEmpty():
                continue
            s = brick.getScale()
            p = brick.getPos()
            h = brick.getHpr()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            lh = self.brick_last_hpr.get(brick)
            if ls is None or s.x != ls.x or s.y != ls.y or s.z != ls.z:
                self._rebuild_grass_shell(brick)
            elif (lp is None or p.x != lp.x or p.y != lp.y or p.z != lp.z or
                  lh is None or h.x != lh.x or h.y != lh.y or h.z != lh.z):
                sh = self.brick_grass_shells[brick]
                if sh and not sh.isEmpty():
                    wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                    sh.setPos(Vec3(wc)); sh.setHpr(h)
                self.brick_last_pos[brick] = Vec3(p)
                self.brick_last_hpr[brick] = Vec3(h)
        for brick in list(self.brick_wood_shells.keys()):
            if brick.isEmpty():
                continue
            s = brick.getScale()
            p = brick.getPos()
            h = brick.getHpr()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            lh = self.brick_last_hpr.get(brick)
            if ls is None or s.x != ls.x or s.y != ls.y or s.z != ls.z:
                self._rebuild_wood_shell(brick)
            elif (lp is None or p.x != lp.x or p.y != lp.y or p.z != lp.z or
                  lh is None or h.x != lh.x or h.y != lh.y or h.z != lh.z):
                sh = self.brick_wood_shells[brick]
                if sh and not sh.isEmpty():
                    wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                    sh.setPos(Vec3(wc)); sh.setHpr(h)
                self.brick_last_pos[brick] = Vec3(p)
                self.brick_last_hpr[brick] = Vec3(h)
        for brick in list(self.brick_stone_shells.keys()):
            if brick.isEmpty():
                continue
            s = brick.getScale()
            p = brick.getPos()
            h = brick.getHpr()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            lh = self.brick_last_hpr.get(brick)
            if ls is None or s.x != ls.x or s.y != ls.y or s.z != ls.z:
                self._rebuild_stone_shell(brick)
            elif (lp is None or p.x != lp.x or p.y != lp.y or p.z != lp.z or
                  lh is None or h.x != lh.x or h.y != lh.y or h.z != lh.z):
                sh = self.brick_stone_shells[brick]
                if sh and not sh.isEmpty():
                    wc = brick.getMat().xformPoint(Point3(0.5, 0.5, 0.5))
                    sh.setPos(Vec3(wc)); sh.setHpr(h)
                self.brick_last_pos[brick] = Vec3(p)
                self.brick_last_hpr[brick] = Vec3(h)
        return Task.cont
