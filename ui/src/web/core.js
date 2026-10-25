// The web app's stand-in for src/muisti/core.py: same method names, same return shapes, so the Svelte views
// work unchanged. Data lives in db.js (Supabase rows mirrored in memory). Everything frequent runs here;
// rarer actions that need Anki's own engine (statistics, deck options, note types, import/export, …) go to the
// worker (web-api/worker.py), which runs core.py itself: api.js sends every method this file lacks there.
import { S, write, pull, flush, sb, mediaUrls, uploadMedia, unsynced, userId } from './db.js'
import { renderCard, stripHtml, clozeNumbers, clozeTexts, compareAnswer } from './render.js'
import { timing, limits, queue, newOrderFor, outcomes, label, revlogFor, isLeech } from './sched.js'
import { search as runSearch } from './search.js'
import { lang, t as tr } from '../lib/i18n.js'

const INBOX_TAG = 'Claude-Eingang'
const FEATURES = { exams: false, plan: false, weak: false, inbox: true }
const EXAMS = 'betteranki.exams' // {deck_id: "YYYY-MM-DD"}, same key as the desktop
const now = () => Math.floor(Date.now() / 1000)
const cfg = (key, dflt) => (S.config.has(key) ? S.config.get(key).val : dflt)
const setCfg = (key, val) => write('config', [{ key, val, mod: now() }])
const deckOf = (id) => S.decks.get(Number(id))?.data
const confOf = (deck) => S.deck_configs.get(deck?.conf ?? 1)?.data ?? S.deck_configs.get(1).data
const nt = (id) => S.notetypes.get(Number(id))?.data
const tagsOf = (note) => note.tags.trim().split(/\s+/).filter(Boolean)
const tagStr = (tags) => (tags.length ? ` ${tags.join(' ')} ` : '')
const t = () => timing(cfg('_crt', now()), cfg('rollover', 4))
let lastId = 0
const newId = () => (lastId = Math.max(Date.now(), lastId + 1))

function saveDeck(d) {
  d.mod = now()
  write('decks', [{ id: d.id, data: d, mod: d.mod }])
}
function saveCards(cards) {
  const m = now()
  write('cards', cards.map((c) => ({ ...c, mod: m })))
}

// ---------- decks ----------

function subtree(id) {
  const name = deckOf(id).name
  return new Set([...S.decks.values()].filter((d) => d.data.name === name || d.data.name.startsWith(name + '::')).map((d) => d.id))
}

function cardsIn(ids) {
  return [...S.cards.values()].filter((c) => ids.has(c.did))
}

/** A deck and its parents, nearest first. */
function chainOf(d) {
  const byName = new Map([...S.decks.values()].map((r) => [r.data.name, r.data]))
  const parts = d.name.split('::')
  return parts.map((_, i) => byName.get(parts.slice(0, parts.length - i).join('::'))).filter(Boolean)
}

/**
 * For queue(): the remaining limits of a card's deck and its parents up to the studied deck (filtered decks
 * have none); the parents above it too if "apply all parent limits" is on, like Anki's v3.
 */
function limitsFor(tm, rootId) {
  const left = new Map()
  const of = (d) => {
    if (!left.has(d.id)) left.set(d.id, limits(d, confOf(d), tm.today))
    return left.get(d.id)
  }
  const depth = (d) => d.name.split('::').length
  const top = cfg('applyAllParentLimits', false) ? 1 : depth(deckOf(rootId))
  return (c) => {
    const d = deckOf(c.did)
    if (!d || d.dyn) return []
    return chainOf(d).filter((p) => depth(p) >= top).map(of)
  }
}

function studyQueue(deck_id, tm) {
  const name = (did) => deckOf(did)?.name ?? ''
  const order = newOrderFor(confOf(deckOf(deck_id)).newGatherPriority ?? 0, name, tm.today)
  return queue(cardsIn(subtree(deck_id)), limitsFor(tm, deck_id), tm, cfg('collapseTime', 1200), order)
}
const countsFor = (id, tm) => studyQueue(id, tm).counts

