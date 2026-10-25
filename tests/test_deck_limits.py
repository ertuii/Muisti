import os
import tempfile

os.environ["MUISTI_DIR"] = tempfile.mkdtemp()

from muisti.core import Core


def test_limits_per_deck_and_mixed_subdecks():
    core = Core(os.path.join(tempfile.mkdtemp(), "collection.anki2"))
    top, a, other = (core.create_deck(n) for n in ("Bio", "Bio::A", "Chemie"))
    core.create_deck("Bio::B")
    for deck in ("Bio::A", "Bio::B"):
        for i in range(3):
            core.add_note("Basic", deck, [f"{deck} q{i}", "a"])

    # a deck's own limit leaves the shared preset and the other decks alone; subdecks only if asked
    o = core.deck_options(top)
    assert o["subdecks"] == 2
    core.save_deck_options(top, {**o, "limits": {**o["limits"], "new": 4}})
    assert core.deck_options(a)["limits"]["new"] is None
    assert core.deck_options(other)["new_per_day"] == 20 and core.deck_options(other)["limits"]["new"] is None
    core.save_deck_options(top, {**o, "limits": {**o["limits"], "new": 4}, "limits_to_subdecks": True})
    assert core.deck_options(a)["limits"]["new"] == 4
    assert core.deck_options(other)["limits"]["new"] is None

    # studying the parent mixes its subdecks (by default, once per collection)
    core.mix_subdecks_by_default()
    assert core.deck_options(top)["new_card_gather_priority"] == 4
    seen = set()
    for _ in range(4):
        c = core.next_card(top)
        seen.add(core._col.get_card(c["card_id"]).did)
        core.answer(c["card_id"], 3)
    assert len(seen) == 2

    # and a deliberate "deck by deck" stays
    core.save_deck_options(top, {**core.deck_options(top), "new_card_gather_priority": 0})
    core.mix_subdecks_by_default()
    assert core.deck_options(top)["new_card_gather_priority"] == 0


if __name__ == "__main__":
    test_limits_per_deck_and_mixed_subdecks()
    print("ok")
