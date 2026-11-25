import os
import tempfile
from pathlib import Path

os.environ["MUISTI_DIR"] = tempfile.mkdtemp()  # backups and sync.json go here, not into the real profile

from muisti.core import Core, data_dir


def test_phase2():
    core = Core(str(data_dir() / "collection.anki2"))
    deck = core.create_deck("Bio")
    for i in range(5):
        core.add_note("Basic", "Bio", [f"q{i}", f"a{i}"])

    # deck options + FSRS
    o = core.deck_options(deck)
    o.update(new_per_day=3, learn_steps=[1, 5], fsrs=True, desired_retention=0.85)
    core.save_deck_options(deck, o)
    o = core.deck_options(deck)
    assert (o["new_per_day"], o["learn_steps"], o["fsrs"], o["desired_retention"]) == (3, [1.0, 5.0], True, 0.85)
    assert core.decks()[0]["new"] == 3
    assert core.optimize_fsrs(deck)["changed"] is False  # too little history

    # filtered deck
    f = core.create_filtered_deck("Pauken", "deck:Bio", 2)
    assert core.next_card(f) is not None
    core.empty_filtered_deck(f)
    core.delete_deck(f)

    # note type edit: rename a field, add one, preview, save
    nt = next(t for t in core.note_types() if t["basic"])["id"]
    n = core.notetype(nt)
    n["fields"][1]["name"] = "Antwort"
    n["fields"].append({"ord": None, "name": "Quelle"})
    n["templates"][0]["afmt"] += "<br>{{Quelle}}"
    assert "(Quelle)" in core.preview_template(n, 0)["answer"]
    core.save_notetype(n)
    assert [f["name"] for f in core.notetype(nt)["fields"]][1:] == ["Antwort", "Quelle"]

    # statistics
    s = core.statistics(None, 30)
    assert len(s["future"]) == 30 and s["card_counts"]["new"] == 5
    assert len(s["minutes"]) == 30 and s["minutes"][-1] == s["today"]["minutes"]  # today is the last bar
    cid = core.search("")[0]["card_id"]
    core.suspend([cid])
    cc = core.statistics(None, 30)["card_counts"]
    assert cc["suspended"] == 1 and cc["new"] == 4
    core.suspend([cid], False)

    # backup + restore brings back the old state
    core.backup(True)
    path = core.backups()[0]["path"]
    core.add_note("Basic", "Bio", ["später", "x"])
    core.restore_backup(path)
    assert len(core.search("")) == 5
    core._close()


if __name__ == "__main__":
    test_phase2()
    print("ok")
