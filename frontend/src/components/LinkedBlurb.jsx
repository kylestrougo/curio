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
