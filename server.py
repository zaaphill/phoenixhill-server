"""
PhoenixHill auth server
Run with:  python server.py
Requires:  pip install fastapi uvicorn
"""
import asyncio, hashlib, os, secrets, sqlite3, time, traceback, uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# build_id -> {player_id -> {ws, username, x, y, z, h}}
_rooms: dict = {}

_DB = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.db")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


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


@app.delete("/api/logout")
def logout(token: str):
    c = _db()
    c.execute("DELETE FROM sessions WHERE token=?", (token,))
    c.commit()
    c.close()
    return {"ok": True}


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
        """SELECT b.id, b.name, b.updated_at, u.username
           FROM builds b JOIN users u ON b.user_id = u.id
           WHERE b.published = 1
           ORDER BY b.updated_at DESC""",
    ).fetchall()
    c.close()
    return {"builds": [dict(r) for r in rows]}


@app.get("/api/rooms")
def get_rooms():
    return {"rooms": {str(bid): len(players) for bid, players in _rooms.items()}}


@app.post("/api/rooms/{build_id}/leave")
async def leave_room(build_id: int, token: str):
    try:
        sess = _get_session(token)
    except HTTPException:
        return {"ok": False}
    username = sess["username"]
    room = _rooms.get(build_id, {})
    gone = [pid for pid, d in list(room.items()) if d["username"] == username]
    for pid in gone:
        room.pop(pid, None)
        print(f"[WS] HTTP leave: {username} removed from room {build_id}", flush=True)
        await _broadcast(build_id, {"type": "left", "player_id": pid})
    if build_id in _rooms and not _rooms[build_id]:
        del _rooms[build_id]
    return {"ok": True}


@app.get("/api/published/{build_id}")
def get_published_build(build_id: int):
    c = _db()
    row = c.execute(
        "SELECT id, name, data FROM builds WHERE id=? AND published=1",
        (build_id,),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "Build not found or not published")
    return {"ok": True, "id": row["id"], "name": row["name"], "data": row["data"]}


# ── Multiplayer WebSocket ─────────────────────────────────────────────────────


async def _broadcast(build_id: int, msg: dict, exclude: str = None):
    dead = []
    for pid, pdata in list(_rooms.get(build_id, {}).items()):
        if pid == exclude:
            continue
        try:
            await pdata["ws"].send_json(msg)
        except Exception:
            dead.append(pid)
    for pid in dead:
        _rooms.get(build_id, {}).pop(pid, None)


@app.websocket("/ws/{build_id}")
async def ws_endpoint(websocket: WebSocket, build_id: int, token: str):
    await websocket.accept()
    try:
        sess = _get_session(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    player_id = str(uuid.uuid4())
    username  = sess["username"]

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
                await old_data["ws"].send_json({"type": "kicked", "reason": "duplicate"})
                await old_data["ws"].close(code=4009)
            except Exception:
                pass
        await _broadcast(build_id, {"type": "left", "player_id": spid})

    # Snapshot the room and send state BEFORE adding ourselves to _rooms.
    # While absent from _rooms, no broadcast can target our socket, so the
    # state send has exactly one writer — us.  Adding first then sending is
    # the classic concurrent-write bug: another player's 20 Hz move broadcast
    # yields into our state send and corrupts the frame → 1005.
    others = {
        pid: {k: v for k, v in d.items() if k != "ws"}
        for pid, d in _rooms.get(build_id, {}).items()
    }
    print(f"[WS] {username} joined room {build_id}. Others: {[d['username'] for d in others.values()]}", flush=True)
    try:
        await websocket.send_json({"type": "state", "players": others})
        print(f"[WS] {username}: state sent OK", flush=True)
    except Exception as _e:
        print(f"[WS] {username}: state send FAILED: {_e}", flush=True)
        traceback.print_exc()
        return

    # Now enter the room and announce — from this point others will write to us.
    _rooms.setdefault(build_id, {})[player_id] = {
        "ws": websocket, "username": username,
        "x": 0.0, "y": 0.0, "z": 0.0, "h": 0.0,
    }
    await _broadcast(build_id, {
        "type": "joined", "player_id": player_id, "username": username,
    }, exclude=player_id)

    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=35.0)
            except asyncio.TimeoutError:
                print(f"[WS] {username}: inactive 35s, kicking (room {build_id})", flush=True)
                try:
                    await websocket.send_json({"type": "kicked", "reason": "inactivity"})
                    await websocket.close(code=4008)
                except Exception:
                    pass
                break
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
            elif msg.get("type") == "chat":
                text = str(msg.get("text", ""))[:200]
                await _broadcast(build_id, {
                    "type": "chat",
                    "player_id": player_id,
                    "username": username,
                    "text": text,
                }, exclude=player_id)
    except WebSocketDisconnect:
        pass
    except Exception as _e:
        print(f"[WS] {username}: recv loop error: {_e}", flush=True)
    finally:
        # Check BEFORE popping — if already absent, we were evicted and our
        # "left" was already broadcast by the eviction code.  Skipping the
        # broadcast here prevents a concurrent write to a new connection's
        # WebSocket (which causes the 1005 reconnect loop).
        was_present = player_id in _rooms.get(build_id, {})
        _rooms.get(build_id, {}).pop(player_id, None)
        if build_id in _rooms and not _rooms[build_id]:
            del _rooms[build_id]
        print(f"[WS] {username} left room {build_id}", flush=True)
        if was_present:
            await _broadcast(build_id, {"type": "left", "player_id": player_id})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_db()
    port = int(os.environ.get("PORT", 8000))
    print(f"PhoenixHill auth server  ->  http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning",
                ws_ping_interval=20, ws_ping_timeout=20)
