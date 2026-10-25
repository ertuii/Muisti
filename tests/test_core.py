import os
import tempfile
from pathlib import Path

from muisti.core import Core, data_dir


def test_roundtrip():
    tmp = Path(tempfile.mkdtemp())
    core = Core(str(tmp / "c.anki2"))
    deck = core.create_deck("Spanisch::Verben")
    nid = core.add_note("Basic", "Spanisch::Verben", {"Front": "hablar", "Back": "sprechen"}, ["verb"])

    assert core.stats()["due_today"] == 1
    card = core.next_card(deck)
    assert "hablar" in card["question"] and "sprechen" in card["answer"]
    assert len(card["buttons"]) == 4
    core.answer(card["card_id"], 3)
    ov = core.overview()
    assert ov["past"][-1] == 1 and ov["streak"] == 1, ov
    assert core.search("deck:Spanisch")[0]["reps"] == 1

    core.update_note(nid, {"Back": "reden"}, ["verb", "a1"])
    assert list(core.get_note(nid)["fields"].values())[1] == "reden"
    assert core.undo()  # undo the update

    out = str(tmp / "x.apkg")
    core.export_deck(out, deck)
    core.delete_notes([nid])
    assert core.search("") == []
    assert "1 neu" in core.import_file(out)
    core._close()


def test_data_dir_moves_betteranki_folder():
    tmp = Path(tempfile.mkdtemp())
    saved = dict(os.environ)
    os.environ.pop("MUISTI_DIR", None)
    os.environ["HOME"] = os.environ["USERPROFILE"] = os.environ["APPDATA"] = str(tmp)
    try:
        base = data_dir().parent
        (base / "Muisti").rmdir()  # first start after the rename: only the old folder exists
        (base / "BetterAnki").mkdir()
        (base / "BetterAnki" / "collection.anki2").write_text("x")
        d = data_dir()
        assert d.name == "Muisti" and (d / "collection.anki2").read_text() == "x"
        assert not (base / "BetterAnki").exists()
        (base / "BetterAnki").mkdir()  # both exist: leave the old one alone
        assert data_dir() == d and (base / "BetterAnki").exists()
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_language():
    path = str(Path(tempfile.mkdtemp()) / "c.anki2")
    core = Core(path)
    assert core.language() is None
    core.set_language("es")  # Anki's own strings follow, the collection stays usable
    assert core._col.tr.statistics_reviews(reviews=3) == "⁨3⁩ repasos"
    core.create_deck("Verbos")
    core._close()
    core = Core(path)  # remembered across restarts
    assert core.language() == "es" and core._col.tr.statistics_reviews(reviews=3) == "⁨3⁩ repasos"
    core.set_language("de")
    core._close()


if __name__ == "__main__":
    test_roundtrip()
    test_data_dir_moves_betteranki_folder()
    test_language()
    print("ok")
