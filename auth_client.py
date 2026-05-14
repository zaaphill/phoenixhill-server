import json
import urllib.request
import urllib.error
from urllib.parse import urlencode
import config as _config

BASE = _config.get()["http"]


def _request(method, path, body=None, params=None, timeout=5):
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("detail", str(e))
        except Exception:
            msg = str(e)
        return None, msg
    except Exception as e:
        msg = str(e)
        if "10061" in msg or "refused" in msg.lower() or "urlopen" in msg.lower():
            msg = "Cannot connect to server. Is server.py running?"
        return None, msg


def register(username, password):
    return _request("POST", "/api/register", {"username": username, "password": password})

def login(username, password):
    return _request("POST", "/api/login", {"username": username, "password": password})

def verify(token):
    return _request("GET", "/api/verify", params={"token": token})

def logout(token):
    return _request("DELETE", "/api/logout", params={"token": token})

# ── Build API ──────────────────────────────────────────────────────────────────

def create_build(token, name, data_str):
    return _request("POST", "/api/builds", {"name": name, "data": data_str}, params={"token": token})

def update_build(token, build_id, name, data_str):
    return _request("PUT", f"/api/builds/{build_id}", {"name": name, "data": data_str}, params={"token": token})

def list_builds(token):
    return _request("GET", "/api/builds", params={"token": token})

def load_build(token, build_id):
    return _request("GET", f"/api/builds/{build_id}", params={"token": token})

def delete_build(token, build_id):
    return _request("DELETE", f"/api/builds/{build_id}", params={"token": token})

def set_published(token, build_id, published: bool):
    return _request("PATCH", f"/api/builds/{build_id}/publish",
                    {"published": published}, params={"token": token})

def browse_published():
    return _request("GET", "/api/published")

def get_published_build(build_id):
    return _request("GET", f"/api/published/{build_id}")

def post_visit(token, build_id):
    return _request("POST", f"/api/published/{build_id}/visit", params={"token": token})

def get_rooms():
    return _request("GET", "/api/rooms")

def get_avatar(token):
    return _request("GET", "/api/avatar", params={"token": token})

def put_avatar(token, colors):
    return _request("PUT", "/api/avatar", {"colors": colors}, params={"token": token})

def get_server_version():
    return _request("GET", "/api/server_version")

def get_game_settings(token, build_id):
    return _request("GET", f"/api/builds/{build_id}/settings", params={"token": token})

def put_game_settings(token, build_id, thumbnail, description, name=""):
    return _request("PUT", f"/api/builds/{build_id}/settings",
                    {"thumbnail": thumbnail, "description": description, "name": name},
                    params={"token": token})

# ── Shop API ──────────────────────────────────────────────────────────────────

def upload_shop_item(token, name, description, price, image_b64):
    return _request("POST", "/api/shop/items",
                    {"name": name, "description": description,
                     "price": price, "image_data": image_b64},
                    params={"token": token}, timeout=30)

def list_shop_items():
    return _request("GET", "/api/shop/items")

def get_shop_item(item_id):
    return _request("GET", f"/api/shop/items/{item_id}")

def buy_shop_item(token, item_id):
    return _request("POST", f"/api/shop/items/{item_id}/buy",
                    params={"token": token})

def get_owned_items(token):
    return _request("GET", "/api/shop/owned", params={"token": token})

def equip_tshirt(token, item_id_or_none):
    return _request("PUT", "/api/avatar/equipped_tshirt",
                    {"item_id": item_id_or_none}, params={"token": token})