export function decks() {
  const tm = t()
  const all = [...S.decks.values()].map((r) => r.data).sort((a, b) => a.name.localeCompare(b.name, 'de'))
  const byName = new Map()
  const roots = []
  for (const d of all) {
    if (d.id === 1 && all.length > 1 && !cardsIn(new Set([1])).length) continue // Anki hides an empty Default
    const c = countsFor(d.id, tm)
    const node = { id: d.id, name: d.name, short: d.name.split('::').pop(), ...c, collapsed: !!d.collapsed, filtered: !!d.dyn, children: [] }
    byName.set(d.name, node)
    const parent = byName.get(d.name.split('::').slice(0, -1).join('::'))
    ;(parent ? parent.children : roots).push(node)
  }
  return roots
}

export function create_deck(name) {
  name = name.trim()
  const parts = name.split('::')
  let id
  for (let i = 1; i <= parts.length; i++) { // parents too, like Anki
    const n = parts.slice(0, i).join('::')
    const found = [...S.decks.values()].find((d) => d.data.name === n)
    if (found) { id = found.id; continue }
    const base = deckOf(1)
    id = newId()
    saveDeck({ ...structuredClone(base), id, name: n, conf: 1, newToday: [0, 0], revToday: [0, 0], lrnToday: [0, 0], timeToday: [0, 0], desc: '', collapsed: false })
  }
  return id
}

export function rename_deck(deck_id, name) {
  const old = deckOf(deck_id).name
  for (const r of S.decks.values()) {
    const d = r.data
    if (d.name === old || d.name.startsWith(old + '::')) saveDeck({ ...d, name: name.trim() + d.name.slice(old.length) })
  }
}

export function delete_deck(deck_id) {
  const ids = subtree(deck_id)
  delete_notes([...new Set(cardsIn(ids).map((c) => c.nid))])
  write('decks', [...ids].filter((id) => id !== 1).map((id) => ({ id, mod: now(), data: deckOf(id), deleted: true })))
}

export function set_collapsed(deck_id, collapsed) {
  saveDeck({ ...deckOf(deck_id), collapsed })
}

export function reset_deck(deck_id) {
  const cards = cardsIn(subtree(deck_id))
  forget_cards(cards.map((c) => c.id))
  const today = t().today
  for (const id of subtree(deck_id)) saveDeck({ ...deckOf(id), newToday: [today, 0], revToday: [today, 0] })
  return cards.length
}

// ---------- studying ----------

let current = null // {card, results, typed, shown}
let undoStack = [] // answers to take back, newest last

const study = (conf) => ({
  autoplay: conf.autoplay ?? true, show_timer: !!conf.timer, stop_timer_on_answer: conf.stopTimerOnAnswer ?? false,
  cap_secs: conf.maxTaken ?? 60, seconds_question: conf.secondsToShowQuestion ?? 0, seconds_answer: conf.secondsToShowAnswer ?? 0,
  question_action: conf.questionAction ?? 0, answer_action: conf.answerAction ?? 0, wait_for_audio: conf.waitForAudio ?? true,
})

/** Media references (src="x.jpg", [sound:x.mp3]) → signed URLs of the private bucket. */
const MEDIA = /(src=["'])(?!https?:|data:|blob:|\/)([^"']+)(["'])|\[sound:([^\]]+)\]/g
async function withUrls(html) {
  const names = [...html.matchAll(MEDIA)].map((m) => decodeURIComponent(m[2] ?? m[4]))
  if (!names.length) return html
  const urls = await mediaUrls(names)
  return html.replace(MEDIA, (all, a, name, b, sound) => {
    const u = urls.get(decodeURIComponent(name ?? sound))
    return !u ? all : sound ? `[sound:${u}]` : `${a}${u}${b}`
  })
}
async function toNames(html) {
  const urls = await mediaUrls([])
  for (const [name, u] of urls) html = html.split(u).join(name)
  return html
}

const TYPE = /\[\[type:(.+?)\]\]/

function typeAnswer(note, fields, ord, question, answer) {
  const m = TYPE.exec(question)
  if (!m) return [question, answer.replace(/\[\[type:.+?\]\]/g, ''), null]
  let fld = m[1], isCloze = false, combining = true
  if (fld.startsWith('cloze:')) [isCloze, fld] = [true, fld.slice(6)]
  if (fld.startsWith('nc:')) [combining, fld] = [false, fld.slice(3)]
  if (!(fld in fields)) return [question.replace(TYPE, `<p>Feld „${fld}“ zum Eintippen gibt es nicht.</p>`), answer.replace(/\[\[type:.+?\]\]/g, ''), null]
  const expected = isCloze ? clozeTexts(fields[fld], ord + 1).join(', ') : fields[fld]
  const input = '<input id="typeans" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">'
  return [question.replace(TYPE, input), answer.replace(TYPE, '[[typeans]]'), { expected, combining }]
}

