// node --test src/web/ : the web scheduler against what Anki's own engine showed for the same cards
// (default preset, values read from describe_next_states in a fresh collection).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { limits, label, outcomes, queue, newOrderFor, timing, revlogFor } from './sched.js'
import stock from './stock.json' with { type: 'json' }

const conf = stock.deck_configs[0]
const deck = stock.decks[0]
const t = { today: 100, now: 1_800_000_000, cutoff: 1_800_050_000 }
const newCard = { id: 1, nid: 1, did: 1, ord: 0, type: 0, queue: 0, due: 1, ivl: 0, factor: 0, reps: 0, lapses: 0, left: 0, odue: 0, odid: 0, flags: 0, data: '{}' }
const labels = (useFsrs, card) => outcomes(card, conf, deck, t, useFsrs).map((r) => label(r.secs, r.learning))
const days = (l) => Number(l.replace(/\D+/g, ''))

test('new card, SM-2: same buttons as Anki', () => {
  const l = labels(false, newCard)
  assert.deepEqual(l.slice(0, 3), ['<1\u00a0Min.', '<6\u00a0Min.', '<10\u00a0Min.'])
  assert.ok(Math.abs(days(l[3]) - conf.new.ints[1]) <= 1, l[3]) // Anki: 3 Tg. (easy interval 4, fuzzed)
})

test('new card, FSRS: learning steps like Anki, Easy graduates after about a week', () => {
  const l = labels(true, newCard)
  assert.deepEqual(l.slice(0, 3), ['<1 Min.', '<6 Min.', '<10 Min.'])
  assert.ok(Math.abs(days(l[3]) - 9) <= 1, l[3]) // Anki: 9 Tg.
})

test('FSRS: Good, Good graduates; Anki shows <1 Min. / <10 Min. / 2 Tg. / 3 Tg. on the second step', () => {
  const first = outcomes(newCard, conf, deck, t, true)[2].card // Good
  assert.equal(first.queue, 1)
  assert.equal(first.left, 1)
  const l = labels(true, first)
  assert.equal(l[0], '<1 Min.')
  assert.equal(l[1], '<10 Min.')
  assert.ok(Math.abs(days(l[2]) - 2) <= 1, l[2])
  assert.ok(Math.abs(days(l[3]) - 4) <= 2, l[3]) // Anki: 3 Tg.; about 4 days before fuzz (3–5)
  const data = JSON.parse(outcomes(first, conf, deck, t, true)[2].card.data)
  assert.ok(data.s > 0 && data.d > 0 && data.lrt === t.now) // memory state as Anki stores it in cards.data
})

test('SM-2 review: hard < good < easy, again relearns with a lapse', () => {
  const rev = { ...newCard, type: 2, queue: 2, due: t.today, ivl: 10, factor: 2500, reps: 5 }
  const [again, hard, good, easy] = outcomes(rev, conf, deck, t, false)
  assert.ok(Math.abs(hard.card.ivl - 12) <= 1 && Math.abs(good.card.ivl - 25) <= 2 && Math.abs(easy.card.ivl - 32) <= 2,
    `${hard.card.ivl} ${good.card.ivl} ${easy.card.ivl}`)
  assert.equal(good.card.due, t.today + good.card.ivl)
  assert.equal(JSON.parse(good.card.data).lrt, t.now) // else Anki's check database fills it in
  assert.deepEqual([again.card.type, again.card.queue, again.card.lapses, again.card.factor], [3, 1, 1, 2300])
  const log = revlogFor(rev, good, 3, 4000, t.now * 1000)
  assert.deepEqual([log.type, log.ivl, log.last_ivl], [1, good.card.ivl, 10])
})

test('queue: learning due now first, then reviews, then new, within limits', () => {
  const cards = [
    { ...newCard, id: 2, due: 5 }, { ...newCard, id: 3, due: 2 },
    { ...newCard, id: 4, type: 2, queue: 2, due: t.today - 1, ivl: 3 },
    { ...newCard, id: 5, type: 1, queue: 1, due: t.now - 5 },
    { ...newCard, id: 6, type: 2, queue: 2, due: t.today + 3 }, // not due
    { ...newCard, id: 7, queue: -1 }, // suspended
  ]
  const lim = { new: 1, review: 10 }
  const q = queue(cards, () => [lim], t)
  assert.deepEqual(q.cards.map((c) => c.id), [5, 4, 3])
  assert.deepEqual(q.counts, { new: 1, learn: 1, review: 1 })
})

