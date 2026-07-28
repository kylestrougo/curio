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
        assert "not a category" in system

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