export async function next_card(deck_id) {
  const tm = t()
  const d = deckOf(deck_id)
  const q = studyQueue(deck_id, tm)
  if (!q.cards.length) return (current = null)
  const card = q.cards[0]
  const note = S.notes.get(card.nid)
  const type = nt(note.mid)
  const cdeck = deckOf(card.did) ?? d
  const cconf = confOf(deckOf(card.odid) ?? cdeck)
  const results = outcomes(card, cconf, cdeck, tm, cfg('fsrs', false))
  const opts = study(cconf)
  const r = renderCard({ ord: card.ord, note, nt: type, deck: cdeck.name, autoplay: opts.autoplay })
  const [question, answer, typed] = typeAnswer(note, r.fields, card.ord, r.question, r.answer)
  current = { card, results, typed, shown: Date.now(), cap: opts.cap_secs }
  return {
    card_id: card.id, note_id: card.nid, ord: card.ord,
    question: await withUrls(question), answer: await withUrls(answer), type_answer: !!typed, css: r.css,
    buttons: results.map((x) => label(x.secs, x.learning, (s, { n }) => tr(s, { n: n.toLocaleString(lang) }))),
    counts: q.counts, queue: card.queue === 3 ? 1 : card.queue, study: opts,
  }
}

export function compare_answer(card_id, typed) {
  if (!current || current.card.id !== card_id || !current.typed) throw new Error('card is no longer current')
  return compareAnswer(current.typed.expected, typed, current.typed.combining)
}

export function leave_study() {
  current = null
}

export function answer(card_id, ease) {
  if (!current || current.card.id !== card_id) throw new Error('card is no longer current')
  const before = current.card
  const res = current.results[ease - 1]
  const card = { ...res.card }
  const deck = deckOf(before.did)
  const conf = confOf(deckOf(before.odid) ?? deck)
  const ms = Math.min(Date.now() - current.shown, current.cap * 1000)
  const log = { ...revlogFor(before, res, ease, ms), mod: 0 }
  if (card.queue === 2 && before.odid) Object.assign(card, { did: before.odid, odid: 0, odue: 0 }) // done in a filtered deck: home again
  const note = S.notes.get(before.nid)
  let noteAfter = null
  if (ease === 1 && card.type === 3 && isLeech(card, conf)) { // Anki: tag "leech", suspend if the preset says so
    noteAfter = { ...note, tags: tagStr([...new Set([...tagsOf(note), 'leech'])]), mod: now() }
    if (conf.lapse.leechAction === 0) card.queue = -1
  }
  const tm = t()
  const field = before.type === 0 ? 'newToday' : before.queue === 2 || before.queue === 3 ? 'revToday' : null
  // Anki counts the answer against the card's deck and all its parents
  const chain = chainOf(deck)
  const decksBefore = structuredClone(chain)
  if (field) for (const d of chain) {
    const [day, n] = d[field] ?? [tm.today, 0]
    saveDeck({ ...d, [field]: [tm.today, (day === tm.today ? n : 0) + 1] })
  }
  // Anki's "bury siblings": the note's other cards wait until tomorrow, as the preset says
  const siblings = cardsOf(before.nid).filter((c) => c.id !== before.id && (
    (c.queue === 0 && conf.new.bury) || (c.queue === 2 && conf.rev.bury) || (c.queue === 3 && conf.buryInterdayLearning)))
  undoStack = [...undoStack.slice(-19), { card: before, decks: decksBefore, log, note: noteAfter && note, siblings }]
  saveCards([card, ...siblings.map((c) => ({ ...c, queue: -2 }))])
  write('revlog', [log])
  if (noteAfter) write('notes', [noteAfter])
  current = null
}

