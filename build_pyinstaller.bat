@echo off
cd /d "%~dp0"
echo Installing PyInstaller...
pip install pyinstaller

echo.
echo Building PiePlex.exe (single file)...
pyinstaller PhoenixHill.spec --noconfirm

echo.
if exist "dist\PiePlex.exe" (
    echo ============================================================
    echo  Done!  dist\PiePlex.exe is ready to share.
    echo  Just send that ONE file -- nothing else needed.
    echo ============================================================
) else (
    echo BUILD FAILED -- see error above.
)
pause
