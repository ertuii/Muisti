<script>
  // Vertical (stacked) bar chart in plain SVG with a hover tooltip per column.
  import { t } from './i18n.js'

  let { rows, series, labels, tickEvery = 1, height = 160, tip, legend = series.length > 1 } = $props()

  let width = $state(600)
  let hover = $state(null)

  const PAD_L = 34
  const PAD_B = 22
  const plotH = $derived(height - PAD_B)
  const total = (r) => series.reduce((s, x) => s + (r[x.key] ?? 0), 0)
  const max = $derived(Math.max(1, ...rows.map(total)))
  const gap = $derived(rows.length > 60 ? 1 : 2)
  const barW = $derived(Math.max(1, (width - PAD_L - gap * (rows.length - 1)) / rows.length))
  const x = (i) => PAD_L + i * (barW + gap)
  const h = (v) => (v / max) * (plotH - 8)

  function segs(r) {
    let y = plotH
    return series.flatMap((s) => {
      const v = r[s.key] ?? 0
      if (!v) return []
      const hh = h(v)
      y -= hh
      return [{ y, hh, color: s.color }]
    })
  }
</script>

<div class="chart" bind:clientWidth={width}>
  {#if legend}
    <div class="legend">
      {#each series as s}<span><i style:background={s.color}></i>{s.label}</span>{/each}
    </div>
  {/if}
  <svg {width} {height} role="img" aria-label={t('Balkendiagramm')}>
    <line class="grid" x1={PAD_L} x2={width} y1={plotH - h(max / 2)} y2={plotH - h(max / 2)} />
    <line class="grid" x1={PAD_L} x2={width} y1={plotH - h(max)} y2={plotH - h(max)} />
    <text class="tick" x={PAD_L - 6} y={plotH - h(max) + 4} text-anchor="end">{Math.round(max)}</text>
    <text class="tick" x={PAD_L - 6} y={plotH - h(max / 2) + 4} text-anchor="end">{Math.round(max / 2)}</text>
    {#each rows as r, i}
      <g class:dim={hover != null && hover !== i}>
        {#each segs(r) as s}
          <!-- the paper-coloured stroke is the 2px gap between stacked segments -->
          <rect x={x(i)} y={s.y} width={barW} height={s.hh} fill={s.color} rx={Math.min(3, barW / 3)} stroke="var(--paper)" stroke-width={series.length > 1 ? 1 : 0} />
        {/each}
      </g>
      <rect class="hit" x={x(i) - gap / 2} y="0" width={barW + gap} height={plotH} role="presentation"
        onmouseenter={() => (hover = i)} onmouseleave={() => (hover = null)} />
      {#if i % tickEvery === 0 && labels[i]}
        <text class="tick" x={x(i) + barW / 2} y={height - 6} text-anchor="middle">{labels[i]}</text>
      {/if}
    {/each}
    <line class="base" x1={PAD_L} x2={width} y1={plotH} y2={plotH} />
  </svg>
  {#if hover != null}
    <div class="tip" style:left="{Math.min(x(hover) + barW / 2, width - 90)}px">
      {@html tip(rows[hover], hover)}
    </div>
  {/if}
</div>

<style>
  .chart { position: relative; }
  svg { display: block; overflow: visible; }
  .grid { stroke: var(--rule); stroke-dasharray: 2 3; }
  .base { stroke: var(--rule-2); }
  .tick { font-size: 11px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }
  .hit { fill: transparent; }
  g { transition: opacity 120ms var(--ease); }
  g.dim { opacity: 0.45; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); margin-bottom: 10px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend i { width: 10px; height: 10px; border-radius: 3px; }
  .tip {
    position: absolute; top: 24px; transform: translateX(-50%); pointer-events: none; z-index: 2;
    background: var(--ink); color: var(--paper); font-size: 12px; line-height: 1.4; padding: 6px 9px;
    border-radius: 6px; white-space: nowrap; box-shadow: 0 4px 14px rgb(0 0 0 / 0.16);
  }
</style>
