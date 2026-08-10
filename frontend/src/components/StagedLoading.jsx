import { useEffect, useState } from 'react';
import Loading from './Loading.jsx';

// The wait for a page, made honest. The tapped door is known before any
// network happens, so it shows as a provisional title instead of a bare
// spinner — and the caption escalates on the same schedule the backend
// actually follows: free models really are slow, and the chain really does
// fall through to another model when one stalls.
const STAGES = [
  { after: 0, text: 'Opening the door…' },
  { after: 7000, text: 'Still working — free models can be slow…' },
  { after: 20000, text: 'Trying another model…' },
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
