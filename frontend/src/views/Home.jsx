import Door from '../components/Door.jsx';
import AskBox from '../components/AskBox.jsx';

function ShuffleIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 3h5v5" />
      <path d="M4 20 21 3" />
      <path d="M21 16v5h-5" />
      <path d="m15 15 6 6" />
      <path d="M4 4l5 5" />
    </svg>
  );
}

// The return hook. Shown once, quietly: where you left off, and one fresh
// door. No counters, no days-since, nothing to break.
function ResumeNote({ hint, onReopen, onDoor, onDismiss }) {
  const wander = hint.wander;
  const door = hint.door;
  return (
    <div className="resume">
      <p className="rlabel">Still open</p>
      {wander && wander.lastTitle && (
        <>
          You left off at{' '}
          <button className="rtitle" onClick={() => onReopen(wander.id)}>
            {wander.lastTitle}
          </button>
        </>
      )}
      {door && door.label && (
        <div className="rdoor">
          <Door label={door.label} type={door.type || 'topic'} onClick={() => onDoor(door)} />
        </div>
      )}
      <p style={{ margin: '10px 0 0' }}>
        <button className="linkbtn" onClick={onDismiss}>
          Not now
        </button>
      </p>
    </div>
  );
}

export default function Home({ w }) {
  const { seeds, ask, setAsk, submitAsk, shuffleDoors, openPage, resumeHint, resumeWander, dismissResume } =
    w;

  return (
    <div className="home">
      <div className="ey">Today's doors</div>
      <h2>
        Follow a thread of <i>curiosity</i>.
      </h2>
      <p className="lede">
        Tap a door to begin. Each page hands you a few new ones — deeper, adjacent, or delightfully
        sideways. You pick the direction.
      </p>

      {resumeHint && (
        <ResumeNote
          hint={resumeHint}
          onReopen={resumeWander}
          onDoor={(d) => openPage(d.label, d.type || 'topic', true)}
          onDismiss={dismissResume}
        />
      )}

      <div className="doors-row">
        <div className="doors-label" style={{ margin: 0 }}>
          Pick a starting point
        </div>
        <button className="shuffle" onClick={shuffleDoors} title="Show me different doors">
          <ShuffleIcon />
          Shuffle
        </button>
      </div>
      <div className="doors" key={seeds.map((s) => s.label).join('|')}>
        {seeds.map((s) => (
          <Door key={s.label} label={s.label} type={s.type} onClick={() => openPage(s.label, s.type, true)} />
        ))}
      </div>
      <Door
        wild
        kindLabel="Wildcard"
        label="✦ Surprise me — somewhere I haven't been"
        style={{ marginTop: 10 }}
        onClick={() => openPage(null, 'topic', true, true)}
      />
      <AskBox
        value={ask}
        onChange={setAsk}
        onSubmit={submitAsk}
        placeholder="…or start somewhere of your own"
        action="Explore"
        style={{ marginTop: 22 }}
      />
      <div className="foot">Follow your curiosity — one door at a time</div>
    </div>
  );
}
