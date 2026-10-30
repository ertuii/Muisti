import json
import os
import tempfile

os.environ["MUISTI_DIR"] = tempfile.mkdtemp()

from muisti.core import Core


def new_core():
    return Core(os.path.join(tempfile.mkdtemp(), "collection.anki2"))


def test_a_changed_value_applies_to_this_deck_only():
    core = new_core()
    a, b = core.create_deck("A"), core.create_deck("B")
    for deck in ("A", "B"):
        for i in range(6):
            core.add_note("Basic", deck, [f"{deck} q{i}", "x"])
    preset = core.deck_options(a)["preset_id"]
    assert not core.deck_options(a)["individual"] and core.deck_options(a)["others"] >= 1

    o = core.deck_options(a)
    core.save_deck_options(a, {**o, "new_per_day": 4, "learn_steps": [5, 15]})
    oa, ob = core.deck_options(a), core.deck_options(b)
    assert oa["individual"] and oa["new_per_day"] == 4 and oa["learn_steps"] == [5, 15]
    assert oa["preset_id"] == preset and oa["base_preset_name"] == ob["base_preset_name"]
    assert not ob["individual"] and ob["new_per_day"] == 20 and ob["learn_steps"] != [5, 15]
    assert core.deck_options(a, preset)["new_per_day"] == 20  # the preset itself is untouched
    assert {d["name"]: d["new"] for d in core.decks()}["A"] == 4  # and scheduling follows
    assert {d["name"]: d["new"] for d in core.decks()}["B"] == 6

    # the hidden config never shows up as a preset, and is reused
    names = [p["name"] for p in oa["presets"]]
    assert not any(n.startswith("Individuell") for n in names), names
    core.save_deck_options(a, {**oa, "new_per_day": 5})
    configs = core._col.decks.all_config()
    assert len([c for c in configs if c["name"].startswith("Individuell")]) == 1
    assert core.deck_options(a)["new_per_day"] == 5

    # choosing the preset again takes its values
    chosen = core.deck_options(a, preset)
    assert not chosen["individual"] and chosen["new_per_day"] == 20
    core.save_deck_options(a, {**chosen, "use_preset": preset})
    oa = core.deck_options(a)
    assert not oa["individual"] and oa["new_per_day"] == 20 and oa["preset_id"] == preset

    # and a change after that is individual again, without the old values
    core.save_deck_options(a, {**oa, "reviews_per_day": 7})
    oa = core.deck_options(a)
    assert oa["individual"] and oa["reviews_per_day"] == 7 and oa["new_per_day"] == 20


def test_saving_overwrites_the_preset_and_the_deck_uses_it_again():
    core = new_core()
    a, b, c = (core.create_deck(n) for n in ("A", "B", "C"))
    core.save_deck_options(c, {**core.deck_options(c), "new_per_day": 3})  # individual: stays out of it
    core.save_deck_options(a, {**core.deck_options(a), "new_per_day": 9})
    o = core.deck_options(a)
    assert o["others"] >= 1  # at least B, the UI asks first
    core.overwrite_preset(a, o)
    oa = core.deck_options(a)
    assert not oa["individual"] and oa["new_per_day"] == 9
    assert core.deck_options(b)["new_per_day"] == 9
    assert core.deck_options(c)["new_per_day"] == 3 and core.deck_options(c)["individual"]


def test_today_only_does_not_make_a_deck_individual():
    core = new_core()
    a = core.create_deck("A")
    for i in range(6):
        core.add_note("Basic", "A", [f"q{i}", "x"])
    o = core.deck_options(a)
    core.save_deck_options(a, {**o, "use_preset": o["preset_id"], "limits": {**o["limits"], "new_today": 2}})
    o = core.deck_options(a)
    assert not o["individual"] and o["limits"]["new_today"] == 2 and o["new_per_day"] == 20
    assert next(d for d in core.decks() if d["id"] == a)["new"] == 2
    core.save_deck_options(a, {**o, "use_preset": o["preset_id"], "limits": {**o["limits"], "new_today": None}})
    assert core.deck_options(a)["limits"]["new_today"] is None
    assert next(d for d in core.decks() if d["id"] == a)["new"] == 6


def test_a_limit_from_before_moves_into_the_individual_options():
    core = new_core()
    a, b = core.create_deck("A"), core.create_deck("B")
    d = core._col.decks.get(a)
    d["newLimit"] = 4
    core._col.decks.save(d)
    o = core.deck_options(a)
    assert o["individual"] and o["new_per_day"] == 4
    assert not core.deck_options(b)["individual"]
    core.save_deck_options(a, o)
    assert core._col.decks.get(a).get("newLimit") is None
    assert core.deck_options(a)["new_per_day"] == 4 and core.deck_options(a)["individual"]


def test_subdecks_stay_alone_unless_asked_and_mixing_still_works():
    core = new_core()
    top, a, other = (core.create_deck(n) for n in ("Bio", "Bio::A", "Chemie"))
    core.create_deck("Bio::B")
    for deck in ("Bio::A", "Bio::B"):
        for i in range(3):
            core.add_note("Basic", deck, [f"{deck} q{i}", "a"])

    o = core.deck_options(top)
    assert o["subdecks"] == 2
    core.save_deck_options(top, {**o, "new_per_day": 4})
    assert not core.deck_options(a)["individual"] and core.deck_options(a)["new_per_day"] == 20
    assert not core.deck_options(other)["individual"]
    core.save_deck_options(top, {**core.deck_options(top), "limits_to_subdecks": True})
    assert core.deck_options(a)["individual"] and core.deck_options(a)["new_per_day"] == 4
    assert not core.deck_options(other)["individual"]

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


def test_a_new_preset_takes_the_values_in_the_form():
    core = new_core()
    a, b = core.create_deck("A"), core.create_deck("B")
    core.new_preset(a, "Klausur", {**core.deck_options(a), "new_per_day": 50})
    o = core.deck_options(a)
    assert not o["individual"] and o["base_preset_name"] == "Klausur" and o["new_per_day"] == 50
    assert core.deck_options(b)["new_per_day"] == 20


def test_individual_options_are_sent_to_other_devices():
    from muisti import cloud

    core = new_core()
    a = core.create_deck("A")
    core.save_deck_options(a, {**core.deck_options(a), "new_per_day": 4})
    sent = {}
    real = cloud._upsert
    cloud._upsert = lambda token, table, rows, ignore=False: sent.setdefault(table, []).extend(rows)
    try:
        cloud._push(core._col, "token", "device", crt=False)
    finally:
        cloud._upsert = real
    hidden = [r for r in sent["deck_configs"] if r["data"]["name"].startswith("Individuell")]
    assert hidden and hidden[0]["data"]["new"]["perDay"] == 4
    assert next(r for r in sent["decks"] if r["id"] == a)["data"]["conf"] == hidden[0]["id"]
    assert any(r["key"] == core._BASE and json.dumps(r["val"]) for r in sent["config"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
