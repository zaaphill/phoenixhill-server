import sys, os

if getattr(sys, 'frozen', False):
    os.chdir(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))

from game import MyGame

if __name__ == "__main__":
    game = MyGame()
    game.run()
