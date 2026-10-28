// node --test src/web/ : the browser's deck filter, as Browser.svelte builds it
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { search } from './search.js'

const decks = { 1: 'Semester_1::Mathe', 2: 'Semester_3::Netze::TCP', 3: 'Semester 3', 4: 'Semester_30' }
const S = { cards: new Map(), notes: new Map() }
for (const did of [1, 2, 3, 4]) {
  S.cards.set(did, { id: did, nid: did, did, odid: 0, ord: 0 })
  S.notes.set(did, { id: did, flds: `Karte ${did}`, sfld: `Karte ${did}`, tags: ' ' })
}
const ids = (q) => search(q, { S, deckName: (id) => decks[id], today: 0 }).map((c) => c.id)
const filter = (name) => `"deck:${name.replace(/["*_\\]/g, '\\$&')}"` // Browser.svelte's fullQuery

test('deck filter: the deck and its subdecks, _ taken literally', () => {
  assert.deepEqual(ids(filter('Semester_3')), [2])
  assert.deepEqual(ids(filter('Semester_1')), [1])
})

test('deck: typed by hand keeps Anki wildcards', () => {
  assert.deepEqual(ids('deck:Semester_3'), [2, 3]) // _ is any one character
  assert.deepEqual(ids('deck:Semester*').length, 4)
  assert.deepEqual(ids('-deck:Semester_1'), [2, 3, 4])
})
