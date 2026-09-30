import { useEffect, useState } from 'react';
import { pickWaitCard, WAIT_CARD_DELAY_MS } from '../waitContent.js';

// Fades in below the skeleton when a door runs slow: a recall quiz from an
// earlier page this wander, or a curio from the shipped deck. It sits BELOW
// everything in the skeleton, so appearing and vanishing never move the text
// above it, and the whole subtree unmounts with StagedLoading the moment the
// first streamed word lands.
export default function WaitCard({ pages }) {
  const [card, setCard] = useState(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    // Content is chosen inside the timer, not at mount: quick doors never
    // consume a deck card, and StrictMode's throwaway mount can't double-draw.
    const t = setTimeout(() => setCard(pickWaitCard(pages)), WAIT_CARD_DELAY_MS);
    return () => clearTimeout(t);
    // One draw per mount; the parent remounts this per tap via its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!card) return null;

  if (card.kind === 'quiz') {
    return (
      <button type="button" className="wait-card" onClick={() => setRevealed(true)}>
        <p className="wc-eyebrow">From an earlier door</p>
        <p className="wc-text">
          {card.prefix}
          <span className={revealed ? 'wc-blank revealed' : 'wc-blank'}>
            {revealed ? card.answer : ' '}
          </span>
          {card.suffix}
        </p>
        {!revealed && <p className="wc-hint">tap to reveal</p>}
      </button>
    );
  }

  return (
    <div className="wait-card">
      <p className="wc-eyebrow">A curio while you wait</p>
      <p className="wc-text">{card.text}</p>
    </div>
  );
}
