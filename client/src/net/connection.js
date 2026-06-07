// src/net/connection.js
const WS_BASE = import.meta.env.VITE_WS_URL?.length
  ? import.meta.env.VITE_WS_URL                                              // prod: wss://<render-app>.onrender.com
  : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;   // local: same-origin via nginx

export function buildWsUrl(canvasId, name, identity = null) {
  const params = new URLSearchParams();
  params.set('name', name);
  if (identity?.user_id) params.set('user_id', identity.user_id);
  if (identity?.color) params.set('color', identity.color);
  return `${WS_BASE}/ws/${canvasId}?${params.toString()}`;
}

/** Reconnect-with-backoff wrapper (connection layer, not the engine). */
export function connectWithBackoff(urlOrFn, { onMessage, onOpen, onClose }) {
  let ws = null;
  let backoffMs = 500;
  let reconnectTimer = null;
  let closed = false;

  const resolveUrl = () => (typeof urlOrFn === 'function' ? urlOrFn() : urlOrFn);

  function scheduleReconnect() {
    const jitter = backoffMs * (0.5 + Math.random() * 0.5);
    reconnectTimer = setTimeout(connect, jitter);
    backoffMs = Math.min(backoffMs * 2, 10_000);
  }

  function connect() {
    ws = new WebSocket(resolveUrl());
    ws.onopen = () => {
      backoffMs = 500;
      onOpen?.(ws);
    };
    ws.onmessage = onMessage;
    ws.onclose = () => {
      onClose?.();
      if (closed) return;
      scheduleReconnect();
    };
  }

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
