from panda3d.core import (
    NodePath, Vec3,
    GeomVertexFormat, GeomVertexData, Geom,
    GeomVertexWriter, GeomTriangles, GeomNode,
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
        self.keys[key] = value

    def start_jump(self):
        if self.is_playtest and not self.is_jumping:
            self.is_jumping = True
            self.vertical_speed = self.jump_speed

    def updateMovement(self, task):
        dt = globalClock.getDt()
        if not self.is_playtest:
            return Task.cont
        if getattr(self, "_chat_input_active", False):
            return Task.cont

        current_pos = self.character.getPos()

        if current_pos.z < -20:
            self.character.setPos(0, 0, self.floor_top)
            self.vertical_speed = 0
            self.is_jumping = False
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

        if getattr(self, 'shift_lock', False):
            self.character.setH(self.cam_angle.x)

        current_pos = self.character.getPos()
        ground_height = self.get_ground_height_at_position(current_pos)

        MAX_STEP = 1.2
        if not self.is_jumping and self.vertical_speed <= 0:
            char_box = self.get_character_collision_box(current_pos)
            for brick in self.bricks:
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

        if not self.is_jumping and self.keys.get("space"):
            self.is_jumping = True
            self.vertical_speed = self.jump_speed

        self.character.setZ(new_z)
        self._unstuck_character()
        return Task.cont

    def spawn_unstuck(self):
        """Called once when entering playtest. If the character overlaps any
        brick, teleport them on top of the highest overlapping brick's surface."""
        pos      = self.character.getPos()
        char_box = self.get_character_collision_box(pos)
        highest_top = None
        for brick in self.bricks:
            brick_box = self.get_brick_collision_box(brick)
            if self.boxes_collide(char_box, brick_box):
                if highest_top is None or brick_box['max_z'] > highest_top:
                    highest_top = brick_box['max_z']
        if highest_top is not None:
            self.character.setZ(highest_top)
            self.vertical_speed = 0
            self.is_jumping = False

    def _unstuck_character(self):
        """If the character overlaps any brick, push them out along the
        minimum-penetration axis. Runs up to 4 iterations per frame so
        overlapping multiple bricks at once is still resolved."""
        for _ in range(4):
            pos      = self.character.getPos()
            char_box = self.get_character_collision_box(pos)

            best_push      = None
            best_push_dist = float('inf')

            for brick in self.bricks:
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
                self.vertical_speed = 0
                self.is_jumping = False
            elif best_push.z < 0 and self.vertical_speed > 0:
                self.vertical_speed = 0
