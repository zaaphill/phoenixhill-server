@echo off
echo ============================================================
echo  PhoenixHill — Distribution Build
echo ============================================================
echo.
echo IMPORTANT: Before building, make sure server.cfg contains
echo your Fly.io host, e.g.:  host=myapp.fly.dev
echo.
echo Current server.cfg:
type server.cfg
echo.
pause

echo Building...
python setup.py build_apps
if errorlevel 1 (
    echo.
    echo BUILD FAILED — see error above.
    pause
    exit /b 1
)

echo.
echo Copying runtime assets into build...
copy /Y server.cfg    build\win_amd64\server.cfg
copy /Y arrow_nw.png  build\win_amd64\arrow_nw.png

echo.
echo ============================================================
echo  Done!  Share the build\win_amd64\ folder with your friends.
echo  They just extract it and double-click PhoenixHill.exe
echo ============================================================
pause
