// The web app's copy of the collection: all rows of the signed-in user in memory, cached in IndexedDB, kept
// current by pulling `usn > last` (like the desktop, see src/muisti/cloud.py). Writes go to a queue that is
// flushed right away and retried when offline, so a review is never lost.
import { createClient } from '@supabase/supabase-js'
import stock from './stock.json'

export const sb = createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY)

export const TABLES = ['config', 'deck_configs', 'decks', 'notetypes', 'notes', 'cards', 'revlog']
const keyOf = (table, row) => (table === 'config' ? row.key : row.id)

/** @type {Record<string, Map<any, any>> & {usn?: number}} */
export const S = Object.fromEntries(TABLES.map((t) => [t, new Map()]))
let uid = null
let usn = 0
let pending = [] // [table, row] not yet confirmed by the server

const device = (() => {
  try {
    let d = localStorage.getItem('muisti-device')
    if (!d) localStorage.setItem('muisti-device', (d = `web-${crypto.randomUUID().slice(0, 8)}`))
    return d
  } catch {
    return `web-${crypto.randomUUID().slice(0, 8)}`
  }
})()

// ---------- IndexedDB: one record per user ----------

const idb = () => new Promise((res, rej) => {
  const r = indexedDB.open('muisti', 1)
  r.onupgradeneeded = () => r.result.createObjectStore('col')
  r.onsuccess = () => res(r.result)
  r.onerror = () => rej(r.error)
})
async function idbDo(mode, fn) {
  const db = await idb()
  return new Promise((res, rej) => {
    const tx = db.transaction('col', mode)
    const req = fn(tx.objectStore('col'))
    tx.oncomplete = () => res(req?.result)
    tx.onerror = () => rej(tx.error)
  })
}
let saveTimer
function persist() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(save, 500)
}
/** Write the cache now, e.g. before a reload (the debounced one would be lost). */
export function save() {
  clearTimeout(saveTimer)
  const snap = { usn, pending, tables: Object.fromEntries(TABLES.map((t) => [t, [...S[t].values()]])) }
  return idbDo('readwrite', (s) => s.put(snap, uid)).catch((e) => console.warn('cache', e))
}

// ---------- loading and pulling ----------

function take(table, row) {
  if (row.deleted) S[table].delete(keyOf(table, row))
  else S[table].set(keyOf(table, row), row)
}

export async function open(userId) {
  uid = userId
  for (const t of TABLES) S[t].clear()
  usn = 0
  pending = []
  try {
    const snap = await idbDo('readonly', (s) => s.get(uid))
    if (snap) {
      usn = snap.usn
      pending = snap.pending
      for (const t of TABLES) for (const r of snap.tables[t]) take(t, r)
    }
  } catch (e) {
    console.warn('cache', e) // private window etc.: load everything from the server
  }
  await pull()
  if (!S.notetypes.size) await seed()
}

/** Everything other devices wrote since the last pull. Returns the number of rows that came in. */
export async function pull() {
  await flush()
  let n = 0, max = usn
  const fetched = await Promise.all(TABLES.map(async (t) => { // one request per table, all at once
    const rows = []
    for (let after = usn; ;) {
      const { data, error } = await sb.from(t).select('*').gt('usn', after).neq('device', device).order('usn').limit(1000)
      if (error) throw new Error(error.message)
      rows.push(...data)
      if (data.length) max = Math.max(max, (after = data[data.length - 1].usn)) // this table's position, not the overall max
      if (data.length < 1000) return rows
    }
  }))
  TABLES.forEach((t, i) => { for (const r of fetched[i]) take(t, r); n += fetched[i].length }) // in TABLES order, note types before notes
  usn = max
  if (n) persist()
  return n
}

/** A new account: Anki's stock note types, default deck and preset, day 0 = today. */
async function seed() {
  const now = Math.floor(Date.now() / 1000)
  const crt = new Date()
  if (crt.getHours() < 4) crt.setDate(crt.getDate() - 1)
  crt.setHours(4, 0, 0, 0)
  write('config', Object.entries(stock.config).map(([key, val]) => ({ key, val, mod: now })))
  write('config', [{ key: '_crt', val: Math.floor(crt.getTime() / 1000), mod: 0 }])
  write('deck_configs', stock.deck_configs.map((d) => ({ id: d.id, data: d, mod: now })))
  write('decks', stock.decks.map((d) => ({ id: d.id, data: d, mod: now })))
  write('notetypes', stock.notetypes.map((d) => ({ id: d.id, data: d, mod: now })))
  await flush()
}

// ---------- writing ----------

const COLS = {
  notes: ['id', 'guid', 'mid', 'mod', 'tags', 'flds', 'sfld', 'csum', 'flags', 'data', 'deleted'],
  cards: ['id', 'nid', 'did', 'ord', 'mod', 'type', 'queue', 'due', 'ivl', 'factor', 'reps', 'lapses', 'left', 'odue', 'odid', 'flags', 'data', 'deleted'],
  revlog: ['id', 'cid', 'ease', 'ivl', 'last_ivl', 'factor', 'time', 'type', 'mod', 'deleted'],
  decks: ['id', 'mod', 'data', 'deleted'], deck_configs: ['id', 'mod', 'data', 'deleted'], notetypes: ['id', 'mod', 'data', 'deleted'],
  config: ['key', 'mod', 'val', 'deleted'],
}

/** Change rows locally and queue them for the server. Rows are whole rows (as in S). */
export function write(table, rows) {
  for (const r of rows) {
    r.deleted ??= false
    take(table, r)
    pending.push([table, Object.fromEntries(COLS[table].map((c) => [c, r[c] ?? null]))])
  }
  persist()
  flush().catch((e) => console.warn('sync', e))
}

let flushing = null
export function flush() {
  // .finally after the assignment: with nothing to send the body finishes synchronously
  if (!flushing) flushing = send().finally(() => (flushing = null))
  return flushing
}

async function send() {
  while (pending.length) {
    // a run of the same table; the same row twice in one upsert is an error in Postgres, the later one counts
    const table = pending[0][0]
    let n = 0
    while (n < pending.length && n < 500 && pending[n][0] === table) n++
    const rows = [...new Map(pending.slice(0, n).map(([, r]) => [keyOf(table, r), { ...r, device }])).values()]
    const { error } = await sb.from(table).upsert(rows, {
      onConflict: table === 'config' ? 'user_id,key' : 'user_id,id', ignoreDuplicates: table === 'revlog' && !rows.some((r) => r.deleted),
    })
    if (error) throw new Error(error.message)
    pending.splice(0, n)
    persist()
  }
}

export const unsynced = () => pending.length
export const userId = () => uid

// ---------- media (private bucket, one folder per user) ----------

const urls = new Map()
export async function mediaUrls(names) {
  const missing = [...new Set(names)].filter((n) => !urls.has(n))
  if (missing.length) {
    const { data } = await sb.storage.from('media').createSignedUrls(missing.map((n) => `${uid}/${n}`), 6 * 3600)
    for (const [i, d] of (data ?? []).entries()) if (d.signedUrl) urls.set(missing[i], d.signedUrl)
  }
  return urls
}
export const mediaNameOf = (url) => [...urls].find(([, u]) => u === url)?.[0]

export async function uploadMedia(name, blob) {
  const { error } = await sb.storage.from('media').upload(`${uid}/${name}`, blob, { upsert: true })
  if (error) throw new Error(error.message)
  urls.delete(name)
}