export function undo() {
  const last = undoStack.pop()
  if (!last) return null
  const { card, decks: before, log, note, siblings } = last
  saveCards([card, ...siblings])
  before.forEach(saveDeck)
  write('revlog', [{ ...log, mod: 1, deleted: true }])
  if (note) write('notes', [{ ...note, mod: now() }])
  return 'Antwort'
}

export function bury_card(card_id) {
  saveCards([{ ...S.cards.get(card_id), queue: -3 }])
}

export function suspend(card_ids, suspended = true) {
  saveCards(card_ids.map((id) => S.cards.get(id)).map((c) => ({ ...c, queue: suspended ? -1 : restoreQueue(c) })))
}

// where a suspended/buried card goes back to; intraday learning is due in epoch seconds, interday in days
const homeQueue = (c) => (c.type === 0 ? 0 : c.type === 2 ? 2 : c.due > 1e9 ? 1 : 3)
const restoreQueue = (c) => (c.queue >= 0 ? c.queue : homeQueue(c))

export function suspend_note(note_id) {
  suspend(cardsOf(note_id).map((c) => c.id))
}

const cardsOf = (nid) => [...S.cards.values()].filter((c) => c.nid === nid)

// Anki unburies at the start of a new day; the web does it when the day changes
let unburiedOn = null
function unburyIfNewDay() {
  const today = t().today
  if (unburiedOn === today) return
  unburiedOn = today
  const buried = [...S.cards.values()].filter((c) => c.queue === -2 || c.queue === -3)
  if (buried.length && cfg('_lastUnburied', -1) < today) {
    saveCards(buried.map((c) => ({ ...c, queue: homeQueue(c) })))
    setCfg('_lastUnburied', today)
  }
}

// ---------- notes ----------

export async function note_types() {
  if (![...S.notetypes.values()].some((r) => r.data.originalStockKind === 6)) await worker('note_types') // adds Anki's image occlusion type
  return [...S.notetypes.values()].map((r) => r.data).map((m) => ({
    id: m.id, name: m.name, fields: m.flds.map((f) => f.name), cloze: m.type === 1,
    basic: m.originalStockKind === 1, io: m.originalStockKind === 6,
  }))
}

function notetypeOf(notetype) {
  const all = [...S.notetypes.values()].map((r) => r.data)
  const m = typeof notetype === 'number' ? nt(notetype) : all.find((x) => x.name === notetype)
    ?? all.find((x) => x.originalStockKind === (notetype === 'Cloze' ? 5 : notetype === 'Basic' ? 1 : -1))
  if (!m) throw new Error(`unknown note type: ${notetype}`)
  return m
}

async function sha1int(text) {
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text))
  return parseInt([...new Uint8Array(buf)].slice(0, 4).map((b) => b.toString(16).padStart(2, '0')).join(''), 16)
}

function fieldList(m, fields) {
  const names = m.flds.map((f) => f.name)
  const aliases = { Front: 0, Text: 0, Back: 1, 'Back Extra': 1 }
  const out = names.map(() => '')
  for (let [k, v] of Object.entries(fields)) {
    if (!names.includes(k) && aliases[k] < names.length) k = names[aliases[k]]
    if (!names.includes(k)) throw new Error(`unknown field '${k}', expected one of ${names}`)
    out[names.indexOf(k)] = v
  }
  return out
}

/** Which card ordinals a note has (Anki: a template whose front isn't empty; cloze: one per number). */
function ordsFor(m, flds) {
  if (m.type === 1) return [...new Set(m.flds.flatMap((_, i) => clozeNumbers(flds[i])))].sort((a, b) => a - b).map((n) => n - 1)
  const note = { flds: flds.join('\x1f'), tags: '' }
  const emptyNote = { flds: flds.map(() => '').join('\x1f'), tags: '' }
  return m.tmpls.map((_, ord) => ord).filter((ord) =>
    renderCard({ ord, note, nt: m, deck: '' }).question !== renderCard({ ord, note: emptyNote, nt: m, deck: '' }).question)
}

function newCard(nid, did, ord) {
  const pos = cfg('nextPos', 1)
  setCfg('nextPos', pos + 1)
  return { id: newId(), nid, did, ord, mod: now(), type: 0, queue: 0, due: pos, ivl: 0, factor: 0, reps: 0, lapses: 0, left: 0, odue: 0, odid: 0, flags: 0, data: '{}' }
}

