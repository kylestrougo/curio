import { useState } from 'react';

export default function Saved({ w }) {
  const { saved, openSaved, wanderRecaps, removeRecap, shareRecap, openPage } = w;
  const nothing = saved.length === 0 && wanderRecaps.length === 0;
  const [copiedId, setCopiedId] = useState(null);

  async function share(r) {
    if ((await shareRecap(r.recap)) === 'copied') {
      setCopiedId(r.id);
      setTimeout(() => setCopiedId((c) => (c === r.id ? null : c)), 2000);
    }
  }

  return (
    <div className="saved-view">
      <h2>Saved pages</h2>
      <p className="sub">The stops worth keeping. Tap one to wander again from there.</p>
      {nothing ? (
        <p className="empty">
          Nothing saved yet. When a page catches you, hit <b>Save this page</b> and it'll wait for you
          here.
        </p>
      ) : (
        saved.map((p, i) => (
          <button key={i} className="saved-item" onClick={() => openSaved(p)}>
            <p className="t">{p.title}</p>
            <p className="b">{p.blurb}</p>
          </button>
        ))
      )}
      {wanderRecaps.length > 0 && (
        <div className="closed-wanders">
          <h2>Wanders, closed</h2>
          <p className="sub">The summaries you kept. Every door is still a door.</p>
          {wanderRecaps.map((r) => (
            <div key={r.id} className="closed-wander">
              <div className="cw-head">
                <span className="cw-date">{(r.closedAt || r.startedAt || '').slice(0, 10)}</span>
                <span className="cw-tools">
                  <button className="linkbtn" onClick={() => share(r)}>
                    {copiedId === r.id ? 'Link copied' : 'Share'}
                  </button>
                  <button className="linkbtn" onClick={() => removeRecap(r.id)}>
                    Remove
                  </button>
                </span>
              </div>
              <div className="recap-path">
                {(r.recap.path || []).map((t, i) => (
                  <span key={i}>
                    {i > 0 && <span className="sep"> › </span>}
                    <button className="cw-door" onClick={() => openPage(t, 'topic', true)}>
                      {t}
                    </button>
                  </span>
                ))}
              </div>
              <p className="recap-synth cw-synth">{r.recap.synthesis}</p>
              {r.recap.thread && (
                <button className="thread-q" onClick={() => openPage(r.recap.thread, 'question', true)}>
                  {r.recap.thread}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
