// UI language. The UI was written in German, so the German text is the key: en.json/es.json map it,
// a missing entry shows the German. Fixed per page load: changing it reloads the page (Settings).
import en from './i18n/en.json'
import es from './i18n/es.json'

export const LANGUAGES = { de: 'Deutsch', en: 'English', es: 'Español' }
// keys with a (context) in brackets: the same German word, translated differently
const DICTS = { de: { 'Lernen (Status)': 'Lernen', 'Übernehmen (Anki)': 'Übernehmen' }, en, es }

export let lang = 'de'

// saved choice, else the browser's language, else English
export function setLang(saved) {
  const browser = navigator.language.slice(0, 2)
  lang = saved in LANGUAGES ? saved : browser in LANGUAGES ? browser : 'en'
  document.documentElement.lang = lang
  return lang
}

const fill = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m))

/** t('{n} Karten fällig', { n: 3 }) */
export const t = (s, vars = {}) => fill(DICTS[lang][s] ?? s, vars)

// Messages from the core (Python or web/core.js), already in German, some with values in them:
// matched against the keys, '{x}' standing for any text.
// ponytail: linear scan over the keys with placeholders, only runs for toasts and errors
export function tmsg(text) {
  text = String(text)
  const d = DICTS[lang]
  if (d[text]) return d[text]
  for (const k in d) {
    if (!k.includes('{')) continue
    const names = []
    const re = k.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{(\w+)\}|[{}]/g, (m, n) => (n ? (names.push(n), '(.+?)') : '\\' + m))
    const m = new RegExp(`^${re}$`, 's').exec(text)
    if (m) return t(k, Object.fromEntries(names.map((n, i) => [n, m[i + 1]])))
  }
  return text
}