async function noteRow(m, flds, tags, base = {}) {
  return {
    guid: Math.random().toString(36).slice(2, 12), flags: 0, data: '', ...base,
    mid: m.id, mod: now(), flds: flds.join('\x1f'), tags: tagStr(tags),
    sfld: stripHtml(flds[m.sortf] ?? flds[0]), csum: await sha1int(stripHtml(flds[0])),
  }
}

export async function duplicate_of(notetype, first_field, note_id = null) {
  const mid = note_id ? S.notes.get(note_id).mid : notetypeOf(notetype).id
  const first = stripHtml(first_field)
  if (!first) return null
  const csum = await sha1int(first)
  return [...S.notes.values()].find((n) => n.mid === mid && n.csum === csum && n.id !== note_id && stripHtml(n.flds.split('\x1f')[0]) === first)?.id ?? null
}

export async function add_note(notetype, deck, fields, tags = [], inbox = false) {
  const m = notetypeOf(notetype)
  const flds = await Promise.all((Array.isArray(fields) ? fields : fieldList(m, fields)).map(toNames))
  if (!flds[0].trim()) throw new Error('first field must not be empty')
  const did = typeof deck === 'number' ? deck : create_deck(deck)
  const ords = ordsFor(m, flds)
  if (!ords.length) throw new Error(m.type === 1 ? 'Kein Lückentext gefunden: markiere etwas mit {{c1::…}}.' : 'Diese Felder ergeben keine Karte.')
  const note = { id: newId(), ...(await noteRow(m, flds, [...tags, ...(inbox ? [INBOX_TAG] : [])])) }
  write('notes', [note])
  saveCards(ords.map((ord) => ({ ...newCard(note.id, did, ord), queue: inbox ? -1 : 0 })))
  return note.id
}

export async function get_note(note_id) {
  const note = S.notes.get(note_id)
  const m = nt(note.mid)
  const vals = note.flds.split('\x1f')
  const cards = cardsOf(note_id).sort((a, b) => a.ord - b.ord)
  const fields = {}
  for (const [i, f] of m.flds.entries()) fields[f.name] = await withUrls(vals[i] ?? '')
  return { id: note.id, notetype: m.name, notetype_id: m.id, fields, tags: tagsOf(note), deck_id: cards[0]?.did ?? null, card_ids: cards.map((c) => c.id) }
}

export async function update_note(note_id, fields = null, tags = null, deck = null) {
  const note = S.notes.get(note_id)
  const m = nt(note.mid)
  let flds = note.flds.split('\x1f')
  if (fields) {
    const given = fieldList(m, fields)
    flds = await Promise.all(flds.map((v, i) => (m.flds[i].name in fields || Object.keys(fields).length === m.flds.length ? toNames(given[i]) : v)))
  }
  const oldTags = tagsOf(note)
  const accepted = tags && oldTags.includes(INBOX_TAG) && !tags.includes(INBOX_TAG)
  write('notes', [{ ...note, ...(await noteRow(m, flds, tags ?? oldTags, note)) }])
  const cards = cardsOf(note_id)
  const did = deck == null ? cards[0]?.did : typeof deck === 'number' ? deck : create_deck(deck)
  const have = new Set(cards.map((c) => c.ord))
  const added = ordsFor(m, flds).filter((o) => !have.has(o)).map((o) => newCard(note_id, did, o)) // e.g. a new cloze number
  saveCards([...cards.map((c) => ({ ...c, did: c.odid ? c.did : did, queue: accepted && c.queue === -1 ? homeQueue(c) : c.queue })), ...added])
}

export function delete_notes(note_ids) {
  const m = now()
  write('cards', note_ids.flatMap(cardsOf).map((c) => ({ ...c, mod: m, deleted: true })))
  write('notes', note_ids.map((id) => ({ ...S.notes.get(id), mod: m, deleted: true })))
  return note_ids.length
}

export async function add_media(filename, data_b64) {
  const bytes = Uint8Array.from(atob(data_b64), (c) => c.charCodeAt(0))
  const clean = (filename.split(/[\\/]/).pop() || 'bild.png').replace(/[^\p{L}\p{N}._-]+/gu, '_')
  const hash = (await sha1int(data_b64)).toString(16)
  const name = clean.replace(/(\.[^.]*)?$/, (ext) => `-${hash}${ext}`) // Anki keeps names unique per content too
  await uploadMedia(name, new Blob([bytes]))
  return (await mediaUrls([name])).get(name) // the editor shows it right away; saving turns it back into the name
}

