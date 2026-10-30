"""Exam dates, study plan, weak spots, Claude inbox, difficult cards."""

import datetime
import os
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["MUISTI_DIR"] = str(HOME / "data")

from muisti.core import Core, collection_path  # noqa: E402

core = Core(collection_path())
col = core._col

# features: off by default except the inbox
assert core.features() == {"exams": False, "plan": False, "weak": False, "inbox": True, "hard_wrong": False}
core.save_features({"exams": True, "plan": True, "weak": True})
assert core.features()["exams"] and core.overview()["features"]["weak"]

# 1. exam: 40 new cards, exam in 20 days -> buffer 4 days -> 3 a day
bio = core.create_deck("Bio")
for i in range(40):
    core.add_note("Basic", "Bio", [f"Frage {i}", "Antwort"], ["zelle"] if i < 20 else ["genetik"])
core.set_exam(bio, (datetime.date.today() + datetime.timedelta(days=20)).isoformat())
plan = core.exam_plan()[0]
assert (plan["new_left"], plan["days"], plan["buffer"], plan["per_day"]) == (40, 20, 4, 3), plan
assert core.apply_exam_pace(bio) == 3
assert core.decks()[0]["new"] == 3 or next(d for d in core.decks() if d["id"] == bio)["new"] == 3
assert core.exam_plan()[0]["current"] == 3
assert core.overview()["exams"][0]["deck_id"] == bio

# 2. study plan: the exam deck comes before others
core.create_deck("Andere")
core.add_note("Basic", "Andere", ["x", "y"])
c = core.plan_next()
assert c["deck"] == "Bio", c

# 3. weak spots: fake review history, 'zelle' forgotten, 'genetik' remembered
cards = {col.get_note(n).tags[0]: [] for n in col.find_notes('"deck:Bio"')}
for cid in col.find_cards('"deck:Bio"'):
    cards[col.get_card(cid).note().tags[0]].append(cid)
rid = (col.sched.day_cutoff - 86400) * 1000
for tag, ease in (("zelle", 1), ("genetik", 3)):
    for cid in cards[tag]:
        rid += 1
        col.db.execute("insert into revlog values (?,?,-1,?,1,1,2500,1000,1)", rid, cid, ease)
w = core.weak_spots()
assert w["spots"][0] == {"kind": "tag", "name": "zelle", "reviews": 20, "retention": 0}, w["spots"][0]
assert w["overall"] == 50
col.db.execute("update cards set type = 2, queue = 2, due = ?, ivl = 3, lapses = 3 where id in (%s)" % ",".join(map(str, cards["zelle"])), col.sched.today + 5)
p = core.practice("tag", "zelle")
assert p["count"] == 20 and p["name"] == "Üben: zelle"
core.end_prelearn(p["deck_id"])
assert not col.decks.by_name("Üben: zelle")

core.save_features({"hard_wrong": True})  # "Schwer" counts as wrong: the same answers now pull the average down
rid = (col.sched.day_cutoff - 86400) * 1000 + 1000
for cid in cards["genetik"][:5]:
    rid += 1
    col.db.execute("insert into revlog values (?,?,-1,2,1,1,2500,1000,1)", rid, cid)
assert core.weak_spots()["overall"] < 50 and core.overview()["retention"] < 50
assert core.statistics()["hard_wrong"] is True
core.save_features({"hard_wrong": False})
assert core.weak_spots()["overall"] > 50
p = core.practice("tag", "zelle", 365)  # the period the statistics show
assert p["count"] == 20
n = core.next_card(p["deck_id"])  # practice leaves the schedule alone
before = col.db.first("select due, ivl, lapses, reps from cards where id = ?", n["card_id"])
due = col.get_card(n["card_id"]).odue
core.answer(n["card_id"], 3)
c = col.get_card(n["card_id"])
assert (c.due, c.ivl, c.lapses, c.reps, c.odid) == (due, before[1], before[2], before[3], 0)
core.end_prelearn(p["deck_id"])

# 5. difficult cards
d = core.difficult_cards("Bio", 5)
assert len(d) == 5 and d[0]["lapses"] == 3 and len(d[0]["fields"]) == 2, d[0]

# 4. inbox: Claude's cards wait suspended, accept/reject
n1 = core.add_note("Basic", "Bio", ["Mitochondrium", "Kraftwerk"], ["zelle"], inbox=True)
n2 = core.add_note("Basic", "Bio", ["Ribosom", "Proteine"], inbox=True)
assert core.inbox_count() == 2 and core.overview()["inbox"] == 2
assert all(col.get_card(c).queue == -1 for c in col.card_ids_of_note(n1))
assert core.inbox()[0]["tags"] in (["zelle"], [])
core.accept_inbox([n1])
assert core.inbox_count() == 1 and col.get_note(n1).tags == ["zelle"]
assert all(col.get_card(c).queue == 0 for c in col.card_ids_of_note(n1))
core.update_note(n2, tags=["selbst"])  # tag removed in the editor = accepted
assert core.inbox_count() == 0 and col.get_card(col.card_ids_of_note(n2)[0]).queue == 0
n2 = core.add_note("Basic", "Bio", ["Ribosom", "Proteine"], inbox=True)
core.update_note(n2, fields={"Back": "Proteinsynthese"})  # editing alone keeps it in the inbox
assert core.inbox_count() == 1
core.reject_inbox([n2])
assert core.inbox_count() == 0
core.save_features({"inbox": False})
n3 = core.add_note("Basic", "Bio", ["Kern", "DNA"], inbox=True)
assert core.inbox_count() == 0 and col.get_card(col.card_ids_of_note(n3)[0]).queue == 0

# reset a deck's progress (Anki's "Forget"), undoable
d = col.decks.get(bio)
d["newToday"] = [col.sched.today, 9999]  # today's new limit used up
col.decks.save(d)
assert core.reset_deck(bio) == len(col.decks.cids(bio, children=True))
assert not col.find_cards('"deck:Bio" -is:new')
assert next(x for x in core.decks() if x["id"] == bio)["new"] > 0  # reset cards are due again today
assert col.get_card(cards["zelle"][0]).lapses == 0
assert core.undo() and col.find_cards('"deck:Bio" -is:new')

# local server: requests with a foreign Host header (DNS rebinding) are refused
import http.client  # noqa: E402

from muisti import server  # noqa: E402

port = int(server.start(core).rsplit(":", 1)[1].strip("/"))
for host, refused in ((f"127.0.0.1:{port}", False), (f"localhost:{port}", False), (f"evil.example:{port}", True)):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/", headers={"Host": host})
    assert (conn.getresponse().status == 403) == refused, host  # "/" is 404 in CI before the UI is built
server.stop()

core.set_exam(bio, None)
assert core.exam_plan() == []
core._close()
print("ok")
