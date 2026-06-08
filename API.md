# Multiplayer Cursors — API Documentation

API documentation for the backend **HTTP** and **WebSocket** interfaces: endpoints, message types, fields, limits, and relay semantics. This document specifies **what the server accepts and emits** — not how the reference client implements prediction, smoothing, or draw simplification (see `client/src/cursorEngine.js` and `AGENTS.md` for that).

**Live backend:** `https://multiplayer-cursors.onrender.com`  
**WebSocket base:** `wss://multiplayer-cursors.onrender.com/ws/{room_id}`

---

## Overview

The server is a **dumb relay** with validation and batching:

1. Clients connect over WebSocket to a **room** (canvas code).
2. Inbound JSON is validated, clamped, and stamped with a server-assigned **`user_id`**.
3. Valid messages are published to Redis (`room:{room_id}`) and received by every app replica in that room.
4. Each replica **coalesces** messages per room and flushes batched frames to local sockets on a fixed **tick** (default 50 ms).

There is **no authentication**. Identity is ephemeral; clients may resubmit `user_id` and `color` on reconnect to keep the same cursor across disconnects.

---

## Coordinate system

All cursor and draw positions on the wire use **normalized logical coordinates**:

| Property | Value |
|----------|--------|
| Range | `[0.0, 1.0]` on both axes |
| Origin | Top-left of the shared 16:9 board `(0, 0)` |
| Aspect | Fixed **16:9** shared screen (not an infinite canvas) |
| Quantization | Server snaps coords to a **12-bit** grid (`4095` steps per axis) on ingest |

Clients map screen pixels ↔ logical coords locally. The reference client uses `client/src/coords/viewport.js` (`fit`, `toScreen`, `toLogical`).

**Velocity** (`v`) is in logical units per second (client-defined; used for extrapolation on receive).

**Time** (`t`) on cursor messages is a client-provided monotonic timestamp in **seconds** (typically `performance.now() / 1000`).

---

## HTTP endpoints

### `GET /healthz`

Liveness check used by Render and operators. **Requires a working Redis connection.**

| Status | Body | Meaning |
|--------|------|---------|
| `200` | `{"ok": true, "redis": "up", "replica": "<id>"}` | Redis ping succeeded |
| `503` | `{"ok": false, "redis": "down", "replica": "<id>"}` | Redis unreachable |

Example:

```bash
curl -s https://multiplayer-cursors.onrender.com/healthz
```

---

## WebSocket connection

### URL

```
ws[s]://<host>/ws/{room_id}?name=<display_name>[&user_id=<id>][&color=<hex>]
```

