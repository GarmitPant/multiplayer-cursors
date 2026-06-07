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
  TRAIL_TTL_MS: 800,
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
