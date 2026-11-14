"""Deck order and reparenting by drag & drop, the archive, exam pace that follows the plan, first run."""

import datetime
import os
import tempfile
from pathlib import Path

os.environ["MUISTI_DIR"] = str(Path(tempfile.mkdtemp()) / "data")

from muisti.core import Core, collection_path  # noqa: E402

core = Core(collection_path())
assert core.overview()["first_run"]
core.save_features({"exams": True})
assert not core.overview()["first_run"]

a, b, c = (core.create_deck(n) for n in ("A", "B", "C"))
names = lambda: [d["name"] for d in core.decks() if d["id"] in (a, b, c)]  # noqa: E731
assert names() == ["A", "B", "C"]
core.move_deck(c, None, [c, a, b])  # C to the top
assert names() == ["C", "A", "B"]
core.move_deck(b, a, [c, a, b])  # B into A
tree = {d["name"]: d for d in core.decks()}
assert [x["name"] for x in tree["A"]["children"]] == ["A::B"]

basic = next(t for t in core.note_types() if t["basic"])["id"]
for i in range(40):
    core.add_note(basic, b, [f"q{i}", "a"])
due = core.overview()["due"]
assert due > 0
core.set_archived(b, True)  # a subdeck goes to the top level on its way into the archive
arch = next(d for d in core.decks() if d["id"] == b)
assert arch["name"] == "B" and arch["archived"] and core.overview()["due"] == 0 and core.plan_next() is None
core.set_archived(b, False)
assert core.overview()["due"] == due

# exam in 20 days, 40 new cards: 3 a day; on automatic the limit follows when cards are added
core.set_exam(b, (datetime.date.today() + datetime.timedelta(days=20)).isoformat())
core.set_exam_auto(b, True)
plan = core.exam_plan()[0]
assert plan["auto"] and plan["current"] == plan["per_day"] == 3 and core.deck_options(b)["exam_auto"]
for i in range(40):
    core.add_note(basic, b, [f"r{i}", "a"])
assert core.overview()["exams"][0]["current"] == 5
core.set_exam(b, None)
assert not core.deck_options(b)["exam_auto"]
print("ok")
