import { useEffect, useState } from 'react';
import Loading from './Loading.jsx';

// The wait for a page. The tapped door is known before any network happens,
// so it shows as a provisional title instead of a bare spinner. Captions stay
// neutral on purpose — no talk of models or infrastructure while someone is
// just trying to read.
const STAGES = [
  { after: 0, text: 'Opening the door…' },
  { after: 12000, text: 'Still opening…' },
];

export default function StagedLoading({ door }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    setStage(0);
    const timers = STAGES.slice(1).map((s, i) =>
      setTimeout(() => setStage(i + 1), s.after)
    );
    return () => timers.forEach(clearTimeout);
  }, [door && door.label]);

  const title = door && door.surprise ? 'Somewhere unexpected…' : door && door.label;

  return (
    <div className="page-skeleton">
      {title && <h2 className="ghost-title">{title}</h2>}
      <div className="ghost-line" />
      <div className="ghost-line short" />
      <Loading style={{ marginTop: 18 }}>{STAGES[stage].text}</Loading>
    </div>
  );
}
