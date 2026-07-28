import React from 'react';

export default function Header({ w, user, onSignOut }) {
  const { view, trail, saved, visitedRef, goToCrumb, setView } = w;
  const signedIn = !!(user && user.id != null);

  return (
    <div className="top">
      <div className="brandrow">
        <div
          className="brand"
          onClick={() => goToCrumb(-1)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && goToCrumb(-1)}
        >
          <span className="mark" />
          <h1>Curio</h1>
        </div>
        <div className="brand-actions">
          <button className="saved-btn" onClick={() => setView('map')}>
            Trail{visitedRef.current.length ? <> · <b>{visitedRef.current.length}</b></> : ''}
          </button>
          <button className="saved-btn" onClick={() => setView('saved')}>
            Saved{saved.length ? <> · <b>{saved.length}</b></> : ''}
          </button>
          {signedIn && user.role === 'admin' && (
            <button className="saved-btn" onClick={() => setView('admin')}>
              Admin
            </button>
          )}
          {signedIn ? (
            <>
              <button
                className="saved-btn who"
                onClick={() => setView('settings')}
                title="Your settings"
              >
                {user.email}
              </button>
              <button className="saved-btn" onClick={onSignOut}>
                Sign out
              </button>
            </>
          ) : (
            <button className="saved-btn" onClick={() => setView('auth')}>
              Sign in
            </button>
          )}
        </div>
      </div>

      {view === 'page' && (
        <div className="trail">
          <button className="crumb" onClick={() => goToCrumb(-1)}>
            Home
          </button>
          {trail.map((p, i) => (
            <React.Fragment key={i}>
              <span className="sep">›</span>
              <button
                className={'crumb' + (i === trail.length - 1 ? ' here' : '')}
                onClick={() => goToCrumb(i)}
              >
                {p.title}
              </button>
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
