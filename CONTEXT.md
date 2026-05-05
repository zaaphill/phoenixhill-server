# PhoenixHill — AI Context Document

## What This Is
A Roblox-style 3D game built with **Python + Panda3D**. Players can build with bricks in a studio editor, save builds to the cloud, publish them, and play published builds in real-time multiplayer. Run with `python main.py` — the server starts automatically.

---

## File Structure & Architecture

All game logic uses the **mixin pattern**: `MyGame` in `game.py` extends `ShowBase` and every mixin class. Each file is one mixin.

| File | Class | Purpose |
|------|-------|---------|
| `main.py` | — | Entry point, just runs `MyGame()` |
| `game.py` | `MyGame` | ShowBase subclass, wires all mixins, sets up lights/camera/keys |
| `character.py` | `CharacterMixin` | Player model, movement, jumping, collision |
| `bricks.py` | `BrickMixin` | Brick placement, hitbox, export/import JSON, `get_build_data()`, `_load_bricks_from_data()` |
| `camera.py` | `CameraMixin` | Orbit camera, shift-lock, zoom |
| `ui.py` | `UIMixin` | Top toolbar (Menu, Play/Edit, +Brick, Move, Scale, Export, Import, Save buttons) |
| `picking.py` | `PickingMixin` | Mouse ray casting for brick selection |
| `shadows.py` | `ShadowMixin` | Blob shadows under character |
| `sky.py` | `SkyMixin` | Sky background |
| `ui_debug.py` | `UIDebugMixin` | Debug overlay |
| `cloud.py` | `CloudMixin` | Save dialog, create/update build, `cloud_save_build()`, `cloud_load_into_scene()`, `_show_toast()` |
| `login_screen.py` | `LoginScreenMixin` | Login/register UI, main menu, browse screen, play mode, server startup |
| `multiplayer.py` | `MultiplayerMixin` | WebSocket multiplayer, remote player models, interpolation, chat UI |
| `server.py` | — | FastAPI + SQLite server (auto-started as subprocess) |
| `auth_client.py` | — | stdlib urllib wrapper for all HTTP API calls |
| `config.py` | — | Reads `server.cfg` for server address (localhost vs remote IP) |
| `server.cfg` | — | User-editable: `host=localhost` or `host=1.2.3.4` for online play |

---

## Character Model (character.py)

The character is a `NodePath("character")` parented to `render`, positioned at feet (`floor_top = 0.5`).

```
character (root, at feet)
├── torso       — models/box, scale(2,1,2), pos(-1,-0.5,2), blue
├── left_arm_pivot  — pos(-1.5, 0, 4)
│   └── left_arm    — models/box, scale(1,1,2), pos(-0.5,-0.5,-2), yellow/skin
├── right_arm_pivot — pos(1.5, 0, 4)
│   └── right_arm   — models/box, scale(1,1,2), pos(-0.5,-0.5,-2), yellow/skin
├── left_leg_pivot  — pos(-0.5, 0, 2)
│   └── left_leg    — models/box, scale(1,1,2), pos(-0.5,-0.5,-2), green
├── right_leg_pivot — pos(0.5, 0, 2)
│   └── right_leg   — models/box, scale(1,1,2), pos(-0.5,-0.5,-2), green
└── head        — custom cylinder, radius=0.7, height=1.1, pos(0,0,4.55), skin color
```

**Critical:** `models/box` ignores `setColor()` unless you call `setTextureOff(1)` first.

Walking animation: arm/leg pivots swing via `setP(sin(walking_angle) * 30)` each frame.

---

## Server (server.py)

FastAPI + SQLite, auto-started by the game as a subprocess. Listens on `0.0.0.0:8000`.

### Database tables
- `users` — id, username (UNIQUE NOCASE), pw_hash, salt, created_at
- `sessions` — token (PK), user_id, username, expires_at (30 days)
- `builds` — id, user_id, name, data (JSON string), updated_at, published (0/1)

### HTTP endpoints
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/register` | — | Register (3–20 chars, alphanum+_) |
| POST | `/api/login` | — | Login, returns token+username |
| GET | `/api/verify?token=` | — | Check token validity |
| DELETE | `/api/logout?token=` | — | Delete session |
| POST | `/api/builds?token=` | token | Create build |
| PUT | `/api/builds/{id}?token=` | token | Update build |
| GET | `/api/builds?token=` | token | List my builds |
| GET | `/api/builds/{id}?token=` | token | Load one build |
| DELETE | `/api/builds/{id}?token=` | token | Delete build |
| PATCH | `/api/builds/{id}/publish?token=` | token | Toggle published |
| GET | `/api/published` | — | Browse all published builds |
| GET | `/api/published/{id}` | — | Load one published build |
| GET | `/api/rooms` | — | Live player counts per build_id |

### WebSocket endpoint
`/ws/{build_id}?token=` — validates token, joins room, streams multiplayer.

Room storage: `_rooms: dict = {}` — `{build_id: {player_id: {ws, username, x, y, z, h}}}`

Each connection gets `player_id = str(uuid.uuid4())` (unique per connection, not per user — allows same account in two windows).

Message types the server handles from clients: `move`, `chat`
Message types the server sends to clients: `state` (on join), `joined`, `left`, `move`, `chat`

---

## Multiplayer (multiplayer.py)

### Flow
1. `start_multiplayer(build_id, token)` — called from `_enter_play_mode()`
2. Creates new asyncio event loop in a daemon thread
3. Background thread runs `_mp_main` which opens WebSocket and gathers recv+send
4. `_mp_update_task` runs every Panda3D frame, drains `queue.Queue`, processes messages
5. `stop_multiplayer()` — called from `_return_to_menu()`

### Send rate: 20 Hz (`asyncio.sleep(0.05)`)

### Remote player model
Mirrors the local character exactly — same torso/arm/leg/head structure with `setTextureOff(1)`. Each remote player gets a color from `_COLORS` list. Billboard TextNode label floats at `z + 5.8`.

### Interpolation
`_update_remote_player` sets `target_pos`/`target_h`. Every frame in `_mp_update_task`, positions lerp toward target with factor `_LERP = 18`. First update snaps directly to avoid sliding from -9999.

### Chat
- Press `/` to open chat input (bottom-left panel)
- Press Enter to send, Enter on empty to close
- `_chat_input_active = True` suppresses character movement while typing (checked in `character.py updateMovement`)
- Server broadcasts chat to all OTHER players (`exclude=player_id`)
- Sender adds message locally immediately

---

## Login / Navigation Flow (login_screen.py)

```
Startup
  → splash screen
  → background thread: install deps (fastapi/uvicorn/websockets), start server, poll
  → if .session file exists: auto-login via /api/verify
  → else: show login form

