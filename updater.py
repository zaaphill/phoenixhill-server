"""
Auto-updater for PhoenixHill / PiePlex.

How to set up:
  1. Set GITHUB_REPO to "yourname/yourrepo"  (e.g. "zaaphill/phoenixhill-server")
  2. Bump VERSION here each time you build a new EXE
  3. On GitHub, create a Release tagged "v1.2.3" and upload the EXE as an asset
  4. The updater will find it automatically via the GitHub Releases API

Swap strategy:
  - Download to %TEMP% (avoids OneDrive file-lock on the exe directory)
  - os.replace() the temp file over sys.executable
  - Relaunch via a detached PowerShell -WindowStyle Hidden process (no
    visible window at all) that sleeps 6 s then starts the new EXE
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────────────

VERSION = "1.1.26"

def _version_url():
    try:
        import config
        return config.get()["http"] + "/api/version"
    except Exception:
        return None

# Log file written beside the EXE so we can inspect what happened.
_LOG_PATH = os.path.join(tempfile.gettempdir(), "_phill_updater.log")

def _log(msg):
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except Exception:
        pass

# ── Version parsing ───────────────────────────────────────────────────────────

def _parse_ver(v):
    try:
        return tuple(int(x) for x in str(v).lstrip("vV").strip().split("."))
    except Exception:
        return (0,)

# ── Background version check ──────────────────────────────────────────────────

def check_for_update(on_available):
    """
    Spawns a daemon thread.  If a newer release exists, calls
    on_available(version_tag, download_url) — may come from any thread.
    Does nothing when running as a plain .py script (dev mode).
    """
    if not getattr(sys, "frozen", False):
        return

    def _run():
        try:
            url = _version_url()
            if not url:
                _log("Could not resolve version URL.")
                return
            _log(f"Checking for update at {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "PhoenixHill-Updater/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())

            latest = data.get("version", "")
            dl_url = data.get("url", "")
            _log(f"Latest: {latest}  running: {VERSION}")
            if not dl_url or _parse_ver(latest) <= _parse_ver(VERSION):
                _log("Already up to date.")
                return

            _log(f"Update available: {latest}")
            on_available(latest, dl_url)
        except Exception as exc:
            _log(f"check_for_update error: {exc}")

    threading.Thread(target=_run, daemon=True).start()

# ── Download + apply ──────────────────────────────────────────────────────────

def download_update(url, on_progress, on_done, on_error):
    """
    Downloads *url* to %TEMP%, then schedules a hidden PowerShell process to
    move it over the running EXE and relaunch after this process exits.

    Keeping the file in %TEMP% avoids WinError 32 — no copy to the EXE
    directory while the game is running; PowerShell does the move after exit.

    Callbacks are called from the worker thread:
      on_progress(float 0..1), on_done(), on_error(str)
    """
    def _run():
        tmp     = None
        staging = None
        try:
            # Step 1: download to %TEMP%
            tmp_fd, tmp = tempfile.mkstemp(suffix=".exe", prefix="_phill_upd_")
            os.close(tmp_fd)
            _log(f"Downloading to tmp: {tmp}")

            req = urllib.request.Request(
                url, headers={"User-Agent": "PhoenixHill-Updater/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done  = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total and on_progress:
                            on_progress(done / total)

            _log(f"Download complete ({done} bytes).")

            # Step 2: schedule a move from %TEMP% directly to the EXE path.
            # Keeping the file in %TEMP% avoids WinError 32 — no need to copy
            # to the EXE directory while the game is still running.
            current = sys.executable
            _log(f"Scheduling post-exit install: {tmp} → {current}")
            tmp_for_ps = tmp
            tmp = None  # prevent cleanup in except block
            _schedule_relaunch(current, tmp_for_ps)

            on_done()

        except Exception as exc:
            _log(f"download_update FAILED: {exc}")
            for path in (tmp, staging):
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            if on_error:
                on_error(str(exc))

    threading.Thread(target=_run, daemon=True).start()


def _schedule_relaunch(current, staging):
    """
    Registers a one-time Windows Scheduled Task (via schtasks.exe) that runs a
    PowerShell script to swap the EXE and relaunch it.  Task Scheduler runs as
    a system service — completely outside any Windows Job Object that would kill
    regular child processes when the PyInstaller game process exits.
    schtasks is called synchronously so registration completes before os._exit.
    """
    import datetime

    sp = staging.replace("'", "''")
    cp = current.replace("'", "''")
    lp = _LOG_PATH.replace("'", "''")
    pid = os.getpid()

    ps_script = f"""
