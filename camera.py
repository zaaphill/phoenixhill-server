from panda3d.core import Vec2, Vec3, WindowProperties
from direct.task import Task
from math import radians, cos, sin


class CameraMixin:
    def zoom_camera(self, direction):
        if self.is_playtest:
            self.cam_distance -= direction * self.zoom_step
            self.cam_distance = max(self.min_cam_distance, min(self.max_cam_distance, self.cam_distance))

    def startRotate(self):
        if getattr(self, 'shift_lock', False):
            return
        if self.mouseWatcherNode.hasMouse():
            self.is_rotating = True
            md = self.win.getPointer(0)
            # Anchor point: cursor stays here visually while rotating.
            # We do NOT hide the cursor — it just appears stationary.
            self._rotate_anchor_x = int(md.getX())
            self._rotate_anchor_y = int(md.getY())

    def stopRotate(self):
        self.is_rotating = False
        # Cursor was never hidden so there is nothing to restore.

    def toggle_shift_lock(self):
        if not self.is_playtest:
            return
        self.shift_lock = not self.shift_lock
        props = WindowProperties()
        props.setCursorHidden(self.shift_lock)
        self.win.requestProperties(props)
        if self.shift_lock:
            wp = self.win.getProperties()
            self.win.movePointer(0, wp.getXSize() // 2, wp.getYSize() // 2)

    def _delta_shift_lock(self):
        """Cursor is hidden; measures delta from screen centre and re-centres."""
        wp = self.win.getProperties()
        cx, cy = wp.getXSize() // 2, wp.getYSize() // 2
        md = self.win.getPointer(0)
        dx, dy = int(md.getX()) - cx, int(md.getY()) - cy
        if dx != 0 or dy != 0:
            self.win.movePointer(0, cx, cy)
        return dx, dy

    def _delta_rotate(self):
        """Cursor stays visible; measures delta from anchor and locks it there."""
        ax = getattr(self, '_rotate_anchor_x', self.win.getProperties().getXSize() // 2)
        ay = getattr(self, '_rotate_anchor_y', self.win.getProperties().getYSize() // 2)
        md = self.win.getPointer(0)
        dx, dy = int(md.getX()) - ax, int(md.getY()) - ay
        if dx != 0 or dy != 0:
            self.win.movePointer(0, ax, ay)
        return dx, dy

    def updateCamera(self):
        h_rad = radians(self.cam_angle.x)
        v_rad = radians(self.cam_angle.y)
        center = self.cam_target.getPos(self.render)
        x = center.x + self.cam_distance * cos(v_rad) * sin(h_rad)
        y = center.y - self.cam_distance * cos(v_rad) * cos(h_rad)
        z = center.z + self.cam_distance * sin(v_rad)
        self.camera.setPos(x, y, z)
        self.camera.lookAt(center)

    def updateCameraTask(self, task):
        dt = globalClock.getDt()
        if self.is_playtest:
            if getattr(self, 'shift_lock', False):
                dx, dy = self._delta_shift_lock()
                self.cam_angle.x -= dx * 0.2
                self.cam_angle.y = max(-10, min(80, self.cam_angle.y - dy * 0.2))
            elif self.is_rotating:
                dx, dy = self._delta_rotate()
                self.cam_angle.x -= dx * 0.2
                self.cam_angle.y = max(-10, min(80, self.cam_angle.y - dy * 0.2))
            self.updateCamera()
        else:
            self.updateFreecam(dt)
        return Task.cont

    def updateFreecam(self, dt):
        speed = 15
        cam_quat = self.camera.getQuat(self.render)
        forward = cam_quat.getForward()
        right    = cam_quat.getRight()
        up       = cam_quat.getUp()
        move_vec = Vec2(0, 0)
        if self.keys["w"]: move_vec.y += 1
        if self.keys["s"]: move_vec.y -= 1
        if self.keys["a"]: move_vec.x -= 1
        if self.keys["d"]: move_vec.x += 1
        move_dir = forward * move_vec.y + right * move_vec.x
        if self.keys["q"]: move_dir -= up
        if self.keys["e"]: move_dir += up
        if move_dir.length() > 0:
            move_dir.normalize()
            self.camera.setPos(self.camera.getPos() + move_dir * speed * dt)
        if self.is_rotating:
            dx, dy = self._delta_rotate()
            self.camera.setH(self.camera.getH() - dx * 0.25)
            self.camera.setP(max(-89, min(89, self.camera.getP() + dy * 0.25)))