| Part | Required | Description |
|------|----------|-------------|
| `room_id` | Yes | Canvas / room code. Max **64** characters. |
| `name` | Recommended | Display name shown on peer cursors. Sanitized and truncated server-side. |
| `user_id` | No | Reconnect continuity. Must match `^u_[0-9a-f]{8}$` or it is ignored and a new id is minted. |
| `color` | No | Cursor color on reconnect. Must be one of the server palette hex values (see [Identity](#identity)). |

**Examples**

```
wss://multiplayer-cursors.onrender.com/ws/ABC123?name=Alex
wss://multiplayer-cursors.onrender.com/ws/ABC123?name=Alex&user_id=u_a1b2c3d4&color=%234a9eed
```

### Connection limits

| Guard | Limit | On violation |
|-------|-------|----------------|
| `room_id` length | ≤ 64 chars | WebSocket closed with code **1008** (`room_id too long`) |
| Connections per room (per replica) | **150** | WebSocket closed with code **1008** (`room full`) |
| Display name | ≤ **32** chars; `<` `>` stripped | Truncated / sanitized at connect |
| Unknown inbound `type` | — | Frame **silently dropped** |
| Malformed JSON / validation error | — | Frame **silently dropped** |

### Wire format

- **Encoding:** UTF-8 text frames
- **Payload:** One JSON object per frame
- **Discriminator:** Required string field `"type"`

---

## Identity

On connect the server mints (or restores) a guest identity:

```json
{
  "user_id": "u_a1b2c3d4",
  "name": "Alex",
  "color": "#4a9eed"
}
```

| Field | Rules |
|-------|--------|
| `user_id` | `u_` + 8 lowercase hex chars. Server-generated unless a valid id is resubmitted in the query string. |
| `name` | Sanitized display name (see limits above). |
| `color` | One of: `#4a9eed`, `#22c55e`, `#f59e0b`, `#ef4444`, `#8b5cf6`, `#ec4899`, `#06b6d4`, `#84cc16`. Invalid values get a random palette color. |

The server **stamps `user_id` on all relayed outbound messages**. Clients must not trust inbound `user_id` for authorization — it is a session label only.

**Reconnect:** Resubmit `user_id` and `color` in the query string. The reference client persists them in `sessionStorage` per room.

**Same user, two sockets:** If the same `user_id` connects again to a room on the same replica, the older socket is closed (reconnect replace).

---

## Client → server messages

All fields not listed are **forbidden** (`extra` fields cause validation failure and the frame is dropped).

### `cursor`

Live cursor sample or keyframe.

```json
{
  "type": "cursor",
  "p": [0.42, 0.61],
  "v": [0.8, -0.2],
  "t": 1730000000.0,
  "kf": true,
  "name": "Alex",
  "color": "#4a9eed"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `p` | `[float, float]` | Yes | Position in `[0, 1]`. Quantized on ingest. |
| `v` | `[float, float]` | Yes | Velocity (logical units / sec). |
| `t` | float | Yes | Client timestamp (seconds). |
| `kf` | bool | No | Keyframe flag (identity refresh). |
| `name` | string | No | Max 64 on wire; server truncates to 32 for storage. |
| `color` | string | No | Max 16 chars. |

**Relay:** Published to Redis and batched for peers. The sender also receives their own cursor via the batch loop — the reference client ignores self updates for rendering.

---

### `cursor_leave`

Hide the sender's cursor from peers (e.g. pointer left the board).

```json
{ "type": "cursor_leave" }
```

**Relay:** Published; delivered as a passthrough presence message (not coalesced into `cursors`).

---

### `draw`

Stroke segment (already simplified on the client).

```json
{
  "type": "draw",
  "seq": 3,
  "pts": [[0.1, 0.2], [0.15, 0.25], [0.2, 0.3]]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `seq` | int ≥ 0 | Yes | Per-user stroke sequence number. |
| `pts` | `[[x,y], …]` | Yes | Max **256** points per message. Each point quantized. |

**Relay:** Points are **appended**, never dropped, per `(user_id, seq)` before batch flush.

---

### `draw_end`

End a stroke.

```json
{ "type": "draw_end", "seq": 3 }
```

**Relay:** Mark stroke ended; `draw_end` is emitted after pending `draw` points for that seq in the same tick batch.

---

### `heartbeat`

```json
{ "type": "heartbeat" }
```

**Relay:** Accepted and **not relayed**. Use for keep-alive at the client’s discretion.

---

### `set_tick_ms`

Dev / inspector hook — changes the **global tick interval on the receiving replica** and broadcasts the new value to the room.

```json
{ "type": "set_tick_ms", "value": 50 }
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `value` | int | Yes | **1–500** ms. Values outside range are rejected. |

**Relay:** Not published as a cursor delta. Handled locally; server broadcasts `{ "type": "tick_ms", "value": N }` to the room so UI sliders stay in sync.

---

## Server → client messages

The server never sends unprompted messages except via the relay path below. The **first** message on every connection is always `init`.

### `init`

Sent once immediately after a successful connect.

```json
{
  "type": "init",
  "self": {
    "user_id": "u_a1b2c3d4",
    "name": "Alex",
    "color": "#4a9eed"
  },
  "peers": [
    { "user_id": "u_bbbbcccc", "name": "Bob", "color": "#22c55e" }
  ],
  "replica": "render-1",
  "tick_ms": 50,
  "default_tick_ms": 50
}
```

| Field | Description |
|-------|-------------|
| `self` | Your assigned identity for this connection. |
| `peers` | Other clients currently connected **to this replica only** (see [Multi-replica note](#multi-replica-behavior)). |
| `replica` | Backend instance id (`REPLICA_ID` env). |
| `tick_ms` | Current flush interval on this replica (may differ from default if changed at runtime). |
| `default_tick_ms` | Boot baseline tick (50 ms); used to reset inspector UI. |

---

### `peer_joined`

A user entered the room (relayed from Redis).

```json
{
  "type": "peer_joined",
  "user_id": "u_bbbbcccc",
  "name": "Bob",
  "color": "#22c55e"
}
```

---

### `peer_left`

A user disconnected.

```json
{
  "type": "peer_left",
  "user_id": "u_bbbbcccc"
}
```

Also evicts that user’s pending cursor from the room batch cache (they will not appear in the next `cursors` frame).

---

### `cursors`

**Batched cursor frame** — one per room per tick when any cursor updates are pending.

```json
{
  "type": "cursors",
  "updates": [
    {
      "user_id": "u_a1b2c3d4",
      "p": [0.42, 0.61],
      "v": [0.8, -0.2],
      "t": 1730000000.0,
      "name": "Alex",
      "color": "#4a9eed"
    }
  ]
}
```

| Behavior | Detail |
|----------|--------|
| Coalescing | **Last-write-wins** per `user_id` within a tick. |
| Identity | `name` / `color` on non-keyframe updates inherit from the last keyframe in cache. |
| Legacy | Single `{ "type": "cursor", … }` frames are not emitted by the server today; the reference client still handles them if present. |

Treat each entry in `updates` like a standalone `cursor` message from that `user_id`.

---

### `cursor` (legacy / single)

The reference client accepts unbatched cursor messages for compatibility:

```json
{
  "type": "cursor",
  "user_id": "u_bbbbcccc",
  "p": [0.5, 0.5],
  "v": [0, 0],
  "t": 1730000001.0
}
```

The production server path emits **`cursors`** batches instead.

---

### `draw`

Relayed stroke points (possibly merged from multiple inbound `draw` messages in one tick).

```json
{
  "type": "draw",
  "user_id": "u_a1b2c3d4",
  "seq": 3,
  "pts": [[0.1, 0.2], [0.15, 0.25]]
}
```

---

### `draw_end`

```json
{
  "type": "draw_end",
  "user_id": "u_a1b2c3d4",
  "seq": 3
}
```

---

### `tick_ms`

Broadcast when any client in the room changes the tick via `set_tick_ms`, or included in `init`.

```json
{ "type": "tick_ms", "value": 35 }
```

Clients should update local UI **without** re-sending `set_tick_ms` (avoid feedback loops).

---

## Relay and batching semantics

### End-to-end path

```
Client ──WS──► Replica ──publish──► Redis channel room:{room_id}
                  ▲                        │
                  │                        ▼
             RoomCache ◄── subscribe ──────┘
                  │
             Ticker (every tick_ms)
                  │
             flush ──► all local WS in room
```

### Per-tick flush order

When the ticker drains a room cache, messages are sent in this order:

1. **Presence** — `peer_joined`, `peer_left`, `cursor_leave`, `tick_ms` (FIFO within the tick)
2. **Draw** — for each active stroke: `{ type: "draw", … }` then `{ type: "draw_end" }` if ended
3. **Cursors** — single `{ type: "cursors", updates: [...] }` if any cursor state remains

### Coalescing rules

| Inbound type | Cache behavior | Outbound |
|--------------|----------------|----------|
| `cursor` | Last-write-wins per `user_id` | Batched in `cursors` |
| `draw` | Append points per `(user_id, seq)` | One or more `draw` frames per tick |
| `draw_end` | Mark stroke ended | `draw_end` after that stroke’s points |
| `peer_joined`, `peer_left`, `cursor_leave`, `tick_ms` | Passthrough queue | Same type, in order |
| `heartbeat`, `set_tick_ms` (inbound) | Not relayed | N/A / local side-effect only |

**Redis note:** Each inbound message is still published individually to Redis. Batching applies only to **socket fan-out** on each replica, not to the Redis publish side.

**Tick scope:** One ticker loop runs per **replica** (shared across all rooms on that instance). The `tick_ms` slider sync broadcast is per **room**.

---

## Multi-replica behavior

In Docker Compose or any multi-instance deploy:

- All replicas subscribe to the same Redis channel per room.
- Each replica only lists **locally connected** peers in `init.peers`.
- Cross-replica users appear after the first relayed `peer_joined` / `cursors` / `draw` message.

The `replica` field in `init` identifies which backend instance served the connection (useful when testing load balancing).

---

## Recommended client behavior

These are not enforced by the server but match the reference client and keep presence stable.

| Concern | Recommendation |
|---------|----------------|
| Send rate | Send-on-delta: emit `cursor` only when position diverges from predicted path beyond ~`0.005` logical units. |
| Keyframes | Emit a `cursor` with `kf: true` (and `name` / `color`) every **~1.5 s** even when idle. |
| Stop | After motion stops, send `cursor` with `v: [0, 0]` within ~**40 ms**. |
| Draw | Assign monotonically increasing `seq` per stroke; send `draw_end` when the pointer is released. |
| Self-echo | Ignore batched / relayed cursor and draw messages where `user_id === self.user_id`. |
| Reconnect | Exponential backoff; resubmit stored `user_id` and `color`; expect a fresh `init`. |
| Receive batch | Unpack `cursors.updates[]` and route each entry through the same handler as a single `cursor`. |

---

## Example session flow

### 1. Connect

```
→ WS OPEN /ws/DEMO?name=Alex
← { "type": "init", "self": { … }, "peers": [], "replica": "render-1", "tick_ms": 50, "default_tick_ms": 50 }
```

(Server publishes `peer_joined` to Redis; peers receive it on the next tick.)

### 2. Move cursor

```
→ { "type": "cursor", "p": [0.3, 0.4], "v": [0.1, 0.0], "t": 100.0 }
```

(On next tick, other clients in the room receive:)

```
← { "type": "cursors", "updates": [{ "user_id": "u_…", "p": [0.3, 0.4], "v": [0.1, 0.0], "t": 100.0, … }] }
```

### 3. Draw a stroke

```
→ { "type": "draw", "seq": 1, "pts": [[0.2, 0.3], [0.25, 0.35]] }
→ { "type": "draw_end", "seq": 1 }
```

Peers receive (same tick or adjacent ticks):

```
← { "type": "draw", "user_id": "u_…", "seq": 1, "pts": [[…], […]] }
← { "type": "draw_end", "user_id": "u_…", "seq": 1 }
```

### 4. Disconnect

```
→ WS CLOSE
```

Peers receive:

```
← { "type": "peer_left", "user_id": "u_…" }
```

---

## Environment variables (operators)

| Variable | Default | Purpose |
|----------|---------|---------|
| `REDIS_URL` | `redis://localhost:6379` | Redis pub/sub backplane (**required in production**) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins for HTTP CORS |
| `REPLICA_ID` | `local` | Shown to clients in `init.replica` |
| `TICK_MS` | *(not env-backed today)* | Boot tick is **50 ms**; runtime override via `set_tick_ms` |

See [DEPLOY.md](DEPLOY.md) for Render + Vercel setup.

---

## What this API deliberately excludes

| Feature | Status |
|---------|--------|
| Authentication / accounts | Not implemented — guest identity only |
| Persistence | No database; state is ephemeral |
| Rate limiting | Not implemented |
| Cursor chat | Not implemented |
| Infinite canvas / pan-zoom | Not implemented — fixed `[0,1]` board |
| Redis-side batching | Not implemented — only socket flush batching |

---

## Related docs

| Document | Contents |
|----------|----------|
| [README.md](README.md) | Runbook, performance numbers, local Docker |
| [DEPLOY.md](DEPLOY.md) | Render + Vercel deploy steps |
| [AGENTS.md](AGENTS.md) | Codebase map and implementation invariants |
