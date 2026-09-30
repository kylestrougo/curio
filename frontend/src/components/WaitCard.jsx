import { useEffect, useRef, useState } from 'react';
import { pickWaitCard, WAIT_CARD_DELAY_MS } from '../waitContent.js';

// Fades in below the skeleton when a door runs slow: a recall quiz from an
// earlier page this wander, or a curio from the shipped deck. Playing a card
// (revealing a quiz, tapping a curio) deals the next one below it, so a long
// wait becomes a growing pile rather than one dead end. Cards only ever
// append at the bottom — everything above keeps its place — and the whole
// subtree unmounts with StagedLoading the moment the first streamed word
// lands.
export default function WaitCard({ pages }) {
  const [cards, setCards] = useState([]);
  // Quiz sentences already dealt this wait; the picker skips them so the
  // pile never asks the same question twice. (The curio deck de-dupes
  // itself via its own cursor.)
  const usedRef = useRef(new Set());

  // Card choice happens inside the timer / tap handlers, never in render or
  // a state updater: picking mutates the deck cursor, and StrictMode's
  // throwaway mount and double-run updaters must not double-draw.
  const deal = () => {
    const card = pickWaitCard(pages, usedRef.current);
    if (card.kind === 'quiz') usedRef.current.add(card.prefix + card.answer + card.suffix);
    setCards((prev) => [...prev, { id: prev.length, card, done: false }]);
  };

  useEffect(() => {
    const t = setTimeout(deal, WAIT_CARD_DELAY_MS);
    return () => clearTimeout(t);
    // One first draw per mount; the parent remounts this per tap via its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Only the newest, still-live card advances the game — a repeat tap on an
  // older card can't double-deal.
  const play = (id) => {
    const last = cards[cards.length - 1];
    if (!last || last.id !== id || last.done) return;
    setCards((prev) => prev.map((c) => (c.id === id ? { ...c, done: true } : c)));
    deal();
  };

  return (
    <>
      {cards.map(({ id, card, done }) =>
        card.kind === 'quiz' ? (
          <button type="button" key={id} className="wait-card" onClick={() => play(id)}>
            <p className="wc-eyebrow">From an earlier door</p>
            <p className="wc-text">
              {card.prefix}
              <span className={done ? 'wc-blank revealed' : 'wc-blank'}>
                {done ? card.answer : ' '}
              </span>
              {card.suffix}
            </p>
            {!done && <p className="wc-hint">tap to reveal</p>}
          </button>
        ) : (
          <button type="button" key={id} className="wait-card" onClick={() => play(id)}>
            <p className="wc-eyebrow">A curio while you wait</p>
            <p className="wc-text">{card.text}</p>
            {!done && <p className="wc-hint">tap for another</p>}
          </button>
        )
      )}
    </>
  );
}
