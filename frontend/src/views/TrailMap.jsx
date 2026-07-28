// The map — the explored territory. The session is a tree (nodeId / parentId);
// tapping any stop rebuilds the linear trail from root to that node.
export default function TrailMap({ w }) {
  const { visitedRef, current, jumpToNode, closeWander } = w;
  const visited = visitedRef.current;

  function renderTree(parentId) {
    const kids = visited.filter((n) => (n.parentId ?? null) === parentId);
    if (!kids.length) return null;
    return kids.map((n) => (
      <div className="tbranch" key={n.nodeId}>
        <button
          className={'tnode' + (current && current.nodeId === n.nodeId ? ' here' : '')}
          onClick={() => jumpToNode(n)}
        >
          <span className={'tdot ' + (n.kind || 'topic')} />
          <span className="tlbl">{n.title}</span>
        </button>
        {renderTree(n.nodeId)}
      </div>
    ));
  }

  return (
    <div className="map-view">
      <h2>Where you've been</h2>
      <p className="sub">
        Every branch of this wander — your map, not an algorithm's. Tap any stop to pick up from
        there.
      </p>
      {visited.length === 0 ? (
        <p className="empty">No territory explored yet. Open a door and the map draws itself.</p>
      ) : (
        <div className="tree">{renderTree(null)}</div>
      )}
      {visited.length >= 3 && (
        <button className="save" style={{ marginTop: 22 }} onClick={closeWander}>
          ✦ Close the wander
        </button>
      )}
    </div>
  );
}
