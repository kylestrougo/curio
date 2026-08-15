// A blurb whose key terms are doors. The server guarantees each term
// appears in the text (case-insensitively); this finds those spans and makes
// them tappable, keeping the blurb's original casing on screen.

// Non-overlapping [start, end, term] spans, longest term first so
// "Royal Society" wins over "Royal", each term linked at most once.
function findSpans(text, terms) {
  const lower = text.toLowerCase();
  const spans = [];
  const taken = (a, b) => spans.some(([s, e]) => a < e && b > s);
  for (const term of [...terms].sort((a, b) => b.length - a.length)) {
    const needle = term.toLowerCase();
    if (!needle) continue;
    let at = lower.indexOf(needle);
    while (at !== -1 && taken(at, at + needle.length)) {
      at = lower.indexOf(needle, at + 1);
    }
    if (at !== -1) spans.push([at, at + needle.length, term]);
  }
  return spans.sort((a, b) => a[0] - b[0]);
}

// Deeper prose (tell-me-more, Q&A answers) carries its links inline instead:
// the model wraps terms in [[double brackets]] as it writes. Complete pairs
// become termlinks (capped at 4, like the blurb); a trailing unclosed
// "[[fragment" mid-stream renders as its bare words so brackets never flash
// on screen; text with no markers renders exactly as before.
export function MarkedProse({ text, onOpen, className }) {
  if (!text || !text.includes('[[')) return <p className={className}>{text}</p>;

  const parts = [];
  let cursor = 0;
  let links = 0;
  while (cursor < text.length) {
    const open = text.indexOf('[[', cursor);
    if (open === -1) {
      parts.push(text.slice(cursor));
      break;
    }
    if (open > cursor) parts.push(text.slice(cursor, open));
    const close = text.indexOf(']]', open + 2);
    if (close === -1) {
      // Mid-stream: the marker hasn't closed yet — show the words, not the brackets.
      parts.push(text.slice(open + 2));
      break;
    }
    const term = text.slice(open + 2, close).trim();
    if (term && links < 4) {
      links += 1;
      parts.push(
        <button type="button" className="termlink" key={open} onClick={() => onOpen(term)}>
          {text.slice(open + 2, close)}
        </button>
      );
    } else {
      parts.push(text.slice(open + 2, close));
    }
    cursor = close + 2;
  }
  return <p className={className}>{parts}</p>;
}

export default function LinkedBlurb({ text, terms, onOpen, className = 'blurb' }) {
  const spans = Array.isArray(terms) && terms.length ? findSpans(text, terms) : [];
  if (!spans.length) return <p className={className}>{text}</p>;

  const parts = [];
  let cursor = 0;
  for (const [start, end] of spans) {
    if (start > cursor) parts.push(text.slice(cursor, start));
    const shown = text.slice(start, end);
    parts.push(
      <button
        type="button"
        className="termlink"
        key={`${start}-${shown}`}
        onClick={() => onOpen(shown)}
      >
        {shown}
      </button>
    );
    cursor = end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <p className={className}>{parts}</p>;
}
