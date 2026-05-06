@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo.
echo Building PhoenixHill.exe (single file)...
pyinstaller PhoenixHill.spec --noconfirm

echo.
if exist "dist\PhoenixHill.exe" (
    echo ============================================================
    echo  Done!  dist\PhoenixHill.exe is ready to share.
    echo  Just send that ONE file — nothing else needed.
    echo ============================================================
) else (
    echo BUILD FAILED — see error above.
)
pause
