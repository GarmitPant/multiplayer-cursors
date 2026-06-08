import { useEffect, useRef, useState } from 'react';
import { DEFAULT_EPS_POS } from '../dev/inspectorDefaults.js';
import './InspectorOverlay.css';

const EPS_MIN = 0.001;
const EPS_MAX = 0.05;
const TICK_MIN = 1;
const TICK_MAX = 500;
const TICK_DEBOUNCE_MS = 300;

export default function InspectorOverlay({
  metricsRef,
  getPeerCountRef,
  emitterConfigRef,
  onSetTickMs,
  defaultTickMs,
  syncTickFromServerRef,
}) {
  const [open, setOpen] = useState(false);
  const [display, setDisplay] = useState({
    sent: 0,
    recvMsgs: 0,
    recvPos: 0,
    peers: 0,
  });
  const [epsPos, setEpsPos] = useState(emitterConfigRef.current.EPS_POS);
  const [tickMs, setTickMs] = useState(defaultTickMs ?? 50);
  const tickDebounceRef = useRef(null);

  useEffect(() => {
    syncTickFromServerRef.current = (value) => {
      if (tickDebounceRef.current) clearTimeout(tickDebounceRef.current);
      setTickMs(value);
    };
    return () => {
      syncTickFromServerRef.current = null;
    };
  }, [syncTickFromServerRef]);

  useEffect(() => {
    function onKey(ev) {
      if (ev.key !== 'i' || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.target instanceof HTMLInputElement || ev.target instanceof HTMLTextAreaElement) {
        return;
      }
      ev.preventDefault();
      setOpen((v) => !v);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      const m = metricsRef.current;
      setDisplay({
        sent: m.sent,
        recvMsgs: m.recvMsgs,
        recvPos: m.recvPos,
        peers: getPeerCountRef.current(),
      });
      m.resetWindow();
    }, 1000);
    return () => clearInterval(id);
  }, [metricsRef, getPeerCountRef]);

  useEffect(() => () => {
    if (tickDebounceRef.current) clearTimeout(tickDebounceRef.current);
  }, []);

  function applyTickMs(value, immediate = false) {
    setTickMs(value);
    if (tickDebounceRef.current) clearTimeout(tickDebounceRef.current);
    if (immediate) {
      onSetTickMs(value);
      return;
    }
    tickDebounceRef.current = setTimeout(() => onSetTickMs(value), TICK_DEBOUNCE_MS);
  }

  function onEpsChange(ev) {
    const v = parseFloat(ev.target.value);
    emitterConfigRef.current.EPS_POS = v;
    setEpsPos(v);
  }

  function onTickChange(ev) {
    applyTickMs(parseInt(ev.target.value, 10));
  }

  function resetEps() {
    emitterConfigRef.current.EPS_POS = DEFAULT_EPS_POS;
    setEpsPos(DEFAULT_EPS_POS);
  }

  function resetTick() {
    if (defaultTickMs == null) return;
    applyTickMs(defaultTickMs, true);
  }

  function resetAll() {
    resetEps();
    resetTick();
  }

  const tickDefaultLabel = defaultTickMs != null ? `${defaultTickMs} ms` : '…';

  return (
    <div className={`inspector-root${open ? ' inspector-root--open' : ''}`}>
      <button
        type="button"
        className="inspector-toggle"
        onClick={() => setOpen((v) => !v)}
        title="Toggle inspector (i)"
        aria-expanded={open}
      >
        {open ? '×' : 'i'}
      </button>
      {open ? (
        <div className="inspector-panel">
          <div className="inspector-title">Inspector</div>
          <dl className="inspector-metrics">
            <div>
              <dt>sent/s</dt>
              <dd>{display.sent}</dd>
            </div>
            <div>
              <dt>recv msgs/s</dt>
              <dd>{display.recvMsgs}</dd>
            </div>
            <div>
              <dt>recv positions/s</dt>
              <dd>{display.recvPos}</dd>
            </div>
            <div>
              <dt>active peers</dt>
              <dd>{display.peers}</dd>
            </div>
          </dl>
          <div className="inspector-slider">
            <div className="inspector-slider-header">
              <span className="inspector-slider-label">
                Send threshold (your cursor → others)
              </span>
              <button
                type="button"
                className="inspector-reset"
                onClick={resetEps}
                title={`Reset to default (${DEFAULT_EPS_POS})`}
                aria-label="Reset send threshold to default"
              >
                ↺
              </button>
            </div>
            <input
              type="range"
              min={EPS_MIN}
              max={EPS_MAX}
              step={0.001}
              value={epsPos}
              onChange={onEpsChange}
            />
            <span className="inspector-slider-value">
              {epsPos.toFixed(3)} (default {DEFAULT_EPS_POS.toFixed(3)})
            </span>
            <span className="inspector-note">
              Higher = sparser sends — your cursor looks choppier on other tabs, not here.
            </span>
          </div>
          <div className="inspector-slider">
            <div className="inspector-slider-header">
              <span className="inspector-slider-label">
                Server tick (GLOBAL — affects all users)
              </span>
              <button
                type="button"
                className="inspector-reset"
                onClick={resetTick}
                disabled={defaultTickMs == null}
                title={`Reset to default (${tickDefaultLabel}) — global flush interval`}
                aria-label="Reset server tick to default"
              >
                ↺
              </button>
            </div>
            <input
              type="range"
              min={TICK_MIN}
              max={TICK_MAX}
              step={1}
              value={tickMs}
              onChange={onTickChange}
            />
            <span className="inspector-slider-value">
              {tickMs} ms (default {tickDefaultLabel})
            </span>
            <span className="inspector-note">
              Server-wide flush interval (1 ms = extreme demo, disables batching).
              Slider syncs via tick_ms broadcast within this room; send threshold stays per-user.
            </span>
          </div>
          <button type="button" className="inspector-reset-all" onClick={resetAll}>
            Reset defaults
          </button>
        </div>
      ) : null}
    </div>
  );
}
