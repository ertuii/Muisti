import { test } from 'node:test'
import assert from 'node:assert/strict'
import { toHtml, closedInline, looksLikeMarkdown, inline } from './markdown.js'

test('pasted Markdown becomes HTML', () => {
  assert.equal(toHtml('Fokus auf:\n- **Nische**\n- *Regionen*\n1. eins'),
    '<div>Fokus auf:</div><ul><li><b>Nische</b></li><li><i>Regionen</i></li></ul><ol><li>eins</li></ol>')
  assert.equal(toHtml('# Titel\n> Zitat <x>'), '<h1>Titel</h1><blockquote>Zitat &lt;x&gt;</blockquote>')
  assert.equal(inline('a * b * c, 2*3*4, ~~weg~~ `x`'), 'a * b * c, 2*3*4, <s>weg</s> <code>x</code>')
})

test('a closing marker while typing', () => {
  assert.deepEqual(closedInline('das ist **fett**'), { start: 8, length: 8, inner: 'fett', tag: 'b' })
  assert.deepEqual(closedInline('ganz *schräg*'), { start: 5, length: 8, inner: 'schräg', tag: 'i' })
  assert.equal(closedInline('noch **offen*'), null)
  assert.equal(closedInline('3 * 4 *'), null)
})

test('only Markdown-looking text is converted', () => {
  assert.ok(looksLikeMarkdown('- a\n- b'))
  assert.ok(looksLikeMarkdown('ist **wichtig**'))
  assert.ok(!looksLikeMarkdown('ganz normaler Text, 3 - 2 = 1'))
})
