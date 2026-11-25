import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pomo, start, stop, tick, skip, left } from './pomodoro.js'

const MIN = 60000
const cfg = { focus: 25, short: 5, long: 15, every: 2 }

test('focus, short break, focus, long break, skip, stop', () => {
  stop()
  assert.equal(tick(0, cfg), null) // idle stays idle
  start(0, cfg)
  assert.equal(pomo.phase, 'focus')
  assert.equal(left(10 * MIN), 15 * MIN)
  assert.equal(tick(24 * MIN, cfg), null)
  assert.equal(tick(25 * MIN, cfg), 'break')
  assert.equal(pomo.long, false)
  assert.equal(left(25 * MIN), 5 * MIN)
  assert.equal(tick(30 * MIN, cfg), 'focus') // break over: round 2
  assert.equal(tick(55 * MIN, cfg), 'break')
  assert.equal(pomo.long, true) // every 2nd round
  assert.equal(left(55 * MIN), 15 * MIN)
  skip(56 * MIN, cfg)
  assert.equal(pomo.phase, 'focus')
  assert.equal(pomo.round, 3)
  stop()
  assert.equal(pomo.phase, 'idle')
})
