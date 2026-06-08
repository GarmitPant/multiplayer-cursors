# Collaborative Cursor System

Real-time multiplayer cursors and draw trails over WebSockets. Vite + React frontend,
FastAPI + Redis backplane backend. The server is a dumb relay — all cursor intelligence
lives in the shared client engine (`client/src/cursorEngine.js`).

## Live demo

**https://multiplayer-cursors-sepia.vercel.app** — the first load after idle shows
**"Connecting…"** while Render wakes from cold start (~30–60s), then cursors sync normally.

## Two deployment modes

| Mode | Purpose | Topology |
|------|---------|----------|
| **Local multi-replica** | Dev/demo of horizontal scaling | Docker Compose: Redis + 3 FastAPI replicas + nginx LB on `:8080` |
| **Public single-instance** | Shareable demo on the internet | Vercel (static SPA) + Render (one Docker Web Service + managed Redis) |

Local Compose proves cross-replica fan-out (nginx round-robin, Redis pub/sub). The public
deploy runs a **single** backend instance on Render free tier (sleeps when idle). Both use
the same client and server code paths.

---

## Local multi-replica (Docker Compose)

Prerequisites: Docker, Node.js 18+.

```bash
cd client
npm install
npm run build          # produces client/dist (nginx static root)

cd ..
docker compose up --build
```

Open http://localhost:8080 — landing page → create/join a Canvas. Open multiple tabs;
cursors and trails sync. The HUD shows `served by: app1|app2|app3` (whichever replica
accepted the WebSocket).

### HMR dev (Vite proxies `/ws` → compose backend on `:8080`)

```bash
docker compose up --build    # from repo root; backend must be running

cd client
npm run dev                  # open http://localhost:5173
```

### Resilience demo

```bash
docker compose kill app1
```

Tabs on `app1` auto-reconnect to another replica; persisted identity keeps the same cursor color.

### Tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest

cd client && npm run test    # viewport property tests (vitest)
```

### Load test

```bash
python tools/simulate.py ws://localhost:8080/ws/demo 100
```

---

## Performance: measured fan-out reduction

Two optimizations work on opposite ends of the message pipe, and were measured
independently. Both runs: **98 simulated users in one room, human-like cursor paths,
local Docker (Redis + replicas + nginx), server tick = 50ms (20 Hz)**, steady state.

- **Send-on-delta (client-side source reduction):** each client only emits when its
  real position diverges from a shared constant-velocity prediction past a threshold,
  so a cursor moving in a straight line emits almost nothing. This thins what each
  client *sends*.
- **+ Server-side batched fan-out:** the server coalesces per-room state and flushes
  one batched frame per client per tick instead of relaying every message immediately.
  This thins what each client *receives*. (Cursors coalesce last-write-wins; draw
  strokes are appended, never dropped.)

| Metric (98 users, steady state) | Send-on-delta only | Send-on-delta + Server batching | Change |
|---|---|---|---|
| Client emit rate (`sent/s`) | ~383 | ~380 | unchanged (batching is receive-side) |
| Total inbound messages/s | ~37,500 | ~1,860 | **~20× fewer** |
| Per-client inbound messages/s | ~383 | ~19 | **~20× fewer** |
| Position info delivered/s | ~37,500 | ~36,400 | preserved (no fidelity lost) |

For reference, a naive client (emit every frame at 20 Hz, no suppression) would send
~1,960 msg/s and fan out to ~190,000 inbound msg/s. Send-on-delta cuts the send side
~80% (1,960 → ~383); server batching then cuts inbound ~20× (~37,500 → ~1,860) by
making inbound scale with tick rate (`users × 20 Hz`) instead of with the number of
active senders.

**Takeaway:** ~20× fewer inbound messages per client with no loss of cursor fidelity
(~36k positions/s delivered either way), at the cost of ≤ one tick (≤50 ms) of added
delivery latency, which the client-side reconstruction smooths out.

---

## Deployment

Frontend (Vercel, static SPA) + backend (Render, Docker + managed Redis), connected
over wss:// — Vercel can't host a persistent WebSocket, so the FastAPI WS server runs
on Render. Full steps and env vars: see [DEPLOY.md](DEPLOY.md).

Live: https://multiplayer-cursors-sepia.vercel.app (first load after idle shows
"Connecting…" during Render cold start).

---

## Operations & robustness

Tier 1 guards for the demo deploy — failures are visible, inputs are bounded; the happy
path is unchanged.

### Logging

| | |
|---|---|
| **What** | Stdlib logging (`logger` name `cursor`, level INFO). Lifecycle: startup, Redis connect, ticker start/stop, room create/teardown, client connect/disconnect. Warnings/errors include stack traces (`exc_info=True`). |
| **Hot path** | Per-cursor messages are **not** logged (would flood). |
| **Where** | stdout only — no file handler (container disk is ephemeral). |
| **Local** | `docker compose logs` or the compose terminal. |
| **Render** | Dashboard → service → **Logs** (live tail + searchable explorer). |

Logs are **transient** — retention is plan-dependent, then they expire. Durable centralized
logging (Render log streams → Datadog/Better Stack/etc.) is a deliberate non-goal for this
demo. Benchmark evidence lives in the repo instead (e.g. pipe a `simulate.py` run to a file).

### Health check

| Response | Meaning |
|----------|---------|
| `200` `{"ok":true,"redis":"up","replica":...}` | Redis ping succeeded |
| `503` `{"ok":false,"redis":"down",...}` | Redis unreachable |

On Render, set **Health Check Path** to `/healthz` so traffic routes only to instances that
can function. See [DEPLOY.md](DEPLOY.md). This couples liveness to Redis; a production
system would split **liveness** (`/healthz`) from **readiness** (`/readyz`).

### Input bounds & error handling

**Server**

| Guard | Limit |
|-------|-------|
| `room_id` / canvas code | 64 chars — connection closed with WebSocket code **1008** if exceeded |
| Display name | Sanitized (angle brackets stripped) + truncated to **32** chars |
| Connections per room | **150** max — new connection rejected with code **1008** |

**Client**

- WebSocket frames parsed defensively — bad JSON dropped with `console.warn`, not thrown.
- `ws.onerror` logged via `console.error`.
- After **8** failed reconnect attempts, UI shows **"Can't connect — retrying…"**; backoff continues.

### Scope (intentionally out of this phase)

No auth (ephemeral guest identity by design), no per-IP rate limiting, and no
metrics/tracing framework. This is a **presence demo**, not an untrusted-public-scale service —
stdlib logging and connection-boundary guards are sufficient for observability and abuse
prevention at demo scale.

---

## Single-node dev (no Docker)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker run -p 6379:6379 redis:7-alpine
REDIS_URL=redis://localhost:6379 uvicorn app.main:app --reload --port 8000

cd client && npm install && npm run dev
```

Point Vite proxy at `:8000` or set `VITE_WS_URL=ws://localhost:8000`.
