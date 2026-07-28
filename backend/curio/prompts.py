"""Every prompt Curio sends, in one file.

These moved server-side from the artifact deliberately: prompt taste is the
biggest quality dial in this product, it now has to be tuned *per model*
(free models vary wildly), and tuning it here ships without rebuilding the
frontend. The admin "test generation" button exercises exactly these.

Wording is carried over from the working prototype — it was tuned by hand and
is not to be casually rewritten.
"""

import random

PERSONA = (
    "You are Curio, the knowledge engine behind a curiosity app. The user explores by tapping. "
    "You are accurate and never invent facts. You write for a curious, intelligent adult and prize "
    "the genuinely fascinating over the obvious."
)

# Free models have poor JSON discipline. We ask for bare JSON, send
# response_format when supported, AND parse tolerantly. Belt, braces, and a
# second pair of braces.
_JSON_RULE = "Respond with ONLY JSON, no markdown, no preamble, no code fences. "

_PAGE_SHAPE = (
    _JSON_RULE + "Shaped exactly: "
    '{"title": string, "blurb": 2 vivid accurate sentences totaling under 45 words, '
    '"buttons":[{"label": short enticing text max 8 words, "type":"fact"|"question"|"topic"}]}. '
    "Return exactly 5 buttons that are a lively mix of surprising facts, provocative open questions, "
    "and adjacent topics worth wandering into."
)


# Named domains, drawn fresh each call.
#
# The old prompt said "a very different domain (e.g. science, history, art,
# technology, everyday life)" on every single call. Two problems with that: the
# five examples became the whole world the model considered, and an identical
# prompt every time samples the same distribution every time — so the doors
# arrived varied *within* a hand and identical *across* hands. Naming specific
# and different territory per call is what actually moves the output.
_DOMAINS = [
    "astronomy and cosmology",
    "geology and deep time",
    "microbiology and the invisible",
    "animal behaviour",
    "plants and fungi",
    "human anatomy and medicine",
    "the history of medicine",
    "linguistics and writing systems",
    "pre-modern history outside Europe",
    "twentieth century history",
    "archaeology",
    "mathematics and its history",
    "materials and manufacturing",
    "civil engineering and infrastructure",
    "computing and networks",
    "cartography and navigation",
    "visual art and architecture",
    "music and acoustics",
    "economics and trade",
    "law and institutions",
    "agriculture and food",
    "textiles and clothing",
    "religion and ritual",
    "philosophy and ideas",
    "psychology and perception",
    "sport and games",
    "transport and logistics",
    "weather and climate",
    "oceans and rivers",
    "energy and power",
    "printing and publishing",
    "espionage and secrecy",
    "urban planning",
    "chemistry in everyday objects",
    "timekeeping and calendars",
    "death and burial customs",
    "childhood and play",
    "waste, ruins and what gets left behind",
    "borders and territory",
    "money, counting and record-keeping",
]

# One of these per call, to shift the register as well as the subject. Without
# it every hand comes back pitched the same way — all "surprising fact about an
# animal", regardless of which domains were named.
_ANGLES = [
    "Favour the very small and specific over the sweeping.",
    "Favour something ancient that still shapes the present.",
    "Favour a person whose name has been forgotten.",
    "Favour a thing that turned out to work completely differently than assumed.",
    "Favour an ordinary object with a strange history.",
    "Favour a decision that could easily have gone the other way.",
    "Favour a place rather than a discovery.",
    "Favour something that was normal once and is unthinkable now.",
    "Favour a mistake, a failure, or a dead end that mattered.",
    "Favour a question nobody has settled yet.",
]

# The chestnuts. Every model reaches for these unprompted, they are on every
# listicle, and a reader who has met one before reads the whole app as generic.
_OVERUSED = (
    "octopuses having three hearts, honey never spoiling, bananas being berries, "
    "sharks being older than trees, Cleopatra and the pyramids, the Great Wall being "
    "visible from space, the human body replacing all its cells, Napoleon's height, "
    "Vikings and horned helmets, and glass being a slow-flowing liquid"
)


