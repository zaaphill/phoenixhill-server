"""
PhoenixHill auth server
Run with:  python server.py
Requires:  pip install fastapi uvicorn
"""
import asyncio, hashlib, json, os, secrets, sqlite3, sys, time, traceback, uuid

_SERVER_INSTANCE_ID = f"{os.getpid()}-{time.time()}"
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json

# ── Auto-update ───────────────────────────────────────────────────────────────
# Bump GAME_VERSION and set GAME_DOWNLOAD_URL each time you ship a new build.
# Old clients check this on startup; if their version differs they silently
# download the new exe and swap it in on next exit.
GAME_VERSION      = "1.1.17"
GAME_DOWNLOAD_URL = "https://github.com/zaaphill/phoenixhill-server/releases/download/v1.1.17/PiePlex.exe"

# Bump this whenever the WebSocket protocol or any critical API changes.
# The game client checks this on startup and restarts the local server if outdated.
_SERVER_API_VERSION = 8

# build_id -> {player_id -> {ws, username, x, y, z, h}}
_rooms: dict = {}

_DB = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.db")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configsv1.json")
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
        configvone = json.load(_f)
except Exception:
    configvone = {"ShareBaseUrl": "", "ServerMaintenance": {"StartsInMinutes": 0}}


@app.on_event("startup")
async def _startup():
    _init_db()


# ── Database ──────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    c = _db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    UNIQUE NOT NULL COLLATE NOCASE,
            pw_hash    TEXT    NOT NULL,
            salt       TEXT    NOT NULL,
            created_at REAL    NOT NULL
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            expires_at REAL    NOT NULL
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS builds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            data       TEXT    NOT NULL,
            updated_at REAL    NOT NULL,
            published  INTEGER DEFAULT 0
        )""")
    # Migration for existing DBs that don't have the published column yet.
    try:
        c.execute("ALTER TABLE builds ADD COLUMN published INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN avatar_colors TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE builds ADD COLUMN thumbnail TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE builds ADD COLUMN description TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE builds ADD COLUMN visits INTEGER DEFAULT 0")
    except Exception:
        pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS build_visits (
            user_id    INTEGER NOT NULL,
            build_id   INTEGER NOT NULL,
            visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, build_id)
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            price       INTEGER DEFAULT 0,
            image_data  TEXT    NOT NULL,
            created_at  REAL    NOT NULL
        )""")
    c.execute("""
        CREATE TABLE IF NOT EXISTS shop_purchases (
            user_id      INTEGER NOT NULL,
            item_id      INTEGER NOT NULL,
            purchased_at REAL    NOT NULL,
            PRIMARY KEY (user_id, item_id)
        )""")
    try:
        c.execute("ALTER TABLE users ADD COLUMN equipped_tshirt INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN equipped_hat INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN equipped_shirt INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN equipped_pants INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN equipped_face INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE shop_items ADD COLUMN category TEXT DEFAULT 'tshirt'")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE shop_items ADD COLUMN hat_data TEXT DEFAULT NULL")
    except Exception:
        pass
    c.commit()
    c.close()

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200_000
    ).hex()


# ── Models ────────────────────────────────────────────────────────────────────

class Creds(BaseModel):
    username: str
    password: str

class BuildBody(BaseModel):
    name: str
    data: str  # JSON string

class PublishBody(BaseModel):
    published: bool

class AvatarBody(BaseModel):
    colors: dict

class ShopItemBody(BaseModel):
    name:        str
    description: str = ""
    price:       int = 0
    image_data:  str  # base64 PNG/JPG thumbnail
    category:    str = "tshirt"   # 'tshirt' or 'hat'
    hat_data:    str = ""         # JSON string; only populated for hats

class EquipTshirtBody(BaseModel):
    item_id: Optional[int] = None

class EquipHatBody(BaseModel):
    item_id: Optional[int] = None

class EquipShirtBody(BaseModel):
    item_id: Optional[int] = None

class EquipPantsBody(BaseModel):
    item_id: Optional[int] = None