test('queue: the limit of a parent deck caps its subdecks together', () => {
  const parent = { new: 3, review: 9 }, a = { new: 2, review: 9 }, b = { new: 2, review: 9 }
  const cards = [1, 2, 3, 4, 5, 6].map((id) => ({ ...newCard, id, due: id, did: id <= 3 ? 10 : 11 }))
  const q = queue(cards, (c) => [c.did === 10 ? a : b, parent], t)
  assert.deepEqual(q.cards.map((c) => c.id), [1, 2, 4]) // a's own limit 2, then the parent's 3 in total
})

test('queue: random notes mix the subdecks, deck order takes them one after the other', () => {
  const cards = [1, 2, 3, 4, 5, 6].map((id) => ({ ...newCard, id, nid: id, due: id, did: id <= 3 ? 10 : 11 }))
  const first3 = (order) => {
    const lim = { new: 3, review: 9 }
    return new Set(queue(cards, () => [lim], t, 1200, order).cards.map((c) => c.did))
  }
  const name = (did) => (did === 10 ? 'Bio::A' : 'Bio::B')
  assert.deepEqual(first3(newOrderFor(0, name)), new Set([10]))
  assert.equal(first3(newOrderFor(4, name, t.today)).size, 2)
})

test('limits count what was done today', () => {
  const d = { ...deck, newToday: [t.today, 15], revToday: [t.today - 1, 50] }
  assert.deepEqual(limits(d, conf, t.today), { new: conf.new.perDay - 15, review: conf.rev.perDay })
})

test('days since creation with a 4 o\'clock rollover', () => {
  const crt = new Date(2026, 0, 10, 4).getTime() / 1000
  assert.equal(timing(crt, 4, new Date(2026, 0, 10, 23).getTime() / 1000).today, 0)
  assert.equal(timing(crt, 4, new Date(2026, 0, 11, 3).getTime() / 1000).today, 0) // before 4:00: still yesterday
  assert.equal(timing(crt, 4, new Date(2026, 0, 11, 5).getTime() / 1000).today, 1)
  // crt isn't shifted by the rollover: 4:00 crt, rollover 7 → day 1 from 7:00 the next day (as Anki)
  assert.equal(timing(crt, 7, new Date(2026, 0, 11, 6).getTime() / 1000).today, 0)
  assert.equal(timing(crt, 7, new Date(2026, 0, 11, 8).getTime() / 1000).today, 1)
})

test('review in a filtered deck: the real due day counts, not the position (values from Anki)', () => {
  const card = { ...newCard, type: 2, queue: 2, ivl: 30, factor: 2500, reps: 5, due: -100000, odid: 9 }
  const [, hard, good] = outcomes({ ...card, odue: t.today }, conf, deck, t, false)
  assert.ok(Math.abs(hard.card.ivl - 36) <= 2, String(hard.card.ivl))
  assert.ok(Math.abs(good.card.ivl - 75) <= 4, String(good.card.ivl)) // not 100 years
  const early = outcomes({ ...card, odue: t.today + 20 }, conf, deck, t, false) // Anki: 18 Tg. / 30 Tg.
  assert.ok(Math.abs(early[1].card.ivl - 18) <= 1, String(early[1].card.ivl))
  assert.ok(Math.abs(early[2].card.ivl - 30) <= 2, String(early[2].card.ivl))
})

test('filtered deck without rescheduling: Again/Hard repeat, Good/Easy go home unchanged (as Anki)', () => {
  const card = { ...newCard, type: 2, queue: 2, ivl: 30, factor: 2500, reps: 5, lapses: 3, due: -100000, odue: 120, did: 9, odid: 7 }
  const [again, hard, good, easy] = outcomes(card, conf, { ...deck, dyn: 1, resched: false, previewAgainSecs: 60, previewHardSecs: 600 }, t, false)
  assert.deepEqual([again.card.queue, again.card.due - t.now, hard.card.due - t.now], [4, 60, 600])
  for (const r of [again, hard, good, easy]) assert.deepEqual([r.card.ivl, r.card.factor, r.card.lapses, r.card.reps], [30, 2500, 3, 5])
  assert.deepEqual([good.card.did, good.card.odid, good.card.odue, good.card.due, good.card.queue], [7, 0, 0, 120, 2])
  assert.equal(revlogFor(card, again, 1, 1000).ivl, -60)
  assert.equal(revlogFor(card, good, 3, 1000).ivl, 0)
  const q = queue([{ ...card, queue: 4, due: t.now - 1 }], () => [], t)
  assert.equal(q.counts.learn, 1)
})
