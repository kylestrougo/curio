"""The page-contract check behind `flask bench-models`.

A benchmark that ranked purely on latency would happily recommend the fastest
model that returns four buttons, or a button type the UI has no colour for.
This gate is what makes the ranking mean "usable", so it is worth pinning.
"""
from curio.cli import _check_page_contract


def page(**over):
    p = {
        "title": "Why do we dream?",
        "blurb": "Dreams weave fears into narratives. They may integrate memories overnight.",
        "buttons": [
            {"label": "Dreams integrate memories", "type": "fact"},
            {"label": "Do dreams predict the future?", "type": "question"},
            {"label": "Lucid dreaming", "type": "topic"},
            {"label": "What triggers REM sleep?", "type": "question"},
            {"label": "REM was found in 1953", "type": "fact"},
        ],
    }
    p.update(over)
    return p


class TestAccepts:
    def test_a_good_page(self):
        assert _check_page_contract(page()) is None

    def test_a_long_but_tolerable_blurb(self):
        # The prompt asks for under 45 words; the gate only rejects well past
        # that, so ordinary overshoot doesn't disqualify an otherwise fine model.
        assert _check_page_contract(page(blurb=" ".join(["word"] * 50))) is None


class TestRejects:
    def test_not_an_object(self):
        assert _check_page_contract(["nope"]) == "not an object"

    def test_missing_title(self):
        assert _check_page_contract(page(title="")) == "no title"

    def test_whitespace_title(self):
        assert _check_page_contract(page(title="   ")) == "no title"

    def test_missing_blurb(self):
        assert _check_page_contract(page(blurb="")) == "no blurb"

    def test_buttons_absent(self):
        p = page()
        del p["buttons"]
        assert _check_page_contract(p) == "no buttons"

    def test_wrong_button_count(self):
        assert _check_page_contract(page(buttons=page()["buttons"][:4])) == "4 buttons, want 5"

    def test_unknown_button_type(self):
        bad = page()["buttons"]
        bad[2] = {"label": "Lucid dreaming", "type": "story"}
        assert "bad button type" in _check_page_contract(page(buttons=bad))

    def test_button_without_label(self):
        bad = page()["buttons"]
        bad[0] = {"type": "fact"}
        assert _check_page_contract(page(buttons=bad)) == "button without a label"

    def test_runaway_blurb(self):
        reason = _check_page_contract(page(blurb=" ".join(["word"] * 80)))
        assert "80 words" in reason
