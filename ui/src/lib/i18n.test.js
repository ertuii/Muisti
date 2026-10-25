// Every literal t('…') / tr('…') key in the UI has an English and a Spanish entry, and both files have the same keys.
// `node src/lib/i18n.test.js --missing` prints the missing keys instead.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'

const src = new URL('..', import.meta.url)
const files = readdirSync(src, { recursive: true }).filter((f) => /\.(svelte|js)$/.test(f) && !f.endsWith('.test.js'))
const dict = (l) => JSON.parse(readFileSync(new URL(`i18n/${l}.json`, import.meta.url), 'utf8'))

// string literals that are the key of a t( ) call: directly in its parentheses, not inside { vars }
export function keys(code) {
  const out = new Set()
  for (const m of code.matchAll(/\b(?:t|tr)\(/g)) {
    let parens = 1, braces = 0
    for (let i = m.index + m[0].length; i < code.length && parens; i++) {
      const c = code[i]
      if (c === "'") {
        let j = i + 1
        while (code[j] !== "'") j += code[j] === '\\' ? 2 : 1
        if (parens === 1 && !braces) out.add(JSON.parse(`"${code.slice(i + 1, j).replace(/\\'/g, "'").replace(/"/g, '\\"')}"`))
        i = j
      } else if (c === '(') parens++
      else if (c === ')') parens--
      else if (c === '{') braces++
      else if (c === '}') braces--
    }
  }
  return out
}

const used = new Set(files.flatMap((f) => [...keys(readFileSync(new URL(f, src), 'utf8'))]))

if (process.argv.includes('--missing')) {
  const en = dict('en')
  console.log(JSON.stringify([...used].filter((k) => !(k in en)), null, 1))
}

test('every key is translated', () => {
  for (const l of ['en', 'es']) {
    const d = dict(l)
    assert.deepEqual([...used].filter((k) => !d[k]), [], l)
  }
})

test('en and es have the same keys, with the same placeholders', () => {
  const en = dict('en'), es = dict('es')
  assert.deepEqual(Object.keys(es).sort(), Object.keys(en).sort())
  const vars = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join()
  for (const k in en) {
    assert.equal(vars(en[k]), vars(k), k)
    assert.equal(vars(es[k]), vars(k), k)
  }
})
