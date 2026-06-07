# Collaborative Cursor System

Real-time multiplayer cursors over WebSockets. FastAPI + Redis backplane, designed
to scale horizontally across stateless replicas. See `HLD_collaborative_cursors.md`
for the design.

## Run the full topology (Redis + 2 replicas + load balancer)

Prerequisite: Docker.

    docker compose up --build

Open http://localhost:8080 in two or more tabs. Move your mouse — cursors sync.
Each tab shows which replica served it ("served by: app1/app2").

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
    # then serve client/ (e.g. `python -m http.server` in ./client) and open it

## Tests

    pip install -r requirements-dev.txt
    pytest

## Status

This is a scaffold with a thin working slice. The batching/coalescing engine,
presence TTL, reconnect, draw trails, and the real cursor capture/render UI are
implemented from the LLD spec (next phase).
