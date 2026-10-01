import { useState } from 'react';
import * as api from '../api.js';
import WindingTrail from '../components/WindingTrail.jsx';

export default function Saved({ w }) {
  const { saved, openSaved, wanderRecaps, removeRecap, shareRecap, openPage } = w;
  const nothing = saved.length === 0 && wanderRecaps.length === 0;
  const [copiedId, setCopiedId] = useState(null);
  // Per-wander trail maps, fetched when first unfolded:
  // id -> node array | 'loading' | 'none' (nothing recorded) | undefined (folded)
  const [trails, setTrails] = useState({});

  async function share(r) {
    if ((await shareRecap(r.recap)) === 'copied') {
      setCopiedId(r.id);
      setTimeout(() => setCopiedId((c) => (c === r.id ? null : c)), 2000);
    }
  }

  async function toggleTrail(r) {
    if (trails[r.id] !== undefined) {
      setTrails((t) => ({ ...t, [r.id]: undefined }));
      return;
    }
    setTrails((t) => ({ ...t, [r.id]: 'loading' }));
    try {
      const j = await api.getWander(r.id);
      const pages = j.pages || [];
      // Same reconciliation as resumeWander: the client node ids carry the
      // parent links; server ids fill in for pages saved before they existed.
      const nodes = pages.map((p) => ({
        nodeId: p.clientNodeId != null ? p.clientNodeId : p.id,
        parentId: p.parentClientNodeId != null ? p.parentClientNodeId : null,
        kind: p.kind,
        title: p.title,
      }));
      setTrails((t) => ({ ...t, [r.id]: nodes.length ? nodes : 'none' }));
    } catch {
      setTrails((t) => ({ ...t, [r.id]: 'none' }));
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
          {wanderRecaps.map((r) => {
            const trail = trails[r.id];
            const doors = r.pageCount || (r.recap.path || []).length;
            const branches = r.branchCount;
            return (
              <div key={r.id} className="closed-wander">
                <div className="cw-head">
                  <span className="cw-date">
                    {(r.closedAt || r.startedAt || '').slice(0, 10)}
                    {doors > 0 && (
                      <span className="cw-metric">
                        {' '}· {doors} {doors === 1 ? 'door' : 'doors'}
                        {branches > 0 &&
                          ` · ${branches} ${branches === 1 ? 'branch' : 'branches'}`}
                      </span>
                    )}
                  </span>
                  <span className="cw-tools">
                    <button className="linkbtn" onClick={() => toggleTrail(r)}>
                      {trail === undefined ? 'See the trail' : 'Hide the trail'}
                    </button>
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
                {trail === 'loading' && <p className="cw-trail-note">Redrawing the map…</p>}
                {trail === 'none' && (
                  <p className="cw-trail-note">No map survives of this one — only the story above.</p>
                )}
                {Array.isArray(trail) && (
                  <div className="cw-trail">
                    <WindingTrail
                      nodes={trail}
                      onTap={(n) => openPage(n.title, n.kind || 'topic', true)}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
