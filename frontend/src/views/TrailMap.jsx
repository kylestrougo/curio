import WindingTrail from '../components/WindingTrail.jsx';

// The map — the explored territory. The session is a tree (nodeId /
// parentId), drawn by WindingTrail as a meandering path whose forks really
// fork. Tapping any stop rebuilds the linear trail from root to that node.
export default function TrailMap({ w }) {
  const { visitedRef, current, jumpToNode, closeWander } = w;
  const visited = visitedRef.current;

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
        <WindingTrail
          nodes={visited}
          currentId={current ? current.nodeId : null}
          onTap={jumpToNode}
        />
      )}
      {visited.length >= 3 && (
        <button className="save" style={{ marginTop: 26 }} onClick={closeWander}>
          ✦ Close the wander
        </button>
      )}
    </div>
  );
}