// ---------- browser ----------

export async function search(query = '', limit = 500) {
  const tm = t()
  const deckName = (id) => deckOf(id)?.name ?? '?'
  const found = runSearch(query, { S, today: tm.today, deckName, nt })
  if (!found) return worker('search', [query, limit]) // OR, brackets, field search …: Anki's own search
  return found.slice(0, limit).map((c) => {
    const note = S.notes.get(c.nid)
    const m = nt(note.mid)
    return {
      card_id: c.id, note_id: c.nid, sort: stripHtml(note.flds.split('\x1f')[m.sortf] ?? '').slice(0, 200), notetype: m.name,
      deck: deckName(c.odid || c.did), tags: tagsOf(note), due: c.queue === 0 ? c.due : null, interval: c.ivl, reps: c.reps,
      suspended: c.queue === -1, flag: c.flags & 7,
    }
  })
}

export function flag(card_ids, flag) {
  saveCards(card_ids.map((id) => S.cards.get(id)).map((c) => ({ ...c, flags: (c.flags & ~7) | flag })))
}

export function move_cards(card_ids, deck) {
  const did = typeof deck === 'number' ? deck : create_deck(deck)
  saveCards(card_ids.map((id) => S.cards.get(id)).map((c) => ({ ...c, did })))
}

export function forget_cards(card_ids) {
  saveCards(card_ids.map((id) => S.cards.get(id)).map((c) => {
    const data = JSON.parse(c.data || '{}')
    return { ...c, type: 0, queue: 0, due: data.pos ?? c.due, ivl: 0, factor: 0, reps: 0, lapses: 0, left: 0, data: JSON.stringify({ pos: data.pos }) }
  }))
  return card_ids.length
}

// ---------- inbox (cards Claude made on the desktop) ----------

const inboxNotes = () => [...S.notes.values()].filter((n) => tagsOf(n).includes(INBOX_TAG))

export function inbox() {
  return inboxNotes().map((note) => {
    const m = nt(note.mid)
    const vals = note.flds.split('\x1f')
    const cards = cardsOf(note.id)
    return {
      note_id: note.id, notetype: m.name, deck: cards.length ? deckOf(cards[0].did)?.name ?? '?' : '?',
      fields: m.flds.map((f, i) => [f.name, stripHtml(vals[i] ?? '').slice(0, 400)]),
      tags: tagsOf(note).filter((x) => x !== INBOX_TAG), cards: cards.length,
    }
  })
}
export const inbox_count = () => inboxNotes().length

export function accept_inbox(note_ids) {
  for (const id of note_ids) {
    const note = S.notes.get(id)
    write('notes', [{ ...note, tags: tagStr(tagsOf(note).filter((x) => x !== INBOX_TAG)), mod: now() }])
    suspend(cardsOf(id).map((c) => c.id), false)
  }
  return note_ids.length
}
export const reject_inbox = delete_notes

// ---------- overview & stats ----------

export function stats() {
  const tm = t()
  const start = (tm.cutoff - 86400) * 1000
  const todays = [...S.revlog.values()].filter((r) => r.id > start)
  const mins = todays.reduce((s, r) => s + r.time, 0) / 60000
  return {
    cards: S.cards.size, notes: S.notes.size,
    studied_today: todays.length ? tr('Heute {n} Karten in {m} Minuten gelernt', { n: todays.length, m: (Math.round(mins * 10) / 10).toLocaleString(lang) }) : tr('Heute noch keine Karten gelernt'),
    due_today: decks().reduce((s, d) => s + d.new + d.learn + d.review, 0),
  }
}

