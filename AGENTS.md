# Agent guide — Collaborative Cursor System

Reference for agents working in this repository. Describes **current behavior and structure only**.

**Live demo:** https://multiplayer-cursors-sepia.vercel.app  
**Repo layout root:** this directory (`app/`, `client/`, `tests/`, `tools/`, `Dockerfile`, `docker-compose.yml`).

---

## Summary

Real-time multiplayer cursors and draw trails over WebSockets.

| Layer | Stack |
|-------|-------|
| Frontend | Vite + React, React Router, vanilla JS cursor engine |
| Backend | FastAPI, WebSockets, Redis pub/sub |
| Deploy | Local: Docker Compose (3 replicas + nginx + Redis). Public: Vercel SPA + Render Docker + managed Redis |

**Architectural split:** the server is a **dumb relay** with validation, coalescing, and batched fan-out. All cursor motion intelligence (send-on-delta, reconstruction, draw simplification) lives in **`client/src/cursorEngine.js`**. Do not reimplement that logic in React.

---

## Architecture invariants

1. **`cursorEngine.js` is the single source of cursor/draw math** — import `Emitter`, `PeerReceiver`, `TrailStore`, etc.; do not duplicate algorithms in components.
2. **Peer cursor positions are not React state** — DOM transforms and rAF loops drive motion; React handles chrome (HUD, presence list, inspector).
3. **Coordinates are logical `[0,1]`** — convert only through `client/src/coords/viewport.js` (`fit`, `toScreen`, `toLogical`). Board is 16:9 cover-fit into the viewport.
4. **Server relays, does not interpret cursors** — validates/clamps/quantizes inbound JSON, publishes to Redis, coalesces per room, flushes batched frames on a tick.
5. **No auth** — ephemeral guest identity minted on connect; clients may resubmit `user_id` + `color` query params for reconnect continuity.

---

## Repository map

```
app/
  main.py          FastAPI app, WS endpoint, lifespan, health check
  protocol.py      Pydantic inbound message validation
  config.py        Settings (env-backed)
  identity.py      EphemeralIdentityProvider
  backplane.py     Redis pub/sub publish/subscribe
  rooms.py         RoomCache — per-room coalescing before socket fan-out
  ticker.py        Fixed-interval drain loop (runtime-adjustable tick_ms)
client/src/
  cursorEngine.js  Framework-agnostic engine (LOCKED surface for cursor/draw)
  coords/viewport.js  Logical ↔ screen mapping
  net/connection.js   WebSocket URL builder + reconnect backoff
  ui/CanvasPage.jsx   Main canvas: WS wiring, rAF loop, draw input
  ui/Landing.jsx      Create/join flow
  ui/InspectorOverlay.jsx  Dev HUD (metrics + sliders)
  ui/AvatarStack.jsx  Presence chips
  lib/               canvasCode, presence, figmaCursor, colors
  metrics/           Inspector counter helpers
  dev/               inspectorDefaults (DEFAULT_EPS_POS)
tests/               pytest (server + engine parity)
tools/simulate.py    Multi-client load/draw simulator
docker-compose.yml   redis + app1/app2/app3 + nginx lb
nginx.conf           Round-robin WS to replicas; serves client/dist
README.md            User-facing runbook + performance numbers
DEPLOY.md            Vercel + Render deploy steps
```

---

## Runtime topologies

### Local multi-replica (Docker Compose)

- **Services:** `redis`, `app1`, `app2`, `app3`, `lb` (nginx on `:8080`)
- **Static client:** `client/dist` mounted into nginx
- **WebSocket:** `ws://localhost:8080/ws/{room_id}?name=…`
- **HUD** shows `served by: app1|app2|app3` from `init.replica`
- Cross-replica sync via Redis; each replica runs its own ticker loop and local socket registry

### Public deploy

- **Frontend:** Vercel (`client/`, `VITE_WS_URL=wss://…`)
- **Backend:** Render Docker Web Service + managed Redis
- **Single backend instance** on free tier (cold start ~30–60s; UI shows “Connecting…”)
- See `DEPLOY.md` for env vars and health check path `/healthz`

### Single-node dev (no Compose)

- `uvicorn app.main:app` + local Redis + `npm run dev` (Vite proxy or `VITE_WS_URL`)

---

## End-to-end data flow

```
Client A ──WS──► Replica ──publish──► Redis channel room:{id}
                      ▲                      │
                      │                      ▼
                 RoomCache ◄── subscribe ────┘ (all replicas)
                      │
                 Ticker (every tick_ms)
                      │
                 flush_fn ──► all local WS in room
```

**Per message path (cursor/draw):**

1. Client sends JSON on WebSocket.
2. `protocol.parse_inbound` validates; malformed frames dropped.
3. Server stamps `user_id`, `backplane.publish(room_id, payload)`.
4. Subscribers on each replica call `RoomCache.ingest`.
5. Every `tick_ms`, `RoomCache.drain()` produces ordered outbound frames; `flush_fn` sends to every socket in that room on **this replica**.

