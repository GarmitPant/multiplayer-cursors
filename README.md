# Collaborative Cursor System

Real-time multiplayer cursors over WebSockets. FastAPI + Redis backplane, designed
to scale horizontally across stateless replicas.

## Run the full topology (Redis + 2 replicas + load balancer)

Prerequisites: Docker, Node.js (for the frontend build).

```bash
cd cursor-system/client
npm install
npm run build          # produces client/dist (nginx static root)

cd ..
docker compose up --build
```

Open http://localhost:8080 in two or more tabs. Move your mouse — cursors sync.
Each tab shows which replica served it ("served by: app1/app2").

### HMR dev (Vite proxies /ws → compose backend on :8080)

In a dedicated terminal:

```bash
cd cursor-system
docker compose up --build    # backend must be running

cd client
npm run dev                  # open the printed http://localhost:5173 URL
```

### Demo: cross-replica fan-out + resilience

- Tabs are round-robined across `app1` and `app2`; cursors still sync because the
  Redis backplane relays between replicas.
- Kill a replica while tabs are open:

      docker compose kill app1

  Tabs served by `app1` lose their cursor (their socket dropped); tabs on `app2`
  are unaffected. Bring it back with `docker compose up -d app1`.

### Load test (100 simulated users)

    pip install -r requirements-dev.txt
    python tools/simulate.py ws://localhost:8080/ws/demo 100

Multi-user draw load (watch overlapping trails in a real browser tab):

    python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 0.5
    python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 1.0 --draw-only

## Run a single node (no Docker, fastest inner loop)

    python3.12 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    docker run -p 6379:6379 redis:7-alpine
    REDIS_URL=redis://localhost:6379 uvicorn app.main:app --reload --port 8000
    cd client && npm install && npm run dev

## Tests

    pip install -r requirements-dev.txt
    pytest
