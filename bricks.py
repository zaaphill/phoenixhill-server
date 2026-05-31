from panda3d.core import (
    CollisionNode, CollisionBox, BitMask32, Point3, Vec3, Vec4,
    GeomVertexFormat, GeomVertexData, Geom,
    GeomVertexWriter, GeomTriangles, GeomNode, NodePath,
    Texture, Shader,
)
from direct.task import Task
import json
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
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec2 p3d_MultiTexCoord0;
out vec2 uv;
out vec3 vNormal;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv      = p3d_MultiTexCoord0;
    vNormal = p3d_Normal;
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
        self.brick_colors         = {}   # tracks current color for every brick
        self.brick_spawn_points   = set()
        self._grass_tex           = None
        self._grass_shader        = None
        self._wood_tex            = None
        self._wood_shader         = None
        self._stone_tex           = None
        self._stone_shader        = None
        self._was_playtest        = False
        if not hasattr(self, '_settings_render_distance'):
            self._settings_render_distance = 1000

    # ── Spatial grid ──────────────────────────────────────────────────────────

    def _grid_cells_for(self, brick):
        p, s = brick.getPos(), brick.getScale()
        cx0, cx1 = int(p.x / _GRID_CELL), int((p.x + s.x) / _GRID_CELL)
        cy0, cy1 = int(p.y / _GRID_CELL), int((p.y + s.y) / _GRID_CELL)
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
            p = brick.getPos()
            s = brick.getScale()
            # AABB closest-point distance so large bricks are never culled when player is on them
            dx = max(p.x - cp.x, 0.0, cp.x - (p.x + s.x))
            dy = max(p.y - cp.y, 0.0, cp.y - (p.y + s.y))
            dz = max(p.z - cp.z, 0.0, cp.z - (p.z + s.z))
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

    def create_solid_box(self, width, depth, height, color):
        vformat = GeomVertexFormat.get_v3n3c4()
        vdata = GeomVertexData('solid_box', vformat, Geom.UH_static)

        vertex       = GeomVertexWriter(vdata, 'vertex')
        normal_writer = GeomVertexWriter(vdata, 'normal')
        color_writer  = GeomVertexWriter(vdata, 'color')

        hw = width  / 2.0
        hd = depth  / 2.0
        hh = height / 2.0

        corners = [
            (-hw, -hd, -hh), ( hw, -hd, -hh), ( hw,  hd, -hh), (-hw,  hd, -hh),
            (-hw, -hd,  hh), ( hw, -hd,  hh), ( hw,  hd,  hh), (-hw,  hd,  hh),
        ]

        faces = [
            ((0, 1, 2, 3), (0,  0, -1)),
            ((4, 5, 6, 7), (0,  0,  1)),
            ((0, 4, 5, 1), (0, -1,  0)),
            ((3, 7, 6, 2), (0,  1,  0)),
            ((0, 3, 7, 4), (-1, 0,  0)),
            ((1, 5, 6, 2), (1,  0,  0)),
        ]

        vert_normals = [Vec3(0, 0, 0) for _ in range(8)]
        for inds, fnormal in faces:
            fn = Vec3(fnormal[0], fnormal[1], fnormal[2])
            for i in inds:
                vert_normals[i] += fn
        for i in range(8):
            n = vert_normals[i]
            if n.lengthSquared() == 0:
                n = Vec3(0, 0, 1)
            else:
                n.normalize()
            vert_normals[i] = n

        for i, pos in enumerate(corners):
            vertex.add_data3(pos[0], pos[1], pos[2])
            n = vert_normals[i]
            normal_writer.add_data3(n.x, n.y, n.z)
            color_writer.add_data4(color[0], color[1], color[2], color[3])

        tris = GeomTriangles(Geom.UH_static)
        for inds, _ in faces:
            a, b, c, d = inds
            tris.add_vertices(a, b, c)
            tris.add_vertices(a, c, d)

        geom = Geom(vdata)
        geom.add_primitive(tris)

        node = GeomNode('solid_box')
        node.add_geom(geom)

        np = NodePath(node)
        np.setTwoSided(True)
        np.setShaderOff()
        return np

    def update_brick_hitbox_visual_scale(self, brick, visual):
        """Reposition and rescale the visual solid to match the brick's world bounds.

        The visual geometry is a box centered at origin with half-extents
        (bw/2, bd/2, bh/2) in local space.  Scaling it by (bx/bw, by/bd, bz/bh)
        makes its world size exactly (bx, by, bz), and placing it at the brick's
        world center keeps it perfectly aligned.
        """
        pos = brick.getPos()
        s   = brick.getScale()
        visual.setPos(pos.x + s.x * 0.5, pos.y + s.y * 0.5, pos.z + s.z * 0.5)
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

    def check_collision_at_position(self, pos):
        char_box = self.get_character_collision_box(pos)
        for brick in self._grid_nearby(pos, 15):
            brick_box = self.get_brick_collision_box(brick)
            if brick_box['max_z'] <= pos.z + 0.05:
                continue
            if self.boxes_collide(char_box, brick_box):
                return True
        return False

    def _create_grass_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1):
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

        # Top
        quad([(x0,y0,z1, 0,0),(x1,y0,z1, ttx,0),(x1,y1,z1, ttx,tty),(x0,y1,z1, 0,tty)],
             0, 0, 1)
        # Bottom
        quad([(x0,y0,z0, 0,0),(x0,y1,z0, 0,tty),(x1,y1,z0, ttx,tty),(x1,y0,z0, ttx,0)],
             0, 0, -1)
        # Front (+Y)
        quad([(x0,y1,z0, 0,0),(x1,y1,z0, tsx,0),(x1,y1,z1, tsx,tsh),(x0,y1,z1, 0,tsh)],
             0, 1, 0)
        # Back (-Y)
        quad([(x1,y0,z0, 0,0),(x0,y0,z0, tsx,0),(x0,y0,z1, tsx,tsh),(x1,y0,z1, 0,tsh)],
             0, -1, 0)
        # Right (+X)
        quad([(x1,y1,z0, 0,0),(x1,y0,z0, tsy,0),(x1,y0,z1, tsy,tsh),(x1,y1,z1, 0,tsh)],
             1, 0, 0)
        # Left (-X)
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
        s  = brick.getScale()
        p  = brick.getPos()
        cx = p.x + s.x / 2
        cy = p.y + s.y / 2
        cz = p.z + s.z / 2
        grass = self._create_grass_shell(cx=cx, cy=cy, cz=cz, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_grass_color.get(brick, (0.40, 0.80, 0.55, 1.0))
        grass.setShaderInput('brickColor', Vec4(*color))
        grass.reparentTo(self.render)
        self.brick_grass_shells[brick] = grass
        self.brick_last_scale[brick]   = Vec3(s)
        self.brick_last_pos[brick]     = Vec3(p)

    def _create_wood_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1):
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

        quad([(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)], (0,0,1),  [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        quad([(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)], (0,0,-1), [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        quad([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)], (0,-1,0), [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        quad([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)], (0,1,0),  [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        quad([(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)], (-1,0,0), [(0,0),(tty,0),(tty,ttz),(0,ttz)])
        quad([(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)], (1,0,0),  [(0,0),(tty,0),(tty,ttz),(0,ttz)])

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
        s  = brick.getScale()
        p  = brick.getPos()
        cx = p.x + s.x / 2
        cy = p.y + s.y / 2
        cz = p.z + s.z / 2
        wood = self._create_wood_shell(cx=cx, cy=cy, cz=cz, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_wood_color.get(brick, (0.80, 0.60, 0.35, 1.0))
        wood.setShaderInput('brickColor', Vec4(*color))
        wood.reparentTo(self.render)
        self.brick_wood_shells[brick] = wood
        self.brick_last_scale[brick]  = Vec3(s)
        self.brick_last_pos[brick]    = Vec3(p)

    def _create_stone_shell(self, cx=0, cy=0, cz=0, sx=50, sy=50, sz=1):
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

        quad([(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)], (0,0,1),  [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        quad([(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)], (0,0,-1), [(0,0),(ttx,0),(ttx,tty),(0,tty)])
        quad([(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)], (0,-1,0), [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        quad([(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)], (0,1,0),  [(0,0),(ttx,0),(ttx,ttz),(0,ttz)])
        quad([(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)], (-1,0,0), [(0,0),(tty,0),(tty,ttz),(0,ttz)])
        quad([(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)], (1,0,0),  [(0,0),(tty,0),(tty,ttz),(0,ttz)])

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
        s  = brick.getScale()
        p  = brick.getPos()
        cx = p.x + s.x / 2
        cy = p.y + s.y / 2
        cz = p.z + s.z / 2
        stone = self._create_stone_shell(cx=cx, cy=cy, cz=cz, sx=s.x, sy=s.y, sz=s.z)
        color = self.brick_stone_color.get(brick, (0.75, 0.72, 0.68, 1.0))
        stone.setShaderInput('brickColor', Vec4(*color))
        stone.reparentTo(self.render)
        self.brick_stone_shells[brick] = stone
        self.brick_last_scale[brick]   = Vec3(s)
        self.brick_last_pos[brick]     = Vec3(p)

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
        self.brick_grass_color[brick] = (0.42, 0.78, 0.28, 1.0)
        self.brick_colors[brick]      = (0.42, 0.78, 0.28, 1.0)
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

    def get_ground_height_at_position(self, pos):
        highest_z = None
        char_box = self.get_character_collision_box(pos)

        for brick in self._grid_nearby(pos, 15):
            brick_box = self.get_brick_collision_box(brick)
            brick_top = brick_box['max_z']

            if (brick_top <= char_box['min_z'] + 0.1 and
                    abs(char_box['center'].x - brick_box['center'].x) < (char_box['half_width'] + brick_box['half_width']) and
                    abs(char_box['center'].y - brick_box['center'].y) < (char_box['half_depth'] + brick_box['half_depth'])):
                if highest_z is None or brick_top > highest_z:
                    highest_z = brick_top

        return highest_z

    def resolve_movement(self, desired_pos):
        if not self.is_playtest:
            return desired_pos

        current_pos = self.character.getPos()
        MAX_STEP    = 1.2
        on_ground   = not self.is_jumping and self.vertical_speed <= 0

        if not self.check_collision_at_position(desired_pos):
            return desired_pos

        # Step-up only when grounded — a jumping player must be stopped by walls,
        # not slipped through the top of them when current_z + MAX_STEP clears.
        if on_ground and not self.check_collision_at_position(
                Vec3(desired_pos.x, desired_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(desired_pos.x, desired_pos.y, current_pos.z)

        # Axis-by-axis sliding, each with a grounded step-up fallback.
        test_x = Vec3(desired_pos.x, current_pos.y, current_pos.z)
        if not self.check_collision_at_position(test_x):
            return test_x
        if on_ground and not self.check_collision_at_position(
                Vec3(desired_pos.x, current_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(desired_pos.x, current_pos.y, current_pos.z)

        test_y = Vec3(current_pos.x, desired_pos.y, current_pos.z)
        if not self.check_collision_at_position(test_y):
            return test_y
        if on_ground and not self.check_collision_at_position(
                Vec3(current_pos.x, desired_pos.y, current_pos.z + MAX_STEP)):
            return Vec3(current_pos.x, desired_pos.y, current_pos.z)

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
                out['bricks'].append({
                    'pos': pos, 'scale': scale, 'color': col, 'texture': tex,
                    'spawn_point': brick in self.brick_spawn_points,
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
            bricks.append({
                'pos': pos, 'scale': [s.x, s.y, s.z], 'color': col, 'texture': tex,
                'spawn_point': brick in self.brick_spawn_points,
            })
        return {'bricks': bricks}

    def _clear_all_bricks(self):
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
            self.remove_brick_blob_shadow(b)
            self.remove_hierarchy_entry(b)
            if b and not b.isEmpty():
                b.removeNode()
        self.bricks.clear()
        self._brick_grid.clear()
        self._brick_cells.clear()

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
            col = self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7))
            tex = 'grass' if brick in self.brick_grass_shells else 'plastic'
            snapshots.append({'pos': [pos.x, pos.y, pos.z],
                               'scale': [s.x, s.y, s.z],
                               'color': list(col), 'texture': tex,
                               'spawn_point': brick in self.brick_spawn_points})
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
            col = self.brick_colors.get(brick, (0.5, 0.5, 0.5, 0.7))
            tex = 'grass' if brick in self.brick_grass_shells else 'plastic'
            self._copy_clipboard.append({
                'pos':     [pos.x, pos.y, pos.z],
                'scale':   [s.x, s.y, s.z],
                'color':   list(col),
                'texture': tex,
                'spawn_point': brick in self.brick_spawn_points,
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

    def updateVisualHitboxes(self, task):
        # Restore visibility when returning from playtest to editor
        if not self.is_playtest and self._was_playtest:
            self._restore_all_brick_visibility()
        self._was_playtest = self.is_playtest

        if self.is_playtest:
            # Bricks never move during playtest — skip all O(N) editor loops
            if task.frame % 20 == 0:
                self._cull_brick_visibility()
            return Task.cont

        # ── Editor mode only below this point ────────────────────────────────
        for brick, visual in self.brick_hitbox_visuals.items():
            self.update_brick_hitbox_visual_scale(brick, visual)
        for brick in list(self.brick_grass_shells.keys()):
            s = brick.getScale()
            p = brick.getPos()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            if (ls is None or lp is None
                    or s.x != ls.x or s.y != ls.y or s.z != ls.z
                    or p.x != lp.x or p.y != lp.y or p.z != lp.z):
                self._rebuild_grass_shell(brick)
        for brick in list(self.brick_wood_shells.keys()):
            s = brick.getScale()
            p = brick.getPos()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            if (ls is None or lp is None
                    or s.x != ls.x or s.y != ls.y or s.z != ls.z
                    or p.x != lp.x or p.y != lp.y or p.z != lp.z):
                self._rebuild_wood_shell(brick)
        for brick in list(self.brick_stone_shells.keys()):
            s = brick.getScale()
            p = brick.getPos()
            ls = self.brick_last_scale.get(brick)
            lp = self.brick_last_pos.get(brick)
            if (ls is None or lp is None
                    or s.x != ls.x or s.y != ls.y or s.z != ls.z
                    or p.x != lp.x or p.y != lp.y or p.z != lp.z):
                self._rebuild_stone_shell(brick)
        return Task.cont
