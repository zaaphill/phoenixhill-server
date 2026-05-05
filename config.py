import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# In packaged builds, os.getcwd() == exe directory (where server.cfg is placed).
# In dev, os.getcwd() == project directory (same location). Either way, cwd wins.
_CFG = os.path.join(os.getcwd(), "server.cfg")
if not os.path.exists(_CFG):
    _CFG = os.path.join(_HERE, "server.cfg")

# Write default config if missing
if not os.path.exists(_CFG):
    with open(_CFG, "w") as _f:
        _f.write(
            "# PhoenixHill server configuration\n"
            "#\n"
            "# host=localhost   -> start a server on THIS computer (default)\n"
            "# host=1.2.3.4     -> connect to a remote server at that IP or domain\n"
            "#\n"
            "# To host for friends:\n"
            "#   1. Forward port 8000 on your router to this computer\n"
            "#   2. Keep host=localhost here\n"
            "#   3. Give friends your PUBLIC IP and tell them to set host=<your IP>\n"
            "\n"
            "host=localhost\n"
            "port=8000\n"
        )


def get():
    """Return a dict with connection settings read from server.cfg."""
    data = {"host": "localhost", "port": "8000"}
    try:
        with open(_CFG) as f:
            for raw in f:
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip().lower()] = v.strip()
    except FileNotFoundError:
        pass

    host  = data.get("host", "localhost").strip()
    port  = data.get("port", "8000").strip()
    local = host.lower() in ("localhost", "127.0.0.1", "")
    is_ip = bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', host))

    if local:
        # Local dev — plain HTTP/WS on the configured port
        return {
            "host":    host,
            "port":    int(port),
            "local":   True,
            "http":    f"http://127.0.0.1:{port}",
            "ws":      f"ws://127.0.0.1:{port}",
            "display": "localhost",
        }
    elif is_ip:
        # Raw IP — plain HTTP/WS on the configured port
        return {
            "host":    host,
            "port":    int(port),
            "local":   False,
            "http":    f"http://{host}:{port}",
            "ws":      f"ws://{host}:{port}",
            "display": f"{host}:{port}",
        }
    else:
        # Domain name (cloud host) — HTTPS/WSS, no port suffix
        return {
            "host":    host,
            "port":    443,
            "local":   False,
            "http":    f"https://{host}",
            "ws":      f"wss://{host}",
            "display": host,
        }
