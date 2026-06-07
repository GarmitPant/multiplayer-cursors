/** Framework-agnostic cursor engine (emitter + receiver reconstruction). */

export const CONFIG = {
  EPS_POS: 0.005,
  VEL_SMOOTH: 0.5,
  KEYFRAME_MS: 1500,
  IDLE_MS: 40,
  CLAMP_GRACE_MS: 60,
  CLAMP_ZERO_MS: 300,
  PRESENCE_TIMEOUT_MS: 5000,
  SMOOTH_TIME: 0.08,
  EPS_RDP: 0.003,
  DRAW_WINDOW: 16,
  ONE_EURO_MINCUTOFF: 1.0,
  ONE_EURO_BETA: 0.007,
  TRAIL_TTL_MS: 3000,
  DCUTOFF: 1.0,
};

export function predictPosition(p0, v0, t0, t) {
  const dt = t - t0;
  return [p0[0] + v0[0] * dt, p0[1] + v0[1] * dt];
}

export function distance(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function shouldEmitDelta(belief, pReal, t, epsPos) {
  if (!belief) return true;
  const pPred = predictPosition(belief.p, belief.v, belief.t, t);
  return distance(pReal, pPred) > epsPos;
}

export function smoothVelocity(prevV, rawV, alpha) {
  if (prevV === null) return rawV;
  return [
    alpha * rawV[0] + (1 - alpha) * prevV[0],
    alpha * rawV[1] + (1 - alpha) * prevV[1],
  ];
}

export function smoothDamp(current, target, vel, smoothTime, dt) {
  const omega = 2 / smoothTime;
  const x = omega * dt;
  const exp = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = current - target;
  const temp = (vel + omega * change) * dt;
  const newVel = (vel - omega * temp) * exp;
  return [target + (change + temp) * exp, newVel];
}

export function decayVelocity(v, silenceMs, graceMs, zeroMs) {
  if (silenceMs <= graceMs) return v;
  if (silenceMs >= zeroMs) return [0, 0];
  const k = 1 - (silenceMs - graceMs) / (zeroMs - graceMs);
  return [v[0] * k, v[1] * k];
}

export class Emitter {
  constructor(config = CONFIG) {
    this.config = config;
    this.belief = null;
    this.prevP = null;
    this.prevT = null;
    this.vSmooth = null;
  }

  reset() {
    this.belief = null;
    this.prevP = null;
    this.prevT = null;
    this.vSmooth = null;
  }

  sample(p, t, forceEmit = false) {
    let rawV = [0, 0];
    if (this.prevP !== null && this.prevT !== null) {
      const dt = t - this.prevT;
      if (dt > 0) rawV = [(p[0] - this.prevP[0]) / dt, (p[1] - this.prevP[1]) / dt];
    }
    const vNew = smoothVelocity(this.vSmooth, rawV, this.config.VEL_SMOOTH);
    this.vSmooth = vNew;
    this.prevP = [p[0], p[1]];
    this.prevT = t;

    if (forceEmit || shouldEmitDelta(this.belief, p, t, this.config.EPS_POS)) {
      const msg = { type: "cursor", p: [p[0], p[1]], v: [vNew[0], vNew[1]], t };
      this.belief = { p: [p[0], p[1]], v: [vNew[0], vNew[1]], t };
      return msg;
    }
    return null;
  }

  keyframe(p, t, name, color, v) {
    const vel = v !== undefined ? v : (this.vSmooth || [0, 0]);
    const msg = {
      type: "cursor",
      p: [p[0], p[1]],
      v: [vel[0], vel[1]],
      t,
      kf: true,
      name,
      color: color || "#333",
    };
    this.belief = { p: [p[0], p[1]], v: [vel[0], vel[1]], t };
    return msg;
  }

  stop(p, t) {
    const msg = { type: "cursor", p: [p[0], p[1]], v: [0, 0], t };
    this.belief = { p: [p[0], p[1]], v: [0, 0], t };
    return msg;
  }
}

export class PeerReceiver {
  constructor(config = CONFIG) {
    this.config = config;
    this.pLast = null;
    this.vLast = null;
    this.tRecvLocal = null;
    this.pRender = null;
    this.vRender = [0, 0];
    this.lastMsgMs = null;
  }

  applyUpdate(msg, nowMs) {
    const tRecv = nowMs / 1000;
    if (this.pLast === null) {
      this.pLast = [msg.p[0], msg.p[1]];
      this.vLast = [msg.v[0], msg.v[1]];
      this.tRecvLocal = tRecv;
      this.pRender = [msg.p[0], msg.p[1]];
      this.vRender = [0, 0];
      this.lastMsgMs = nowMs;
    } else {
      this.pLast = [msg.p[0], msg.p[1]];
      this.vLast = [msg.v[0], msg.v[1]];
      this.tRecvLocal = tRecv;
      this.lastMsgMs = nowMs;
    }
  }

  touch(nowMs) {
    if (this.lastMsgMs !== null) this.lastMsgMs = nowMs;
  }

  step(nowMs, dtSec) {
    if (this.pLast === null) return undefined;
    const silenceMs = nowMs - this.lastMsgMs;
    if (silenceMs > this.config.PRESENCE_TIMEOUT_MS) return null;

    const nowSec = nowMs / 1000;
    const vEff = decayVelocity(
      this.vLast, silenceMs, this.config.CLAMP_GRACE_MS, this.config.CLAMP_ZERO_MS);
    const target = predictPosition(this.pLast, vEff, this.tRecvLocal, nowSec);
    const [rx, nvx] = smoothDamp(
      this.pRender[0], target[0], this.vRender[0], this.config.SMOOTH_TIME, dtSec);
    const [ry, nvy] = smoothDamp(
      this.pRender[1], target[1], this.vRender[1], this.config.SMOOTH_TIME, dtSec);
    this.pRender = [rx, ry];
    this.vRender = [nvx, nvy];
    return { x: this.pRender[0], y: this.pRender[1] };
  }
}

// ── draw trail engine (M4) ────────────────────────────────────────────────────

const PI = Math.PI;

function lowpass(x, prev, a) {
  return a * x + (1 - a) * prev;
}

function euroAlpha(cutoff, dt) {
  return 1 / (1 + (1 / (2 * PI * cutoff)) / dt);
}

export class OneEuro {
  constructor(mincutoff, beta, dcutoff = CONFIG.DCUTOFF) {
    this.mincutoff = mincutoff;
    this.beta = beta;
    this.dcutoff = dcutoff;
    this.xPrev = null;
    this.dxPrev = 0;
    this.tPrev = null;
  }

  reset() {
    this.xPrev = null;
    this.dxPrev = 0;
    this.tPrev = null;
  }

  filter(x, t) {
    if (this.xPrev === null) {
      this.xPrev = x;
      this.dxPrev = 0;
      this.tPrev = t;
      return x;
    }
    const dt = Math.max(1e-6, t - this.tPrev);
    const dx = (x - this.xPrev) / dt;
    const aD = euroAlpha(this.dcutoff, dt);
    const edx = lowpass(dx, this.dxPrev, aD);
    const cutoff = this.mincutoff + this.beta * Math.abs(edx);
    const aX = euroAlpha(cutoff, dt);
    const xFilt = lowpass(x, this.xPrev, aX);
    this.xPrev = xFilt;
    this.dxPrev = edx;
    this.tPrev = t;
    return xFilt;
  }
}

function perpDistance(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  if (dx === 0 && dy === 0) return distance(p, a);
  const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy);
  const px = a[0] + t * dx;
  const py = a[1] + t * dy;
  return distance(p, [px, py]);
}

