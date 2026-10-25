// Anki's scheduler for the web app: days since collection creation, study queue, FSRS (ts-fsrs) and SM-2.
// Pure functions over plain rows (cards, deck dicts, preset dicts), so they run in tests without a browser.
// ponytail: v3's order simplified (learning due now, then reviews, then new; no new/review mixing options,
// no load balancing or easy days). Limits apply per deck and its parents, like v3. New cards follow the
// preset's gather priority (newOrder), their sort order is not modelled.
import { fsrs, Rating, State, StrategyMode, ConvertStepUnitToMinutes } from 'ts-fsrs'

const DAY = 86400

/** Anki's day numbering: local calendar days since crt, each day starting at `rollover` o'clock. */
export function timing(crt, rollover = 4, now = Date.now() / 1000) {
  const dayNo = (ts) => {
    const d = new Date((ts - rollover * 3600) * 1000)
    return Math.round(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY / 1000)
  }
  const today = dayNo(now) - dayNo(crt)
  const next = new Date(now * 1000)
  next.setHours(rollover, 0, 0, 0)
  if (next.getTime() / 1000 <= now) next.setDate(next.getDate() + 1)
  return { today, cutoff: next.getTime() / 1000, now }
}

/** Daily limits left today for a deck (its own preset and per-deck overrides). */
export function limits(deck, conf, today) {
  const pick = (todayKey, key, preset) => (deck[todayKey]?.today === today ? deck[todayKey].limit : deck[key] ?? preset)
  const done = (k) => (deck[k]?.[0] === today ? deck[k][1] : 0)
  return {
    new: Math.max(0, pick('newLimitToday', 'newLimit', conf.new.perDay) - done('newToday')),
    review: Math.max(0, pick('reviewLimitToday', 'reviewLimit', conf.rev.perDay) - done('revToday')),
  }
}

/**
 * The cards to study in a deck tree, in order, plus the counts shown on the study screen.
 * limitsOf(card): the remaining-limit objects ({new, review}) of the card's deck and all its parents; a card is
 * taken only while every one of them has room, and counts against all of them (Anki's v3 rule).
 * newOrder: comparator for new cards (see newOrderFor() below).
 */
export function queue(cards, limitsOf, t, learnAhead = 1200, newOrder = newOrderFor(2)) {
  const lrnNow = [], lrnLater = [], rev = [], fresh = []
  for (const c of cards) {
    if (c.queue === 1) (c.due <= t.now ? lrnNow : c.due <= t.now + learnAhead ? lrnLater : null)?.push(c)
    else if ((c.queue === 2 || c.queue === 3) && c.due <= t.today) rev.push(c)
    else if (c.queue === 0) fresh.push(c)
  }
  lrnNow.sort((a, b) => a.due - b.due)
  lrnLater.sort((a, b) => a.due - b.due)
  rev.sort((a, b) => a.due - b.due || a.id - b.id)
  fresh.sort(newOrder)
  const take = (list, kind) => list.filter((c) => {
    const chain = limitsOf(c)
    if (!chain.every((l) => l[kind] > 0)) return false
    chain.forEach((l) => l[kind]--)
    return true
  })
  const reviews = take(rev, 'review'), news = take(fresh, 'new')
  return {
    cards: [...lrnNow, ...reviews, ...news, ...lrnLater],
    counts: { new: news.length, learn: lrnNow.length + lrnLater.length, review: reviews.length },
  }
}

const rnd = (x, seed) => { const v = Math.sin(x * 12.9898 + seed * 78.233) * 43758.5453; return v - Math.floor(v) }

/**
 * Anki's "gather new cards" priority as a comparator: 0 deck, 1 deck then random notes, 2 ascending position,
 * 3 descending position, 4 random notes, 5 random cards. Random is stable for a day (seed), so the queue
 * doesn't reshuffle after every answer. deckName(did) orders decks for 0 and 1.
 * @param {number} gather
 * @param {(did: number) => string} [deckName]
 * @param {number} [seed]
 */
export function newOrderFor(gather, deckName = () => '', seed = 0) {
  const pos = (a, b) => a.due - b.due || a.id - b.id
  const deck = (a, b) => deckName(a.did).localeCompare(deckName(b.did), 'de')
  const notes = (a, b) => rnd(a.nid, seed) - rnd(b.nid, seed) || a.nid - b.nid || a.ord - b.ord
  return [
    (a, b) => deck(a, b) || pos(a, b),
    (a, b) => deck(a, b) || notes(a, b),
    pos,
    (a, b) => -pos(a, b),
    notes,
    (a, b) => rnd(a.id, seed) - rnd(b.id, seed) || a.id - b.id,
  ][gather] ?? pos
}

// ---------- interval labels (as Anki's describe_next_states) ----------

