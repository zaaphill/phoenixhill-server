import os as _os
import random
from panda3d.core import (
    NodePath, Vec3,
    GeomVertexFormat, GeomVertexData, Geom,
    GeomVertexWriter, GeomTriangles, GeomNode,
    CardMaker, TransparencyAttrib, Filename,
    TextureStage,
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
        if getattr(self, '_respawning', False):
            return Task.cont   # freeze physics/input during countdown

        current_pos = self.character.getPos()

        if current_pos.z < getattr(self, '_void_limit', -80):
            self._trigger_respawn()
            return Task.cont

        # Kill-brick detection
        if not getattr(self, '_respawning', False):
            char_box = self.get_character_collision_box(current_pos)
            for brick in self._grid_nearby(current_pos, 12):
                if brick in getattr(self, 'brick_kill_bricks', set()):
                    brick_box = self.get_brick_collision_box(brick)
                    if self.boxes_collide(char_box, brick_box):
                        self._trigger_respawn()
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
            cx = char_box['center'].x
            cy = char_box['center'].y
            for brick in self._grid_nearby(current_pos, 15):
                hpr = brick.getHpr()
                if abs(hpr.x) > 0.5 or abs(hpr.y) > 0.5 or abs(hpr.z) > 0.5:
                    # Rotated bricks: get_ground_height_at_position already uses
                    # a 1.2-unit tolerance and returns the slope surface height.
                    # A second step-up pass here produces conflicting ground_height
                    # values on the same frame and is the source of the remaining
                    # jitter — skip and let the gravity snap handle it.
                    continue
                brick_box = self.get_brick_collision_box(brick)
                brick_top = brick_box['max_z']
                if (char_box['min_z'] + 0.05 < brick_top <= char_box['min_z'] + MAX_STEP and
                        abs(cx - brick_box['center'].x) < char_box['half_width'] + brick_box['half_width'] and
                        abs(cy - brick_box['center'].y) < char_box['half_depth'] + brick_box['half_depth']):
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

    def _trigger_respawn(self):
        if getattr(self, '_respawning', False):
            return
        self._respawning = True
        self.vertical_speed = 0
        self.is_jumping = False
        # Hide character visuals. Character node stays in place so the camera
        # (which orbits cam_target, a child of head → character) keeps its view.
        self.character.hide()
        hat = getattr(self, '_equipped_hat_model', None)
        if hat and not hat.isEmpty():
            hat.hide()
        broadcast = getattr(self, '_broadcast_player_visibility', None)
        if broadcast:
            broadcast(False)
        self._respawn_countdown(3)

    def _respawn_countdown(self, n):
        from direct.gui.OnscreenText import OnscreenText
        lbl = getattr(self, '_respawn_lbl', None)
        if lbl:
            try: lbl.destroy()
            except Exception: pass
        if n > 0:
            self._respawn_lbl = OnscreenText(
                text=f"Respawning in {n}...",
                pos=(0, 0.15), scale=0.10,
                fg=(1, 1, 1, 1), shadow=(0, 0, 0, 0.7),
                mayChange=True,
            )
            self.taskMgr.doMethodLater(
                1.0, self._respawn_tick, '_respawnCountdown',
                extraArgs=[n - 1], appendTask=True,
            )
        else:
            self._respawn_lbl = None
            self._finish_respawn()

    def _respawn_tick(self, n, task):
        self._respawn_countdown(n)
        return task.done

    def _finish_respawn(self):
        self.spawn_unstuck()
        self.character.show()
        hat = getattr(self, '_equipped_hat_model', None)
        if hat and not hat.isEmpty():
            hat.show()
        broadcast = getattr(self, '_broadcast_player_visibility', None)
        if broadcast:
            broadcast(True)
        self._respawning = False

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
                hpr = brick.getHpr()
                if abs(hpr.x) > 0.5 or abs(hpr.y) > 0.5 or abs(hpr.z) > 0.5:
                    if not self._obb_aabb_collide(char_box, brick):
                        continue
                    surf_z = self._rotated_surface_z(brick, char_box['center'].x, char_box['center'].y)
                    if surf_z is None:
                        # Strict footprint missed (slope edge) — retry with clamping
                        # before falling back to a side-push that can cause jitter.
                        surf_z = self._rotated_surface_z(brick, char_box['center'].x, char_box['center'].y, clamp=True)
                    if surf_z is not None:
                        # On or near the top face — push only vertically so the
                        # character doesn't slide sideways down the slope.
                        push_up = surf_z - char_box['min_z']
                        if push_up <= 0.02:
                            continue  # dead zone: prevents ping-pong with gravity snap
                        if push_up < 2.0 and push_up < best_push_dist:
                            best_push_dist = push_up
                            best_push = Vec3(0, 0, push_up)
                    else:
                        # Truly at a side or bottom face — minimum-penetration push
                        push = self._obb_aabb_push(char_box, brick)
                        if push is not None:
                            dist = push.length()
                            if dist > 0 and dist < best_push_dist:
                                best_push_dist = dist
                                best_push = push
                    continue
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
            np.setShaderOff()
            np.setDepthWrite(False)
            np.setDepthOffset(3)  # pants=1, shirt=2, tshirt=3 so tshirt renders on top
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

    # Standard Roblox R6 shirt template regions (pixels) for a 585×559 template.
    # Based on 32px per Roblox stud: torso 2×1×3 studs, arms 1×1×3 studs.
    _SHIRT_REGIONS = {
        # Torso
        "torso_up":    (243,   9, 345,  71),
        "torso_left":  (364,  78, 416, 194),
        "torso_front": (232,  74, 356, 196),
        "torso_right": (173,  78, 225, 194),
        "torso_back":  (430,  74, 554, 196),
        "torso_down":  (230, 227, 326, 259),
        # Right arm
        "rarm_up":    (221, 298, 275, 350),
        "rarm_left":  ( 19, 356,  81, 482),
        "rarm_front": (219, 356, 279, 480),
        "rarm_right": (512, 358, 568, 478),
        "rarm_back":  ( 86, 356, 146, 480),
        "rarm_down":  (218, 490, 278, 550),
        # Left arm
        "larm_up":    (311, 297, 365, 349),
        "larm_left":  (378, 360, 434, 480),
        "larm_front": (313, 358, 369, 478),
        "larm_right": (511, 360, 563, 476),
        "larm_back":  (446, 358, 498, 478),
        "larm_down":  (218, 486, 278, 546),
    }
    _SHIRT_TEMPLATE_W = 585
    _SHIRT_TEMPLATE_H = 559

    # Standard Roblox R6 pants template regions (pixels) for a 585×559 template.
    # Torso section uses the same template layout as shirts (calibrate with F8 debug).
    _PANTS_REGIONS = {
        # Torso/waist — same layout as shirt torso (pants creator can fill this area)
        "torso_up":    (263,   9, 325,  71),
        "torso_left":  (364,  78, 416, 194),
        "torso_front": (232,  74, 356, 196),
        "torso_right": (173,  78, 225, 194),
        "torso_back":  (430,  74, 554, 196),
        "torso_down":  (230, 227, 326, 259),
        # Right leg — same template position as left arm in shirt template
        "rleg_up":    (311, 297, 365, 349),
        "rleg_left":  (378, 360, 434, 480),
        "rleg_front": (313, 358, 369, 478),
        "rleg_right": (511, 360, 563, 476),
        "rleg_back":  (446, 358, 498, 478),
        "rleg_down":  (218, 486, 278, 546),
        # Left leg — same template position as right arm in shirt template
        "lleg_up":    (221, 298, 275, 350),
        "lleg_left":  ( 20, 355,  80, 479),
        "lleg_front": (219, 356, 279, 480),
        "lleg_right": (512, 358, 568, 478),
        "lleg_back":  ( 86, 356, 146, 480),
        "lleg_down":  (218, 490, 278, 550),
    }
    _PANTS_TEMPLATE_W = 585
    _PANTS_TEMPLATE_H = 559

    @staticmethod
    def _make_shirt_box_geom(w, d, h, regions, template_w=585, template_h=559):
        """
        Build a GeomNode box with UV coordinates sampling the correct shirt template regions.
        w=X size, d=Y size, h=Z size. regions maps face name → (px_l, px_t, px_r, px_b).
        The full shirt texture is applied once; UVs pull each region from the template.
        """
        from panda3d.core import (
            GeomVertexFormat, GeomVertexData, GeomVertexWriter,
            GeomTriangles, Geom, GeomNode,
        )
        TW, TH = float(template_w), float(template_h)

        def to_uv(px, py):
            return px / TW, 1.0 - py / TH

        def region_uvs(key):
            if key not in regions:
                return None
            px0, py0, px1, py1 = regions[key]
            ul, vt = to_uv(px0, py0)   # upper-left pixel → low-U, high-V
            ur, vb = to_uv(px1, py1)   # lower-right pixel → high-U, low-V
            # Returned as (BL, BR, TR, TL) UV pairs
            return (ul, vb), (ur, vb), (ur, vt), (ul, vt)

        fmt   = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData('shirt_box', fmt, Geom.UHStatic)
        vw    = GeomVertexWriter(vdata, 'vertex')
        nw    = GeomVertexWriter(vdata, 'normal')
        tw    = GeomVertexWriter(vdata, 'texcoord')
        prim  = GeomTriangles(Geom.UHStatic)
        vi    = [0]

        def quad(verts, uvs, normal):
            for (x, y, z), (u, v) in zip(verts, uvs):
                vw.addData3(x, y, z); nw.addData3(*normal); tw.addData2(u, v)
            i = vi[0]
            prim.addVertices(i, i+1, i+2); prim.addVertices(i, i+2, i+3)
            vi[0] += 4

        # Front (Y=d, +Y normal). Template left = char right (+X) so flip U.
        uvs = region_uvs('front')
        if uvs:
            bl, br, tr, tl = uvs
            quad([(0,d,0),(w,d,0),(w,d,h),(0,d,h)], [br, bl, tl, tr], (0, 1, 0))

        # Back (Y=0, -Y normal). No U-flip: local X=0 (char left) → u_left.
        uvs = region_uvs('back')
        if uvs:
            bl, br, tr, tl = uvs
            quad([(0,0,0),(w,0,0),(w,0,h),(0,0,h)], [bl, br, tr, tl], (0, -1, 0))

        # Right (X=w, +X normal). Looking from +X: Y=d=front, Y=0=back.
        uvs = region_uvs('right')
        if uvs:
            quad([(w,d,0),(w,0,0),(w,0,h),(w,d,h)], list(uvs), (1, 0, 0))

        # Left (X=0, -X normal). Looking from -X: Y=0=back, Y=d=front.
        uvs = region_uvs('left')
        if uvs:
            bl, br, tr, tl = uvs
            quad([(0,0,0),(0,d,0),(0,d,h),(0,0,h)], [br, bl, tl, tr], (-1, 0, 0))

        # Top (Z=h, +Z normal). Flip U and V to match Roblox template.
        uvs = region_uvs('top')
        if uvs:
            bl, br, tr, tl = uvs
            quad([(0,d,h),(w,d,h),(w,0,h),(0,0,h)], [tr, tl, bl, br], (0, 0, 1))

        # Bottom (Z=0, -Z normal).
        uvs = region_uvs('bottom')
        if uvs:
            quad([(0,0,0),(w,0,0),(w,d,0),(0,d,0)], list(uvs), (0, 0, -1))

        geom = Geom(vdata); geom.addPrimitive(prim)
        node = GeomNode('shirt_box'); node.addGeom(geom)
        return node

    def apply_shirt(self, image_b64):
        """Apply a Roblox shirt template using UV-mapped custom geometry (not cards)."""
        print(f"[SHIRT_DBG] apply_shirt called, b64 length={len(image_b64) if image_b64 else 0}", flush=True)
        self.remove_shirt()
        if not image_b64:
            print("[SHIRT_DBG] apply_shirt: empty image_b64, aborting", flush=True); return
        if "|SHIRTDATA|" in image_b64:
            image_b64 = image_b64.split("|SHIRTDATA|")[0]
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib

            raw = base64.b64decode(image_b64)
            print(f"[SHIRT_DBG] decoded {len(raw)} bytes", flush=True)
            ss  = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                print("[SHIRT_DBG] PNMImage.read() FAILED", flush=True); return
            print(f"[SHIRT_DBG] PNMImage ok: {pnm.getXSize()}x{pnm.getYSize()}", flush=True)
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)

            def attach(parent, reg_map, w, d, h, pos):
                node = self._make_shirt_box_geom(w, d, h, reg_map)
                np = parent.attachNewNode(node)
                np.setPos(*pos)
                np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setDepthOffset(2)  # pants=1, shirt=2, tshirt=3
                np.setTransparency(TransparencyAttrib.MAlpha)
                return np

            R = self._SHIRT_REGIONS
            nodes = [
                attach(self.character, {
                    'front': R['torso_front'], 'back':  R['torso_back'],
                    'left':  R['torso_left'],  'right': R['torso_right'],
                    'top':   R['torso_up'],    'bottom':R['torso_down'],
                }, 2, 1, 2, (-1, -0.5, 2)),

                attach(self.right_arm_pivot, {
                    'front': R['rarm_front'], 'back':  R['rarm_back'],
                    'left':  R['rarm_left'],  'right': R['rarm_right'],
                    'top':   R['rarm_up'],    'bottom':R['rarm_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),

                attach(self.left_arm_pivot, {
                    'front': R['larm_front'], 'back':  R['larm_back'],
                    'left':  R['larm_left'],  'right': R['larm_right'],
                    'top':   R['larm_up'],    'bottom':R['larm_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
            ]
            self._shirt_nodes = nodes
            print("[SHIRT] applied UV-mapped shirt", flush=True)
        except Exception as e:
            print(f"[SHIRT] apply failed: {e}", flush=True)

    def remove_shirt(self):
        import traceback as _tb
        nodes = getattr(self, '_shirt_nodes', [])
        if nodes:
            print(f"[SHIRT_DBG] remove_shirt called with {len(nodes)} nodes, caller:", flush=True)
            _tb.print_stack(limit=5)
        for n in nodes:
            if n and not n.isEmpty():
                n.removeNode()
        self._shirt_nodes = []

    def apply_pants(self, image_b64):
        """Apply a Roblox pants template using UV-mapped custom geometry."""
        self.remove_pants()
        if "|PANTSDATA|" in image_b64:
            image_b64 = image_b64.split("|PANTSDATA|")[0]
        try:
            import base64
            from panda3d.core import PNMImage, StringStream, Texture, TransparencyAttrib

            raw = base64.b64decode(image_b64)
            ss  = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss):
                print("[PANTS] failed to decode image", flush=True); return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)

            def attach(parent, reg_map, w, d, h, pos):
                node = self._make_shirt_box_geom(w, d, h, reg_map,
                    template_w=self._PANTS_TEMPLATE_W, template_h=self._PANTS_TEMPLATE_H)
                np = parent.attachNewNode(node)
                np.setPos(*pos); np.setTexture(tex)
                np.setTwoSided(True); np.setShaderOff()
                np.setDepthOffset(1)  # above body; shirt uses 2 so shirt renders on top
                np.setTransparency(TransparencyAttrib.MAlpha)
                return np

            R = self._PANTS_REGIONS
            nodes = [
                attach(self.character, {
                    'front': R['torso_front'], 'back':  R['torso_back'],
                    'left':  R['torso_left'],  'right': R['torso_right'],
                    'top':   R['torso_up'],    'bottom':R['torso_down'],
                }, 2, 1, 2, (-1, -0.5, 2)),
                attach(self.right_leg_pivot, {
                    'front': R['rleg_front'], 'back':  R['rleg_back'],
                    'left':  R['rleg_left'],  'right': R['rleg_right'],
                    'top':   R['rleg_up'],    'bottom':R['rleg_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
                attach(self.left_leg_pivot, {
                    'front': R['lleg_front'], 'back':  R['lleg_back'],
                    'left':  R['lleg_left'],  'right': R['lleg_right'],
                    'top':   R['lleg_up'],    'bottom':R['lleg_down'],
                }, 1, 1, 2, (-0.5, -0.5, -2)),
            ]
            self._pants_nodes = nodes
            print("[PANTS] applied UV-mapped pants", flush=True)
        except Exception as e:
            print(f"[PANTS] apply failed: {e}", flush=True)

    def remove_pants(self):
        for n in getattr(self, '_pants_nodes', []):
            if n and not n.isEmpty():
                n.removeNode()
        self._pants_nodes = []

    # ── Shirt UV debug mode ─────────────────────────────────────────────────
    # Each entry: (region_key, parent_attr, pos, card_frame, hpr)
    _SHIRT_DBG_FACES = [
        ('torso_front','character',      ( 0,     0.52,  2),(-1, 1, 0,  2),(180,0,0)),
        ('torso_back', 'character',      ( 0,    -0.52,  2),(-1, 1, 0,  2),(  0,0,0)),
        ('torso_right','character',      ( 1.02,  0,     2),(-0.5,0.5,0,2),(-90,0,0)),
        ('torso_left', 'character',      (-1.02,  0,     2),(-0.5,0.5,0,2),( 90,0,0)),
        ('torso_up',   'character',      ( 0,     0,  4.02),(-1,1,-0.5,0.5),(0,-90,0)),
        ('torso_down', 'character',      ( 0,     0,  1.98),(-1,1,-0.5,0.5),(0, 90,0)),
        ('rarm_front', 'right_arm_pivot',( 0,     0.52, -2),(-0.5,0.5,0,2),(180,0,0)),
        ('rarm_back',  'right_arm_pivot',( 0,    -0.52, -2),(-0.5,0.5,0,2),(  0,0,0)),
        ('rarm_right', 'right_arm_pivot',( 0.52,  0,    -2),(-0.5,0.5,0,2),(-90,0,0)),
        ('rarm_left',  'right_arm_pivot',(-0.52,  0,    -2),(-0.5,0.5,0,2),( 90,0,0)),
        ('rarm_up',    'right_arm_pivot',( 0,     0,  0.02),(-0.5,0.5,-0.5,0.5),(0,-90,0)),
        ('rarm_down',  'right_arm_pivot',( 0,     0, -2.02),(-0.5,0.5,-0.5,0.5),(0, 90,0)),
        ('larm_front', 'left_arm_pivot', ( 0,     0.52, -2),(-0.5,0.5,0,2),(180,0,0)),
        ('larm_back',  'left_arm_pivot', ( 0,    -0.52, -2),(-0.5,0.5,0,2),(  0,0,0)),
        ('larm_right', 'left_arm_pivot', ( 0.52,  0,    -2),(-0.5,0.5,0,2),(-90,0,0)),
        ('larm_left',  'left_arm_pivot', (-0.52,  0,    -2),(-0.5,0.5,0,2),( 90,0,0)),
        ('larm_up',    'left_arm_pivot', ( 0,     0,  0.02),(-0.5,0.5,-0.5,0.5),(0,-90,0)),
        ('larm_down',  'left_arm_pivot', ( 0,     0, -2.02),(-0.5,0.5,-0.5,0.5),(0, 90,0)),
    ]

    def start_shirt_debug(self, image_b64):
        """Shirt UV debug mode.
        Tab/Shift-Tab: cycle faces   Arrows: move region
        Ctrl+Arrows: resize (zoom)   \\ / Shift-\\: stretch all sides out/in
        +/-: step size   P: print coords   F8: exit"""
        self.stop_shirt_debug()
        self.remove_shirt()
        if '|SHIRTDATA|' in image_b64:
            image_b64 = image_b64.split('|SHIRTDATA|')[0]
        try:
            from PIL import Image as _PIL
            import base64, io as _io
            from panda3d.core import PNMImage, StringStream, Texture
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode as _TN

            raw   = base64.b64decode(image_b64)
            tmpl  = _PIL.open(_io.BytesIO(raw)).convert("RGBA")
            # Normalize to 585×559 so crop coords are always correct
            if tmpl.size != (585, 559):
                tmpl = tmpl.resize((585, 559), _PIL.LANCZOS)

            self._sdbg_tmpl  = tmpl
            self._sdbg_raw   = image_b64
            self._sdbg_regs  = {k: list(v) for k, v in self._SHIRT_REGIONS.items()}
            self._sdbg_idx   = 0
            self._sdbg_step  = 2
            self._sdbg_cards = {}

            for (key, par_attr, pos, frame, hpr) in self._SHIRT_DBG_FACES:
                parent = getattr(self, par_attr, None)
                if not parent: continue
                cm = CardMaker(f'sdbg_{key}'); cm.setFrame(*frame)
                anchor = parent.attachNewNode(f'sdbg_a_{key}'); anchor.setPos(*pos)
                card   = anchor.attachNewNode(cm.generate()); card.setHpr(*hpr)
                card.setTransparency(TransparencyAttrib.MAlpha)
                card.setShaderOff(); card.setLightOff()
                card.setDepthOffset(2); card.setDepthWrite(False)
                card.setTwoSided(True)   # prevent blank faces from backface culling
                self._sdbg_cards[key] = (anchor, card)
                self._sdbg_rebuild_tex(key)

            self._sdbg_lbl_face = OnscreenText(
                text='', pos=(-1.55, 0.92), scale=0.042,
                fg=(1, 1, 0.2, 1), align=_TN.ALeft, mayChange=True)
            self._sdbg_lbl_coord = OnscreenText(
                text='', pos=(-1.55, 0.80), scale=0.048,
                fg=(0.3, 1, 0.3, 1), align=_TN.ALeft, mayChange=True)
            self._sdbg_lbl_hint = OnscreenText(
                text='Tab/Shift-Tab: cycle   Arrows: move   Shift+Arrows: resize   +/-: zoom\n'
                     '[/]: shrink/expand width   ,/.: shrink/expand height   Z/X: speed   P: print   F8: exit',
                pos=(-1.55, 0.65), scale=0.034,
                fg=(0.8, 0.8, 1, 1), align=_TN.ALeft, mayChange=False)

            self.accept('tab',               self._sdbg_cycle,       [ 1])
            self.accept('shift-tab',         self._sdbg_cycle,       [-1])
            # Move
            self.accept('arrow_left',        self._sdbg_move,        [-1,  0])
            self.accept('arrow_right',       self._sdbg_move,        [ 1,  0])
            self.accept('arrow_up',          self._sdbg_move,        [ 0, -1])
            self.accept('arrow_down',        self._sdbg_move,        [ 0,  1])
            # Resize right/bottom edge (Shift avoids Windows Ctrl+Arrow intercept)
            self.accept('shift-arrow_left',  self._sdbg_resize,      [-1,  0])
            self.accept('shift-arrow_right', self._sdbg_resize,      [ 1,  0])
            self.accept('shift-arrow_up',    self._sdbg_resize,      [ 0, -1])
            self.accept('shift-arrow_down',  self._sdbg_resize,      [ 0,  1])
            # Stretch: [/] = shrink/expand width,  ,/. = shrink/expand height
            self.accept('[',                 self._sdbg_stretch_w,   [-1])
            self.accept(']',                 self._sdbg_stretch_w,   [ 1])
            self.accept(',',                 self._sdbg_stretch_h,   [-1])
            self.accept('.',                 self._sdbg_stretch_h,   [ 1])
            self.accept('=',                 self._sdbg_do_zoom,     [ 1])
            self.accept('-',                 self._sdbg_do_zoom,     [-1])
            self.accept('z',                 self._sdbg_step_sz,     [ 1])
            self.accept('x',                 self._sdbg_step_sz,     [-1])
            self.accept('delete',            self._sdbg_toggle_arms)
            self.accept('p',                 self._sdbg_print)
            self.accept('f8',               self.stop_shirt_debug)

            self._sdbg_update_hud()
            print('[SHIRT_DBG] started', flush=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f'[SHIRT_DBG] start error: {e}', flush=True)

    def stop_shirt_debug(self):
        for attr in ('_sdbg_lbl_face', '_sdbg_lbl_coord', '_sdbg_lbl_hint'):
            w = getattr(self, attr, None)
            if w:
                try: w.destroy()
                except Exception: pass
            setattr(self, attr, None)
        for key, (anchor, _) in getattr(self, '_sdbg_cards', {}).items():
            if anchor and not anchor.isEmpty(): anchor.removeNode()
        self._sdbg_cards = {}
        for ev in ('tab','shift-tab','arrow_left','arrow_right','arrow_up','arrow_down',
                   'shift-arrow_left','shift-arrow_right','shift-arrow_up','shift-arrow_down',
                   '[',']',',','.','=','-','z','x','delete','p','f8'):
            self.ignore(ev)
        for d in ('left','right','up','down'):
            if hasattr(self, '_hat_flip'):
                self.accept(f'arrow_{d}', self._hat_flip, [d])
        self._sdbg_tmpl = None
        if getattr(self, '_sdbg_arms_out', False):
            self._sdbg_arms_out = False
            r_pivot = getattr(self, 'right_arm_pivot', None)
            l_pivot = getattr(self, 'left_arm_pivot', None)
            if r_pivot: r_pivot.setR(0)
            if l_pivot: l_pivot.setR(0)
        print('[SHIRT_DBG] stopped', flush=True)

    def _sdbg_rebuild_tex(self, key):
        """Crop the template region and apply as a fresh texture to that face card."""
        if key not in getattr(self, '_sdbg_cards', {}): return
        _, card = self._sdbg_cards[key]
        tmpl = getattr(self, '_sdbg_tmpl', None)
        if tmpl is None: return
        from panda3d.core import PNMImage, StringStream, Texture
        import io as _io
        px0, py0, px1, py1 = self._sdbg_regs[key]
        # Clamp to template bounds
        px0 = max(0, px0); py0 = max(0, py0)
        px1 = min(585, max(px0+1, px1)); py1 = min(559, max(py0+1, py1))
        crop = tmpl.crop((px0, py0, px1, py1))
        buf  = _io.BytesIO(); crop.save(buf, 'PNG')
        ss   = StringStream(buf.getvalue()); pnm = PNMImage()
        if pnm.read(ss):
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            card.setTexture(tex, 1)

    def _sdbg_update_hud(self):
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        idx   = getattr(self, '_sdbg_idx', 0) % len(faces)
        key   = faces[idx]
        reg   = self._sdbg_regs.get(key, [0,0,0,0])
        step  = getattr(self, '_sdbg_step', 2)
        lf = getattr(self, '_sdbg_lbl_face',  None)
        lc = getattr(self, '_sdbg_lbl_coord', None)
        if lf: lf.setText(f'Face {idx+1}/{len(faces)}: {key}   step={step}px')
        if lc: lc.setText(f'({reg[0]}, {reg[1]}, {reg[2]}, {reg[3]})')
        for k, (_, card) in self._sdbg_cards.items():
            card.setColorScale((1, 1, 0.1, 1) if k == key else (1, 1, 1, 1))

    def _sdbg_cycle(self, d):
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        self._sdbg_idx = (self._sdbg_idx + d) % len(faces)
        self._sdbg_update_hud()

    def _sdbg_move(self, dx, dy):
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        key = faces[self._sdbg_idx % len(faces)]
        s = self._sdbg_step; r = self._sdbg_regs[key]
        r[0] += dx*s; r[2] += dx*s
        r[1] += dy*s; r[3] += dy*s
        self._sdbg_rebuild_tex(key); self._sdbg_update_hud()

    def _sdbg_resize(self, dw, dh):
        """Ctrl+arrows: grow/shrink right or bottom edge."""
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        key = faces[self._sdbg_idx % len(faces)]
        s = self._sdbg_step; r = self._sdbg_regs[key]
        r[2] += dw*s; r[3] += dh*s
        self._sdbg_rebuild_tex(key); self._sdbg_update_hud()

    def _sdbg_stretch_w(self, d):
        """[: shrink width,  ]: expand width — moves left and right edges symmetrically."""
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        key = faces[self._sdbg_idx % len(faces)]
        s = self._sdbg_step; r = self._sdbg_regs[key]
        r[0] -= d*s; r[2] += d*s
        self._sdbg_rebuild_tex(key); self._sdbg_update_hud()

    def _sdbg_stretch_h(self, d):
        """,: shrink height,  .: expand height — moves top and bottom edges symmetrically."""
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        key = faces[self._sdbg_idx % len(faces)]
        s = self._sdbg_step; r = self._sdbg_regs[key]
        r[1] -= d*s; r[3] += d*s
        self._sdbg_rebuild_tex(key); self._sdbg_update_hud()

    def _sdbg_step_sz(self, d):
        self._sdbg_step = max(1, self._sdbg_step + d)
        self._sdbg_update_hud()

    def _sdbg_do_zoom(self, d):
        """+=zoom in (shrink crop), -=zoom out (expand crop), d=+1 or -1."""
        faces = [f[0] for f in self._SHIRT_DBG_FACES]
        key = faces[self._sdbg_idx % len(faces)]
        s = self._sdbg_step; r = self._sdbg_regs[key]
        r[0] += d*s; r[1] += d*s; r[2] -= d*s; r[3] -= d*s
        self._sdbg_rebuild_tex(key); self._sdbg_update_hud()

    def _sdbg_toggle_arms(self):
        """DEL: spread arms to T-pose so torso faces are visible; press again to reset."""
        self._sdbg_arms_out = not getattr(self, '_sdbg_arms_out', False)
        r_pivot = getattr(self, 'right_arm_pivot', None)
        l_pivot = getattr(self, 'left_arm_pivot', None)
        if self._sdbg_arms_out:
            if r_pivot: r_pivot.setR(-90)
            if l_pivot: l_pivot.setR( 90)
        else:
            if r_pivot: r_pivot.setR(0)
            if l_pivot: l_pivot.setR(0)

    def _sdbg_print(self):
        print('\n=== SHIRT DEBUG REGIONS (copy into _SHIRT_REGIONS) ===', flush=True)
        for k, v in self._sdbg_regs.items():
            print(f'    "{k}": ({v[0]}, {v[1]}, {v[2]}, {v[3]}),', flush=True)
        print('======================================================\n', flush=True)

    # ── Pants UV debug mode ─────────────────────────────────────────────────
    _PANTS_DBG_FACES = [
        ('torso_front','character',       ( 0,     0.52,  2),(-1, 1, 0,  2),(180,0,0)),
        ('torso_back', 'character',       ( 0,    -0.52,  2),(-1, 1, 0,  2),(  0,0,0)),
        ('torso_right','character',       ( 1.02,  0,     2),(-0.5,0.5,0,2),(-90,0,0)),
        ('torso_left', 'character',       (-1.02,  0,     2),(-0.5,0.5,0,2),( 90,0,0)),
        ('torso_up',   'character',       ( 0,     0,  4.02),(-1,1,-0.5,0.5),(0,-90,0)),
        ('torso_down', 'character',       ( 0,     0,  1.98),(-1,1,-0.5,0.5),(0, 90,0)),
        ('rleg_front', 'right_leg_pivot', ( 0,     0.52, -2),(-0.5,0.5,0,2),(180,0,0)),
        ('rleg_back',  'right_leg_pivot', ( 0,    -0.52, -2),(-0.5,0.5,0,2),(  0,0,0)),
        ('rleg_right', 'right_leg_pivot', ( 0.52,  0,    -2),(-0.5,0.5,0,2),(-90,0,0)),
        ('rleg_left',  'right_leg_pivot', (-0.52,  0,    -2),(-0.5,0.5,0,2),( 90,0,0)),
        ('rleg_up',    'right_leg_pivot', ( 0,     0,  0.02),(-0.5,0.5,-0.5,0.5),(0,-90,0)),
        ('rleg_down',  'right_leg_pivot', ( 0,     0, -2.02),(-0.5,0.5,-0.5,0.5),(0, 90,0)),
        ('lleg_front', 'left_leg_pivot',  ( 0,     0.52, -2),(-0.5,0.5,0,2),(180,0,0)),
        ('lleg_back',  'left_leg_pivot',  ( 0,    -0.52, -2),(-0.5,0.5,0,2),(  0,0,0)),
        ('lleg_right', 'left_leg_pivot',  ( 0.52,  0,    -2),(-0.5,0.5,0,2),(-90,0,0)),
        ('lleg_left',  'left_leg_pivot',  (-0.52,  0,    -2),(-0.5,0.5,0,2),( 90,0,0)),
        ('lleg_up',    'left_leg_pivot',  ( 0,     0,  0.02),(-0.5,0.5,-0.5,0.5),(0,-90,0)),
        ('lleg_down',  'left_leg_pivot',  ( 0,     0, -2.02),(-0.5,0.5,-0.5,0.5),(0, 90,0)),
    ]

    def start_pants_debug(self, image_b64):
        """Pants UV debug mode — same controls as shirt debug (F9 to exit)."""
        self.stop_pants_debug()
        self.remove_pants()
        if '|PANTSDATA|' in image_b64:
            image_b64 = image_b64.split('|PANTSDATA|')[0]
        try:
            from PIL import Image as _PIL
            import base64, io as _io
            from panda3d.core import PNMImage, StringStream, Texture
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode as _TN

            raw   = base64.b64decode(image_b64)
            tmpl  = _PIL.open(_io.BytesIO(raw)).convert("RGBA")
            if tmpl.size != (585, 559):
                tmpl = tmpl.resize((585, 559), _PIL.LANCZOS)

            self._pdbg_tmpl  = tmpl
            self._pdbg_raw   = image_b64
            self._pdbg_regs  = {k: list(v) for k, v in self._PANTS_REGIONS.items()}
            self._pdbg_idx   = 0
            self._pdbg_step  = 2
            self._pdbg_cards = {}

            for (key, par_attr, pos, frame, hpr) in self._PANTS_DBG_FACES:
                parent = getattr(self, par_attr, None)
                if not parent: continue
                from panda3d.core import CardMaker, TransparencyAttrib
                cm = CardMaker(f'pdbg_{key}'); cm.setFrame(*frame)
                anchor = parent.attachNewNode(f'pdbg_a_{key}'); anchor.setPos(*pos)
                card   = anchor.attachNewNode(cm.generate()); card.setHpr(*hpr)
                card.setTransparency(TransparencyAttrib.MAlpha)
                card.setShaderOff(); card.setLightOff()
                card.setDepthOffset(3); card.setDepthWrite(False)
                card.setTwoSided(True)
                self._pdbg_cards[key] = (anchor, card)
                self._pdbg_rebuild_tex(key)

            self._pdbg_lbl_face = OnscreenText(
                text='', pos=(-1.55, 0.92), scale=0.042,
                fg=(1, 1, 0.2, 1), align=_TN.ALeft, mayChange=True)
            self._pdbg_lbl_coord = OnscreenText(
                text='', pos=(-1.55, 0.80), scale=0.048,
                fg=(0.3, 1, 0.3, 1), align=_TN.ALeft, mayChange=True)
            self._pdbg_lbl_hint = OnscreenText(
                text='Tab/Shift-Tab: cycle   Arrows: move   Shift+Arrows: resize   +/-: zoom\n'
                     '[/]: width   ,/.: height   Z/X: speed   E: spread legs   P: print   F9: exit',
                pos=(-1.55, 0.65), scale=0.034,
                fg=(0.8, 0.8, 1, 1), align=_TN.ALeft, mayChange=False)

            self.accept('tab',               self._pdbg_cycle,       [ 1])
            self.accept('shift-tab',         self._pdbg_cycle,       [-1])
            self.accept('arrow_left',        self._pdbg_move,        [-1,  0])
            self.accept('arrow_right',       self._pdbg_move,        [ 1,  0])
            self.accept('arrow_up',          self._pdbg_move,        [ 0, -1])
            self.accept('arrow_down',        self._pdbg_move,        [ 0,  1])
            self.accept('shift-arrow_left',  self._pdbg_resize,      [-1,  0])
            self.accept('shift-arrow_right', self._pdbg_resize,      [ 1,  0])
            self.accept('shift-arrow_up',    self._pdbg_resize,      [ 0, -1])
            self.accept('shift-arrow_down',  self._pdbg_resize,      [ 0,  1])
            self.accept('[',                 self._pdbg_stretch_w,   [-1])
            self.accept(']',                 self._pdbg_stretch_w,   [ 1])
            self.accept(',',                 self._pdbg_stretch_h,   [-1])
            self.accept('.',                 self._pdbg_stretch_h,   [ 1])
            self.accept('=',                 self._pdbg_do_zoom,     [ 1])
            self.accept('-',                 self._pdbg_do_zoom,     [-1])
            self.accept('z',                 self._pdbg_step_sz,     [ 1])
            self.accept('x',                 self._pdbg_step_sz,     [-1])
            self.accept('p',                 self._pdbg_print)
            self.accept('e',                 self._pdbg_toggle_legs)
            self.accept('f9',                self.stop_pants_debug)

            self._pdbg_update_hud()
            print('[PANTS_DBG] started', flush=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f'[PANTS_DBG] start error: {e}', flush=True)

    def stop_pants_debug(self):
        for attr in ('_pdbg_lbl_face', '_pdbg_lbl_coord', '_pdbg_lbl_hint'):
            w = getattr(self, attr, None)
            if w:
                try: w.destroy()
                except Exception: pass
            setattr(self, attr, None)
        for key, (anchor, _) in getattr(self, '_pdbg_cards', {}).items():
            if anchor and not anchor.isEmpty(): anchor.removeNode()
        self._pdbg_cards = {}
        for ev in ('tab','shift-tab','arrow_left','arrow_right','arrow_up','arrow_down',
                   'shift-arrow_left','shift-arrow_right','shift-arrow_up','shift-arrow_down',
                   '[',']',',','.','=','-','z','x','e','p','f9'):
            self.ignore(ev)
        if getattr(self, '_pdbg_legs_out', False):
            self._pdbg_legs_out = False
            for piv in (getattr(self,'right_leg_pivot',None), getattr(self,'left_leg_pivot',None)):
                if piv: piv.setP(0); piv.setR(0)
        self._pdbg_tmpl = None
        print('[PANTS_DBG] stopped', flush=True)

    def _pdbg_rebuild_tex(self, key):
        if key not in getattr(self, '_pdbg_cards', {}): return
        _, card = self._pdbg_cards[key]
        tmpl = getattr(self, '_pdbg_tmpl', None)
        if tmpl is None: return
        try:
            from PIL import Image as _PIL
            import base64, io as _io
            from panda3d.core import PNMImage, StringStream, Texture
            r = self._pdbg_regs[key]
            x0,y0,x1,y1 = int(r[0]),int(r[1]),int(r[2]),int(r[3])
            w = max(1, abs(x1-x0)); h = max(1, abs(y1-y0))
            crop = tmpl.crop((min(x0,x1),min(y0,y1),min(x0,x1)+w,min(y0,y1)+h))
            buf = _io.BytesIO(); crop.save(buf, "PNG")
            raw = buf.getvalue()
            ss = StringStream(raw); pnm = PNMImage()
            if not pnm.read(ss): return
            tex = Texture(); tex.load(pnm)
            tex.setMagfilter(Texture.FTLinear); tex.setMinfilter(Texture.FTLinear)
            card.setTexture(tex, 1)
        except Exception as e:
            print(f'[PANTS_DBG] rebuild_tex {key}: {e}', flush=True)

    def _pdbg_update_hud(self):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        idx = self._pdbg_idx % len(faces); key = faces[idx]
        step = self._pdbg_step; reg = self._pdbg_regs[key]
        lf = getattr(self, '_pdbg_lbl_face', None)
        lc = getattr(self, '_pdbg_lbl_coord', None)
        if lf: lf.setText(f'Face {idx+1}/{len(faces)}: {key}   step={step}px')
        if lc: lc.setText(f'({reg[0]}, {reg[1]}, {reg[2]}, {reg[3]})')
        for k, (_, card) in self._pdbg_cards.items():
            card.setColorScale((1, 1, 0.1, 1) if k == key else (1, 1, 1, 1))

    def _pdbg_cycle(self, d):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        self._pdbg_idx = (self._pdbg_idx + d) % len(faces)
        self._pdbg_update_hud()

    def _pdbg_move(self, dx, dy):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        key = faces[self._pdbg_idx % len(faces)]
        s = self._pdbg_step; r = self._pdbg_regs[key]
        r[0] += dx*s; r[2] += dx*s; r[1] += dy*s; r[3] += dy*s
        self._pdbg_rebuild_tex(key); self._pdbg_update_hud()

    def _pdbg_resize(self, dw, dh):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        key = faces[self._pdbg_idx % len(faces)]
        s = self._pdbg_step; r = self._pdbg_regs[key]
        r[2] += dw*s; r[3] += dh*s
        self._pdbg_rebuild_tex(key); self._pdbg_update_hud()

    def _pdbg_stretch_w(self, d):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        key = faces[self._pdbg_idx % len(faces)]
        s = self._pdbg_step; r = self._pdbg_regs[key]
        r[0] -= d*s; r[2] += d*s
        self._pdbg_rebuild_tex(key); self._pdbg_update_hud()

    def _pdbg_stretch_h(self, d):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        key = faces[self._pdbg_idx % len(faces)]
        s = self._pdbg_step; r = self._pdbg_regs[key]
        r[1] -= d*s; r[3] += d*s
        self._pdbg_rebuild_tex(key); self._pdbg_update_hud()

    def _pdbg_step_sz(self, d):
        self._pdbg_step = max(1, self._pdbg_step + d)
        self._pdbg_update_hud()

    def _pdbg_do_zoom(self, d):
        faces = [f[0] for f in self._PANTS_DBG_FACES]
        key = faces[self._pdbg_idx % len(faces)]
        s = self._pdbg_step; r = self._pdbg_regs[key]
        r[0] += d*s; r[1] += d*s; r[2] -= d*s; r[3] -= d*s
        self._pdbg_rebuild_tex(key); self._pdbg_update_hud()

    def _pdbg_toggle_legs(self):
        """E: roll legs out to sides so side/back faces are visible; press again to reset."""
        self._pdbg_legs_out = not getattr(self, '_pdbg_legs_out', False)
        r_piv = getattr(self, 'right_leg_pivot', None)
        l_piv = getattr(self, 'left_leg_pivot', None)
        if self._pdbg_legs_out:
            if r_piv: r_piv.setR(-90)
            if l_piv: l_piv.setR( 90)
        else:
            if r_piv: r_piv.setR(0)
            if l_piv: l_piv.setR(0)

    def _pdbg_print(self):
        print('\n=== PANTS DEBUG REGIONS (copy into _PANTS_REGIONS) ===', flush=True)
        for k, v in self._pdbg_regs.items():
            print(f'    "{k}": ({v[0]}, {v[1]}, {v[2]}, {v[3]}),', flush=True)
        print('======================================================\n', flush=True)

    def apply_face(self, frames_b64):
        """Replace the animated face sprite with up to 3 custom PNG frames.
        frames_b64 is a list of base64-encoded PNG strings."""
        import base64 as _b64
        from panda3d.core import PNMImage, StringStream, Texture
        textures = []
        for i, fb in enumerate(frames_b64 or []):
            try:
                raw = _b64.b64decode(fb)
                print(f"[FACE_APPLY] frame {i} first32={raw[:32]}", flush=True)
                ss  = StringStream(raw)
                pnm = PNMImage()
                ok  = pnm.read(ss, "frame.png")
                print(f"[FACE_APPLY] frame {i}: raw_len={len(raw)} pnm_read={ok} size={pnm.getXSize()}x{pnm.getYSize()}", flush=True)
                if ok:
                    tex = Texture()
                    tex.load(pnm)
                    tex.setMagfilter(Texture.FTLinear)
                    tex.setMinfilter(Texture.FTLinear)
                    textures.append(tex)
            except Exception as e:
                print(f"[FACE_APPLY] frame {i} decode error: {e}", flush=True)
        print(f"[FACE_APPLY] total textures loaded: {len(textures)}", flush=True)
        if not textures:
            return
        self._face_textures = textures
        self._face_frame    = 0
        self._face_anim_t   = 0.0
        spr = getattr(self, '_face_sprite', None)
        print(f"[FACE_APPLY] _face_sprite exists={spr is not None} empty={spr.isEmpty() if spr else 'N/A'}", flush=True)
        if spr and not spr.isEmpty():
            spr.setTexture(textures[0])
            print(f"[FACE_APPLY] setTexture called OK", flush=True)

    def remove_face(self):
        """Restore the default built-in face textures."""
        import os as _os
        from panda3d.core import Filename
        _face_dir = _os.path.join(_os.getcwd(), 'textures', 'face sprites')
        textures = []
        for fname in ('facesprite1-removebg-preview.png',
                      'facesprite2-removebg-preview.png',
                      'facesprite3-removebg-preview.png'):
            t = self.loader.loadTexture(
                Filename.fromOsSpecific(_os.path.join(_face_dir, fname)))
            if t:
                textures.append(t)
        if textures:
            self._face_textures = textures
            self._face_frame    = 0
            self._face_anim_t   = 0.0
            spr = getattr(self, '_face_sprite', None)
            if spr and not spr.isEmpty():
                spr.setTexture(textures[0])

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
                from panda3d.core import PNMImage, StringStream, Texture
                raw = base64.b64decode(tex_b64)
                ss  = StringStream(raw)
                pnm = PNMImage()
                if pnm.read(ss):
                    tex = Texture()
                    tex.load(pnm)
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
        if not self.is_playtest or getattr(self, '_respawning', False):
            m.hide()
            return Task.cont
        m.show()
        hp = self.head.getPos(self.render)
        z  = getattr(self, '_equipped_hat_z_off', 0.0)
        m.setPos(hp.x, hp.y, hp.z + 0.55 + z)
        h0, p0, r0 = getattr(self, '_equipped_hat_hpr', [0, 0, -90])
        m.setHpr(self.character.getH() + h0, p0, r0)
        return Task.cont