export function rdp(points, eps) {
  if (points.length <= 2) return points.map(p => [p[0], p[1]]);
  const first = points[0];
  const last = points[points.length - 1];
  let maxDist = 0;
  let index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const d = perpDistance(points[i], first, last);
    if (d > maxDist) {
      maxDist = d;
      index = i;
    }
  }
  if (maxDist > eps) {
    const left = rdp(points.slice(0, index + 1), eps);
    const right = rdp(points.slice(index), eps);
    return left.slice(0, -1).concat(right);
  }
  return [[first[0], first[1]], [last[0], last[1]]];
}

function crPoint(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return [
    0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
      + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
      + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
    0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
      + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
      + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
  ];
}

export function catmullRom(controlPts, segs = 8) {
  if (controlPts.length === 0) return [];
  if (controlPts.length === 1) return [[controlPts[0][0], controlPts[0][1]]];
  const pts = controlPts.map(p => [p[0], p[1]]);
  const n = pts.length;
  const get = (i) => {
    if (i < 0) return pts[0];
    if (i >= n) return pts[n - 1];
    return pts[i];
  };
  const out = [];
  for (let i = 0; i < n - 1; i++) {
    const p0 = get(i - 1);
    const p1 = get(i);
    const p2 = get(i + 1);
    const p3 = get(i + 2);
    const lastSeg = i === n - 2;
    const limit = lastSeg ? segs : segs - 1;
    for (let s = 0; s <= limit; s++) {
      out.push(crPoint(p0, p1, p2, p3, s / segs));
    }
  }
  return out;
}