// German by default; core.js passes i18n's t for the UI language
export function label(secs, learning, tr = (s, { n }) => s.replace('{n}', String(n).replace('.', ','))) {
  const n = (x) => Math.round(x * 10) / 10
  const s = secs < 60 ? tr('{n}\u00a0Sek.', { n: Math.round(secs) }) : secs < 3600 ? tr('{n}\u00a0Min.', { n: Math.round(secs / 60) })
    : secs < DAY ? tr('{n}\u00a0Std.', { n: n(secs / 3600) }) : secs < 30 * DAY ? tr('{n}\u00a0Tg.', { n: Math.round(secs / DAY) })
      : secs < 365 * DAY ? tr('{n}\u00a0Mon.', { n: n(secs / DAY / 30) }) : tr('{n}\u00a0J.', { n: n(secs / DAY / 365) })
  return learning ? `<${s}` : s
}

// ---------- answering ----------

const stepsOf = (card) => card.left % 1000

/** The four possible outcomes (Again … Easy) of answering `card`; each is {card, revlog, secs}. */
export function outcomes(card, conf, deck, t, useFsrs) {
  const data = JSON.parse(card.data || '{}')
  if (useFsrs && (card.type === 0 || data.s)) return fsrsOutcomes(card, data, conf, deck, t)
  return [1, 2, 3, 4].map((ease) => {
    const res = sm2(card, ease, conf, t)
    res.card.data = JSON.stringify({ ...data, lrt: Math.round(t.now) }) // Anki keeps the last review time for every card
    return res
  })
}

/**
 * @param {any} card
 * @param {{type: number, delaySecs?: number, ivl?: number, factor?: number, left?: number, lapses?: number}} o
 * @param {any} t
 */
function after(card, o, t) {
  const { type, delaySecs = 0, ivl, factor, left, lapses = card.lapses } = o
  const learning = type === 1 || type === 3
  const c = { ...card, type, ivl: ivl ?? card.ivl, factor: factor ?? card.factor, left: left ?? 0, lapses, reps: card.reps + 1 }
  if (learning && delaySecs < DAY) Object.assign(c, { queue: 1, due: Math.round(t.now + delaySecs) })
  else if (learning) Object.assign(c, { queue: 3, due: t.today + Math.round(delaySecs / DAY) })
  else Object.assign(c, { queue: 2, due: t.today + c.ivl })
  return { card: c, secs: learning ? delaySecs : c.ivl * DAY, learning: learning && delaySecs < DAY }
}

function fuzz(ivl, seed) {
  if (ivl < 2.5) return Math.round(ivl)
  const r = ivl < 7 ? 1 : Math.max(2, Math.round(ivl * 0.05))
  const x = Math.sin(seed) * 10000
  return Math.round(ivl) + Math.round((x - Math.floor(x)) * 2 * r - r)
}

function sm2(card, ease, conf, t) {
  const newSteps = conf.new.delays, lapseSteps = conf.lapse.delays
  const learningStep = (steps, type, graduate) => {
    const left = stepsOf(card) || steps.length
    const idx = steps.length - left
    if (ease === 1) return after(card, { type, delaySecs: steps[0] * 60, left: steps.length }, t)
    if (ease === 2) {
      const d = idx === 0 ? (steps.length > 1 ? (steps[0] + steps[1]) / 2 : steps[0] * 1.5) : steps[idx]
      return after(card, { type, delaySecs: d * 60, left }, t)
    }
    if (ease === 3 && idx + 1 < steps.length) return after(card, { type, delaySecs: steps[idx + 1] * 60, left: left - 1 }, t)
    return after(card, { type: 2, ivl: graduate(ease === 4), factor: card.factor || conf.new.initialFactor }, t)
  }
  if (card.type === 0 || card.type === 1)
    return learningStep(newSteps, 1, (easy) => (easy ? conf.new.ints[1] : conf.new.ints[0]))
  if (card.type === 3)
    return learningStep(lapseSteps, 3, () => Math.max(conf.lapse.minInt, card.ivl))

  // review
  const late = Math.max(0, t.today - card.due)
  const f = card.factor / 1000, mod = conf.rev.ivlFct, max = conf.rev.maxIvl
  if (ease === 1) {
    const ivl = Math.max(conf.lapse.minInt, Math.round(card.ivl * conf.lapse.mult))
    const factor = Math.max(1300, card.factor - 200)
    if (lapseSteps.length) return after(card, { type: 3, delaySecs: lapseSteps[0] * 60, ivl, factor, left: lapseSteps.length, lapses: card.lapses + 1 }, t)
    return after(card, { type: 2, ivl, factor, lapses: card.lapses + 1 }, t)
  }
  const hard = Math.min(max, Math.max(card.ivl + 1, Math.round(card.ivl * conf.rev.hardFactor * mod)))
  const good = Math.min(max, Math.max(hard + 1, Math.round((card.ivl + late / 2) * f * mod)))
  const easy = Math.min(max, Math.max(good + 1, Math.round((card.ivl + late) * f * conf.rev.ease4 * mod)))
  const ivl = { 2: hard, 3: good, 4: easy }[ease]
  const factor = { 2: card.factor - 150, 3: card.factor, 4: card.factor + 150 }[ease]
  return after(card, { type: 2, ivl: Math.min(max, fuzz(ivl, card.id + t.today)), factor: Math.max(1300, factor) }, t)
}