def seeds(count: int, exclude: list[str], rng=None) -> tuple[str, str]:
    """Doors for the home screen.

    `rng` exists for the tests — pass a seeded random.Random to make the domain
    and angle draw reproducible. Production passes nothing and gets a fresh
    draw per call, which is the entire point of this function.
    """
    rng = rng or random
    picked = rng.sample(_DOMAINS, min(count, len(_DOMAINS)))
    angle = rng.choice(_ANGLES)

    system = (
        PERSONA
        + f" Produce {count} irresistible entry points into knowledge. "
        + "Take one from each of these domains, in order, and do not stray outside them: "
        + "; ".join(picked)
        + ". "
        + angle
        + " Each door must be specific enough to be a real subject, not a category — "
        "'The clock that runs on melting ice' works, 'Interesting facts about clocks' does not. "
        f"Never use the overused stock trivia: {_OVERUSED}. "
        + ("Avoid anything close to the excluded list. " if exclude else "")
        + _JSON_RULE
        + '{"seeds":[{"label": short enticing text max 8 words, "type": "fact"|"question"|"topic"}]}'
    )
    if exclude:
        user = (
            f"Excluded (already shown): {' | '.join(exclude)}.\n"
            f"Give me {count} new doors."
        )
    else:
        user = f"Give me today's {count} doors."
    return system, user


def page(label, kind, path: list[str], surprise: bool, exclude: list[str]) -> tuple[str, str]:
    if surprise:
        system = (
            PERSONA + _PAGE_SHAPE
            + " Choose ONE genuinely delightful topic from a domain entirely absent from the "
            "excluded list — something the user would never think to search for, but will be "
            "glad they found."
        )
        user = (
            f"Excluded territory: {' | '.join(exclude) or 'none'}.\n"
            "Surprise me. Pick the topic and generate its page."
        )
        return system, user

    system = (
        PERSONA + " For the item the user just tapped," + _PAGE_SHAPE
        + " Do not repeat recent steps in the path."
    )
    user = (
        f"Recent path: {' > '.join(path) or 'start'}.\n"
        f'The user tapped: "{label}" (kind: {kind}).\n'
        f'Generate the page for "{label}".'
    )
    return system, user


def more(title: str, said: str) -> tuple[str, str]:
    system = (
        PERSONA + " " + _JSON_RULE
        + '{"more": "3-4 vivid accurate sentences"}. '
        "Go one level deeper on the page — new detail, mechanism, or story. "
        "Do not repeat anything already said."
    )
    return system, f'Page: "{title}".\nAlready said: {said}\nTell me more.'


def ask(title: str, said: str, question: str) -> tuple[str, str]:
    system = (
        PERSONA + " " + _JSON_RULE
        + '{"answer": "2-4 clear accurate sentences"}. '
        "Answer the user's follow-up question in the context of the page."
    )
    return system, f'Page: "{title}".\nPage says: {said}\nFollow-up question: {question}'


def recap(path: list[str]) -> tuple[str, str]:
    system = (
        PERSONA + " " + _JSON_RULE
        + '{"synthesis": "3 warm sentences naming the thread that quietly connects this walk — '
        'a real intellectual connection, not flattery", '
        '"thread": "one open question worth carrying into tomorrow, under 15 words"}'
    )
    return system, f"The user wandered through, in order: {' > '.join(path)}.\nClose the wander."


def email_doors(topics: list[str], wildcard: bool, thread: str | None, count: int = 3):
    """Doors for the daily email, generated from the user's own stated topics.

    Note this is an *invitation*: the copy elsewhere never nags, and this prompt
    is told to write for someone who may not open it.
    """
    system = (
        PERSONA
        + f" Produce {count} irresistible entry points into knowledge for a specific reader, "
        "drawn from their stated interests. Each should stand alone and be worth a few minutes "
        "of wandering. Write for someone who may not read this today — no urgency, no hype. "
        + (
            "Include exactly one door from a domain completely unrelated to their interests, "
            "as a pleasant surprise. "
            if wildcard
            else ""
        )
        + f"Never use the overused stock trivia: {_OVERUSED}. "
        + _JSON_RULE
        + '{"seeds":[{"label": short enticing text max 8 words, "type": "fact"|"question"|"topic"}]}'
    )
    user = f"Their interests: {', '.join(topics) or 'general curiosity'}."
    if thread:
        user += f'\nAn open question they left hanging last time: "{thread}". You may build on it.'
    user += f"\nGive me {count + (1 if wildcard else 0)} doors."
    return system, user
