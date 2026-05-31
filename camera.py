from panda3d.core import Vec2, Vec3, WindowProperties
from direct.task import Task
from math import radians, cos, sin


class CameraMixin:
    def zoom_camera(self, direction):
        if not self.is_playtest:
            return
        if self.is_first_person:
            if direction < 0:  # scroll out → exit first-person
                self._exit_first_person()
            return
        new_dist = self.cam_distance - direction * self.zoom_step
        if new_dist < self.min_cam_distance and direction > 0:
            # Trying to zoom past the minimum → snap to first-person
            self.cam_distance = self.min_cam_distance
            self._enter_first_person()
        else:
            self.cam_distance = max(self.min_cam_distance, min(self.max_cam_distance, new_dist))

    def _enter_first_person(self):
        # Cancel any in-progress right-click rotation so it doesn't bleed through.
        self.is_rotating = False
        self._hide_fake_cursor()
        self.is_first_person = True
        self.character.hide()
        props = WindowProperties()
        props.setCursorHidden(True)
        self.win.requestProperties(props)
        wp = self.win.getProperties()
        self.win.movePointer(0, wp.getXSize() // 2, wp.getYSize() // 2)

    def _exit_first_person(self):
        if not self.is_first_person:
            return
        self.is_first_person = False
        self.is_rotating = False  # ensure no leftover rotation state
        # Seed the delta-rotate tracker so the first right-click drag starts clean.
        md = self.win.getPointer(0)
        self._rot_last_x = int(md.getX())
        self._rot_last_y = int(md.getY())
        self.cam_distance = self.min_cam_distance
        self.character.show()
        if not getattr(self, 'shift_lock', False):
            self._restore_cursor()
        else:
            wp = self.win.getProperties()
            self.win.movePointer(0, wp.getXSize() // 2, wp.getYSize() // 2)

    def _update_first_person_camera(self):
        h_rad = radians(self.cam_angle.x)
        v_rad = radians(self.cam_angle.y)
        eye = self.cam_target.getPos(self.render)
        self.camera.setPos(eye)
        # Mirror the third-person look direction: orbit at (h,v) looks toward the center
        # with direction (-cos(v)*sin(h), cos(v)*cos(h), -sin(v)), so FP uses the same.
        look = eye + Vec3(
            -cos(v_rad) * sin(h_rad),
             cos(v_rad) * cos(h_rad),
            -sin(v_rad),
        )
        self.camera.lookAt(look)

    def _restore_cursor(self):
        """Show the custom cursor, re-applying the .cur file so it never reverts to default."""
        from panda3d.core import Filename as Fn
        props = WindowProperties()
        props.setCursorHidden(False)
        path = getattr(self, '_cursor_path', None)
        if path:
            props.setCursorFilename(Fn.fromOsSpecific(path))
        self.win.requestProperties(props)

    def _init_fake_cursor(self):
        from panda3d.core import CardMaker, TransparencyAttrib
        try:
            cursor_px = getattr(self, '_cursor_size_px', 32)
            win_w = max(self.win.getXSize(), 1)
            win_h = max(self.win.getYSize(), 1)
            # render2d spans exactly -1 to +1 in both axes over the full window.
            # Size in render2d units so the card is cursor_px × cursor_px pixels.
            sx = cursor_px * 2.0 / win_w
            sz = cursor_px * 2.0 / win_h
            # Card origin (0,0,0) = arrow hotspot (top-left corner).
            cm = CardMaker('fake_cursor')
            cm.setFrame(0, sx, -sz, 0)   # extends right (+x) and down (-z)
            np = self.render2d.attachNewNode(cm.generate())
            tex = self.loader.loadTexture('arrow_nw.png')
            np.setTexture(tex)
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setLightOff()
            np.setShaderOff()
            np.setBin('gui-popup', 60)
            np.setDepthWrite(False)
            np.hide()
            self._fake_cursor_img = np
        except Exception as e:
            print(f'[FAKE_CURSOR] init failed: {e}', flush=True)
            self._fake_cursor_img = None

    def _show_fake_cursor(self, mx, my):
        """mx, my are raw getMouse() values — render2d coords, no conversion needed."""
        if not hasattr(self, '_fake_cursor_img'):
            self._init_fake_cursor()
        img = getattr(self, '_fake_cursor_img', None)
        if img is None:
            return
        img.setPos(mx, 0, my)
        img.show()

    def _hide_fake_cursor(self):
        img = getattr(self, '_fake_cursor_img', None)
        if img:
            img.hide()

    def startRotate(self):
        if self.is_first_person or getattr(self, 'shift_lock', False):
            return
        if self.mouseWatcherNode.hasMouse():
            self.is_rotating = True
            md = self.win.getPointer(0)
            self._rotate_anchor_x = int(md.getX())
            self._rotate_anchor_y = int(md.getY())
            # Seed last-position tracker so the first delta is zero.
            self._rot_last_x = self._rotate_anchor_x
            self._rot_last_y = self._rotate_anchor_y
            mpos = self.mouseWatcherNode.getMouse()
            # Show fake cursor BEFORE hiding the real one — no flash.
            self._show_fake_cursor(mpos.x, mpos.y)
            props = WindowProperties()
            props.setCursorHidden(True)
            self.win.requestProperties(props)
            # Skip centering on the first _delta_rotate call so the cursor
            # hide has one frame to take effect before movePointer runs.
            self._rotate_skip_first = True

    def stopRotate(self):
        if self.is_first_person or getattr(self, 'shift_lock', False):
            return
        self.is_rotating = False
        self._hide_fake_cursor()
        ax = getattr(self, '_rotate_anchor_x', None)
        ay = getattr(self, '_rotate_anchor_y', None)
        if ax is not None and ay is not None:
            self.win.movePointer(0, ax, ay)
        self._restore_cursor()

    def toggle_shift_lock(self):
        if not self.is_playtest or self.is_first_person:
            return
        self.shift_lock = not self.shift_lock
        if self.shift_lock:
            self.is_rotating = False
            self._hide_fake_cursor()
            props = WindowProperties()
            props.setCursorHidden(True)
            self.win.requestProperties(props)
            wp = self.win.getProperties()
            self.win.movePointer(0, wp.getXSize() // 2, wp.getYSize() // 2)
        else:
            self._restore_cursor()

    def _delta_shift_lock(self):
        """Cursor hidden; measures delta from centre and re-centres (shift-lock mode)."""
        wp = self.win.getProperties()
        cx, cy = wp.getXSize() // 2, wp.getYSize() // 2
        md = self.win.getPointer(0)
        dx, dy = int(md.getX()) - cx, int(md.getY()) - cy
        if dx != 0 or dy != 0:
            self.win.movePointer(0, cx, cy)
        return dx, dy

    def _delta_rotate(self):
        """Cursor hidden; measures delta then re-centres to prevent screen-edge lock."""
        wp = self.win.getProperties()
        cenx, ceny = wp.getXSize() // 2, wp.getYSize() // 2
        md = self.win.getPointer(0)
        px, py = int(md.getX()), int(md.getY())
        lx = getattr(self, '_rot_last_x', px)
        ly = getattr(self, '_rot_last_y', py)
        dx, dy = px - lx, py - ly
        # On the very first frame after startRotate, skip the centre-warp so
        # the cursor-hide request has one frame to take effect — prevents the
        # real cursor from flashing at the centre of the screen.
        if getattr(self, '_rotate_skip_first', False):
            self._rotate_skip_first = False
            self._rot_last_x = px
            self._rot_last_y = py
            return 0, 0
        self.win.movePointer(0, cenx, ceny)
        self._rot_last_x = cenx
        self._rot_last_y = ceny
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
            invert = getattr(self, '_settings_invert_play', False)
            if self.is_first_person:
                dx, dy = self._delta_shift_lock()
                self.cam_angle.x -= dx * 0.2
                # Mouse UP → dy < 0. Normal: y decreases → look.z rises → looks up.
                # Inverted: y increases → look.z drops → looks down.
                if invert:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y - dy * 0.2))
                else:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y + dy * 0.2))
                self._update_first_person_camera()
            elif getattr(self, 'shift_lock', False):
                dx, dy = self._delta_shift_lock()
                self.cam_angle.x -= dx * 0.2
                if invert:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y + dy * 0.2))
                else:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y - dy * 0.2))
                self.updateCamera()
            elif self.is_rotating:
                dx, dy = self._delta_rotate()
                self.cam_angle.x -= dx * 0.2
                if invert:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y + dy * 0.2))
                else:
                    self.cam_angle.y = max(-80, min(80, self.cam_angle.y - dy * 0.2))
                self.updateCamera()
            else:
                self.updateCamera()
        else:
            self.updateFreecam(dt)
        return Task.cont

    def updateFreecam(self, dt):
        speed = getattr(self, '_settings_editor_speed', 15)
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
            invert_ed = getattr(self, '_settings_invert_editor', False)
            self.camera.setH(self.camera.getH() - dx * 0.25)
            if invert_ed:
                self.camera.setP(max(-89, min(89, self.camera.getP() - dy * 0.25)))
            else:
                self.camera.setP(max(-89, min(89, self.camera.getP() + dy * 0.25)))