export function overview(past_days = 126, future_days = 28) {
  unburyIfNewDay()
  const tm = t()
  const past = new Array(past_days).fill(0)
  const monthAgo = (tm.cutoff - 30 * 86400) * 1000
  let passed = 0, total = 0, timeSum = 0, timeN = 0
  for (const r of S.revlog.values()) {
    const ago = Math.floor((tm.cutoff - r.id / 1000 - 1) / 86400)
    if (ago < past_days) past[past_days - 1 - ago]++
    if (r.id > monthAgo) {
      timeSum += r.time
      timeN++
      if (r.type === 1) { total++; if (r.ease > 1) passed++ }
    }
  }
  const future = new Array(future_days).fill(0)
  for (const c of S.cards.values()) {
    const i = c.due - tm.today
    if ((c.queue === 2 || c.queue === 3) && i >= 1 && i <= future_days) future[i - 1]++
  }
  let streak = 0
  const back = (i) => past[past_days - 1 - i]
  while (streak < past_days && back(streak + (back(0) ? 0 : 1))) streak++
  const due = decks().reduce((s, d) => s + d.new + d.learn + d.review, 0)
  const features_ = features()
  return {
    due, minutes: Math.round((due * (timeN ? timeSum / timeN / 1000 : 10)) / 60), streak,
    retention: total ? Math.round((100 * passed) / total) : null, past, future, overdue: overdue(tm),
    features: features_, exams: features_.exams ? exam_plan() : [], inbox: inbox_count(),
  }
}

// ---------- settings ----------

export const features = () => ({ ...FEATURES, ...cfg('betteranki.features', {}) })
export function save_features(f) {
  setCfg('betteranki.features', Object.fromEntries(Object.keys(FEATURES).filter((k) => k in f).map((k) => [k, !!f[k]])))
}
export const theme = () => cfg('betteranki.theme', 'system')
export const set_theme = (v) => setCfg('betteranki.theme', v)
export const language = () => cfg('betteranki.lang', null)
export const set_language = (v) => setCfg('betteranki.lang', v)

const PREFS = { // Anki's preferences ↔ collection config keys
  scheduling: { rollover: ['rollover', 4], learn_ahead_secs: ['collapseTime', 1200], day_learn_first: ['dayLearnFirst', false] },
  reviewing: {
    show_remaining_due_counts: ['dueCounts', true], show_intervals_on_buttons: ['estTimes', true], hide_audio_play_buttons: ['hideAudioPlayButtons', false],
    time_limit_secs: ['timeLim', 0], load_balancer_enabled: ['loadBalancerEnabled', true], fsrs_short_term_with_steps_enabled: ['fsrsShortTermWithStepsEnabled', false],
  },
  editing: {
    adding_defaults_to_current_deck: ['addToCur', true], paste_strips_formatting: ['pasteStripsFormatting', false],
    default_search_text: ['defaultSearchText', ''], ignore_accents_in_search: ['ignoreAccentsInSearch', false],
  },
}
export const preferences = () => Object.fromEntries(Object.entries(PREFS).map(([g, keys]) =>
  [g, Object.fromEntries(Object.entries(keys).map(([k, [key, d]]) => [k, cfg(key, d)]))]))
export function save_preferences(p) {
  for (const [g, keys] of Object.entries(PREFS)) for (const [k, [key]] of Object.entries(keys))
    if (p[g]?.[k] !== undefined && p[g][k] !== cfg(key)) setCfg(key, p[g][k])
}

// ---------- app & account ----------

export const app_version = () => import.meta.env.VITE_APP_VERSION
export async function check_update() { // a newer deploy: offer a reload
  try {
    const r = await fetch('/version.json', { cache: 'no-store' })
    const { version } = await r.json()
    return version !== import.meta.env.VITE_APP_VERSION ? { version } : null
  } catch {
    return null
  }
}
export const install_update = () => location.reload()
export const update_failure = () => null

export async function cloud_account() {
  return (await sb.auth.getUser()).data.user?.email ?? null
}
export async function cloud_sync() {
  await flush()
  const received = await pull()
  return { sent: 0, received, media: 0, pending: unsynced() }
}
export async function change_password(password) {
  const { error } = await sb.auth.updateUser({ password })
  if (error) throw new Error(error.message)
}
export async function cloud_logout() {
  await flush().catch(() => {})
  await sb.auth.signOut()
  location.reload()
}

// ---------- exams & study plan (as core.py) ----------

function overdue(tm) {
  const out = {}
  for (const r of S.decks.values()) {
    if (r.data.name.includes('::')) continue
    const n = cardsIn(subtree(r.id)).filter((c) => c.queue === 2 && c.due < tm.today).length
    if (n) out[r.id] = n
  }
  return out
}