Login Form
  → Log In / Register
  → on success: show Main Menu

Main Menu
  → My Builds list (Pub/Unpub toggle, Load, Del per build)
  → Browse Builds button
  → New Build button
  → Log Out

Browse Builds Screen
  → fetches /api/published + /api/rooms
  → sorts by online player count (most first)
  → shows "N online" / "empty" badge, green tint for active rooms
  → Play button → _enter_play_mode()

Play Mode (_enter_play_mode)
  → hides all editor UI (only Menu button stays)
  → is_playtest = True, _is_play_only = True
  → loads bricks from published build data
  → calls start_multiplayer(build_id, token)

Return to Menu (_return_to_menu)  [Menu button in top bar]
  → calls stop_multiplayer()
  → hides character, resets state
  → shows main menu

Studio Mode (_enter_studio)
  → shows all editor buttons
  → is_playtest = False
  → _cloud_build_id = None (new build)
```

---

## Server Auto-Start Logic (login_screen.py)

Only runs when `config.get()["local"] == True` (i.e. `host=localhost` in server.cfg).

1. Check `browse_published()` — if responds AND `get_rooms()` responds → server is current → skip
2. If server responds but missing `/api/rooms` → outdated → kill and restart
3. Lock file (`.server_starting`) prevents two simultaneous instances from both starting the server
4. `_kill_port_8000()` uses `netstat -ano` + `taskkill /F /PID` to kill whatever is on port 8000
5. Polls every 0.3s for up to 10s for the server to come up

---

## Online Play (config.py + server.cfg)

`server.cfg` is auto-created in the game folder:
```
host=localhost   # auto-host locally
# host=1.2.3.4  # connect to remote server
port=8000
```

- `host=localhost` → game starts local server, connects to 127.0.0.1
- `host=<IP>` → game skips server startup, connects to that IP
- Server binds to `0.0.0.0` so it accepts external connections
- For friends to connect: host forwards port 8000 on their router, shares public IP

---

## Key Panda3D Notes

- `models/box` needs `setTextureOff(1)` before `setColor()` or color is ignored
- `globalClock.getDt()` for delta time in tasks
- Tasks return `Task.cont` to keep running, `Task.done` to stop
- `self.taskMgr.doMethodLater(0, cb, name, extraArgs=[...], appendTask=True)` to schedule a callback on the Panda3D main thread from a background thread
- `base.a2dBottomLeft` — anchor for bottom-left GUI elements
- DirectEntry `command=cb` fires with text when Enter pressed
- `setBillboardPointEye()` on a NodePath makes it always face the camera

---

## What's Working

- Accounts: register, login, auto-login via `.session` file, logout
- Cloud save/load/delete builds per user
- Publish/unpublish toggle; browse all published builds
- Play-only mode (published builds, no editor)
- Studio: full editor (place, move, scale, color, texture bricks), playtest, export/import JSON
- Real-time multiplayer: see other players move with smooth interpolation, walking animation
- Chat: press `/`, type, Enter to send — visible to all players in the room
- Browse screen shows live player counts, sorted by most players first
- Online play via `server.cfg` (port forward or dedicated server)

---

## Current State / What Was Just Done

The user just finished implementing the full multiplayer + chat + online play system. The most recent changes were:

1. **Online play** — added `config.py` + `server.cfg` so the server address is configurable
2. **Player counts** — browse screen fetches `/api/rooms` and shows live counts, sorted
3. **Chat fix** — server excludes sender from broadcast (sender already shows locally); hotkey changed to `/`
4. **Smooth movement** — remote players interpolate position (lerp factor 18, 20Hz updates) instead of snapping
5. **Full character model** for remote players — matches local character exactly (torso/arms/legs/head/billboard label)

The game is functionally complete for its current feature set. Possible next steps:
- More brick types / textures / colors UI
- Saving multiplayer-specific things (player positions persist across sessions)
- A lobby / server browser with more info
- Admin tools for build moderation
- Sound effects / music
- Mobile/gamepad controls
