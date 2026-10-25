<script>
  // The semester strip: one cell per day. Past = reviews done, today outlined, future = forecast due.
  // Clicking a future day with due cards offers to learn them ahead.
  import { lang, t } from './i18n.js'

  let { past, future, exams = [], onPrelearn = null } = $props()
  let width = $state(1000)
  let picked = $state(null) // { index, cell }

  const DAY = 86400000
  const fmt = (d) => d.toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'short' })

  const cells = $derived.by(() => {
    const now = new Date()
    now.setHours(12, 0, 0, 0)
    const max = Math.max(1, ...past)
    const all = [
      ...past.map((n, i) => {
        const ago = past.length - 1 - i
        const level = n === 0 ? 0 : Math.min(3, Math.ceil((n / max) * 3))
        return { n, ago, level, kind: ago === 0 ? 'today' : 'past' }
      }),
      ...future.map((n, i) => ({ n, ago: -(i + 1), level: 0, kind: 'future' })),
    ].map((c) => ({ ...c, date: new Date(now.getTime() - c.ago * DAY) }))
    // ponytail: narrow windows drop the oldest days instead of shrinking cells below ~6px
    const fit = Math.max(future.length + 14, Math.floor(width / 9))
    return all.slice(-fit)
  })

  const months = $derived(
    cells
      .flatMap((c, i) => (i === 0 || c.date.getDate() === 1 ? [{ col: i + 1, label: c.date.toLocaleDateString(lang, { month: 'long' }) }] : []))
      .filter((m, i, all) => !all[i + 1] || all[i + 1].col - m.col > 10), // drop a cut-off first month
  )

  // exam markers under the strip, at their day
  const examMarks = $derived(
    exams.filter((e) => e.days > 0).flatMap((e) => {
      const col = cells.findIndex((c) => -c.ago === e.days)
      return col < 0 ? [] : [{ col: col + 1, label: e.name.split('::').pop() }]
    }),
  )

  const tip = (c) =>
    c.kind === 'future' ? `${fmt(c.date)}: ${t('{n} Wiederholungen geplant', { n: c.n })}${c.n ? t(' – klicken zum Vorlernen') : ''}`
    : `${fmt(c.date)}${c.kind === 'today' ? t(' (heute)') : ''}: ${t(c.n === 1 ? '{n} Karte gelernt' : '{n} Karten gelernt', { n: c.n })}`
</script>

<svelte:window onclick={(e) => !(e.target instanceof Element && e.target.closest('.strip-wrap')) && (picked = null)} />

<div class="strip-wrap" bind:clientWidth={width}>
  <div class="strip" style:grid-template-columns="repeat({cells.length}, 1fr)" aria-label={t('Lernverlauf und Prognose')}>
    {#each cells as c, i}
      {#if c.kind === 'future' && c.n > 0 && onPrelearn}
        <i class="l{c.level} future has pick" class:on={picked?.index === i} title={tip(c)} role="button" tabindex="0"
          aria-label={t('{date}: {n} fällig, vorlernen', { date: fmt(c.date), n: c.n })}
          onclick={() => (picked = picked?.index === i ? null : { index: i, cell: c })}
          onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), (picked = { index: i, cell: c }))}></i>
      {:else}
        <i class="l{c.level} {c.kind}" class:has={c.kind === 'future' && c.n > 0} title={tip(c)}></i>
      {/if}
    {/each}
  </div>
  {#if picked}
    <div class="pop" style:left="{Math.min(Math.max((picked.index + 0.5) / cells.length * 100, 12), 88)}%" role="dialog" aria-label={t('Vorlernen')}>
      <b>{fmt(picked.cell.date)}</b>
      <span class="muted">{t(picked.cell.n === 1 ? '{n} Karte fällig' : '{n} Karten fällig', { n: picked.cell.n })}, {t(-picked.cell.ago === 1 ? 'in {d} Tag' : 'in {d} Tagen', { d: -picked.cell.ago })}</span>
      <button class="sm" onclick={() => { onPrelearn(-picked.cell.ago); picked = null }}>{t('Jetzt vorlernen')}</button>
    </div>
  {/if}
  {#if examMarks.length}
    <div class="marks" style:grid-template-columns="repeat({cells.length}, 1fr)">
      {#each examMarks as m}<span style:grid-column="{m.col} / span 1" title={t('Prüfung: {name}', { name: m.label })} aria-label={t('Prüfung: {name}', { name: m.label })}></span>{/each}
    </div>
  {/if}
  <div class="months" style:grid-template-columns="repeat({cells.length}, 1fr)">
    {#each months as m}<span style:grid-column="{m.col} / span 20">{m.label}</span>{/each}
  </div>
</div>

<style>
  .strip-wrap { position: relative; }
  .strip { display: grid; gap: 2px; }
  .pick { cursor: pointer; }
  .pick:hover, .pick.on { background: var(--heat-2); border-color: var(--heat-3); }
  .pop {
    position: absolute; top: 34px; transform: translateX(-50%); z-index: 5; display: flex; flex-direction: column; gap: 6px;
    background: var(--paper); border: 1px solid var(--rule); border-radius: 10px; padding: 12px 14px; min-width: 210px;
    box-shadow: 0 8px 28px rgb(0 0 0 / 0.14); font-size: 13px; animation: in 160ms var(--ease);
  }
  .pop button { margin-top: 4px; align-self: flex-start; }
  @keyframes in { from { opacity: 0; transform: translate(-50%, -4px); } }
  i { height: 22px; border-radius: 2px; background: var(--paper-3); transition: transform 120ms var(--ease); }
  i:hover { transform: scaleY(1.25); }
  .l1 { background: var(--heat-1); }
  .l2 { background: var(--heat-2); }
  .l3 { background: var(--heat-3); }
  .today { outline: 2px solid var(--paper); box-shadow: 0 0 0 4px var(--ink); z-index: 1; }
  .today.l0 { background: var(--paper-3); }
  .future { background: transparent; border: 1px dashed var(--rule-2); }
  .future.has { border-style: solid; border-color: var(--heat-2); }
  .marks { display: grid; margin-top: 4px; }
  .marks span { grid-row: 1; height: 8px; margin: 0 auto; width: 8px; border-radius: 50%; background: var(--ink); }
  .months { display: grid; font-size: 12px; color: var(--ink-2); margin-top: 8px; }
  .months span { grid-row: 1; white-space: nowrap; }
</style>
