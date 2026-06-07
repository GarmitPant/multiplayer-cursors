// src/net/connection.js
const WS_BASE = import.meta.env.VITE_WS_URL?.length
  ? import.meta.env.VITE_WS_URL                                              // prod: wss://<render-app>.onrender.com
  : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;   // local: same-origin via nginx

export function buildWsUrl(canvasId, name) {
  return `${WS_BASE}/ws/${canvasId}?name=${encodeURIComponent(name)}`;
}

/** Minimal reconnect-with-backoff wrapper (connection layer, not the engine). */
export function connectWithBackoff(url, { onMessage, onOpen, onClose }) {
  let ws = null;
  let backoffMs = 500;
  let reconnectTimer = null;
  let closed = false;

  function connect() {
    ws = new WebSocket(url);
    ws.onopen = () => {
      backoffMs = 500;
      onOpen?.(ws);
    };
    ws.onmessage = onMessage;
    ws.onclose = () => {
      onClose?.();
      if (closed) return;
      reconnectTimer = setTimeout(connect, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 10_000);
    };
  }

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