export function set_exam(deck_id, date) {
  const exams = { ...cfg(EXAMS, {}) }
  if (date) exams[String(deck_id)] = date
  else delete exams[String(deck_id)]
  setCfg(EXAMS, exams)
}

export function exam_plan() {
  const midnight = (d) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
  const today = midnight(new Date())
  return Object.entries(cfg(EXAMS, {})).sort((a, b) => a[1].localeCompare(b[1])).flatMap(([did, date]) => {
    const d = deckOf(did)
    if (!d) return [] // deck was deleted
    const [y, m, dd] = date.split('-').map(Number)
    const days = Math.round((Date.UTC(y, m - 1, dd) - today) / 864e5)
    const newLeft = cardsIn(subtree(d.id)).filter((c) => c.queue === 0).length
    const buffer = Math.min(7, Math.max(1, Math.floor(days / 5))) // the last fifth (1–7 days) is for reviewing
    const perDay = newLeft && days > 0 ? Math.ceil(newLeft / Math.max(1, days - buffer)) : 0
    return [{ deck_id: d.id, name: d.name, date, days, new_left: newLeft, per_day: perDay, current: d.newLimit ?? confOf(d).new.perDay, buffer }]
  })
}

/** Next card of a session across all decks: decks with the nearest exam first, then the rest in order. */
export async function plan_next() {
  const exams = features().exams ? cfg(EXAMS, {}) : {}
  const first = (d) => [...subtree(d.id)].map((i) => exams[String(i)]).filter(Boolean).sort()[0] ?? '9999'
  const tops = decks().filter((d) => !d.filtered).sort((a, b) => first(a).localeCompare(first(b)))
  for (const d of tops) {
    const card = d.new + d.learn + d.review ? await next_card(d.id) : null
    if (card) return { ...card, deck: d.name }
  }
  return null
}

// ---------- the worker: Anki's engine for the rarer actions ----------

// these only read: the web has nothing new to pull afterwards
const READS = new Set(['warm', 'statistics', 'weak_spots', 'difficult_cards', 'card_info', 'deck_options', 'notetype',
  'preview_template', 'inspect_import', 'search'])

export async function worker(method, args = []) {
  await flush() // the worker must see everything done here
  const { data } = await sb.auth.getSession()
  let body
  try {
    const r = await fetch('/api/worker', {
      method: 'POST', body: JSON.stringify({ method, args }),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${data.session?.access_token}` },
    })
    body = r.status === 401 ? { error: 'Bitte melde dich neu an.' } : await r.json()
  } catch {
    throw new Error('Der Server ist gerade nicht erreichbar. Bitte versuch es gleich noch einmal.')
  }
  if (body.error) throw new Error(body.error)
  if (!READS.has(method)) await pull() // and the web what the worker changed
  if (method.startsWith('export_')) await download(String(args[0]))
  return body.result
}

// files travel through the user's storage folder: "storage:<name>" is _tmp/<name> there (see worker.py)
const safeName = (n) => n.replace(/[^\p{L}\p{N}._-]+/gu, '_')

export async function upload_import(file) {
  const name = `${crypto.randomUUID().slice(0, 8)}-${safeName(file.name)}`
  await uploadMedia(`_tmp/${name}`, file)
  return `storage:${name}`
}

export function pick_import_file() {
  return new Promise((resolve) => {
    const input = Object.assign(document.createElement('input'), { type: 'file', accept: '.apkg,.colpkg,.csv,.tsv,.txt' })
    input.onchange = () => (input.files[0] ? upload_import(input.files[0]).then(resolve) : resolve(null))
    input.oncancel = () => resolve(null)
    input.click()
  })
}

export const pick_export_file = (name, ext = 'apkg') => `storage:${safeName(name)}.${ext}`

async function download(path) {
  const name = path.replace(/^storage:/, '')
  const { data, error } = await sb.storage.from('media').createSignedUrl(`${userId()}/_tmp/${name}`, 600, { download: name })
  if (error) throw new Error(error.message)
  Object.assign(document.createElement('a'), { href: data.signedUrl }).click()
}

// desktop only; the settings hide these in the web app
export const sync_account = () => null
export const backups = () => []
export const storage = () => null
export const claude_status = () => null
