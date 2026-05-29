import os as _os
import random
from panda3d.core import (
    NodePath, Vec3,
    GeomVertexFormat, GeomVertexData, Geom,
    GeomVertexWriter, GeomTriangles, GeomNode,
    CardMaker, TransparencyAttrib, Filename,
)
from direct.task import Task
from math import sin, cos, atan2, degrees, pi


class CharacterMixin:
    def setup_character(self):
        self.character = NodePath("character")
        self.character.reparentTo(self.render)
        self.floor_top = 0.5
        self.character.setZ(self.floor_top)

        self.torso = self.loader.loadModel("models/box")
        self.torso.reparentTo(self.character)
        self.torso.setScale(2, 1, 2)
        self.torso.setPos(-1, -0.5, 2)
        self.torso.setColor(23/255, 107/255, 170/255, 1)
        self.torso.setTextureOff(1)

        torso_center_x = self.torso.getX() + 1
        torso_center_y = self.torso.getY() + 0.5
        torso_top_z = self.torso.getZ() + 2
        torso_bottom_z = self.torso.getZ()

        self.left_arm_pivot = self.character.attachNewNode("left_arm_pivot")
        self.left_arm_pivot.setPos(torso_center_x - 1.5, torso_center_y, torso_top_z)
        self.right_arm_pivot = self.character.attachNewNode("right_arm_pivot")
        self.right_arm_pivot.setPos(torso_center_x + 1.5, torso_center_y, torso_top_z)

        self.left_arm = self.loader.loadModel("models/box")
        self.left_arm.reparentTo(self.left_arm_pivot)
        self.left_arm.setScale(1, 1, 2)
        self.left_arm.setPos(-0.5, -0.5, -2)
        self.left_arm.setColor(244/255, 204/255, 67/255, 1)
        self.left_arm.setTextureOff(1)

        self.right_arm = self.loader.loadModel("models/box")
        self.right_arm.reparentTo(self.right_arm_pivot)
        self.right_arm.setScale(1, 1, 2)
        self.right_arm.setPos(-0.5, -0.5, -2)
        self.right_arm.setColor(244/255, 204/255, 67/255, 1)
        self.right_arm.setTextureOff(1)

        self.left_leg_pivot = self.character.attachNewNode("left_leg_pivot")
        self.left_leg_pivot.setPos(torso_center_x - 0.5, torso_center_y, torso_bottom_z)
        self.right_leg_pivot = self.character.attachNewNode("right_leg_pivot")
        self.right_leg_pivot.setPos(torso_center_x + 0.5, torso_center_y, torso_bottom_z)

        self.left_leg = self.loader.loadModel("models/box")
        self.left_leg.reparentTo(self.left_leg_pivot)
        self.left_leg.setScale(1, 1, 2)
        self.left_leg.setPos(-0.5, -0.5, -2)
        self.left_leg.setColor(165/255, 188/255, 80/255, 1)
        self.left_leg.setTextureOff(1)

        self.right_leg = self.loader.loadModel("models/box")
        self.right_leg.reparentTo(self.right_leg_pivot)
        self.right_leg.setScale(1, 1, 2)
        self.right_leg.setPos(-0.5, -0.5, -2)
        self.right_leg.setColor(165/255, 188/255, 80/255, 1)
        self.right_leg.setTextureOff(1)

        self.head = self.create_cylinder(radius=0.7, height=1.1, segments=16)
        self.head.reparentTo(self.character)
        self.head.setColor(244/255, 204/255, 67/255, 1)
        self.head.setTwoSided(True)
        self.head.setTextureOff(1)
        head_center_z = torso_top_z + 0.55
        self.head.setPos(torso_center_x, torso_center_y, head_center_z)

        self.cam_target = self.head.attachNewNode("cam_target")
        self.cam_target.setPos(0, 0, 0.55)

        _face_dir = _os.path.join(_os.getcwd(), 'textures', 'face sprites')
        self._face_textures = []
        for fname in ('facesprite1-removebg-preview.png', 'facesprite2-removebg-preview.png', 'facesprite3-removebg-preview.png'):
            t = self.loader.loadTexture(Filename.fromOsSpecific(_os.path.join(_face_dir, fname)))
            if t:
                self._face_textures.append(t)
        if self._face_textures:
            _cm = CardMaker('face')
            _cm.setFrame(-0.70, 0.70, -0.55, 0.55)
            _face_anchor = self.character.attachNewNode("face_anchor")
            _face_anchor.setPos(torso_center_x, torso_center_y + 0.72, head_center_z)
            self._face_sprite = _face_anchor.attachNewNode(_cm.generate())
            self._face_sprite.setTransparency(TransparencyAttrib.MAlpha)
            self._face_sprite.setTwoSided(False)
            self._face_sprite.setColor(1, 1, 1, 1)
            self._face_sprite.setLightOff()
            self._face_sprite.setShaderOff()
            self._face_sprite.setDepthWrite(False)
            self._face_sprite.setH(180)
            self._face_sprite.setTexture(self._face_textures[0])
            self._face_frame = 0
            self._face_anim_t = 0.0

        self.apply_avatar_colors()

    def create_cylinder(self, radius=0.7, height=1.1, segments=16):
        vformat = GeomVertexFormat.get_v3n3()
        vdata = GeomVertexData('cylinder', vformat, Geom.UH_static)
        vertex = GeomVertexWriter(vdata, 'vertex')
        normal = GeomVertexWriter(vdata, 'normal')
        for i in range(segments):
            angle = 2 * pi * i / segments
            x = radius * cos(angle)
            y = radius * sin(angle)
            vertex.add_data3(x, y, height / 2)
            normal.add_data3(cos(angle), sin(angle), 0)
            vertex.add_data3(x, y, -height / 2)
            normal.add_data3(cos(angle), sin(angle), 0)
        prim = GeomTriangles(Geom.UH_static)
        for i in range(segments):
            next_i = (i + 1) % segments
            prim.add_vertices(i * 2, next_i * 2, i * 2 + 1)
            prim.add_vertices(i * 2 + 1, next_i * 2, next_i * 2 + 1)
        top_center = vdata.get_num_rows()
        vertex.add_data3(0, 0, height / 2)
        normal.add_data3(0, 0, 1)
        for i in range(segments):
            next_i = (i + 1) % segments
            prim.add_vertices(top_center, i * 2, next_i * 2)
        bottom_center = vdata.get_num_rows()
        vertex.add_data3(0, 0, -height / 2)
        normal.add_data3(0, 0, -1)
        for i in range(segments):
            next_i = (i + 1) % segments
            prim.add_vertices(bottom_center, next_i * 2 + 1, i * 2 + 1)
        geom = Geom(vdata)
        geom.add_primitive(prim)
        node = GeomNode('cylinder')
        node.add_geom(geom)
        return NodePath(node)

    def setKey(self, key, value):
        if getattr(self, '_ui_modal_open', False):
            return
        self.keys[key] = value

    def start_jump(self):
        if self.is_playtest and not self.is_jumping:
            self.is_jumping = True
            self.vertical_speed = self.jump_speed

    def updateMovement(self, task):
        dt = min(globalClock.getDt(), 1 / 20.0)

        face_spr = getattr(self, '_face_sprite', None)
        if face_spr and getattr(self, '_face_textures', []):
            self._face_anim_t += dt
            if self._face_anim_t >= 0.25:  # 4 fps
                self._face_anim_t -= 0.25
                self._face_frame = (self._face_frame + 1) % len(self._face_textures)
                face_spr.setTexture(self._face_textures[self._face_frame % len(self._face_textures)])

        if not self.is_playtest:
            return Task.cont
        if getattr(self, "_chat_input_active", False):
            return Task.cont

        current_pos = self.character.getPos()

        if current_pos.z < getattr(self, '_void_limit', -80):
            self.vertical_speed = 0
            self.is_jumping = False
            spawn_pts = list(getattr(self, 'brick_spawn_points', set()))
            if spawn_pts:
                sp = random.choice(spawn_pts)
                p = sp.getPos(); s = sp.getScale()
                self.character.setPos(p.x + s.x / 2, p.y + s.y / 2, p.z + s.z)
            else:
                self.character.setPos(0, 0, self.floor_top)
            return Task.cont

        move_x = move_y = 0
        if self.keys["w"]: move_y += 1
        if self.keys["s"]: move_y -= 1
        if self.keys["a"]: move_x -= 1
        if self.keys["d"]: move_x += 1

        if move_x != 0 or move_y != 0:
            cam_quat = self.camera.getQuat(self.render)
            forward = cam_quat.getForward()
            forward.z = 0
            forward.normalize()
            right = cam_quat.getRight()
            right.z = 0
            right.normalize()

            move_vec = forward * move_y + right * move_x
            if move_vec.length() > 0:
                move_vec.normalize()
                desired_pos = current_pos + move_vec * self.move_speed * dt
                resolved_pos = self.resolve_movement(desired_pos)
                self.character.setPos(resolved_pos)

                if not getattr(self, 'shift_lock', False):
                    target_h = degrees(atan2(move_vec.y, move_vec.x)) - 90
                    current_h = self.character.getH()
                    diff = (target_h - current_h + 180) % 360 - 180
                    turn = max(-self.turn_speed * dt, min(self.turn_speed * dt, diff))
                    self.character.setH(current_h + turn)

                self.walking_angle += self.walking_speed * dt
                self.left_arm_pivot.setP(sin(self.walking_angle) * self.max_swing_angle)
                self.right_arm_pivot.setP(sin(self.walking_angle + pi) * self.max_swing_angle)
                self.left_leg_pivot.setP(sin(self.walking_angle + pi) * self.max_swing_angle)
                self.right_leg_pivot.setP(sin(self.walking_angle) * self.max_swing_angle)
        else:
            t = min(1.0, 12.0 * dt)
            self.walking_angle    *= (1 - t)
            self.left_arm_pivot.setP(self.left_arm_pivot.getP()   * (1 - t))
            self.right_arm_pivot.setP(self.right_arm_pivot.getP() * (1 - t))
            self.left_leg_pivot.setP(self.left_leg_pivot.getP()   * (1 - t))
            self.right_leg_pivot.setP(self.right_leg_pivot.getP() * (1 - t))

        if getattr(self, 'shift_lock', False) or getattr(self, 'is_first_person', False):
            self.character.setH(self.cam_angle.x)

        current_pos = self.character.getPos()
        ground_height = self.get_ground_height_at_position(current_pos)
        if ground_height is None:
            ground_height = current_pos.z - 9999.0  # freefall — no surface below

        MAX_STEP = 1.2
        if not self.is_jumping and self.vertical_speed <= 0:
            char_box = self.get_character_collision_box(current_pos)
            for brick in self._grid_nearby(current_pos, 15):
                brick_box = self.get_brick_collision_box(brick)
                brick_top = brick_box['max_z']
                if (char_box['min_z'] + 0.05 < brick_top <= char_box['min_z'] + MAX_STEP and
                        abs(char_box['center'].x - brick_box['center'].x) < char_box['half_width'] + brick_box['half_width'] and
                        abs(char_box['center'].y - brick_box['center'].y) < char_box['half_depth'] + brick_box['half_depth']):
                    ground_height = max(ground_height, brick_top)

        step_diff = ground_height - current_pos.z
        if not self.is_jumping and self.vertical_speed <= 0 and 0.05 < step_diff <= MAX_STEP:
            new_z = current_pos.z + min(step_diff, 14.0 * dt)
            self.vertical_speed = 0
            self.is_jumping = False
        else:
            if current_pos.z > ground_height or self.vertical_speed > 0:
                self.vertical_speed += self.gravity * dt
                if self.vertical_speed < -300.0:
                    self.vertical_speed = -300.0

            new_z = current_pos.z + self.vertical_speed * dt

            if self.vertical_speed > 0:
                test_ceiling_pos = Vec3(current_pos.x, current_pos.y, new_z)
                if self.check_collision_at_position(test_ceiling_pos):
                    self.vertical_speed = 0
                    new_z = current_pos.z

            if new_z <= ground_height and self.vertical_speed <= 0:
                new_z = ground_height
                self.vertical_speed = 0
                self.is_jumping = False

        # Jump input read BEFORE setZ so _unstuck_character knows not to cancel it
        jump_initiated = False
        if not self.is_jumping and self.keys.get("space"):
            self.is_jumping = True
            self.vertical_speed = self.jump_speed
            jump_initiated = True

        self.character.setZ(new_z)
        self._unstuck_character(allow_jump_cancel=not jump_initiated)
        return Task.cont

    def spawn_unstuck(self):
        """Place character on a spawn point (random if multiple), or fall back
        to centroid-above-build if no spawn points exist."""
        live_bricks = [b for b in self.bricks if not b.isEmpty()]
        if live_bricks:
            min_brick_z = min(b.getPos().z for b in live_bricks)
            self._void_limit = min(min_brick_z - 50, -80)
        else:
            self._void_limit = -80

        self.vertical_speed = 0
        self.is_jumping = False

        spawn_pts = [sp for sp in list(getattr(self, 'brick_spawn_points', set()))
                     if not sp.isEmpty()]
        if spawn_pts:
            sp = random.choice(spawn_pts)
            p  = sp.getPos()
            s  = sp.getScale()
            self.character.setPos(p.x + s.x / 2, p.y + s.y / 2, p.z + s.z)
            return

        if not live_bricks:
            return

        # Fallback: find the highest brick overlapping the character's current XY footprint
        pos      = self.character.getPos()
        char_box = self.get_character_collision_box(pos)
        highest_top = None
        for brick in live_bricks:
            brick_box = self.get_brick_collision_box(brick)
            if self.boxes_collide(char_box, brick_box):
                if highest_top is None or brick_box['max_z'] > highest_top:
                    highest_top = brick_box['max_z']

        if highest_top is None:
            # No overlap at current XY — place above the build centroid
            boxes = [self.get_brick_collision_box(b) for b in live_bricks]
            avg_x = sum(bx['center'].x for bx in boxes) / len(boxes)
            avg_y = sum(bx['center'].y for bx in boxes) / len(boxes)
            top_z = max(bx['max_z'] for bx in boxes)
            self.character.setPos(avg_x, avg_y, top_z + 2)
        else:
            self.character.setZ(highest_top)

    def _unstuck_character(self, allow_jump_cancel=True):
        """If the character overlaps any brick, push them out along the
        minimum-penetration axis. Runs up to 4 iterations per frame so
        overlapping multiple bricks at once is still resolved."""
        for _ in range(4):
            pos      = self.character.getPos()
            char_box = self.get_character_collision_box(pos)

            best_push      = None
            best_push_dist = float('inf')

            for brick in self._grid_nearby(pos, 12):
                brick_box = self.get_brick_collision_box(brick)
                if not self.boxes_collide(char_box, brick_box):
                    continue

                ox    = (char_box['half_width']  + brick_box['half_width'])  - abs(char_box['center'].x - brick_box['center'].x)
                oy    = (char_box['half_depth']  + brick_box['half_depth'])  - abs(char_box['center'].y - brick_box['center'].y)
                oz_up = brick_box['max_z'] - char_box['min_z']
                oz_dn = char_box['max_z'] - brick_box['min_z']
                oz    = min(oz_up, oz_dn)

                min_o = min(ox, oy, oz)
                if min_o < best_push_dist:
                    best_push_dist = min_o
                    if min_o == oz:
                        if oz_up <= oz_dn:
                            best_push = Vec3(0, 0, oz_up)
                        else:
                            best_push = Vec3(0, 0, -oz_dn)
                    elif min_o == ox:
                        sign = 1 if char_box['center'].x >= brick_box['center'].x else -1
                        best_push = Vec3(ox * sign, 0, 0)
                    else:
                        sign = 1 if char_box['center'].y >= brick_box['center'].y else -1
                        best_push = Vec3(0, oy * sign, 0)

            if best_push is None:
                break

            self.character.setPos(pos + best_push)
            if best_push.z > 0:
                # Ignore microscopic float-noise pushes — they fire when the character
                # is sitting exactly on a surface and would cancel a just-initiated jump.
                if allow_jump_cancel and best_push.z > 0.05:
                    self.vertical_speed = 0
                    self.is_jumping = False
            elif best_push.z < 0 and self.vertical_speed > 0:
                self.vertical_speed = 0

    def apply_tshirt(self, image_b64):
        """Attach a T-shirt card to the front of the torso."""
        self.remove_tshirt()
        try:
            import base64, tempfile, os as _os
            from panda3d.core import CardMaker, TransparencyAttrib, Filename, PNMImage
            raw = base64.b64decode(image_b64)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                tf.write(raw)
                tmp = tf.name
            tex = self.loader.loadTexture(Filename.fromOsSpecific(tmp))
            _os.unlink(tmp)
            if not tex:
                return
            cm = CardMaker('tshirt')
            cm.setFrame(-1, 1, 0, 2)
            anchor = self.character.attachNewNode("tshirt_anchor")
            anchor.setPos(0, 0.51, 2)
            np = anchor.attachNewNode(cm.generate())
            np.setH(180)
            np.setTexture(tex)
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setLightOff()
            np.setShaderOff()
            np.setDepthWrite(False)
            np.setDepthOffset(1)
            self._tshirt_node = np
            self._tshirt_anchor = anchor
        except Exception as e:
            print(f"[TSHIRT] apply failed: {e}", flush=True)

    def remove_tshirt(self):
        for attr in ('_tshirt_node', '_tshirt_anchor'):
            n = getattr(self, attr, None)
            if n and not n.isEmpty():
                n.removeNode()
            setattr(self, attr, None)

    def apply_hat(self, hat_data_json):
        """Load a hat from server hat_data JSON and attach it (follows head each frame)."""
        self.remove_hat()
        import json as _json, base64, tempfile, os as _os, shutil
        try:
            data = _json.loads(hat_data_json)
        except Exception as e:
            print(f"[HAT_APPLY] JSON parse: {e}", flush=True)
            return
        tmp_dir = None
        try:
            from panda3d.core import Filename
            # Write OBJ + MTL into the same temp directory so Panda3D can
            # resolve the mtllib reference correctly when loading the model.
            tmp_dir = tempfile.mkdtemp(prefix="phx_hat_")
            obj_tmp = _os.path.join(tmp_dir, "hat.obj")
            with open(obj_tmp, 'wb') as f:
                f.write(base64.b64decode(data["obj_b64"]))

            mtl_b64  = data.get("mtl_b64")
            mtl_name = data.get("mtl_name") or "hat.mtl"
            if mtl_b64:
                with open(_os.path.join(tmp_dir, mtl_name), 'wb') as f:
                    f.write(base64.b64decode(mtl_b64))

            hat_model = self.loader.loadModel(Filename.fromOsSpecific(obj_tmp))
            # Safe to remove temp files now — model data is in memory
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir = None

            if not hat_model:
                print("[HAT_APPLY] loader returned None", flush=True)
                return

            hat_model.setR(-90)  # OBJ Y-up → Panda3D Z-up

            # User-applied texture overrides any MTL texture
            tex_b64 = data.get("texture_b64")
            if tex_b64:
                raw = base64.b64decode(tex_b64)
                tex_tmp = _os.path.join(tempfile.gettempdir(), "phx_hat_tex.png")
                with open(tex_tmp, 'wb') as f:
                    f.write(raw)
                tex = self.loader.loadTexture(Filename.fromOsSpecific(tex_tmp))
                try: _os.unlink(tex_tmp)
                except Exception: pass
                if tex:
                    hat_model.setTexture(tex, 1)

            bs = data.get("brick_scale", [2, 2, 2])
            ms = data.get("model_scale", [1, 1, 1])
            world_scale = [bs[i] * ms[i] for i in range(3)]
            hat_model.reparentTo(self.render)
            hat_model.setScale(*world_scale)
            hat_model.setHpr(*data.get("model_hpr", [0, 0, -90]))
            hat_model.setShaderOff()
            hat_model.setTwoSided(True)
            self._equipped_hat_model = hat_model
            self._equipped_hat_z_off = float(data.get("z_offset", 0.0))
            self._equipped_hat_hpr   = data.get("model_hpr", [0, 0, -90])
            from direct.task import Task
            self.taskMgr.add(self._equipped_hat_follow, "_equippedHatFollowTask")
            print("[HAT_APPLY] loaded OK", flush=True)
        except Exception as e:
            print(f"[HAT_APPLY] error: {e}", flush=True)
            import traceback; traceback.print_exc()
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def remove_hat(self):
        self.taskMgr.remove("_equippedHatFollowTask")
        n = getattr(self, '_equipped_hat_model', None)
        if n and not n.isEmpty():
            n.removeNode()
        self._equipped_hat_model = None

    def _equipped_hat_follow(self, task):
        from direct.task import Task
        m = getattr(self, '_equipped_hat_model', None)
        if not m or m.isEmpty():
            return Task.done
        hp = self.head.getPos(self.render)
        z  = getattr(self, '_equipped_hat_z_off', 0.0)
        m.setPos(hp.x, hp.y, hp.z + 0.55 + z)
        h0, p0, r0 = getattr(self, '_equipped_hat_hpr', [0, 0, -90])
        m.setHpr(self.character.getH() + h0, p0, r0)
        return Task.cont
