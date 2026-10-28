"""Muisti account sync: two collections (two devices) on one account merge through Supabase.

Needs a confirmed test account: MUISTI_TEST_EMAIL / MUISTI_TEST_PASSWORD (skipped without, e.g. in forks).
The account's online rows are wiped first.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from anki.collection import Collection  # noqa: E402

from muisti import cloud  # noqa: E402

EMAIL, PASSWORD = os.environ.get("MUISTI_TEST_EMAIL"), os.environ.get("MUISTI_TEST_PASSWORD")
if not EMAIL:
    print("test_cloud: skipped (MUISTI_TEST_EMAIL not set)")
    sys.exit(0)


def device():
    d = Path(tempfile.mkdtemp())
    acc = cloud.Account(d)
    acc.login(EMAIL, PASSWORD)
    return Collection(str(d / "collection.anki2")), acc


col_a, acc_a = device()
token = acc_a.token()
for t in cloud.TABLES:  # start from an empty account
    cloud._http("DELETE", f"/rest/v1/{t}?user_id=not.is.null", token=token)

# A creates a deck and a card, syncs
did = col_a.decks.id("Bio::Zelle")
note = col_a.new_note(col_a.models.by_name("Basic"))
note["Front"], note["Back"] = "Mitochondrium", "Kraftwerk der Zelle"
col_a.add_note(note, did)
assert cloud.sync(col_a, acc_a)["sent"] > 0

# B (empty) gets everything, including day 0
col_b, acc_b = device()
time.sleep(1)
cloud.sync(col_b, acc_b)
assert col_b.crt == col_a.crt
assert col_b.decks.id_for_name("Bio::Zelle") == did
b_note = col_b.get_note(note.id)
assert b_note["Front"] == "Mitochondrium", b_note["Front"]
assert col_b.card_count() == 1
assert sorted(m["name"] for m in col_b.models.all()) == sorted(m["name"] for m in col_a.models.all())  # no "Basic+"

# B answers the card, A sees the review and the new schedule
col_b.decks.select(did)
card = col_b.sched.getCard()
assert card and card.nid == note.id
col_b.sched.answerCard(card, 3)
cloud.sync(col_b, acc_b)
cloud.sync(col_a, acc_a)
assert col_a.db.scalar("select count() from revlog") == 1
assert col_a.get_card(card.id).reps == 1

# both edit the same note: the later edit wins on both sides
n = col_a.get_note(note.id)
n["Back"] = "von A"
col_a.update_note(n)
time.sleep(1.1)  # mod is in seconds
n = col_b.get_note(note.id)
n["Back"] = "von B"
col_b.update_note(n)
cloud.sync(col_a, acc_a)
cloud.sync(col_b, acc_b)
cloud.sync(col_a, acc_a)
assert col_a.get_note(note.id)["Back"] == "von B"
assert col_b.get_note(note.id)["Back"] == "von B"

# nothing changed: nothing is sent, revlog isn't doubled
assert cloud.sync(col_a, acc_a)["sent"] == 0
assert col_a.db.scalar("select count() from revlog") == 1

# deleting on A removes it on B
col_a.remove_notes([note.id])
cloud.sync(col_a, acc_a)
cloud.sync(col_b, acc_b)
assert col_b.note_count() == 0 and col_b.card_count() == 0

# a fresh device joining the account doesn't overwrite its settings with the defaults of a new collection
conf = col_a.decks.get_config(1)
conf["new"]["perDay"] = 7
col_a.decks.save(conf)
cloud.sync(col_a, acc_a)
col_c, acc_c = device()
cloud.sync(col_c, acc_c)
assert col_c.decks.get_config(1)["new"]["perDay"] == 7
cloud.sync(col_a, acc_a)
assert col_a.decks.get_config(1)["new"]["perDay"] == 7

# deleting a note type reaches the other devices
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
nt = col_a.models.copy(col_a.models.by_name("Basic"))
cloud.sync(col_a, acc_a)
cloud.sync(col_b, acc_b)
assert col_b.models.get(nt["id"])
from muisti.core import Core  # noqa: E402

core_a = Core.__new__(Core)
core_a._col = col_a
Core.delete_notetype.__wrapped__(core_a, nt["id"])
cloud.sync(col_a, acc_a)
cloud.sync(col_b, acc_b)
assert not col_b.models.get(nt["id"])
assert col_a.get_config(cloud.GONE_NOTETYPES, None) is None
col_c.close()

# A's collection is replaced (Anki migration, .colpkg, AnkiWeb download): its rows come with old usns, all still reach B
sem = col_a.decks.id("Semester_3::Netze")
old = col_a.new_note(col_a.models.by_name("Basic"))
old["Front"], old["Back"] = "TCP", "verbindungsorientiert"
col_a.add_note(old, sem)
for t in cloud.LOCAL_TABLES:
    col_a.db.execute(f"update {t} set usn = 5")  # as synced with AnkiWeb before
col_a.remove_config(cloud.LINKED)  # a replaced collection never synced with this account
cloud.sync(col_a, acc_a)
cloud.sync(col_b, acc_b)
assert col_b.get_note(old.id)["Front"] == "TCP"
assert col_b.decks.id_for_name("Semester_3::Netze") == sem
assert col_a.get_config(cloud.LINKED) == acc_a.load()["user_id"]

# everything is still a valid Anki collection
for c in (col_a, col_b):
    problems, ok = c.fix_integrity()
    assert ok and problems.splitlines()[1:] == [], problems  # first line: "Database rebuilt and optimized."
    c.close()
print("test_cloud: ok")
