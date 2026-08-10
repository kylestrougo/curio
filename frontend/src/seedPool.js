// Local seed pool — home renders instantly from these; fresh doors swap in
// quietly if the background call returns before the user starts wandering.
//
// Two things this list is trying to be, and both matter more than its length:
//
// 1. NOT THE OBVIOUS ONES. Octopus hearts, honey never spoiling, bananas being
//    berries — every model reaches for those and so does every listicle. A door
//    only works if it's something the reader hasn't already been told twice.
// 2. SPREAD ACROSS DOMAINS. `domain` is not decoration: pickSeeds deals one
//    door per domain, so a hand of four can't come back as four biology facts.
//    Four random draws from a science-heavy list regularly do exactly that,
//    which reads as a narrow app rather than an unlucky shuffle.
//
// Every `fact` here is true as stated. These labels are fed back to the model
// as the subject of a generated page, so a wrong one doesn't just sit there —
// it becomes a whole page of confident elaboration on something false.

// The doors themselves live in shared/seed-pool.json, NOT here — the backend
// reads the same file to pre-generate their pages overnight (flask warm-cache),
// so the doors a visitor actually sees first are the ones already cached.
// Editing the pool means editing the JSON; this module only deals hands.
import SEED_POOL from '../../shared/seed-pool.json';

export { SEED_POOL };

/**
 * Deal `n` doors, preferring one per domain.
 *
 * Backend-generated seeds carry no domain. Those are treated as each being
 * their own domain rather than all sharing an undefined one — otherwise a
 * single fresh door would block every other fresh door from being dealt.
 */
export function pickSeeds(n = 4, exclude = [], source = SEED_POOL) {
  const excluded = new Set(exclude);
  const pool = source.filter((s) => s && s.label && !excluded.has(s.label));

  // Fisher-Yates on a copy — splice-at-random-index biases toward the tail.
  const shuffled = [...pool];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }

  const out = [];
  const usedDomains = new Set();
  const sameDomain = [];

  for (const s of shuffled) {
    if (out.length >= n) break;
    if (s.domain && usedDomains.has(s.domain)) {
      sameDomain.push(s);
      continue;
    }
    if (s.domain) usedDomains.add(s.domain);
    out.push(s);
  }

  // Not enough distinct domains left to fill the hand — top up with the rest.
  for (const s of sameDomain) {
    if (out.length >= n) break;
    out.push(s);
  }

  return out;
}