**Coalescing rules (`rooms.py`):**

| Inbound | Cache behavior | Outbound |
|---------|----------------|----------|
| `cursor` | Last-write-wins per `user_id` | Batched in `{ type: "cursors", updates: [...] }` |
| `draw` | Append points per `(user_id, seq)` | `{ type: "draw", … }` then `{ type: "draw_end" }` |
| `peer_joined`, `peer_left`, `cursor_leave`, `tick_ms` | Passthrough queue | Same type, in order before cursors/draw |

Draw points are **never dropped**; cursor updates coalesce to latest position per user per tick.

---

## WebSocket protocol

**Endpoint:** `GET /ws/{room_id}?name=&user_id=&color=`

**Room ID:** canvas code, max **64** chars (longer → close **1008**). Max **150** connections per room.

### Client → server (validated inbound)

| `type` | Fields | Notes |
|--------|--------|-------|
| `cursor` | `p`, `v`, `t`; optional `kf`, `name`, `color` | Coords clamped `[0,1]`, quantized (`quant_bits=12`) |
| `cursor_leave` | — | Hides local cursor |
| `draw` | `seq`, `pts[]` | Max **256** points per message |
| `draw_end` | `seq` | Ends stroke |
| `heartbeat` | — | Accepted, not relayed |
| `set_tick_ms` | `value` | **1–500** ms; dev hook; updates replica ticker; **not** cursor relay semantics |

`set_tick_ms` is handled locally on the receiving replica (not published as a cursor delta). Server broadcasts `{ type: "tick_ms", value: N }` to the **room** so inspector sliders stay in sync.

### Server → client

| `type` | When |
|--------|------|
| `init` | On connect: `self`, `peers[]`, `replica`, `tick_ms` (current), `default_tick_ms` (boot baseline, 50) |
| `peer_joined` | After Redis relay |
| `peer_left` | User disconnected |
| `cursors` | Batched cursor updates (`updates[]` with `user_id`, `p`, `v`, `t`, …) |
| `cursor` | Unbatched path still handled client-side (legacy/single) |
| `draw` / `draw_end` | Stroke segments |
| `tick_ms` | Inspector sync after tick change |

---

## Server configuration (`app/config.py`)

| Setting | Default | Role |
|---------|---------|------|
| `redis_url` | `redis://localhost:6379` | Backplane |
| `cors_origins` | `*` | FastAPI CORS (comma-separated in prod) |
| `replica_id` | `local` | Shown in client HUD |
| `quant_bits` | `12` | Coordinate grid quantization |
| `tick_ms` | **50** | Ticker interval (ms); runtime override via `set_tick_ms` |
| `max_room_id_len` | 64 | WS reject |
| `max_display_name_len` | 32 | Name sanitize/truncate |
| `max_room_connections` | 150 | WS reject |

**Health:** `GET /healthz` → `200` if Redis ping OK, else `503`.

**Logging:** stdlib logger `"cursor"`, INFO, lifecycle + errors to stdout; **no per-cursor logging**.

---

## Client engine (`cursorEngine.js`)

### CONFIG defaults (tuned constants)

| Key | Value | Role |
|-----|-------|------|
| `EPS_POS` | 0.005 | Send-on-delta threshold (logical units) |
| `VEL_SMOOTH` | 0.5 | Outbound velocity smoothing |
| `KEYFRAME_MS` | 1500 | Periodic keyframe with name/color |
| `IDLE_MS` | 40 | Stop message after idle |
| `PRESENCE_TIMEOUT_MS` | 5000 | Hide peer if no updates |
| `SMOOTH_TIME` | 0.08 | Inbound reconstruction smoothing |
| `EPS_RDP` | 0.003 | Draw stroke simplification |
| `TRAIL_TTL_MS` | 3000 | Trail fade |

### Key classes

- **`Emitter`** — `sample()`, `keyframe()`, `stop()`; send-on-delta using constant-velocity prediction.
- **`PeerReceiver`** — applies inbound cursor updates; `step()` in rAF for smooth display.
- **`StrokeSimplifier` + `OneEuro`** — draw capture pipeline (matches `tools/draw_pipeline.py`).
- **`TrailStore`** — local trail rendering with Catmull-Rom splines.

---

## Client UI

### Routing (`App.jsx`)

- `/` — Landing (create canvas / join by 6-char code)
- `/canvas/:code` — CanvasPage

Canvas codes: uppercase alphanumeric (`canvasCode.js`), 6 chars generated on create.

### CanvasPage responsibilities

