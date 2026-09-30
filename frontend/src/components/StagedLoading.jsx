import { useEffect, useState } from 'react';
import Loading from './Loading.jsx';
import WaitCard from './WaitCard.jsx';

// The wait for a page. The tapped door is known before any network happens,
// so it shows as a provisional title instead of a bare spinner. Captions stay
// neutral on purpose — no talk of models or infrastructure while someone is
// just trying to read. The server sends only attempt numbers; the words that
// stand in for them are chosen here.
const STAGES = [
  { after: 0, text: 'Opening the door…' },
  { after: 12000, text: 'Still opening…' },
];

// Honest wait news, in the house voice. Two lines cap the whimsy — a long
// chain of retries must never read as a countdown of failures.
function statusLine(status) {
  if (!status) return null;
  if (status.fallback) return 'Taking the long way round…';
  if (status.attempt >= 3) return 'Jiggling a stubborn lock…';
  return "The first key didn't fit — trying another…";
}

export default function StagedLoading({ door, status, trailPages }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    setStage(0);
    const timers = STAGES.slice(1).map((s, i) =>
      setTimeout(() => setStage(i + 1), s.after)
    );
    return () => timers.forEach(clearTimeout);
    // reqSeq, not label: surprise doors have no label, and two surprises in a
    // row still deserve a fresh timer.
  }, [door && door.reqSeq]);

  const title = door && door.surprise ? 'Somewhere unexpected…' : door && door.label;
  const caption = statusLine(status) || STAGES[stage].text;

  return (
    <div className="page-skeleton">
      {title && <h2 className="ghost-title">{title}</h2>}
      <div className="ghost-line" />
      <div className="ghost-line short" />
      <Loading style={{ marginTop: 18 }}>{caption}</Loading>
      <WaitCard key={door && door.reqSeq} pages={trailPages} />
    </div>
  );
}
