import { useState } from 'react';
import * as api from '../api.js';

function readable(e, isSignup) {
  if (!e) return "That didn't go through.";
  if (e.status === 409) return "There's already an account with that email.";
  if (e.status === 401) return "That email and password don't match.";
  if (e.status === 400) return e.message || 'Check the email and password and try once more.';
  if (e.status === 429) return e.message || 'Too many tries just now — give it a minute.';
  return e.message || (isSignup ? "Couldn't make the account." : "Couldn't sign you in.");
}

export default function Auth({ onAuthed, onCancel }) {
  const [mode, setMode] = useState('login'); // login | signup
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const isSignup = mode === 'signup';

  async function submit(e) {
    if (e) e.preventDefault();
    if (busy) return;
    const address = email.trim();
    if (!address || !password) {
      setErr('An email and a password, and you are in.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = isSignup
        ? await api.signup({ email: address, password })
        : await api.login({ email: address, password });
      onAuthed(r.user || null);
    } catch (e2) {
      setErr(readable(e2, isSignup));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>{isSignup ? 'Make an account' : 'Sign in'}</h2>
      <p className="sub">
        An account keeps your wanders, your map, and your saved pages. You can wander perfectly well
        without one — nothing here is gated.
      </p>

      {err && <p className="formnote bad">{err}</p>}

      <form onSubmit={submit}>
        <div className="field">
          <label className="flabel" htmlFor="curio-email">
            Email
          </label>
          <input
            id="curio-email"
            className="finput"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="flabel" htmlFor="curio-password">
            Password
          </label>
          <input
            id="curio-password"
            className="finput"
            type="password"
            autoComplete={isSignup ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {isSignup && (
            <p className="fhelp">Anything you will remember. Stored hashed, never in the clear.</p>
          )}
        </div>

        <div className="btnrow">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? 'One moment…' : isSignup ? 'Create account' : 'Sign in'}
          </button>
          <button className="btn ghost" type="button" onClick={onCancel} disabled={busy}>
            Back to the doors
          </button>
        </div>
      </form>

      <p className="note">
        {isSignup ? 'Already have an account? ' : 'New here? '}
        <button
          className="linkbtn"
          type="button"
          onClick={() => {
            setMode(isSignup ? 'login' : 'signup');
            setErr(null);
          }}
        >
          {isSignup ? 'Sign in instead' : 'Make one'}
        </button>
      </p>
    </div>
  );
}