/** Anki's learning steps (ts-fsrs differs on Hard: Anki repeats the current step after the first one). */
function ankiSteps(params, state, cur) {
  const review = state === State.Review || state === State.Relearning
  const mins = (review ? params.relearning_steps : params.learning_steps).map(ConvertStepUnitToMinutes)
  if (!mins.length) return {}
  if (state === State.Review) return { [Rating.Again]: { scheduled_minutes: mins[0], next_step: 0 } }
  if (cur >= mins.length) return {}
  const hard = cur === 0 ? (mins.length > 1 ? (mins[0] + mins[1]) / 2 : Math.min(mins[0] * 1.5, mins[0] + 1440)) : mins[cur]
  const out = {
    [Rating.Again]: { scheduled_minutes: mins[0], next_step: 0 },
    [Rating.Hard]: { scheduled_minutes: Math.round(hard), next_step: cur },
  }
  if (cur + 1 < mins.length) out[Rating.Good] = { scheduled_minutes: mins[cur + 1], next_step: cur + 1 }
  return out
}

function fsrsOutcomes(card, data, conf, deck, t) {
  const w = [conf.fsrsParams6, conf.fsrsParams5, conf.fsrsWeights].find((p) => p?.length)
  const f = fsrs({
    ...(w ? { w } : {}),
    request_retention: deck.desiredRetention ?? conf.desiredRetention ?? 0.9,
    maximum_interval: conf.rev.maxIvl,
    enable_fuzz: true,
    learning_steps: conf.new.delays.map((m) => `${m}m`),
    relearning_steps: conf.lapse.delays.map((m) => `${m}m`),
  }).useStrategy(StrategyMode.LEARNING_STEPS, ankiSteps)
  const steps = card.type === 3 ? conf.lapse.delays : conf.new.delays
  const now = new Date(t.now * 1000)
  const dayToDate = (day) => new Date((t.now + (day - t.today) * DAY) * 1000)
  const input = {
    state: card.type, // Anki's card types are FSRS's states (new, learning, review, relearning)
    due: card.queue === 1 ? new Date(card.due * 1000) : card.type === 0 ? now : dayToDate(card.due),
    stability: data.s ?? 0, difficulty: data.d ?? 0, elapsed_days: 0, scheduled_days: card.ivl,
    reps: card.reps, lapses: card.lapses,
    learning_steps: card.type === 1 || card.type === 3 ? Math.max(0, steps.length - stepsOf(card)) : 0,
    last_review: data.lrt ? new Date(data.lrt * 1000) : card.type === 2 ? dayToDate(card.due - card.ivl) : undefined,
  }
  const preview = f.repeat(input, now)
  return [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy].map((r) => {
    const n = preview[r].card
    const type = n.state === State.New ? 1 : n.state
    const delaySecs = (n.due.getTime() - now.getTime()) / 1000
    const nsteps = n.state === State.Relearning ? conf.lapse.delays.length : conf.new.delays.length
    const res = after(card, {
      type, delaySecs, ivl: type === 2 ? Math.max(1, n.scheduled_days) : type === 3 ? card.ivl : 0,
      left: type === 2 ? 0 : Math.max(1, nsteps - n.learning_steps), lapses: n.lapses,
    }, t)
    res.card.data = JSON.stringify({
      ...data, s: round(n.stability), d: round(n.difficulty), dr: deck.desiredRetention ?? conf.desiredRetention ?? 0.9,
      decay: w?.length === 21 ? w[20] : 0.1542, lrt: Math.round(t.now),
    })
    return res
  })
}

const round = (x) => Math.round(x * 10000) / 10000

/** The revlog row for an answer (Anki's columns; ivl negative = seconds in learning). */
export function revlogFor(before, res, ease, ms, now = Date.now()) {
  const ivlOf = (c, secs) => (c.queue === 1 ? -Math.round(secs) : c.ivl)
  return {
    id: now, cid: before.id, ease, ivl: ivlOf(res.card, res.secs),
    last_ivl: before.type === 2 ? before.ivl : before.queue === 1 ? -Math.max(0, before.due - Math.round(now / 1000)) : 0,
    factor: res.card.factor, time: ms,
    type: before.odid ? 3 : before.type === 0 || before.type === 1 ? 0 : before.type === 2 ? 1 : 2,
  }
}

/** Anki's leech rule: every `leechFails` lapses (then every half of it) → tag, and suspend if set so. */
export function isLeech(card, conf) {
  const n = conf.lapse.leechFails
  return n > 0 && card.lapses >= n && (card.lapses - n) % Math.max(1, Math.ceil(n / 2)) === 0
}
