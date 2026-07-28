// Local seed pool — home renders instantly from these; fresh doors swap in
// quietly if the background call returns before the user starts wandering.
export const SEED_POOL = [
  { label: 'Why do we dream?', type: 'question' },
  { label: 'The library that mapped the ancient world', type: 'topic' },
  { label: 'Octopuses have three hearts', type: 'fact' },
  { label: 'How does a single idea become a whole language?', type: 'question' },
  { label: 'Honey never spoils', type: 'fact' },
  { label: 'The sound of a dying star', type: 'topic' },
  { label: "Why is the ocean salty but rain isn't?", type: 'question' },
  { label: "Rome's concrete outlasted ours — why?", type: 'question' },
  { label: 'The woman who mapped the ocean floor', type: 'topic' },
  { label: 'Sharks are older than trees', type: 'fact' },
  { label: 'How do cities decide where streets go?', type: 'question' },
  { label: 'The color that used to be poisonous', type: 'topic' },
  { label: 'Your body replaces itself — mostly', type: 'fact' },
  { label: 'What did silence sound like before machines?', type: 'question' },
  { label: 'The great emu war of 1932', type: 'topic' },
  { label: "Bananas are berries; strawberries aren't", type: 'fact' },
  { label: 'Why do we find things beautiful?', type: 'question' },
  { label: 'The last common language of the Silk Road', type: 'topic' },
  { label: 'Lightning strikes Earth 8 million times a day', type: 'fact' },
  { label: 'Could you patent a color?', type: 'question' },
];

export function pickSeeds(n = 4, exclude = [], source = SEED_POOL) {
  const pool = source.filter((s) => !exclude.includes(s.label));
  const out = [];
  while (out.length < n && pool.length) {
    out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
  }
  return out;
}
