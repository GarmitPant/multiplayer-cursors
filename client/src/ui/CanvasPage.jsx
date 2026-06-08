import { useEffect, useRef, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import {
  CONFIG, Emitter, PeerReceiver, OneEuro, StrokeSimplifier, TrailStore, catmullRom,
} from '../cursorEngine.js';
import { buildWsUrl, connectWithBackoff } from '../net/connection.js';
import { fit, toScreen, toLogical } from '../coords/viewport.js';
import { canvasIdFromParam } from '../lib/canvasCode.js';
import { mergePresenceRecord } from '../lib/presence.js';
import { applyFigmaCursorIdentity, createFigmaCursorElement } from '../lib/figmaCursor.js';
import AvatarStack from './AvatarStack.jsx';
import '../App.css';
import './CanvasPage.css';

const GRID_PITCH_PX = 24;
const NAME_KEY = 'cursor-display-name';

function identityStorageKey(roomId) {
  return `cursor-identity:${roomId}`;
}

function loadPersistedIdentity(roomId) {
  try {
    const raw = sessionStorage.getItem(identityStorageKey(roomId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function persistIdentity(roomId, identity) {
  sessionStorage.setItem(identityStorageKey(roomId), JSON.stringify({
    user_id: identity.user_id,
    name: identity.name,
    color: identity.color,
  }));
}

function SharePanel({ canvasId }) {
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}/canvas/${canvasId}`;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="share-panel">
      <span className="share-label">Canvas</span>
      <code className="share-code">{canvasId}</code>
      <button type="button" className="share-copy" onClick={copyLink}>
        {copied ? 'Copied!' : 'Copy link'}
      </button>
    </div>
  );
}

function NameGate({ onSubmit }) {
  const [name, setName] = useState(sessionStorage.getItem(NAME_KEY) || '');

  function submit(ev) {
    ev.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    sessionStorage.setItem(NAME_KEY, trimmed);
    onSubmit(trimmed);
  }

  return (
    <div className="name-gate">
      <form className="name-gate-card" onSubmit={submit}>
        <h2>Join this Canvas</h2>
        <p>Enter your name to connect with others on this board.</p>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          autoFocus
          maxLength={40}
        />
        <button type="submit">Continue</button>
      </form>
    </div>
  );
}

export default function CanvasPage() {
  const { code: rawCode } = useParams();
  const location = useLocation();
  const canvasId = canvasIdFromParam(rawCode);

  const canvasRef = useRef(null);
  const cursorsRef = useRef(null);
  const [hudText, setHudText] = useState('');
  const [displayName, setDisplayName] = useState(() => {
    return location.state?.name || sessionStorage.getItem(NAME_KEY) || '';
  });
  const [active, setActive] = useState(() => {
    return !!(location.state?.name || sessionStorage.getItem(NAME_KEY));
  });
  const [presence, setPresence] = useState([]);
  const [connStatus, setConnStatus] = useState('connecting');
  const setPresenceRef = useRef(setPresence);
  setPresenceRef.current = setPresence;
  const setConnStatusRef = useRef(setConnStatus);
  setConnStatusRef.current = setConnStatus;

  useEffect(() => {
    if (!active || !displayName) return undefined;

    const canvas = canvasRef.current;
    const cursorsRoot = cursorsRef.current;
    const ctx = canvas.getContext('2d');
    let dpr = window.devicePixelRatio || 1;

    const peers = {};
    const trailStore = new TrailStore();
    let me = null;
    let myColor = null;
    let ws = null;
    let rafId = 0;
    let lastFrameMs = performance.now();

    const emitter = new Emitter();
    let pointerInside = true;
    let lastMoveMs = 0;
    let stopped = true;
    let strokeSeq = 0;
    let dragging = false;
    let simplifier = null;
    let euroX = null;
    let euroY = null;
    let board = fit(innerWidth, innerHeight);
    const presenceById = new Map();

    function syncPresenceState() {
      const list = Array.from(presenceById.values()).sort((a, b) => (
        a.user_id.localeCompare(b.user_id)
      ));
      setPresenceRef.current(list);
    }

    function upsertPresence(user) {
      if (!user?.user_id) return;
      const prev = presenceById.get(user.user_id);
      presenceById.set(user.user_id, mergePresenceRecord(prev, user));
      syncPresenceState();
    }

    function removePresence(userId) {
      if (!presenceById.delete(userId)) return;
      syncPresenceState();
    }

    function resizeCanvas() {
      dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(innerWidth * dpr);
      canvas.height = Math.floor(innerHeight * dpr);
      canvas.style.width = `${innerWidth}px`;
      canvas.style.height = `${innerHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      board = fit(innerWidth, innerHeight);
    }

    function ensurePeer(uid, color, nm) {
      let p = peers[uid];
      if (!p) {
        const cursorParts = createFigmaCursorElement(color, nm);
        cursorsRoot.appendChild(cursorParts.el);
        p = peers[uid] = {
          el: cursorParts.el,
          cursorParts,
          receiver: null,
          color: color || '#333',
          name: nm || '',
        };
      }
      applyPeerIdentity(uid, color, nm);
      return p;
    }

    function applyPeerIdentity(uid, color, nm) {
      const p = peers[uid];
      if (!p) return;
      if (color) p.color = color;
      if (nm) p.name = nm;
      applyFigmaCursorIdentity(p.cursorParts, color || p.color, nm || p.name);
    }

    function peerColor(uid) {
      return peers[uid]?.color || '#333';
    }

    function movePeer(uid, x, y) {
      const p = peers[uid];
      if (!p) return;
      const [sx, sy] = toScreen([x, y], board);
      p.el.style.transform = `translate(${sx}px, ${sy}px)`;
    }

    function hidePeerCursor(uid) {
      trailStore.removeUser(uid);
      if (peers[uid]) {
        peers[uid].el.remove();
        delete peers[uid];
      }
    }

    function dropPeer(uid) {
      hidePeerCursor(uid);
      removePresence(uid);
    }

    function touchPeer(uid) {
      const p = peers[uid];
      if (p?.receiver) p.receiver.touch(performance.now());
    }

    function onPeerCursor(uid, m) {
      ensurePeer(uid, m.color, m.name);
      upsertPresence({ user_id: uid, name: m.name, color: m.color });
      if (m.kf || m.name || m.color) applyPeerIdentity(uid, m.color, m.name);
      const p = peers[uid];
      if (!p.receiver) p.receiver = new PeerReceiver();
      p.receiver.applyUpdate(m, performance.now());
    }

    function drawBoard(f) {
      const w = innerWidth;
      const h = innerHeight;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#fafafa';
      ctx.fillRect(f.ox, f.oy, f.bw, f.bh);
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.06)';
      ctx.lineWidth = 1;
      for (let x = f.ox; x <= f.ox + f.bw; x += GRID_PITCH_PX) {
        ctx.beginPath();
        ctx.moveTo(x, f.oy);
        ctx.lineTo(x, f.oy + f.bh);
        ctx.stroke();
      }
      for (let y = f.oy; y <= f.oy + f.bh; y += GRID_PITCH_PX) {
        ctx.beginPath();
        ctx.moveTo(f.ox, y);
        ctx.lineTo(f.ox + f.bw, y);
        ctx.stroke();
      }
    }

    function drawTrails(nowMs) {
      drawBoard(board);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.lineWidth = 2.5;
      for (const stroke of trailStore.renderable(nowMs)) {
        const pts = stroke.controlPts;
        if (pts.length === 0) continue;
        if (pts.length === 1) {
          const [sx, sy] = toScreen(pts[0], board);
          ctx.globalAlpha = Math.max(0, stroke.alphas[0]);
          ctx.fillStyle = stroke.color;
          ctx.beginPath();
          ctx.arc(sx, sy, 2, 0, Math.PI * 2);
          ctx.fill();
          continue;
        }
        const dense = catmullRom(pts, 8);
        ctx.strokeStyle = stroke.color;
        for (let i = 0; i < dense.length - 1; i++) {
          const ci = Math.min(Math.floor(i / 8), stroke.alphas.length - 1);
          ctx.globalAlpha = Math.max(0, stroke.alphas[ci]);
          const [x0, y0] = toScreen(dense[i], board);
          const [x1, y1] = toScreen(dense[i + 1], board);
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    function send(msg) {
      if (msg && ws?.readyState === 1) ws.send(JSON.stringify(msg));
    }

    function sendPresenceKeyframe() {
      if (!ws || ws.readyState !== 1 || me === null) return;
      const t = performance.now() / 1000;
      const p = emitter.prevP || [0.5, 0.5];
      const v = stopped ? [0, 0] : (emitter.vSmooth || [0, 0]);
      send(emitter.keyframe(p, t, displayName, myColor || '#333', v));
    }

    function normPos(ev) {
      return toLogical([ev.clientX, ev.clientY], board);
    }

    function emitDrawPts(seq, pts) {
      if (!pts.length || me === null) return;
      send({ type: 'draw', seq, pts });
      trailStore.append(me, seq, pts, myColor || '#333', performance.now());
    }

    function reconstructionTick() {
      const nowMs = performance.now();
      const dtSec = Math.max(0, (nowMs - lastFrameMs) / 1000);
      lastFrameMs = nowMs;

      for (const uid of Object.keys(peers)) {
        const p = peers[uid];
        if (!p.receiver) continue;
        const pos = p.receiver.step(nowMs, dtSec);
        if (pos === null) {
          hidePeerCursor(uid);
          continue;
        }
        if (pos !== undefined) movePeer(uid, pos.x, pos.y);
      }
      drawTrails(nowMs);
      rafId = requestAnimationFrame(reconstructionTick);
    }

    function onWsMessage(e) {
      let m;
      try {
        m = JSON.parse(e.data);
      } catch {
        console.warn('dropping non-JSON ws frame');
        return;
      }
      if (m.type === 'init') {
        me = m.self.user_id;
        myColor = m.self.color;
        persistIdentity(canvasId, m.self);
        setHudText(`Canvas: ${canvasId} | name: ${m.self.name} | served by: ${m.replica}`);
        upsertPresence(m.self);
        (m.peers || []).forEach((p) => upsertPresence(p));
        (m.peers || []).forEach((p) => ensurePeer(p.user_id, p.color, p.name));
        sendPresenceKeyframe();
      } else if (m.type === 'peer_joined') {
        upsertPresence({ user_id: m.user_id, name: m.name, color: m.color });
        if (me !== null && m.user_id !== me) {
          ensurePeer(m.user_id, m.color, m.name);
          touchPeer(m.user_id);
        }
      } else if (m.type === 'peer_left') {
        dropPeer(m.user_id);
      } else if (m.type === 'cursor') {
        if (m.user_id && m.user_id !== me && m.p) onPeerCursor(m.user_id, m);
      } else if (m.type === 'cursors') {
        for (const u of m.updates) {
          if (u.user_id) {
            upsertPresence({ user_id: u.user_id, name: u.name, color: u.color });
          }
          if (u.user_id && u.user_id !== me && u.p) onPeerCursor(u.user_id, u);
        }
      } else if (m.type === 'draw') {
        if (m.user_id && m.user_id !== me && m.pts) {
          ensurePeer(m.user_id);
          const p = peers[m.user_id];
          upsertPresence({ user_id: m.user_id, name: p?.name, color: p?.color });
          trailStore.append(m.user_id, m.seq, m.pts, peerColor(m.user_id), performance.now());
        }
      } else if (m.type === 'draw_end') {
        if (m.user_id && m.user_id !== me) trailStore.markEnd(m.user_id, m.seq);
      }
    }

    setHudText(`Canvas: ${canvasId} | name: ${displayName}`);

    const disconnect = connectWithBackoff(() => {
      const id = loadPersistedIdentity(canvasId);
      return buildWsUrl(canvasId, displayName, id);
    }, {
      onConnecting: () => setConnStatusRef.current('connecting'),
      onOpen: (socket) => {
        ws = socket;
        setConnStatusRef.current('connected');
      },
      onMessage: onWsMessage,
      onClose: () => { ws = null; },
      onDegraded: () => setConnStatusRef.current('degraded'),
    });

    const keyframeTimer = setInterval(() => {
      if (ws?.readyState !== 1 || emitter.prevP === null) return;
      const t = performance.now() / 1000;
      const v = stopped ? [0, 0] : (emitter.vSmooth || [0, 0]);
      send(emitter.keyframe(emitter.prevP, t, displayName, myColor || '#333', v));
    }, CONFIG.KEYFRAME_MS);

    const idleTimer = setInterval(() => {
      if (stopped || emitter.prevP === null || ws?.readyState !== 1) return;
      if (performance.now() - lastMoveMs > CONFIG.IDLE_MS) {
        stopped = true;
        send(emitter.stop(emitter.prevP, performance.now() / 1000));
      }
    }, 50);

    function onMouseMove(ev) {
      if (!pointerInside) pointerInside = true;
      stopped = false;
      lastMoveMs = performance.now();
      const t = performance.now() / 1000;
      const p = normPos(ev);
      send(emitter.sample(p, t, emitter.belief === null));
    }

    function onMouseLeave() {
      pointerInside = false;
      stopped = true;
      if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'cursor_leave' }));
      emitter.reset();
    }

    function onMouseEnter() {
      pointerInside = true;
      emitter.reset();
      stopped = true;
    }

    function onPointerDown(ev) {
      if (ev.button !== 0) return;
      dragging = true;
      strokeSeq += 1;
      const t = performance.now() / 1000;
      const raw = normPos(ev);
      euroX = new OneEuro(CONFIG.ONE_EURO_MINCUTOFF, CONFIG.ONE_EURO_BETA);
      euroY = new OneEuro(CONFIG.ONE_EURO_MINCUTOFF, CONFIG.ONE_EURO_BETA);
      euroX.filter(raw[0], t);
      euroY.filter(raw[1], t);
      simplifier = new StrokeSimplifier(raw, CONFIG.EPS_RDP, CONFIG.DRAW_WINDOW);
      emitDrawPts(strokeSeq, simplifier.strokeOrigin());
    }

    function onPointerMove(ev) {
      if (!dragging || !simplifier) return;
      const coalesced = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
      let t = performance.now() / 1000;
      for (const evc of coalesced) {
        const raw = toLogical([evc.clientX, evc.clientY], board);
        const x = euroX.filter(raw[0], t);
        const y = euroY.filter(raw[1], t);
        t += 0.0005;
        const emitted = simplifier.push([x, y]);
        if (emitted.length) emitDrawPts(strokeSeq, emitted);
      }
    }

    function onPointerUp() {
      if (!dragging) return;
      dragging = false;
      if (simplifier) {
        const rest = simplifier.flush();
        if (rest.length) emitDrawPts(strokeSeq, rest);
      }
      send({ type: 'draw_end', seq: strokeSeq });
      simplifier = null;
      euroX = null;
      euroY = null;
    }

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseleave', onMouseLeave);
    window.addEventListener('mouseenter', onMouseEnter);
    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    rafId = requestAnimationFrame(reconstructionTick);

    return () => {
      cancelAnimationFrame(rafId);
      clearInterval(keyframeTimer);
      clearInterval(idleTimer);
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseleave', onMouseLeave);
      window.removeEventListener('mouseenter', onMouseEnter);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      disconnect();
      Object.keys(peers).forEach(dropPeer);
      presenceById.clear();
      setPresenceRef.current([]);
      setConnStatusRef.current('connecting');
    };
  }, [canvasId, displayName, active]);

  function handleNameSubmit(name) {
    sessionStorage.setItem(NAME_KEY, name);
    setDisplayName(name);
    setActive(true);
  }

  return (
    <div className="app">
      {!active ? <NameGate onSubmit={handleNameSubmit} /> : null}
      <canvas ref={canvasRef} className="trail" />
      <div ref={cursorsRef} className="cursors" />
      <AvatarStack users={presence} />
      {active && connStatus === 'connecting' ? (
        <div className="connecting-banner" role="status" aria-live="polite">
          Connecting…
        </div>
      ) : null}
      {active && connStatus === 'degraded' ? (
        <div className="connecting-banner connecting-banner--degraded" role="alert" aria-live="polite">
          Can&apos;t connect — retrying…
        </div>
      ) : null}
      <div className="canvas-chrome-left">
        <div className="hud">{hudText}</div>
        <SharePanel canvasId={canvasId} />
      </div>
    </div>
  );
}
