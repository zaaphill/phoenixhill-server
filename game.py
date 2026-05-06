from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    VBase4, Vec2, AmbientLight, DirectionalLight,
    CollisionTraverser, CollisionHandlerQueue, CollisionNode,
    CollisionRay, BitMask32, WindowProperties, Filename,
    loadPrcFileData,
)
import os
import struct

loadPrcFileData("", "win-size 1280 720")
loadPrcFileData("", "win-origin -2 -2")
loadPrcFileData("", "window-title PhoenixHill")

def _set_png_cursor(win, png_name, hotspot_x=0, hotspot_y=0):
    """Scale a PNG to the system cursor size, wrap it in a .cur container
    (PNG-in-CUR is supported on Windows Vista+), and apply it to the window."""
    import ctypes, tempfile
    from panda3d.core import PNMImage, Filename as Fn

    # os.getcwd() is the app directory both in dev and in packaged builds.
    png_path = os.path.join(os.getcwd(), png_name)
    if not os.path.exists(png_path):
        return

    try:
        target = ctypes.windll.user32.GetSystemMetrics(13)  # SM_CXCURSOR
        if target <= 0:
            target = 32
    except Exception:
        target = 32

    img = PNMImage()
    img.read(Fn.fromOsSpecific(png_path))
    if img.getXSize() != target or img.getYSize() != target:
        scaled = PNMImage(target, target, img.getNumChannels())
        scaled.gaussianFilterFrom(1.0, img)
        img = scaled

    # Write temp files to the OS temp directory (always writable).
    tmp_dir  = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, '_phx_cursor.png')
    cur_path = os.path.join(tmp_dir, png_name.rsplit('.', 1)[0] + '.cur')

    img.write(Fn.fromOsSpecific(tmp_path))
    with open(tmp_path, 'rb') as fh:
        png_data = fh.read()
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    w = struct.unpack('>I', png_data[16:20])[0]
    h = struct.unpack('>I', png_data[20:24])[0]
    icondir = struct.pack('<HHH', 0, 2, 1)
    entry   = struct.pack('<BBBBHHII',
        w if w < 256 else 0, h if h < 256 else 0, 0, 0,
        hotspot_x, hotspot_y,
        len(png_data), 6 + 16)
    with open(cur_path, 'wb') as fh:
        fh.write(icondir + entry + png_data)

    props = WindowProperties()
    props.setCursorFilename(Fn.fromOsSpecific(cur_path))
    win.requestProperties(props)


from character import CharacterMixin
from camera import CameraMixin
from ui import UIMixin
from bricks import BrickMixin
from picking import PickingMixin
from shadows import ShadowMixin
from ui_debug import UIDebugMixin
from sky import SkyMixin
from login_screen import LoginScreenMixin
from cloud import CloudMixin
from multiplayer import MultiplayerMixin


class MyGame(ShowBase, BrickMixin, PickingMixin, UIMixin, CharacterMixin, CameraMixin, ShadowMixin, UIDebugMixin, SkyMixin, LoginScreenMixin, CloudMixin, MultiplayerMixin):
    def __init__(self):
        ShowBase.__init__(self)

        self.setBackgroundColor(0.49, 0.72, 0.83, 1)

        _set_png_cursor(self.win, 'arrow_nw.png', hotspot_x=0, hotspot_y=0)

        self.setup_sky()

        # Character
        self.setup_character()

        # Directional sun light (no shadow map — blob shadows handle it)
        self.dlight = DirectionalLight("dlight")
        self.dlight.setColor(VBase4(1.0, 0.95, 0.85, 1))
        self.dlnp = self.render.attachNewNode(self.dlight)
        self.dlnp.setHpr(-30, -65, 0)
        self.render.setLight(self.dlnp)

        alight = AmbientLight("alight")
        alight.setColor(VBase4(0.55, 0.6, 0.68, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)
        self.render.setShaderAuto()
        self.character.setShaderOff()
        self.setup_blob_shadows()

        # Camera
        self.disableMouse()
        self.cam_distance = 20
        self.cam_angle = Vec2(0, 20)
        self.is_rotating = False
        self.last_mouse_pos = None
        self.updateCamera()

        self.accept("wheel_up",   self._on_wheel, [1])
        self.accept("wheel_down", self._on_wheel, [-1])
        self.min_cam_distance = 5
        self.max_cam_distance = 40
        self.zoom_step = 2

        # Movement
        self.keys = {"w": False, "a": False, "s": False, "d": False, "q": False, "e": False, "space": False}
        for k in self.keys:
            self.accept(k,        self.setKey, [k, True])
            self.accept(k + "-up", self.setKey, [k, False])
        self.is_jumping    = False
        self.jump_speed    = 50
        self.vertical_speed = 0
        self.gravity       = -196.2
        self.walking_angle  = 0.0
        self.walking_speed  = 10.0
        self.max_swing_angle = 30
        self.accept("mouse3",    self.startRotate)
        self.accept("mouse3-up", self.stopRotate)
        self.shift_lock = False
        self.accept("lshift", self.toggle_shift_lock)

        # Tasks — movement runs first so camera has the updated position this frame
        self.taskMgr.add(self.updateMovement,       "updateMovementTask")
        self.taskMgr.add(self.updateCameraTask,     "updateCameraTask")
        self.taskMgr.add(self.updateHandlesTask,    "updateHandlesTask")
        self.taskMgr.add(self.updateVisualHitboxes, "updateVisualHitboxesTask")

        self.move_speed  = 16
        self.turn_speed  = 720

        # Mode flags
        self.is_playtest   = True
        self.is_move_mode  = False
        self.is_scale_mode = False

        # Brick state
        self.bricks = []
        self.brick_collision_nodes = {}
        self.selected_brick = None
        self.move_handles = []
        self.dragging = False
        self.drag_handle = None
        self.drag_start_mouse_world = None
        self.drag_start_brick_pos = None
        self.scale_handles = []
        self.scale_dragging = False
        self.scale_drag_start_scale = None
        self.scale_drag_start_pos   = None
        self.scale_drag_center      = None
        self.scale_drag_start_mouse = None

        # Sub-systems
        self.setup_collision_system()
        self.setup_visual_hitboxes()
        self.setup_ui()
        self.setup_ui_debug()
        self.create_baseplate()

        # Mouse picking
        self.picker    = CollisionTraverser()
        self.pq        = CollisionHandlerQueue()
        self.pickerNode = CollisionNode('mouseRay')
        self.pickerNP  = self.camera.attachNewNode(self.pickerNode)
        self.pickerNode.setFromCollideMask(BitMask32.bit(1))
        self.pickerNode.setIntoCollideMask(BitMask32.allOff())
        self.pickerRay = CollisionRay()
        self.pickerNode.addSolid(self.pickerRay)
        self.picker.addCollider(self.pickerNP, self.pq)

        self.accept("mouse1",    self.on_mouse1_down)
        self.accept("mouse1-up", self.on_mouse1_up)

        self.setup_login_screen()

    def userExit(self):
        """Called when the window X button is clicked."""
        self.stop_multiplayer()
        ShowBase.userExit(self)
