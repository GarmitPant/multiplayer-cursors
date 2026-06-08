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

## Deployment

Frontend (Vercel, static SPA) + backend (Render, Docker + managed Redis), connected
over wss:// — Vercel can't host a persistent WebSocket, so the FastAPI WS server runs
on Render. Full steps and env vars: see [DEPLOY.md](DEPLOY.md).

Live: https://multiplayer-cursors-sepia.vercel.app (first load after idle shows
"Connecting…" during Render cold start).

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
