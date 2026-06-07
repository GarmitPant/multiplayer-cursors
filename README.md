# Collaborative Cursor System

Real-time multiplayer cursors and draw trails over WebSockets. Vite + React frontend,
FastAPI + Redis backplane backend. The server is a dumb relay — all cursor intelligence
lives in the shared client engine (`client/src/cursorEngine.js`).

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
cd cursor-system/client
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
cd cursor-system
docker compose up --build    # backend must be running

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

## Public deploy (Vercel + Render)

The frontend and backend deploy separately. The **Vercel URL is the user-facing link**;
it connects to Render over `wss://` cross-origin.

### Environment variables

**Render Web Service** (repo root: `cursor-system/`, Docker, existing `Dockerfile`):

| Variable | Example | Notes |
|----------|---------|-------|
| `REDIS_URL` | `redis://…` | Render Key Value or Redis Cloud |
| `CORS_ORIGINS` | `https://your-app.vercel.app` | **Exact** Vercel origin, no trailing slash |
| `REPLICA_ID` | `render` | Shown in client HUD |

**Vercel project** (root directory: `client/`, framework: Vite):

| Variable | Example | Notes |
|----------|---------|-------|
| `VITE_WS_URL` | `wss://your-app.onrender.com` | Render service URL, no trailing slash |

Leave `VITE_WS_URL` unset locally — the client uses same-origin WebSocket via nginx.

`app/config.py` reads `CORS_ORIGINS`; FastAPI CORS middleware is already wired in
`app/main.py`. **This is the only backend change in the M5 phase** (config only, no new
server logic).

> **Follow-up (not required):** optionally validate the WebSocket `Origin` header against
> the CORS allowlist in the WS endpoint.

---

### (HUMAN) Deploy backend to Render

1. Create a **Web Service** from this repo; set **Root Directory** to `cursor-system`.
2. Runtime: **Docker** (uses the existing `Dockerfile`).
3. Add **managed Redis** (Render Key Value or external); set `REDIS_URL`.
4. Set `CORS_ORIGINS` to your Vercel origin (placeholder OK on first deploy — update after
   Vercel URL is known, then redeploy).
5. Deploy; copy the service URL → `wss://<your-app>.onrender.com`.

Dashboard UIs change over time; the structure above is stable.

### (HUMAN) Deploy frontend to Vercel

1. Import the repo; set **Root Directory** to `cursor-system/client`.
2. Framework preset: **Vite**; build command `npm run build`; output `dist`.
3. Set `VITE_WS_URL=wss://<your-app>.onrender.com` (from Render step).
4. Deploy; copy the Vercel URL (e.g. `https://your-app.vercel.app`).

`client/vercel.json` rewrites all routes to `index.html` for React Router (`/canvas/:code`).

### (HUMAN) Final CORS pass

Set Render `CORS_ORIGINS` to the **exact** Vercel origin and redeploy if you used a
placeholder earlier. Open the Vercel URL in two browsers — cursors/trails should sync with
no CORS errors in the console.

On first hit after Render idle sleep, the Canvas shows **"Connecting…"** until the WebSocket
opens (cold start + reconnect backoff).

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
