from setuptools import setup

setup(
    name="PhoenixHill",
    options={
        "build_apps": {
            # gui_apps = no console window on Windows
            "gui_apps": {
                "PhoenixHill": "main.py",
            },
            # Errors and print() output go here (useful for bug reports)
            "log_filename": "$USER_APPDATA/PhoenixHill/game.log",
            "log_append": False,

            "plugins": [
                "pandagl",        # OpenGL renderer
                "p3openal_audio", # Audio (not used yet, but avoids startup errors)
            ],

            # Non-Python assets to bundle (Python files are auto-detected via imports)
            "include_patterns": [
                "textures/**",
                "citrus_orchard_puresky_4k.exr",
                "Config.prc",
            ],

            # Extra pip packages to download and bundle (panda3d is automatic)
            "requirements_path": "requirements-client.txt",

            "platforms": ["win_amd64"],
        }
    }
)
