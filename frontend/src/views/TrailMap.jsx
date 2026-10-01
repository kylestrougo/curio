import { useEffect, useRef } from 'react';

// The map — the explored territory as a winding road. The session is a tree
// (nodeId / parentId); it's flattened depth-first so each branch runs as one
// contiguous stretch, then laid out in rows of three that alternate
// direction, snaking down the page like a board game. The whole width always
// fits the column — a long wander grows downward, never sideways.
// Tapping any stop rebuilds the linear trail from root to that node.
const COLS = 3;

// Depth-first flatten: children in insertion order, so a branch reads as a
// contiguous stretch of the road before the path moves on to the next fork.
function flatten(visited) {
  const byParent = new Map();
  for (const n of visited) {
    const key = n.parentId ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(n);
  }
  const out = [];
  const walk = (parentId) => {
    for (const n of byParent.get(parentId) || []) {
      out.push(n);
      walk(n.nodeId);
    }
  };
  walk(null);
  return out;
}

export default function TrailMap({ w }) {
  const { visitedRef, current, jumpToNode, closeWander } = w;
  const visited = visitedRef.current;

  const flat = flatten(visited);
  const byId = new Map(visited.map((n) => [n.nodeId, n]));
  const rows = [];
  for (let i = 0; i < flat.length; i += COLS) rows.push(flat.slice(i, i + COLS));

  // A long wander puts "you are here" far down the page; bring it into view.
  // The rAF defers past useWander's scroll-to-top on view change (parent
  // effects run after child effects), so this wins.
  const hereRef = useRef(null);
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      if (hereRef.current) hereRef.current.scrollIntoView({ block: 'center' });
    });
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="map-view">
      <h2>Where you've been</h2>
      <p className="sub">
        Every stop of this wander, in walking order — your map, not an algorithm's. Tap any stop
        to pick up from there.
      </p>
      {visited.length === 0 ? (
        <p className="empty">No territory explored yet. Open a door and the map draws itself.</p>
      ) : (
        <div className="spath">
          {rows.map((row, ri) => (
            <div className={ri % 2 ? 'srow rev' : 'srow'} key={ri}>
              {row.map((n, ci) => {
                const i = ri * COLS + ci;
                const next = flat[i + 1];
                // One connector per stop: a dash toward the neighbour in this
                // row, or — at a row's end — down to where the path resumes.
                const conn = !next ? '' : ci < COLS - 1 ? ' c-h' : ' c-v';
                const here = current && current.nodeId === n.nodeId;
                // The road can't literally fork; a stop that doesn't follow
                // its parent on the road says where it branched from.
                const prev = flat[i - 1];
                const jumped = i > 0 && (n.parentId ?? null) !== (prev ? prev.nodeId : null);
                const via = jumped
                  ? n.parentId != null
                    ? `↳ via ${(byId.get(n.parentId) || {}).title || 'an earlier stop'}`
                    : '↳ a fresh start'
                  : null;
                return (
                  <button
                    type="button"
                    className={'snode' + conn + (here ? ' here' : '')}
                    key={n.nodeId}
                    ref={here ? hereRef : undefined}
                    onClick={() => jumpToNode(n)}
                  >
                    {via && <span className="svia">{via}</span>}
                    <span className={'tdot ' + (n.kind || 'topic')} />
                    <span className="slbl">{n.title}</span>
                    {here && <span className="shere">you are here</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {visited.length >= 3 && (
        <button className="save" style={{ marginTop: 26 }} onClick={closeWander}>
          ✦ Close the wander
        </button>
      )}
    </div>
  );
}
