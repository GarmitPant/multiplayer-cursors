// src/coords/viewport.js — the ONLY seam between logical [0,1] and screen pixels.
export const BOARD_ASPECT = 16 / 9;   // documented constant

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

// Letterbox a fixed-aspect board into the viewport (vw, vh).
export function fit(vw, vh, aspect = BOARD_ASPECT) {
  const vAspect = vw / vh;
  let bw, bh;
  if (vAspect > aspect) { bh = vh; bw = vh * aspect; }   // limited by height (viewport wider than board)
  else                  { bw = vw; bh = vw / aspect; }   // limited by width  (viewport taller than board)
  return { bw, bh, ox: (vw - bw) / 2, oy: (vh - bh) / 2 };  // centered ⇒ equal margins
}

// logical [0,1] → screen px
export function toScreen(l, f) {
  return [f.ox + l[0] * f.bw, f.oy + l[1] * f.bh];
}

// screen px → logical [0,1] (capture); clamps so margin points map into the board
export function toLogical(s, f) {
  return [clamp01((s[0] - f.ox) / f.bw), clamp01((s[1] - f.oy) / f.bh)];
}
