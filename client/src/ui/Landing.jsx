import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { generateCanvasCode, normalizeCanvasCode } from '../lib/canvasCode.js';
import './Landing.css';

const NAME_KEY = 'cursor-display-name';

function persistName(name) {
  sessionStorage.setItem(NAME_KEY, name);
}

export default function Landing() {
  const navigate = useNavigate();
  const [name, setName] = useState(() => sessionStorage.getItem(NAME_KEY) || '');
  const [joinCode, setJoinCode] = useState('');
  const [error, setError] = useState('');

  function requireName() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Enter your name to continue.');
      return null;
    }
    setError('');
    persistName(trimmed);
    return trimmed;
  }

  function onCreate() {
    const displayName = requireName();
    if (!displayName) return;
    const code = generateCanvasCode();
    navigate(`/canvas/${code}`, { state: { name: displayName } });
  }

  function onJoin(ev) {
    ev.preventDefault();
    const displayName = requireName();
    if (!displayName) return;
    const code = normalizeCanvasCode(joinCode) || joinCode.trim();
    if (!code) {
      setError('Enter a Canvas code to join.');
      return;
    }
    navigate(`/canvas/${code}`, { state: { name: displayName } });
  }

  return (
    <div className="landing">
      <div className="landing-grid" aria-hidden="true" />
      <main className="landing-card">
        <p className="landing-eyebrow">Multiplayer Cursors</p>
        <h1 className="landing-title">Share a Canvas</h1>
        <p className="landing-lead">
          Draw together in real time on a shared grid. Pick a name, create a Canvas, or join with a code.
        </p>

        <label className="landing-field">
          <span>Your name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => { setName(e.target.value); setError(''); }}
            placeholder="Alex"
            autoComplete="nickname"
            maxLength={40}
          />
        </label>

        {error ? <p className="landing-error" role="alert">{error}</p> : null}

        <button type="button" className="landing-primary" onClick={onCreate}>
          Create Canvas
        </button>

        <form className="landing-join" onSubmit={onJoin}>
          <label className="landing-field">
            <span>Canvas code</span>
            <input
              type="text"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="ABC123"
              autoComplete="off"
              spellCheck={false}
              maxLength={12}
            />
          </label>
          <button type="submit" className="landing-secondary">
            Join Canvas
          </button>
        </form>
      </main>
    </div>
  );
}
