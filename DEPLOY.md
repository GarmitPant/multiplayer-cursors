## Public deploy (Vercel + Render)

The frontend and backend deploy separately. The **Vercel URL is the user-facing link**;
it connects to Render over `wss://` cross-origin.

### Environment variables

**Render Web Service** (repo root, Docker, existing `Dockerfile`):

| Variable | Example | Notes |
|----------|---------|-------|
| `REDIS_URL` | `redis://…` | Render Key Value or Redis Cloud |
| `CORS_ORIGINS` | `https://your-app.vercel.app` | **Exact** Vercel origin, no trailing slash |
| `REPLICA_ID` | `render` | Shown in client HUD |

**Vercel project** (root directory: `client/`, framework: Vite):

| Variable | Example | Notes |
|----------|---------|-------|
| `VITE_WS_URL` | `wss://your-app.onrender.com` | Render service URL, no trailing slash |

`app/config.py` reads `CORS_ORIGINS`; CORS middleware is wired in `app/main.py`.

> Optionally validate the WebSocket `Origin` header against the CORS allowlist in the WS endpoint.

---

### Deploy backend to Render

1. Create a **Web Service** from this repo; leave **Root Directory** blank (repo root).
2. Runtime: **Docker** (uses the existing `Dockerfile`).
3. Set **Health Check Path** to `/healthz` (pings Redis — see [README § Operations & robustness](README.md#operations--robustness)).
4. Add **managed Redis** (Render Key Value or external); set `REDIS_URL`.
5. Set `CORS_ORIGINS` to your Vercel origin (placeholder OK on first deploy — update after
   Vercel URL is known, then redeploy).
6. Deploy; copy the service URL → `wss://<your-app>.onrender.com`.

Dashboard UIs change over time; the structure above is stable.

### Deploy frontend to Vercel

1. Import the repo; set **Root Directory** to `client`.
2. Framework preset: **Vite**; build command `npm run build`; output `dist`.
3. Set `VITE_WS_URL=wss://<your-app>.onrender.com` (from Render step).
4. Deploy; copy the Vercel URL (e.g. `https://your-app.vercel.app`).

`client/vercel.json` rewrites all routes to `index.html` for React Router (`/canvas/:code`).

### Final CORS pass

Set Render `CORS_ORIGINS` to the **exact** Vercel origin and redeploy if you used a
placeholder earlier. Open the Vercel URL in two browsers — cursors/trails should sync with
no CORS errors in the console.

On first hit after Render idle sleep, the Canvas shows **"Connecting…"** until the WebSocket
opens (cold start + reconnect backoff).
