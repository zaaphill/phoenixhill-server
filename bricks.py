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
        self.brick_last_scale     = {}
        self.brick_last_pos       = {}
        self.brick_colors         = {}   # tracks current color for every brick
        self._grass_tex           = None
        self._grass_shader        = None

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
        for brick in self.bricks:
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
        self.add_hierarchy_entry(brick, name="Baseplate")

    def get_ground_height_at_position(self, pos):
        highest_z = -9999.0
        char_box = self.get_character_collision_box(pos)

        for brick in self.bricks:
            brick_box = self.get_brick_collision_box(brick)
            brick_top = brick_box['max_z']

            if (brick_top <= char_box['min_z'] + 0.1 and
                    abs(char_box['center'].x - brick_box['center'].x) < (char_box['half_width'] + brick_box['half_width']) and
                    abs(char_box['center'].y - brick_box['center'].y) < (char_box['half_depth'] + brick_box['half_depth'])):
                if brick_top > highest_z:
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
        self.create_brick_blob_shadow(brick)
        self.add_hierarchy_entry(brick)

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
                tex   = 'grass' if brick in self.brick_grass_shells else 'plastic'
                out['bricks'].append({
                    'pos': pos, 'scale': scale, 'color': col, 'texture': tex,
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
            tex = 'grass' if brick in self.brick_grass_shells else 'plastic'
            bricks.append({'pos': pos, 'scale': [s.x, s.y, s.z], 'color': col, 'texture': tex})
        return {'bricks': bricks}

    def _clear_all_bricks(self):
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
            self.brick_default_scale.pop(b, None)
            self.brick_grass_color.pop(b, None)
            self.brick_last_scale.pop(b, None)
            self.brick_last_pos.pop(b, None)
            self.brick_colors.pop(b, None)
            self.remove_brick_blob_shadow(b)
            self.remove_hierarchy_entry(b)
            if b and not b.isEmpty():
                b.removeNode()
        self.bricks.clear()

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
        self.create_brick_blob_shadow(brick)
        self.add_hierarchy_entry(brick)

        if texture == 'grass':
            self.brick_grass_color[brick] = color
            self.apply_texture_to_brick(brick, 'grass')

    def updateVisualHitboxes(self, task):
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
        return Task.cont