class EquipFaceBody(BaseModel):
    item_id: Optional[int] = None


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_session(token: str):
    c = _db()
    row = c.execute(
        "SELECT * FROM sessions WHERE token=? AND expires_at>?",
        (token, time.time()),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(401, "Invalid or expired session")
    return row


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/register")
def register(r: Creds):
    u = r.username.strip()
    if not (3 <= len(u) <= 20):
        raise HTTPException(400, "Username must be 3–20 characters")
    if not all(c.isalnum() or c == "_" for c in u):
        raise HTTPException(400, "Username: letters, numbers and _ only")
    if len(r.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    salt = secrets.token_hex(16)
    c = _db()
    try:
        c.execute(
            "INSERT INTO users (username, pw_hash, salt, created_at) VALUES (?,?,?,?)",
            (u, _hash(r.password, salt), salt, time.time()),
        )
        c.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Username already taken")
    finally:
        c.close()

@app.get("/api/accounts/testroute/kubaxonemade")
def testingroute():
  return {"ok": "ok"}

@app.post("/api/login")
def login(r: Creds):
    c = _db()
    row = c.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (r.username,)
    ).fetchone()
    c.close()
    if not row or _hash(r.password, row["salt"]) != row["pw_hash"]:
        raise HTTPException(401, "Incorrect username or password")
    token = secrets.token_hex(32)
    c = _db()
    c.execute(
        "INSERT INTO sessions VALUES (?,?,?,?)",
        (token, row["id"], row["username"], time.time() + 86400 * 30),
    )
    c.commit()
    c.close()
    return {"ok": True, "token": token, "username": row["username"]}


@app.get("/api/verify")
def verify(token: str):
    c = _db()
    row = c.execute(
        "SELECT * FROM sessions WHERE token=? AND expires_at>?",
        (token, time.time()),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(401, "Session expired or invalid")
    return {"ok": True, "username": row["username"]}


@app.get("/api/version")
def get_version():
    return {"version": GAME_VERSION, "url": GAME_DOWNLOAD_URL}


@app.get("/api/server_version")
def get_server_version():
    return {
        "api_version": _SERVER_API_VERSION,
        "instance":    _SERVER_INSTANCE_ID,
        "pid":         os.getpid(),
        "file":        os.path.abspath(__file__),
        "cwd":         os.getcwd(),
    }


@app.delete("/api/logout")
def logout(token: str):
    c = _db()
    c.execute("DELETE FROM sessions WHERE token=?", (token,))
    c.commit()
    c.close()
    return {"ok": True}

@app.get("/api/configs/v1")
def config():
  return configvone


# ── Build endpoints ───────────────────────────────────────────────────────────

@app.post("/api/builds")
def create_build(token: str, b: BuildBody):
    sess = _get_session(token)
    name = b.name.strip()
    if not name:
        raise HTTPException(400, "Build name cannot be empty")
    c = _db()
    cur = c.execute(
        "INSERT INTO builds (user_id, name, data, updated_at) VALUES (?,?,?,?)",
        (sess["user_id"], name, b.data, time.time()),
    )
    build_id = cur.lastrowid
    c.commit()
    c.close()
    return {"ok": True, "id": build_id}


@app.put("/api/builds/{build_id}")
def update_build(build_id: int, token: str, b: BuildBody):
    sess = _get_session(token)
    c = _db()
    c.execute(
        "UPDATE builds SET name=?, data=?, updated_at=? WHERE id=? AND user_id=?",
        (b.name.strip(), b.data, time.time(), build_id, sess["user_id"]),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/api/builds")
def list_builds(token: str):
    sess = _get_session(token)
    c = _db()
    rows = c.execute(
        "SELECT id, name, updated_at, published FROM builds WHERE user_id=? ORDER BY updated_at DESC",
        (sess["user_id"],),
    ).fetchall()
    c.close()
    return {"builds": [dict(r) for r in rows]}


@app.get("/api/builds/{build_id}")
def get_build(build_id: int, token: str):
    sess = _get_session(token)
    c = _db()
    row = c.execute(
        "SELECT id, name, data FROM builds WHERE id=? AND user_id=?",
        (build_id, sess["user_id"]),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Build not found")
    return {"ok": True, "id": row["id"], "name": row["name"], "data": row["data"]}

@app.get("/api/users/{username}/avatar")
def get_user_avatar(username: str):
    c = _db()
    row = c.execute(
        """
        SELECT username, avatar_colors,
               equipped_tshirt,
               equipped_hat,
               equipped_shirt,
               equipped_pants,
               equipped_face
        FROM users
        WHERE username=? COLLATE NOCASE
        """,
        (username,)
    ).fetchone()
    c.close()

    if not row:
        raise HTTPException(404, "User not found")

    return dict(row)


@app.delete("/api/builds/{build_id}")
def delete_build(build_id: int, token: str):
    sess = _get_session(token)
    c = _db()
    c.execute("DELETE FROM builds WHERE id=? AND user_id=?", (build_id, sess["user_id"]))
    c.commit()
    c.close()
    return {"ok": True}


@app.patch("/api/builds/{build_id}/publish")
def set_published(build_id: int, token: str, b: PublishBody):
    sess = _get_session(token)
    c = _db()
    c.execute(
        "UPDATE builds SET published=? WHERE id=? AND user_id=?",
        (1 if b.published else 0, build_id, sess["user_id"]),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/api/published")
def browse_published():
    c = _db()
    rows = c.execute(
        """SELECT b.id, b.name, b.updated_at, b.visits, b.description, b.thumbnail, u.username
           FROM builds b JOIN users u ON b.user_id = u.id
           WHERE b.published = 1
           ORDER BY b.updated_at DESC""",
    ).fetchall()
    c.close()
    return {"builds": [dict(r) for r in rows]}


@app.get("/api/avatar")
def get_avatar(token: str):
    sess = _get_session(token)
    c = _db()
    row = c.execute("SELECT avatar_colors, equipped_tshirt, equipped_hat, equipped_shirt, equipped_pants, equipped_face FROM users WHERE id=?", (sess["user_id"],)).fetchone()
    c.close()
    equipped_tshirt = int(row["equipped_tshirt"]) if row and row["equipped_tshirt"] else None
    equipped_hat    = int(row["equipped_hat"])    if row and row["equipped_hat"]    else None
    equipped_shirt  = int(row["equipped_shirt"])  if row and row["equipped_shirt"]  else None
    equipped_pants  = int(row["equipped_pants"])  if row and row["equipped_pants"]  else None
    equipped_face   = int(row["equipped_face"])   if row and row["equipped_face"]   else None
    base = {"equipped_tshirt": equipped_tshirt, "equipped_hat": equipped_hat,
            "equipped_shirt": equipped_shirt, "equipped_pants": equipped_pants,
            "equipped_face": equipped_face}
    if not row or not row["avatar_colors"]:
        return {**base, "colors": {}}
    return {**base, "colors": json.loads(row["avatar_colors"])}

@app.get("/api/kubaxone/test")
def kubaxonestesst():
  return {"h8": "ok"}


@app.put("/api/avatar")
def put_avatar(token: str, b: AvatarBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET avatar_colors=? WHERE id=?",
              (json.dumps(b.colors), sess["user_id"]))
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/api/rooms")
def get_rooms():
    return {"rooms": {str(bid): len(players) for bid, players in _rooms.items()}}


@app.get("/api/server_api_version")
def api_version():
    return {"version": _SERVER_API_VERSION, "build_visits_exists": True}


@app.get("/api/published/{build_id}")
def get_published_build(build_id: int):
    # Pure data retrieval — no side effects
    c = _db()
    row = c.execute(
        "SELECT id, name, data FROM builds WHERE id=? AND published=1",
        (build_id,),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Build not found or not published")
    return {"ok": True, "id": row["id"], "name": row["name"], "data": row["data"]}


@app.post("/api/published/{build_id}/visit")
def record_visit(build_id: int, token: str = ""):
    if not token:
        return {"ok": False, "reason": "no_token"}
    try:
        user_id = _get_session(token)["user_id"]
    except Exception:
        return {"ok": False, "reason": "invalid_token"}
    c = _db()
    with c:
        c.execute(
            "INSERT OR IGNORE INTO build_visits (user_id, build_id) VALUES (?,?)",
            (user_id, build_id),
        )
        inserted = c.execute("SELECT changes()").fetchone()[0]
        if inserted:
            c.execute(
                "UPDATE builds SET visits = COALESCE(visits,0)+1 WHERE id=?",
                (build_id,),
            )
    print(f"[VISIT] user={user_id} build={build_id} counted={bool(inserted)}", flush=True)
    c.close()
    return {"ok": True, "counted": bool(inserted)}


class GameSettingsBody(BaseModel):
    thumbnail:   str = ""    # base64-encoded PNG/JPG, or empty to clear
    description: str = ""
    name:        str = ""    # if non-empty, rename the build


@app.put("/api/builds/{build_id}/settings")
def update_game_settings(build_id: int, token: str, b: GameSettingsBody):
    sess = _get_session(token)
    c = _db()
    if b.name.strip():
        c.execute(
            "UPDATE builds SET thumbnail=?, description=?, name=? WHERE id=? AND user_id=?",
            (b.thumbnail or None, b.description, b.name.strip(), build_id, sess["user_id"]),
        )
    else:
        c.execute(
            "UPDATE builds SET thumbnail=?, description=? WHERE id=? AND user_id=?",
            (b.thumbnail or None, b.description, build_id, sess["user_id"]),
        )
    c.commit()
    c.close()
    return {"ok": True}


@app.get("/api/builds/{build_id}/settings")
def get_game_settings(build_id: int, token: str):
    sess = _get_session(token)
    c = _db()
    row = c.execute(
        "SELECT name, thumbnail, description FROM builds WHERE id=? AND user_id=?",
        (build_id, sess["user_id"]),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Build not found")
    return {"name": row["name"] or "", "thumbnail": row["thumbnail"] or "", "description": row["description"] or ""}


@app.post("/api/shop/items")
def create_shop_item(token: str, b: ShopItemBody):
    sess = _get_session(token)
    name = b.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    if not b.image_data:
        raise HTTPException(400, "Image required")
    category = b.category.strip().lower() if b.category else "tshirt"
    if category not in ("tshirt", "hat"):
        category = "tshirt"
    c = _db()
    cur = c.execute(
        "INSERT INTO shop_items (user_id, name, description, price, image_data, category, hat_data, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (sess["user_id"], name, b.description.strip(), max(0, b.price), b.image_data,
         category, b.hat_data or None, time.time()),
    )
    item_id = cur.lastrowid
    c.commit()
    c.close()
    return {"ok": True, "id": item_id}

@app.get("/api/shop/items")
def list_shop_items():
    c = _db()
    rows = c.execute(
        """SELECT s.id, s.name, s.description, s.price, s.image_data,
                  CASE WHEN s.hat_data IS NOT NULL THEN 'hat'
                       ELSE COALESCE(s.category,'tshirt') END as category,
                  s.created_at, u.username
           FROM shop_items s JOIN users u ON s.user_id = u.id
           ORDER BY s.created_at DESC""",
    ).fetchall()
    c.close()
    return {"items": [dict(r) for r in rows]}

@app.get("/api/shop/items/{item_id}")
def get_shop_item(item_id: int):
    c = _db()
    row = c.execute(
        """SELECT s.id, s.name, s.description, s.price, s.image_data,
                  CASE WHEN s.hat_data IS NOT NULL THEN 'hat'
                       ELSE COALESCE(s.category,'tshirt') END as category,
                  s.hat_data, s.created_at, u.username
           FROM shop_items s JOIN users u ON s.user_id = u.id
           WHERE s.id=?""",
        (item_id,),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Item not found")
    return dict(row)

@app.delete("/api/shop/items/{item_id}")
def delete_shop_item(item_id: int, token: str):
    sess = _get_session(token)
    c = _db()
    row = c.execute("SELECT user_id FROM shop_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404, "Item not found")
    if row["user_id"] != sess["user_id"]:
        c.close()
        raise HTTPException(403, "Not your item")
    c.execute("DELETE FROM shop_purchases WHERE item_id=?", (item_id,))
    c.execute("DELETE FROM shop_items WHERE id=?", (item_id,))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/shop/items/{item_id}/buy")
def buy_shop_item(item_id: int, token: str):
    sess = _get_session(token)
    c = _db()
    if not c.execute("SELECT id FROM shop_items WHERE id=?", (item_id,)).fetchone():
        c.close()
        raise HTTPException(404, "Item not found")
    c.execute(
        "INSERT OR IGNORE INTO shop_purchases (user_id, item_id, purchased_at) VALUES (?,?,?)",
        (sess["user_id"], item_id, time.time()),
    )
    c.commit()
    c.close()
    return {"ok": True}

@app.get("/api/shop/owned")
def get_owned_items(token: str):
    sess = _get_session(token)
    c = _db()
    rows = c.execute(
        """SELECT s.id, s.name, s.description, s.price, s.image_data,
                  CASE WHEN s.hat_data IS NOT NULL THEN 'hat'
                       ELSE COALESCE(s.category,'tshirt') END as category,
                  u.username
           FROM shop_purchases p
           JOIN shop_items s ON p.item_id = s.id
           JOIN users u ON s.user_id = u.id
           WHERE p.user_id=?
           ORDER BY p.purchased_at DESC""",
        (sess["user_id"],),
    ).fetchall()
    c.close()
    return {"items": [dict(r) for r in rows]}

@app.put("/api/avatar/equipped_tshirt")
def equip_tshirt_endpoint(token: str, b: EquipTshirtBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET equipped_tshirt=? WHERE id=?", (b.item_id, sess["user_id"]))
    c.commit()
    c.close()
    return {"ok": True}

@app.put("/api/avatar/equipped_hat")
def equip_hat_endpoint(token: str, b: EquipHatBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET equipped_hat=? WHERE id=?", (b.item_id, sess["user_id"]))
    c.commit()
    c.close()
    return {"ok": True}

@app.put("/api/avatar/equipped_shirt")
def equip_shirt_endpoint(token: str, b: EquipShirtBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET equipped_shirt=? WHERE id=?", (b.item_id, sess["user_id"]))
    c.commit(); c.close()
    return {"ok": True}

@app.put("/api/avatar/equipped_pants")
def equip_pants_endpoint(token: str, b: EquipPantsBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET equipped_pants=? WHERE id=?", (b.item_id, sess["user_id"]))
    c.commit(); c.close()
    return {"ok": True}

@app.put("/api/avatar/equipped_face")
def equip_face_endpoint(token: str, b: EquipFaceBody):
    sess = _get_session(token)
    c = _db()
    c.execute("UPDATE users SET equipped_face=? WHERE id=?", (b.item_id, sess["user_id"]))
    c.commit(); c.close()
    return {"ok": True}


# ── Multiplayer WebSocket ─────────────────────────────────────────────────────


async def _broadcast(build_id: int, msg: dict, exclude: str = None):
    dead = []
    for pid, pdata in list(_rooms.get(build_id, {}).items()):
        if pid == exclude:
            continue
        try:
            await pdata["websocket"].send_json(msg)
        except Exception:
            dead.append(pid)
    for pid in dead:
        _rooms.get(build_id, {}).pop(pid, None)

@app.websocket("/api/voice/v1")
async def voice(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)

    try:
        while True:
            audio = await websocket.receive_bytes()

            for client in clients:
                if client != websocket:
                    await client.send_bytes(audio)

    finally:
        clients.remove(websocket)

@app.websocket("/ws/{build_id}")
async def ws_endpoint(websocket: WebSocket, build_id: int, token: str):
    print(f"[WS] incoming connection build_id={build_id}", flush=True)
    try:
        await websocket.accept()
        print(f"[WS] accepted build_id={build_id}", flush=True)
    except Exception as _e:
        print(f"[WS] accept FAILED: {_e}", flush=True)
        traceback.print_exc()
        return

    try:
        sess = _get_session(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    player_id = str(uuid.uuid4())
    username  = sess["username"]
    print(f"[WS] {username} authenticated (room {build_id})", flush=True)

    # Load colors from DB — guaranteed up-to-date (pushed on every color pick + on login).
    try:
        uc = _db()
        urow = uc.execute("SELECT avatar_colors, equipped_tshirt, equipped_hat, equipped_shirt, equipped_pants, equipped_face FROM users WHERE id=?", (sess["user_id"],)).fetchone()
        uc.close()
        player_colors   = json.loads(urow["avatar_colors"]) if urow and urow["avatar_colors"] else {}
        equipped_tshirt = int(urow["equipped_tshirt"]) if urow and urow["equipped_tshirt"] else None
        equipped_hat    = int(urow["equipped_hat"])    if urow and urow["equipped_hat"]    else None
        equipped_shirt  = int(urow["equipped_shirt"])  if urow and urow["equipped_shirt"]  else None
        equipped_pants  = int(urow["equipped_pants"])  if urow and urow["equipped_pants"]  else None
        equipped_face   = int(urow["equipped_face"])   if urow and urow["equipped_face"]   else None
    except Exception:
        player_colors = {}
        equipped_tshirt = None
        equipped_shirt  = None
        equipped_pants  = None
        equipped_face   = None
    print(f"[WS_CONNECT_PARSED] username={username} colors={'yes' if player_colors else 'none'}", flush=True)

    # Evict stale same-username connections.
    # We are NOT in _rooms yet, so no other player's broadcast can write to our
    # socket concurrently during the yields inside this loop.
    if build_id not in _rooms:
        _rooms[build_id] = {}
    stale = [pid for pid, d in list(_rooms[build_id].items()) if d["username"] == username]
    for spid in stale:
        old_data = _rooms[build_id].pop(spid, None)
        print(f"[WS] kicked old session for {username} ({spid})", flush=True)
        if old_data:
            try:
                await old_data["websocket"].send_json({"type": "kicked", "reason": "duplicate"})
                await old_data["websocket"].close(code=4009)
            except Exception:
                pass
        await _broadcast(build_id, {"type": "left", "player_id": spid})

    # Snapshot the room and send state BEFORE adding ourselves to _rooms.
    # While absent from _rooms, no broadcast can target our socket, so the
    # state send has exactly one writer — us.  Adding first then sending is
    # the classic concurrent-write bug: another player's 20 Hz move broadcast
    # yields into our state send and corrupts the frame → 1005.
    _snap = {p: {k: v for k, v in d.items() if k != "websocket"} for p, d in _rooms.get(build_id, {}).items()}
    print(f"[STATE_BUILD] room_before_snapshot={_snap}", flush=True)
    try:
        others = {
            pid: {
                "username":  d.get("username", ""),
                "x":         d.get("x", 0.0),
                "y":         d.get("y", 0.0),
                "z":         d.get("z", 0.0),
                "h":         d.get("h", 0.0),
                "colors":    d.get("colors") or {},
                "tshirt_id": d.get("tshirt_id"),
                "hat_id":    d.get("hat_id"),
                "shirt_id":  d.get("shirt_id"),
                "pants_id":  d.get("pants_id"),
                "face_id":   d.get("face_id"),
            }
            for pid, d in _rooms.get(build_id, {}).items()
        }
    except Exception as _e:
        print(f"[WS] {username}: state snapshot FAILED: {_e}", flush=True)
        traceback.print_exc()
        return
    print(f"[STATE_PAYLOAD] {username} -> {json.dumps({'type': 'state', 'players': others})}", flush=True)
    try:
        await websocket.send_json({"type": "state", "players": others})
        print(f"[WS] {username}: state sent OK", flush=True)
    except Exception as _e:
        print(f"[WS] {username}: state send FAILED: {_e}", flush=True)
        traceback.print_exc()
        return

    # Now enter the room and announce — from this point others will write to us.
    _rooms.setdefault(build_id, {})[player_id] = {
        "websocket": websocket, "username": username,
        "x": 0.0, "y": 0.0, "z": 0.0, "h": 0.0,
        "colors": player_colors,
        "tshirt_id": equipped_tshirt,
        "hat_id": equipped_hat,
        "shirt_id": equipped_shirt,
        "pants_id": equipped_pants,
        "face_id": equipped_face,
    }
    _entry_log = {k: v for k, v in _rooms[build_id][player_id].items() if k != "websocket"}
    print(f"[ROOM_STORE] {username}: {_entry_log}", flush=True)
    try:
        await _broadcast(build_id, {
            "type": "joined", "player_id": player_id, "username": username,
            "colors": player_colors,
            "tshirt_id": equipped_tshirt,
            "hat_id": equipped_hat,
            "shirt_id": equipped_shirt,
            "pants_id": equipped_pants,
            "face_id": equipped_face,
        }, exclude=player_id)
        print(f"[WS] {username}: joined broadcast done", flush=True)
    except Exception as _e:
        print(f"[WS] {username}: joined broadcast FAILED: {_e}", flush=True)
        traceback.print_exc()

    last_msg_time = time.time()
    msg_count = 0
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=35.0)
            except asyncio.TimeoutError:
                idle = time.time() - last_msg_time
                print(f"[WS] {username}: TIMEOUT — no message for {idle:.1f}s, kicking (room {build_id})", flush=True)
                try:
                    await websocket.send_json({"type": "kicked", "reason": "inactivity"})
                    await websocket.close(code=4008)
                except Exception:
                    pass
                break
            last_msg_time = time.time()
            msg_count += 1
            # Log a heartbeat every ~10 s (200 messages at 20 Hz) so the logs show the timer resetting
            if msg_count % 200 == 0:
                print(f"[WS] {username}: active — {msg_count} msgs (room {build_id})", flush=True)
            if msg.get("type") == "move":
                entry = _rooms.get(build_id, {}).get(player_id)
                if not entry:
                    break
                entry.update({
                    "x": msg.get("x", 0.0), "y": msg.get("y", 0.0),
                    "z": msg.get("z", 0.0), "h": msg.get("h", 0.0),
                })
                await _broadcast(build_id, {
                    "type": "move", "player_id": player_id,
                    "x": msg.get("x", 0.0), "y": msg.get("y", 0.0),
                    "z": msg.get("z", 0.0), "h": msg.get("h", 0.0),
                }, exclude=player_id)
            elif msg.get("type") == "avatar_colors":
                try:
                    colors = msg.get("colors")
                    print(f"[WS_AVATAR_MSG] from={username}/{player_id} msg={msg}", flush=True)
                    print(f"[WS_RELAY] {username} avatar_colors -> room {build_id} has_colors={bool(colors)} keys={list(colors.keys()) if isinstance(colors, dict) else None}", flush=True)
                    if isinstance(colors, dict):
                        entry = _rooms.get(build_id, {}).get(player_id)
                        if entry:
                            entry["colors"] = colors
                        await _broadcast(build_id, {
                            "type": "avatar_colors",
                            "player_id": player_id,
                            "colors": colors,
                        }, exclude=player_id)
                except Exception as _ace:
                    print(f"[AVATAR_COLORS_CRASH] {username}: {repr(_ace)}", flush=True)
                    traceback.print_exc()
            elif msg.get("type") == "chat":
                text = str(msg.get("text", ""))[:400]
                await _broadcast(build_id, {
                    "type": "chat",
                    "player_id": player_id,
                    "username": username,
                    "text": text,
                }, exclude=player_id)
            elif msg.get("type") == "equip_tshirt":
                item_id = msg.get("item_id")
                entry = _rooms.get(build_id, {}).get(player_id)
                if entry:
                    entry["tshirt_id"] = item_id
                await _broadcast(build_id, {
                    "type": "equip_tshirt",
                    "player_id": player_id,
                    "item_id": item_id,
                }, exclude=player_id)
            elif msg.get("type") == "equip_hat":
                item_id = msg.get("item_id")
                entry = _rooms.get(build_id, {}).get(player_id)
                if entry:
                    entry["hat_id"] = item_id
                await _broadcast(build_id, {
                    "type": "equip_hat",
                    "player_id": player_id,
                    "item_id": item_id,
                }, exclude=player_id)
            elif msg.get("type") == "equip_shirt":
                item_id = msg.get("item_id")
                entry = _rooms.get(build_id, {}).get(player_id)
                if entry:
                    entry["shirt_id"] = item_id
                await _broadcast(build_id, {
                    "type": "equip_shirt",
                    "player_id": player_id,
                    "item_id": item_id,
                }, exclude=player_id)
            elif msg.get("type") == "equip_pants":
                item_id = msg.get("item_id")
                entry = _rooms.get(build_id, {}).get(player_id)
                if entry:
                    entry["pants_id"] = item_id
                await _broadcast(build_id, {
                    "type": "equip_pants",
                    "player_id": player_id,
                    "item_id": item_id,
                }, exclude=player_id)
    except WebSocketDisconnect as _wd:
        code = getattr(_wd, "code", "?")
        print(f"[WS] {username}: clean disconnect (code={code}, room {build_id})", flush=True)
    except Exception as _fatal:
        print(f"[WS_FATAL] {username} room={build_id}: {repr(_fatal)}", flush=True)
        traceback.print_exc()
    finally:
        # Identity-safe cleanup: only remove and broadcast if our websocket
        # object is still the active session.  During map switching a new
        # connection can evict us and replace our player_id entry before this
        # finally block runs; blindly popping would delete the new entry and
        # the new player would never appear to other clients.
        room    = _rooms.get(build_id, {})
        current = room.get(player_id)
        if current and current.get("websocket") is websocket:
            room.pop(player_id, None)
            if build_id in _rooms and not _rooms[build_id]:
                del _rooms[build_id]
            print(f"[WS] {username} removed from room {build_id}", flush=True)
            await _broadcast(build_id, {"type": "left", "player_id": player_id})
        else:
            print(f"[WS] {username}: skipped stale cleanup for {player_id} (already evicted)", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_db()
    port = int(os.environ.get("PORT", 8000))
    print(f"PhoenixHill auth server  ->  http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning",
                ws_ping_interval=20, ws_ping_timeout=20)
