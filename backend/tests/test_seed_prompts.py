"""The seeds prompt is the home screen's variety knob.

The complaint these tests exist to prevent: home doors that "feel hard coded".
Half of that was a client bug; the other half was this prompt being byte-for-byte
identical on every call, which samples the same distribution every time.
"""

import random

from curio import prompts


class TestSeedPromptVaries:
    def test_two_calls_name_different_domains(self):
        # Not a taste judgement — just that consecutive calls aren't identical.
        # A fixed prompt is what made every hand of doors feel like the last one.
        systems = {prompts.seeds(4, [])[0] for _ in range(12)}
        assert len(systems) > 1

    def test_names_one_domain_per_door(self):
        system, _ = prompts.seeds(4, [], rng=random.Random(7))
        named = [d for d in prompts._DOMAINS if d in system]
        assert len(named) == 4

    def test_domains_are_distinct(self):
        for seed in range(25):
            system, _ = prompts.seeds(4, [], rng=random.Random(seed))
            named = [d for d in prompts._DOMAINS if d in system]
            assert len(named) == len(set(named))

    def test_count_larger_than_domain_list_does_not_raise(self):
        # rng.sample raises if asked for more than the population holds.
        system, _ = prompts.seeds(len(prompts._DOMAINS) + 5, [])
        assert system

    def test_seeded_rng_is_reproducible(self):
        a = prompts.seeds(4, [], rng=random.Random(3))
        b = prompts.seeds(4, [], rng=random.Random(3))
        assert a == b


class TestSeedPromptQualityRules:
    def test_bans_the_stock_trivia(self):
        system, _ = prompts.seeds(4, [])
        assert "octopuses having three hearts" in system
        assert "bananas being berries" in system

    def test_email_doors_ban_the_same_trivia(self):
        # Home and email generate the same shape; a chestnut banned from one and
        # allowed in the other is just an inconsistency waiting to be noticed.
        system, _ = prompts.email_doors(["history"], False, None)
        assert "octopuses having three hearts" in system

    def test_demands_subjects_not_categories(self):
        system, _ = prompts.seeds(4, [])
        assert "not to be a category" in system

    def test_exclude_list_is_carried_into_the_user_message(self):
        _, user = prompts.seeds(4, ["Why do we dream?", "The Radium Girls"])
        assert "Why do we dream?" in user
        assert "The Radium Girls" in user

    def test_no_exclude_list_asks_plainly(self):
        _, user = prompts.seeds(4, [])
        assert "Excluded" not in user

    def test_still_asks_for_bare_json(self):
        system, _ = prompts.seeds(4, [])
        assert "ONLY JSON" in system
        assert '"seeds"' in system


class TestTopicalSeeds:
    """The home-page row anchored to saved interests."""

    def test_topics_and_excludes_reach_the_user_message(self):
        _, user = prompts.topical_seeds(["deep sea biology"], ["shown already"])
        assert "deep sea biology" in user
        assert "shown already" in user

    def test_demands_adjacency_not_restatement(self):
        system, _ = prompts.topical_seeds(["old maps"], [])
        assert "adjacent" in system
        assert "never a restatement" in system

    def test_bans_stock_trivia_and_fabrication(self):
        system, _ = prompts.topical_seeds(["history"], [])
        assert "octopuses having three hearts" in system
        assert "real, verifiable subject" in system

    def test_seeded_rng_is_reproducible(self):
        a = prompts.topical_seeds(["x"], [], rng=random.Random(5))
        b = prompts.topical_seeds(["x"], [], rng=random.Random(5))
        assert a == b

    def test_angle_varies_between_calls(self):
        systems = {prompts.topical_seeds(["x"], [])[0] for _ in range(12)}
        assert len(systems) > 1


class TestAntiFabrication:
    """Every prompt inherits the no-invention clause; the risky ones add more.

    These pin wording deliberately: the counterweight to 'vivid, surprising,
    obscure' is these exact clauses, and losing one in a rewrite should fail
    a test, not a user."""

    def test_persona_forbids_invention(self):
        assert "Never invent names, dates, numbers" in prompts.PERSONA
        assert "certain is real" in prompts.PERSONA

    def test_ask_admits_uncertainty_rather_than_guessing(self):
        system, _ = prompts.ask("T", "said", "q?")
        assert "say so plainly instead of guessing" in system

    def test_seeds_require_real_subjects(self):
        system, _ = prompts.seeds(4, [])
        assert "real, verifiable subject" in system

    def test_email_doors_require_real_subjects(self):
        system, _ = prompts.email_doors(["history"], False, None)
        assert "real, verifiable subject" in system

    def test_risky_angles_were_tempered(self):
        joined = " ".join(prompts._ANGLES)
        assert "a person whose name has been forgotten" not in joined
        assert "real, documented person" in joined


class TestTermMarkers:
    """Deeper prose carries its tap-to-wander links as inline [[term]] markers.

    The client's parser is the only consumer, so the contract lives in the
    prompt wording: all four prose prompts (streaming and JSON fallback alike)
    must ask for the same marker syntax — a stream failure that falls back to
    JSON must not silently lose the links."""

    def test_all_four_prose_prompts_ask_for_markers(self):
        for system in (
            prompts.more("T", "said")[0],
            prompts.ask("T", "said", "q?")[0],
            prompts.more_prose("T", "said")[0],
            prompts.ask_prose("T", "said", "q?")[0],
        ):
            assert "[[Fritz Haber]]" in system
            assert "double square brackets" in system

    def test_page_blurb_does_not_use_markers(self):
        # The blurb's links come from the verified terms array instead;
        # markers leaking into the blurb prompt would render as raw brackets.
        system, _ = prompts.page("label", "topic", [], False, [])
        assert "[[" not in system