export class StrokeSimplifier {
  constructor(anchor, eps, windowSize) {
    this.eps = eps;
    this.windowSize = windowSize;
    this.anchor = [anchor[0], anchor[1]];
    this.buffer = [[anchor[0], anchor[1]]];
  }

  strokeOrigin() {
    return [[this.anchor[0], this.anchor[1]]];
  }

  push(point) {
    this.buffer.push([point[0], point[1]]);
    if (this.buffer.length >= this.windowSize) return this._emitWindow();
    return [];
  }

  _emitWindow() {
    const simplified = rdp(this.buffer, this.eps);
    const toEmit = simplified.length > 1 ? simplified.slice(1) : [];
    const lastRaw = this.buffer[this.buffer.length - 1];
    this.anchor = [lastRaw[0], lastRaw[1]];
    this.buffer = [[this.anchor[0], this.anchor[1]]];
    return toEmit;
  }

  flush() {
    if (this.buffer.length <= 1) return [];
    const simplified = rdp(this.buffer, this.eps);
    const toEmit = simplified.length > 1 ? simplified.slice(1) : [];
    this.buffer = [[this.anchor[0], this.anchor[1]]];
    return toEmit;
  }
}

export class TrailStore {
  constructor(config = CONFIG) {
    this.config = config;
    this.strokes = new Map();
  }

  _key(userId, seq) {
    return `${userId}:${seq}`;
  }

  append(userId, seq, pts, color, nowMs) {
    if (!pts.length) return;
    const key = this._key(userId, seq);
    if (!this.strokes.has(key)) {
      this.strokes.set(key, { color: color || "#333", points: [], ended: false });
    }
    const stroke = this.strokes.get(key);
    if (color) stroke.color = color;
    for (const pt of pts) {
      stroke.points.push({ x: pt[0], y: pt[1], born: nowMs });
    }
  }

  markEnd(userId, seq) {
    const stroke = this.strokes.get(this._key(userId, seq));
    if (stroke) stroke.ended = true;
  }

  removeUser(userId) {
    for (const key of [...this.strokes.keys()]) {
      if (key.startsWith(`${userId}:`)) this.strokes.delete(key);
    }
  }

  renderable(nowMs) {
    const ttl = this.config.TRAIL_TTL_MS;
    const result = [];
    const toDelete = [];
    for (const [key, stroke] of this.strokes.entries()) {
      stroke.points = stroke.points.filter(p => (nowMs - p.born) <= ttl);
      if (stroke.points.length === 0) {
        if (stroke.ended) toDelete.push(key);
        continue;
      }
      result.push({
        color: stroke.color,
        controlPts: stroke.points.map(p => [p.x, p.y]),
        alphas: stroke.points.map(p => 1 - (nowMs - p.born) / ttl),
      });
    }
    for (const key of toDelete) this.strokes.delete(key);
    return result;
  }
}
