# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Pull in everything panda3d and direct ship with (DLLs, PYDs, data files)
p3d_d, p3d_b, p3d_h = collect_all('panda3d')
dir_d, dir_b, dir_h = collect_all('direct')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=p3d_b + dir_b,
    datas=p3d_d + dir_d + [
        ('textures',                     'textures'),
        ('citrus_orchard_puresky_4k.exr', '.'),
        ('Config.prc',                   '.'),
        ('arrow_nw.png',                 '.'),
    ],
    hiddenimports=p3d_h + dir_h + ['websockets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'email', 'html', 'http', 'xml',
              'xmlrpc', 'pydoc', 'doctest', 'difflib'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PhoenixHill',
    debug=False,
    strip=False,
    upx=False,          # UPX breaks panda3d DLLs
    console=False,      # no black console window
    icon=None,
)
