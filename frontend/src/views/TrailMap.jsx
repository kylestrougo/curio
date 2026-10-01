import { useEffect, useLayoutEffect, useRef, useState } from 'react';

// The map — the explored territory as a wandering trail. The session is a
// tree (nodeId / parentId); it's flattened depth-first and each stop becomes
// a dot placed on a meandering curve down the page. Every parent→child link
// is drawn as a smooth dashed curve, so a fork in the wander really forks on
// the map: a second path peels off the same dot. The full width always fits
// the column — a long wander grows downward, never sideways.
// Tapping any stop rebuilds the linear trail from root to that node.
const STEP_Y = 86; // minimum vertical distance between stops
const GAP_Y = 26; // minimum clear air between two labels
const TOP_PAD = 26;
const BOT_PAD = 20;

// Depth-first flatten: children in insertion order, so a branch reads as a
// contiguous stretch of trail before the map moves on to the next fork.
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

// The meander: two sines out of phase, so the sway drifts rather than
// repeating cleanly. Returns a fraction of the container width, kept well
// clear of the edges so labels have room beside their dot.
function waveU(i) {
  return 0.5 + 0.3 * Math.sin(i * 0.85) + 0.08 * Math.sin(i * 2.1 + 1.3);
}

// A flowing segment between two stops: vertical tangents at both ends, so
// consecutive segments join into one continuous river.
function curve(a, b) {
  const lead = Math.min((b.y - a.y) / 2, 60);
  return `M ${a.x} ${a.y} C ${a.x} ${a.y + lead}, ${b.x} ${b.y - lead}, ${b.x} ${b.y}`;
}

export default function TrailMap({ w }) {
  const { visitedRef, current, jumpToNode, closeWander } = w;
  const visited = visitedRef.current;
  const flat = flatten(visited);

  // The curve needs real pixels; measure the column and redo on resize.
  const boxRef = useRef(null);
  const [wid, setWid] = useState(0);
  useLayoutEffect(() => {
    const measure = () => {
      if (boxRef.current) setWid(boxRef.current.clientWidth);
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  // Wrapped titles make stops different heights, so even spacing would let a
  // tall label bleed into its neighbour. After each render that can change a
  // height (new width, new stop, "you are here" moving), measure the real
  // label boxes and push stops apart just enough that none can touch. Runs
  // before paint, so the corrected layout is the only one ever seen.
  const nodeRefs = useRef([]);
  const [layout, setLayout] = useState(null); // {ys:[...], height}
  useLayoutEffect(() => {
    if (!wid || !flat.length) return;
    const hs = flat.map((_, i) => {
      const el = nodeRefs.current[i];
      return el ? el.offsetHeight : 28;
    });
    const ys = [TOP_PAD + Math.max(hs[0] / 2, STEP_Y / 3)];
    for (let i = 1; i < flat.length; i++) {
      ys.push(Math.max(ys[i - 1] + STEP_Y, ys[i - 1] + hs[i - 1] / 2 + GAP_Y + hs[i] / 2));
    }
    const height = ys[ys.length - 1] + hs[hs.length - 1] / 2 + BOT_PAD;
    setLayout({ ys, height });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid, visited.length, current && current.nodeId]);

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

  const pos = new Map(); // nodeId -> {x, y}
  flat.forEach((n, i) => {
    pos.set(n.nodeId, {
      x: wid * waveU(i),
      y: layout && layout.ys[i] != null ? layout.ys[i] : TOP_PAD + i * STEP_Y,
    });
  });
  const height = layout ? layout.height : flat.length * STEP_Y + TOP_PAD + BOT_PAD;

  // Every tree edge becomes a curve. The one feeding the stop right below is
  // the trail itself; a longer reach back to its parent is a fork peeling off.
  const edges = [];
  flat.forEach((n, i) => {
    if (n.parentId == null) return;
    const a = pos.get(n.parentId);
    const b = pos.get(n.nodeId);
    if (!a || !b) return;
    const fork = !flat[i - 1] || flat[i - 1].nodeId !== n.parentId;
    edges.push({ d: curve(a, b), fork, key: n.nodeId });
  });

  return (
    <div className="map-view">
      <h2>Where you've been</h2>
      <p className="sub">
        Every stop of this wander — your map, not an algorithm's. Where the trail forks, you
        doubled back and opened a different door. Tap any stop to pick up from there.
      </p>
      {visited.length === 0 ? (
        <p className="empty">No territory explored yet. Open a door and the map draws itself.</p>
      ) : (
        <div className="wind" ref={boxRef} style={{ height }}>
          {wid > 0 && (
            <>
              <svg className="wsvg" width={wid} height={height} aria-hidden="true">
                {edges.map((e) => (
                  <path key={e.key} className={e.fork ? 'wtrail fork' : 'wtrail'} d={e.d} />
                ))}
              </svg>
              {flat.map((n, i) => {
                const p = pos.get(n.nodeId);
                const here = current && current.nodeId === n.nodeId;
                // Label sits on whichever side has the room.
                const lft = p.x > wid / 2;
                return (
                  <button
                    type="button"
                    className={'wnode' + (lft ? ' lft' : '') + (here ? ' here' : '')}
                    key={n.nodeId}
                    ref={(el) => {
                      nodeRefs.current[i] = el;
                      if (here) hereRef.current = el;
                    }}
                    style={{ left: p.x, top: p.y }}
                    onClick={() => jumpToNode(n)}
                  >
                    <span className={'tdot ' + (n.kind || 'topic')} />
                    <span className="wtxt">
                      <span className="wlbl">{n.title}</span>
                      {n.parentId == null && flat[0] !== n && (
                        <span className="svia">↳ a fresh start</span>
                      )}
                      {here && <span className="shere">you are here</span>}
                    </span>
                  </button>
                );
              })}
            </>
          )}
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
