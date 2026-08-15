import { useEffect, useState } from 'react';
import './styles/curio.css';
import * as api from './api.js';
import { useWander } from './hooks/useWander.js';
import Header from './components/Header.jsx';
import Home from './views/Home.jsx';
import Page from './views/Page.jsx';
import Saved from './views/Saved.jsx';
import TrailMap from './views/TrailMap.jsx';
import Recap from './views/Recap.jsx';
import Auth from './views/Auth.jsx';
import Settings from './views/Settings.jsx';
import Admin from './views/Admin.jsx';

// ─────────────────────────────────────────────────────────────
// Curio — a curiosity engine.
// Tap a door → land on a page → tap where curiosity pulls → repeat.
// Every page is generated live by the backend, seeded with your path so far.
// ─────────────────────────────────────────────────────────────

export default function App() {
  // undefined = we haven't heard back from /api/auth/me yet; null = signed out.
  const [user, setUser] = useState(undefined);
  const w = useWander(user);
  const { view, setView, goToCrumb } = w;

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((r) => live && setUser(r.user || null))
      .catch(() => live && setUser(null)); // no backend? wander anonymously.
    return () => {
      live = false;
    };
  }, []);

  async function signOut() {
    try {
      await api.logout();
    } catch {
      /* the session is going away on this side regardless */
    }
    setUser(null);
    goToCrumb(-1);
  }

  // Someone who is not an admin has no business on the admin panel, even if
  // they get the view set somehow.
  const resolved = view === 'admin' && !(user && user.role === 'admin') ? 'home' : view;

  return (
    <div className="curio-root" ref={w.scrollRef} style={{ overflowY: 'auto', height: '100%' }}>
      <div className="wrap">
        <Header w={w} user={user} onSignOut={signOut} />

        {resolved === 'home' && <Home w={w} />}
        {resolved === 'page' && <Page w={w} />}
        {resolved === 'saved' && <Saved w={w} />}
        {resolved === 'map' && <TrailMap w={w} />}
        {resolved === 'recap' && <Recap w={w} />}
        {resolved === 'auth' && (
          <Auth
            onAuthed={(u) => {
              setUser(u);
              goToCrumb(-1);
            }}
            onCancel={() => goToCrumb(-1)}
          />
        )}
        {resolved === 'settings' &&
          (user ? (
            <Settings onDone={() => goToCrumb(-1)} onPrefsSaved={w.refreshTopicalSeeds} />
          ) : (
            <div className="panel">
              <h2>Doors in your inbox</h2>
              <p className="sub">Sign in first and this is yours to set.</p>
              <div className="btnrow">
                <button className="btn" onClick={() => setView('auth')}>
                  Sign in
                </button>
              </div>
            </div>
          ))}
        {resolved === 'admin' && <Admin onDone={() => goToCrumb(-1)} />}
      </div>
    </div>
  );
}
