// Pomodoro timer for the study screen. Kept at module level so it keeps running while the
// study screen is left and opened again. Time left comes from `endsAt`, so it never drifts.
const MIN = 60000

export const DEFAULTS = { focus: 25, short: 5, long: 15, every: 4 } // minutes; a long break after `every` rounds
export const pomo = { phase: 'idle', endsAt: 0, round: 0, long: false } // phase: idle | focus | break

export function start(now, cfg = DEFAULTS) {
  Object.assign(pomo, { phase: 'focus', endsAt: now + cfg.focus * MIN, round: pomo.round + 1, long: false })
}

export const stop = () => Object.assign(pomo, { phase: 'idle', endsAt: 0, round: 0, long: false })

// moves on when the current phase is over; returns the phase it moved into, else null
export function tick(now, cfg = DEFAULTS) {
  if (pomo.phase === 'idle' || now < pomo.endsAt) return null
  if (pomo.phase === 'focus') {
    const long = pomo.round % cfg.every === 0
    Object.assign(pomo, { phase: 'break', endsAt: now + (long ? cfg.long : cfg.short) * MIN, long })
  } else start(now, cfg)
  return pomo.phase
}

export function skip(now, cfg = DEFAULTS) {
  if (pomo.phase === 'break') start(now, cfg)
}

export const left = (now) => Math.max(0, pomo.endsAt - now)
