const CHARSET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

export function generateCanvasCode(length = 6) {
  const chars = [];
  const rand = new Uint32Array(length);
  crypto.getRandomValues(rand);
  for (let i = 0; i < length; i += 1) {
    chars.push(CHARSET[rand[i] % CHARSET.length]);
  }
  return chars.join('');
}

export function normalizeCanvasCode(raw) {
  return (raw || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
}

export function canvasIdFromParam(param) {
  const normalized = normalizeCanvasCode(param);
  return normalized || (param || '').trim() || 'canvas';
}
