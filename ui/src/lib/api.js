// Bridge to the core: Python via pywebview (js_api = Core) on the desktop, src/web/core.js in the web build
// (vite --mode web). Every call returns a Promise.
export const web = import.meta.env.MODE === 'web'
const webCore = web ? import('../web/core.js') : null // not in the desktop bundle
const pw = () => /** @type {any} */ (window).pywebview

const ready = web ? Promise.resolve() : new Promise((resolve) => {
  if (pw()?.api) resolve()
  else window.addEventListener('pywebviewready', resolve, { once: true })
})

/** @type {any} */
export const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    if (web) {
      const core = await webCore
      // what the browser can't do itself runs on the worker, with Anki's own engine (web-api/worker.py)
      return typeof core[name] === 'function' ? core[name](...args) : core.worker(name, args)
    }
    await ready
    return pw().api[name](...args)
  },
})

// One fixed marker hue per top-level deck, derived from its id so it never shifts.
const HUES = ['red', 'blue', 'green', 'ochre', 'violet', 'teal', 'pink']
export const hueFor = (topId) => `var(--m-${HUES[Number(BigInt(topId) % 7n)]})`
// what a top-level deck's chip can be changed to on "Heute" (core.set_deck_color)
export const PASTELS = ['#f4a7a1', '#f7c59f', '#f3e09b', '#b5dfa6', '#9fd8cf', '#a8c8f0', '#c6b4ee', '#f2b5d4']

// Anki's card flags (0 = none); labels go through t()
export const FLAG_COLORS = [
  { n: 0, label: 'Keine Markierung', color: 'var(--ink-3)' },
  { n: 1, label: 'Rot', color: 'var(--m-red)' },
  { n: 2, label: 'Orange', color: 'var(--m-ochre)' },
  { n: 3, label: 'Grün', color: 'var(--m-green)' },
  { n: 4, label: 'Blau', color: 'var(--m-blue)' },
  { n: 5, label: 'Pink', color: 'var(--m-pink)' },
  { n: 6, label: 'Türkis', color: 'var(--m-teal)' },
  { n: 7, label: 'Violett', color: 'var(--m-violet)' },
]

// Deck tree -> flat rows with depth, the top-level id and its hue (the chosen color, else the fixed one).
export function flatten(decks, depth = 0, top = null, out = []) {
  for (const d of decks) {
    const t = top ?? d
    out.push({ ...d, depth, top: t.id, hue: t.color || hueFor(t.id) })
    flatten(d.children, depth + 1, t, out)
  }
  return out
}

export const total = (d) => d.new + d.learn + d.review