function Log($m) {{
    try {{ Add-Content -Path '{lp}' -Value "$([DateTime]::Now.ToString('HH:mm:ss'))  PS: $m" }} catch {{}}
}}
Log 'Task started'
if (Get-Process -Id {pid} -EA SilentlyContinue) {{
    Log 'waiting for PID {pid}'
    $dl = (Get-Date).AddSeconds(30)
    while ((Get-Process -Id {pid} -EA SilentlyContinue) -and (Get-Date) -lt $dl) {{ Start-Sleep 1 }}
    Stop-Process -Id {pid} -Force -EA SilentlyContinue
}}
Log 'process gone, sleeping 2s'
Start-Sleep 2
$ok = $false
for ($i = 0; $i -lt 30; $i++) {{
    try {{
        [System.IO.File]::Replace('{sp}', '{cp}', '{cp}.bak')
        Remove-Item '{cp}.bak' -Force -EA SilentlyContinue
        $ok = $true
        Log "replace ok attempt $i"
        break
    }} catch {{
        Log "attempt $i failed: $($_.Exception.Message)"
        Start-Sleep 1
    }}
}}
if ($ok) {{
    Log 'launching'
    for ($j = 0; $j -lt 20; $j++) {{
        try {{ Start-Process '{cp}'; Log 'launch ok'; break }}
        catch {{ Log "launch $j failed: $($_.Exception.Message)"; Start-Sleep 1 }}
    }}
}} else {{
    Log 'all replace attempts failed'
}}
schtasks /delete /tn PhillUpdater /f 2>$null
Remove-Item -Path $PSCommandPath -Force -EA SilentlyContinue
"""

    script_path = os.path.join(tempfile.gettempdir(), '_phill_relaunch.ps1')
    try:
        with open(script_path, 'w', encoding='utf-8-sig') as f:
            f.write(ps_script)
    except Exception as e:
        _log(f"Failed to write relaunch script: {e}")
        return

    # Schedule 2 minutes from now. schtasks /st only accepts HH:MM (no
    # seconds), so we round forward to a whole minute. Using 2 min ensures
    # the scheduled time is always in the future even after rounding.
    run_at = (datetime.datetime.now() + datetime.timedelta(minutes=2)).strftime('%H:%M')
    try:
        result = subprocess.run(
            ['schtasks', '/create', '/f',
             '/tn', 'PhillUpdater',
             '/tr', f'powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script_path}"',
             '/sc', 'once',
             '/st', run_at],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            _log(f"schtasks failed: {result.stderr.decode(errors='replace').strip()}")
            return
        _log(f"Task scheduled for {run_at}")
    except Exception as e:
        _log(f"schtasks error: {e}")
        return

    _log("Scheduling relaunch")

# ── Panda3D integration ───────────────────────────────────────────────────────

_active_dialog = None   # module-level ref so GC doesn't collect the DirectFrame


def start_update_check(game):
    """
    Call once after the Panda3D window is open (e.g. at end of game __init__).
    Runs the version check in the background; shows a dialog if an update
    is available.
    """
    _pending = []   # list.append / list.pop are GIL-atomic in CPython

    def _on_available(ver, url):
        _pending.append((ver, url))

    check_for_update(_on_available)

    def _poll(task):
        if _pending:
            ver, url = _pending.pop(0)
            _show_dialog(game, ver, url)
            return task.done
        return task.cont

    game.taskMgr.add(_poll, "_update_poll_task")


def _show_dialog(game, new_ver, dl_url):
    global _active_dialog
    from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectButton

    DARK   = (0.09, 0.10, 0.14, 0.97)
    MED    = (0.17, 0.19, 0.26, 1.0)
    BTN    = (0.19, 0.21, 0.29, 1.0)
    ACCT   = (0.18, 0.38, 0.72, 1.0)
    TEXT   = (0.88, 0.90, 0.95, 1.0)
    TEXT_D = (0.54, 0.57, 0.65, 1.0)

    root = DirectFrame(
        frameColor=DARK,
        frameSize=(-0.60, 0.60, -0.38, 0.38),
        pos=(0, 0, 0),
        sortOrder=200,
    )
    _active_dialog = root   # keep alive

    DirectLabel(
        parent=root, text="Update Available", scale=0.072,
        pos=(0, 0, 0.24), text_fg=TEXT, frameColor=(0, 0, 0, 0),
    )
    DirectLabel(
        parent=root,
        text=f"Version {new_ver} is ready.  You are on {VERSION}.",
        scale=0.050, pos=(0, 0, 0.09), text_fg=TEXT_D, frameColor=(0, 0, 0, 0),
    )

    # Progress bar (hidden until download starts)
    bar_bg = DirectFrame(
        parent=root, frameColor=MED,
        frameSize=(-0.44, 0.44, -0.024, 0.024),
        pos=(0, 0, -0.07),
    )
    bar_fill = DirectFrame(
        parent=root, frameColor=ACCT,
        frameSize=(0, 0, -0.024, 0.024),
        pos=(-0.44, 0, -0.07),
    )
    bar_bg.hide()
    bar_fill.hide()

    status = DirectLabel(
        parent=root, text="", scale=0.046,
        pos=(0, 0, -0.15), text_fg=TEXT_D, frameColor=(0, 0, 0, 0),
    )

    _prog = [0.0]

    def _begin():
        update_btn["state"] = "disabled"
        skip_btn["state"]   = "disabled"
        bar_bg.show()
        bar_fill.show()
        status["text"] = "Downloading…"

        def _prog_cb(frac):
            _prog[0] = frac   # written from worker, read from main task — float assign is atomic

        def _done_cb():
            _prog[0] = 1.0
            # threading.Timer bypasses the Panda3D C++ task runner entirely.
            # os._exit(0) skips all Python/Panda3D cleanup that can hang.
            threading.Timer(0.8, lambda: os._exit(0)).start()

        def _err_cb(msg):
            status["text"] = f"Error — {msg}"
            update_btn["state"] = "normal"
            skip_btn["state"]   = "normal"
            bar_bg.hide()
            bar_fill.hide()

        download_update(dl_url, _prog_cb, _done_cb, _err_cb)

        def _anim(task):
            frac = _prog[0]
            bar_fill["frameSize"] = (0, 0.88 * frac, -0.024, 0.024)
            if frac >= 1.0:
                status["text"] = "Restarting…"
                return task.done
            status["text"] = f"Downloading… {int(frac * 100)}%"
            return task.cont

        game.taskMgr.add(_anim, "_upd_anim")

    update_btn = DirectButton(
        parent=root, text="Update Now", scale=0.056,
        pos=(-0.18, 0, -0.27),
        frameColor=ACCT, frameSize=(-1.9, 1.9, -0.65, 0.85),
        text_fg=TEXT, relief=1,
        command=_begin,
    )
    skip_btn = DirectButton(
        parent=root, text="Skip", scale=0.056,
        pos=(0.32, 0, -0.27),
        frameColor=BTN, frameSize=(-1.2, 1.2, -0.65, 0.85),
        text_fg=TEXT_D, relief=1,
        command=lambda: root.destroy(),
    )