- WebSocket lifecycle via `connectWithBackoff` (8 failures → “Can't connect — retrying…”)
- Window-level pointer handlers for cursor + draw (blocked over UI chrome via `eventOverUiChrome`)
- **`presenceById` Map** → React `presence` for AvatarStack (merge on init/join/cursors; remove on `peer_left` only)
- **`peers` object** — DOM cursor elements + `PeerReceiver` instances (separate from avatar state)
- Identity persisted in `sessionStorage` per room (`user_id`, `color`, `name`)

### Inspector overlay (`InspectorOverlay.jsx`)

Toggle: **`i`** key or bottom-right button. Hidden by default.

| Feature | Behavior |
|---------|----------|
| Metrics | `sent/s`, `recv msgs/s`, `recv positions/s`, `active peers` — ref counters, 1s sampler |
| Send threshold slider | Mutates `emitterConfigRef.EPS_POS` (0.001–0.05); **per-user**; affects how **others** see your cursor |
| Server tick slider | Sends debounced `set_tick_ms` (1–500 ms); **global per replica**; synced via `tick_ms` broadcast **within room** |
| Reset ↺ / Reset defaults | EPS → `DEFAULT_EPS_POS`; tick → `default_tick_ms` from init (50 ms boot baseline) |

**Scope note:** one ticker loop per **replica** (all rooms share it). `tick_ms` slider sync broadcast is per **room** — users in other rooms on the same replica feel the interval change but their slider may not update.

Metrics counting mirrors `tools/simulate.py`: batched `cursors` = 1 msg, `len(updates)` positions.

---

## Performance model (measured)

Two independent optimizations:

1. **Send-on-delta (client)** — emit only when position diverges from predicted path beyond `EPS_POS`.
2. **Server-side tick batching (`RoomCache` + `ticker`)** — coalesce per tick; one `cursors` frame per client per tick instead of N immediate relays.

Reference numbers (98 simulated users, 50 ms tick, Docker multi-replica): ~20× fewer inbound WS messages per client with position delivery preserved. See README § Performance.

---

## Identity

- Server: `EphemeralIdentityProvider.create(name, user_id=, color=)` → `{ user_id, name, color }`
- `user_id` format: `u_` + 8 hex chars if client resubmits valid ID
- Client reconnect sends stored identity in query string to keep color across reconnects / replica failover

---

## Testing

```bash
source .venv/bin/activate && pip install -r requirements-dev.txt && pytest   # 50 tests
cd client && npm run test    # vitest: viewport + inspector metrics
cd client && npm run build
```

| Suite | Covers |
|-------|--------|
| `test_protocol.py` | Inbound validation, quantize properties, `set_tick_ms` bounds |
| `test_coalescing.py` | RoomCache ingest/drain |
| `test_emitter.py` / `test_receiver.py` | Engine parity with client |
| `test_robustness.py` | healthz, room_id length, connection cap |
| `test_draw.py` | Draw relay |
| `test_smoke.py` | WS integration smoke |
| `client/src/coords/viewport.test.js` | Cover-fit mapping properties |

---

## Load / draw simulation

```bash
python tools/simulate.py ws://localhost:8080/ws/demo 100
python tools/simulate.py ws://localhost:8080/ws/demo 80 --draw-frac 0.5
```

Bots use the same send-on-delta and draw pipeline as the client. Stats print every 2s: `sent/s`, `recv_msgs/s`, `recv_pos/s`, draw rates.

---

## Agent constraints (do / don't)

**Do**

- Extend behavior through existing seams (`cursorEngine.js`, `protocol.py`, `RoomCache`, `CanvasPage` effect wiring).
- Keep hot paths off React state (counters, cursor positions, emitter config during drag).
- Match existing naming, file layout, and test patterns.
- Run `pytest` + `npm run test` after server/client changes.

**Don't**

- Reimplement cursor prediction, reconstruction, or draw simplification in React or Python relay code.
- Log per-cursor messages on the server.
- Publish `set_tick_ms` through the cursor delta path (it's a local control hook + room broadcast for UI sync).
- Hardcode a second copy of `EPS_POS` or default tick — use `CONFIG.EPS_POS`, `DEFAULT_EPS_POS`, and init `default_tick_ms` / `tick_ms`.

---

## Quick file index for common tasks

| Task | Start here |
|------|------------|
| Add inbound message type | `app/protocol.py`, `app/main.py`, `app/rooms.py` (if passthrough/batch) |
| Change batching / tick | `app/rooms.py`, `app/ticker.py`, `app/main.py` |
| Change cursor send logic | `client/src/cursorEngine.js` (`Emitter`) |
| Change peer rendering | `client/src/cursorEngine.js` (`PeerReceiver`), `CanvasPage.jsx` rAF loop |
| WS reconnect / URL | `client/src/net/connection.js` |
| UI chrome / inspector | `client/src/ui/InspectorOverlay.jsx`, `CanvasPage.jsx` |
| Deploy / env | `DEPLOY.md`, `app/config.py`, `client/.env.example` |
