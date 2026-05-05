from panda3d.core import CardMaker, TransparencyAttrib, PNMImage, Texture
from direct.task import Task


class ShadowMixin:
    def setup_blob_shadows(self):
        self.blob_shadow_tex = self._make_blob_texture()
        self.brick_blob_shadows = {}
        self.char_shadow = self._create_shadow_card()
        self.taskMgr.add(self.update_blob_shadows_task, "updateBlobShadowsTask")

    def _make_blob_texture(self):
        size = 64
        img = PNMImage(size, size, 4)
        img.fill(0, 0, 0)
        img.alpha_fill(0)
        cx = cy = size / 2.0
        r  = size / 2.0
        for y in range(size):
            for x in range(size):
                dx = abs(x + 0.5 - cx) / r   # 0 at center, 1 at edge
                dy = abs(y + 0.5 - cy) / r
                # Independent per-axis linear fade, multiplied together.
                # Avoids the diagonal seam that Chebyshev/Euclidean distance
                # creates, and stretches naturally to match any card aspect ratio.
                alpha = max(0.0, 1.0 - dx) * max(0.0, 1.0 - dy)
                img.set_alpha(x, y, alpha)
        tex = Texture("blob_shadow")
        tex.load(img)
        tex.setWrapU(Texture.WMClamp)
        tex.setWrapV(Texture.WMClamp)
        return tex

    def _create_shadow_card(self):
        """1×1 unit card. Callers size it with setScale(world_x, 1, world_y)."""
        cm = CardMaker("blob_shadow")
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        card = self.render.attachNewNode(cm.generate())
        card.setP(-90)
        card.setColor(0, 0, 0, 0.35)
        card.setTransparency(TransparencyAttrib.MAlpha)
        card.setLightOff()
        card.setShaderOff()
        card.setDepthWrite(False)
        card.setTexture(self.blob_shadow_tex)
        card.setBin("transparent", 0)
        return card

    def _get_shadow_region(self, brick_box):
        """Intersect the shadow footprint with every ground brick below and
        return (cx, cy, w, d, ground_h) for the union bounding box, or None
        if there is no ground at all under this brick."""
        PAD = 1.1
        s_x0 = brick_box['center'].x - brick_box['half_width']  * PAD
        s_x1 = brick_box['center'].x + brick_box['half_width']  * PAD
        s_y0 = brick_box['center'].y - brick_box['half_depth']  * PAD
        s_y1 = brick_box['center'].y + brick_box['half_depth']  * PAD
        above_z = brick_box['min_z']

        best_ground = -9999.0
        u_x0, u_x1 = s_x1, s_x0   # start inverted; union expands outward
        u_y0, u_y1 = s_y1, s_y0
        found = False

        for other in self.bricks:
            box = self.get_brick_collision_box(other)
            if box['max_z'] >= above_z - 0.1:
                continue
            g_x0 = box['center'].x - box['half_width']
            g_x1 = box['center'].x + box['half_width']
            g_y0 = box['center'].y - box['half_depth']
            g_y1 = box['center'].y + box['half_depth']
            ix0 = max(s_x0, g_x0);  ix1 = min(s_x1, g_x1)
            iy0 = max(s_y0, g_y0);  iy1 = min(s_y1, g_y1)
            if ix0 < ix1 and iy0 < iy1:
                u_x0 = min(u_x0, ix0);  u_x1 = max(u_x1, ix1)
                u_y0 = min(u_y0, iy0);  u_y1 = max(u_y1, iy1)
                best_ground = max(best_ground, box['max_z'])
                found = True

        if not found:
            return None
        return (
            (u_x0 + u_x1) / 2,
            (u_y0 + u_y1) / 2,
            u_x1 - u_x0,
            u_y1 - u_y0,
            best_ground,
        )

    def create_brick_blob_shadow(self, brick):
        shadow = self._create_shadow_card()
        shadow.hide()   # positioned on the first update-task tick
        self.brick_blob_shadows[brick] = shadow

    def remove_brick_blob_shadow(self, brick):
        shadow = self.brick_blob_shadows.pop(brick, None)
        if shadow and not shadow.isEmpty():
            shadow.removeNode()

    def update_blob_shadows_task(self, task):
        if self.is_playtest:
            char_pos = self.character.getPos()
            ground_h = self.get_ground_height_at_position(char_pos)
            height_above = max(0.0, char_pos.z - ground_h)
            alpha = max(0.0, 1.0 - height_above / 12.0)
            grow  = 1.0 + height_above * 0.05
            self.char_shadow.show()
            self.char_shadow.setPos(char_pos.x, char_pos.y, ground_h + 0.02)
            self.char_shadow.setScale(3.0 * grow, 1, 2.0 * grow)
            self.char_shadow.setAlphaScale(alpha)
        else:
            self.char_shadow.hide()

        for brick, shadow in list(self.brick_blob_shadows.items()):
            try:
                if not brick.isEmpty():
                    brick_box = self.get_brick_collision_box(brick)
                    region = self._get_shadow_region(brick_box)
                    if region is None:
                        shadow.hide()
                    else:
                        cx, cy, w, d, ground_h = region
                        shadow.show()
                        shadow.setPos(cx, cy, ground_h + 0.02)
                        shadow.setScale(w, 1, d)
            except Exception:
                pass

        return Task.cont
