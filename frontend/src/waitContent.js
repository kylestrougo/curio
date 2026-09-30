// Content for the wait card — the small diversion that fades in when a door
// is slow to open. No React, no DOM: pure functions plus one session-scoped
// deck cursor, so all of this can be unit-tested directly.
import { CURIO_CARDS } from './data/curioCards.js';

export const WAIT_CARD_DELAY_MS = 4000;

function shuffled(list) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// A recall quiz from the pages already read this wander: one sentence with an
// interesting word blanked out. Returns {kind:'quiz', prefix, answer, suffix,
// source} where prefix + answer + suffix is the original sentence, or null
// when nothing usable exists (first door of a wander, or blurbs too odd).
export function buildQuiz(pages) {
  for (const page of shuffled(pages || [])) {
    const text = String(page.blurb || '').replace(/\[\[|\]\]/g, '');
    // No lookbehind — the Pi's browser may be an older WebKit.
    const sentences = (text.match(/[^.!?]+[.!?]+/g) || [])
      .map((s) => s.trim())
      .filter((s) => s.length >= 40 && s.length <= 160);
    for (const sentence of shuffled(sentences)) {
      const blank = pickBlank(sentence, page.terms);
      if (!blank) continue;
      return {
        kind: 'quiz',
        prefix: sentence.slice(0, blank.start),
        answer: sentence.slice(blank.start, blank.end),
        suffix: sentence.slice(blank.end),
        source: page.title,
      };
    }
  }
  return null;
}

// The word to hide: prefer one of the page's own key terms found in the
// sentence (blanked as written there, casing preserved), else the longest
// plain word of six letters or more.
function pickBlank(sentence, terms) {
  const lower = sentence.toLowerCase();
  for (const term of terms || []) {
    const needle = String(term).toLowerCase();
    if (needle.length < 4) continue;
    const at = lower.indexOf(needle);
    if (at !== -1) return { start: at, end: at + needle.length };
  }
  let best = null;
  const re = /[A-Za-zÀ-ÖØ-öø-ÿ'’-]{6,}/g;
  let m;
  while ((m = re.exec(sentence)) !== null) {
    if (!best || m[0].length > best.end - best.start) {
      best = { start: m.index, end: m.index + m[0].length };
    }
  }
  return best;
}

// The shipped deck: shuffled once per session, dealt without repeats until it
// runs out, then reshuffled (nudging the first card if it would repeat the
// last one dealt across the boundary).
let deck = null;
let cursor = 0;

export function drawCurioCard() {
  if (!deck) deck = shuffled(CURIO_CARDS);
  if (cursor >= deck.length) {
    const last = deck[deck.length - 1];
    deck = shuffled(CURIO_CARDS);
    cursor = 0;
    if (deck.length > 1 && deck[0] === last) [deck[0], deck[1]] = [deck[1], deck[0]];
  }
  return deck[cursor++];
}

export function pickWaitCard(pages) {
  return buildQuiz(pages) || { kind: 'curio', text: drawCurioCard() };
}
