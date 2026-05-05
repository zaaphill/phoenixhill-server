import sys, os

# When packaged with PyInstaller, switch to the bundle directory so all
# relative paths (server.cfg, arrow_nw.png, textures/) resolve correctly.
if getattr(sys, 'frozen', False):
    os.chdir(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))

from game import MyGame

if __name__ == "__main__":
    game = MyGame()
    game.run()
