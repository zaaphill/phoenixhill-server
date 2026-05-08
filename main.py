import sys, os

# Must match GAME_VERSION in server.py — bump both together when shipping.
MY_VERSION = "1.0"

if getattr(sys, 'frozen', False):
    os.chdir(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))

from game import MyGame

# Path to a pending update batch script; set by _update_worker when ready.
_pending_update_bat = None


def _start_update_check():
    import threading
    threading.Thread(target=_update_worker, daemon=True).start()


def _update_worker():
    global _pending_update_bat
    import json, tempfile
    from urllib.request import urlopen, urlretrieve

    try:
        import config as cfg_mod
        cfg = cfg_mod.get()
        with urlopen(f"{cfg['http']}/api/version", timeout=6) as r:
            data = json.loads(r.read())

        remote  = data.get("version", "")
        dl_url  = data.get("url", "")

        if not remote or remote == MY_VERSION:
            return
        if not dl_url:
            print(f"[UPDATE] v{remote} available but no download URL set on server")
            return
        if not getattr(sys, "frozen", False):
            print(f"[UPDATE] v{remote} available (skipping auto-update in dev mode)")
            return

        print(f"[UPDATE] downloading v{remote} ...")
        tmp = os.path.join(tempfile.gettempdir(), "PhoenixHill_update.exe")
        urlretrieve(dl_url, tmp)

        cur = sys.executable
        bat = os.path.join(tempfile.gettempdir(), "ph_update.bat")
        with open(bat, "w") as f:
            f.write("@echo off\n")
            f.write("timeout /t 2 /nobreak >nul\n")        # wait for old exe to exit
            f.write(f'move /y "{tmp}" "{cur}"\n')          # swap in new exe
            f.write(f'start "" "{cur}"\n')                 # relaunch
            f.write('del "%~f0"\n')                        # self-delete batch
        _pending_update_bat = bat
        print(f"[UPDATE] v{remote} ready — will apply when game closes")

    except Exception as e:
        print(f"[UPDATE] check failed: {e}")


if __name__ == "__main__":
    _start_update_check()
    game = MyGame()
    game.run()

    # game.run() returns when the window is closed — apply update now if ready.
    if _pending_update_bat and os.path.exists(_pending_update_bat):
        import subprocess
        subprocess.Popen(["cmd", "/c", _pending_update_bat],
                         creationflags=subprocess.CREATE_NO_WINDOW)
