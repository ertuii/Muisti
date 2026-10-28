// The common part of Anki's search syntax, answered in the browser: words and "quoted phrases" (in any field),
// deck:, tag:, note:, is:new|learn|review|due|suspended|buried, flag:N, prop:ivl/due/reps/lapses, -negation,
// all terms ANDed. Anything else (OR, brackets, field:, rated:, re: …) goes to Anki's own search on the worker.
import { stripHtml } from './render.js'

const fold = (s) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// * and _ are wildcards; \* \_ \" \\ stand for the characters themselves (Anki's escapes)
const glob = (pat) => new RegExp('^' + pat.replace(/\\(.)|[*_]|[^\\*_]+/g, (m, lit) =>
  lit !== undefined ? esc(lit) : m === '*' ? '.*' : m === '_' ? '.' : esc(m)) + '$', 'i')
// deck:a and tag:a match a and everything below it
const inTree = (re, name) => name.split('::').some((_, i, parts) => re.test(parts.slice(0, i + 1).join('::')))

function terms(q) {
  return [...q.matchAll(/(-?)(?:(\w+):)?(?:"((?:[^"\\]|\\.)*)"|(\S+))/g)].map(([, neg, key, quoted, word]) => {
    let val = quoted ?? word
    const inner = !key && quoted !== undefined && /^(\w+):(.*)$/s.exec(quoted) // Anki's "deck:a b"
    if (inner) [, key, val] = inner
    return { neg: !!neg, key: key?.toLowerCase(), val }
  })
}

function matcher({ key, val }, ctx) {
  const v = val.toLowerCase()
  if (key === 'deck') {
    const re = glob(val)
    return (c) => inTree(re, ctx.deckName(c.odid || c.did))
  }
  if (key === 'tag') {
    const re = glob(val)
    return (c, note) => note.tags.trim().split(/\s+/).some((t) => inTree(re, t))
  }
  if (key === 'note') { const re = glob(val); return (c, note) => re.test(ctx.nt(note.mid)?.name ?? '') }
  if (key === 'flag') return (c) => (c.flags & 7) === Number(val)
  if (key === 'is') {
    return {
      new: (c) => c.type === 0, learn: (c) => c.queue === 1 || c.queue === 3, review: (c) => c.type === 2 || c.type === 3,
      due: (c) => ((c.queue === 2 || c.queue === 3) && c.due <= ctx.today) || (c.queue === 1 && c.due <= Date.now() / 1000),
      suspended: (c) => c.queue === -1, buried: (c) => c.queue === -2 || c.queue === -3,
    }[v] ?? (() => false)
  }
  if (key === 'prop') {
    const m = /^(ivl|due|reps|lapses|ease)(<=|>=|!=|=|<|>)(-?[\d.]+)$/.exec(val)
    if (!m) return () => false
    const [, prop, op, num] = m
    const get = { ivl: (c) => c.ivl, reps: (c) => c.reps, lapses: (c) => c.lapses, ease: (c) => c.factor / 1000,
      due: (c) => (c.queue === 2 || c.queue === 3 ? c.due - ctx.today : NaN) }[prop]
    const n = Number(num)
    const cmp = { '<': (a) => a < n, '>': (a) => a > n, '<=': (a) => a <= n, '>=': (a) => a >= n, '=': (a) => a === n, '!=': (a) => a !== n }[op]
    return (c) => cmp(get(c))
  }
  // plain text, also an unknown "key:value" (e.g. a field search) as text
  const text = fold(key ? `${key}:${val}` : val)
  const re = text.includes('*') || text.includes('_') ? new RegExp(text.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/_/g, '.')) : null
  return (c, note) => {
    const hay = fold(stripHtml(note.flds.replace(/\x1f/g, ' ')))
    return re ? re.test(hay) : hay.includes(text)
  }
}

const KEYS = new Set(['deck', 'tag', 'note', 'flag', 'is', 'prop'])
const IS = new Set(['new', 'learn', 'review', 'due', 'suspended', 'buried'])

/** Cards matching `query`, sorted by the notes' sort field like Anki's default browser order.
 * null when the query needs more than this subset (OR, brackets, field search, …): ask Anki itself then. */
export function search(query, ctx) {
  const parsed = terms(query.trim())
  const simple = !/[()]/.test(query) && parsed.every((t) =>
    t.key ? KEYS.has(t.key) && (t.key !== 'is' || IS.has(t.val.toLowerCase())) : !/^(or|and)$/i.test(t.val))
  if (!simple) return null
  const tests = parsed.map((t) => ({ neg: t.neg, fn: matcher(t, ctx) }))
  const out = []
  for (const c of ctx.S.cards.values()) {
    const note = ctx.S.notes.get(c.nid)
    if (note && tests.every(({ neg, fn }) => fn(c, note) !== neg)) out.push([note.sfld ?? '', c])
  }
  return out.sort((a, b) => String(a[0]).localeCompare(String(b[0]), 'de') || a[1].ord - b[1].ord).map(([, c]) => c)
}
