export default function Saved({ w }) {
  const { saved, openSaved } = w;

  return (
    <div className="saved-view">
      <h2>Saved pages</h2>
      <p className="sub">The stops worth keeping. Tap one to wander again from there.</p>
      {saved.length === 0 ? (
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
    </div>
  );
}
