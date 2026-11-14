<script>
  // A date field with its own small calendar instead of the browser's. value: 'YYYY-MM-DD' or ''.
  import { CalendarDays, ChevronLeft, ChevronRight } from '@lucide/svelte'
  import { lang, t } from './i18n.js'

  let { value = $bindable(''), min = '', label } = $props()
  let open = $state(false)
  let root = $state(null)
  let view = $state(new Date()) // any day of the month shown

  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const at = (s) => new Date(s + 'T12:00')
  const today = iso(new Date())
  // ponytail: weeks start on Monday in every language
  const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7].map((d) => new Date(2024, 0, d).toLocaleDateString(lang, { weekday: 'short' }).slice(0, 2))

  const days = $derived.by(() => {
    const y = view.getFullYear(), m = view.getMonth()
    const lead = (new Date(y, m, 1).getDay() + 6) % 7
    return Array.from({ length: lead + new Date(y, m + 1, 0).getDate() }, (_, i) => (i < lead ? null : iso(new Date(y, m, i - lead + 1))))
  })
  const canGoBack = $derived(!min || iso(new Date(view.getFullYear(), view.getMonth(), 0)) >= min)

  function toggle() {
    open = !open
    if (open) view = at(value || (min > today ? min : today))
  }
  const turn = (by) => (view = new Date(view.getFullYear(), view.getMonth() + by, 1))
</script>

<svelte:window onclick={(e) => !(e.target instanceof Element && e.target.closest('.dp') === root) && (open = false)} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span class="dp" bind:this={root} onkeydown={(e) => e.key === 'Escape' && open && (e.stopPropagation(), (open = false))}>
  <button type="button" class="ghost field" class:empty={!value} aria-haspopup="dialog" aria-expanded={open} aria-label={label} onclick={toggle}>
    <CalendarDays size={15} />{value ? at(value).toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' }) : t('Datum wählen')}
  </button>
  {#if open}
    <div class="cal" role="dialog" aria-label={label}>
      <div class="head">
        <button type="button" class="plain" disabled={!canGoBack} aria-label={t('Voriger Monat')} onclick={() => turn(-1)}><ChevronLeft size={16} /></button>
        <b>{view.toLocaleDateString(lang, { month: 'long', year: 'numeric' })}</b>
        <button type="button" class="plain" aria-label={t('Nächster Monat')} onclick={() => turn(1)}><ChevronRight size={16} /></button>
      </div>
      <div class="grid">
        {#each WEEKDAYS as w}<span class="wd">{w}</span>{/each}
        {#each days as d}
          {#if d}
            <button type="button" class="plain day num" class:on={d === value} class:today={d === today} disabled={!!min && d < min}
              aria-label={at(d).toLocaleDateString(lang, { day: 'numeric', month: 'long', year: 'numeric' })} aria-pressed={d === value}
              onclick={() => { value = d; open = false }}>{Number(d.slice(8))}</button>
          {:else}<span></span>{/if}
        {/each}
      </div>
    </div>
  {/if}
</span>

<style>
  .dp { position: relative; display: inline-flex; }
  .field { font-weight: 500; justify-content: flex-start; width: 100%; }
  .field.empty { color: var(--ink-3); }
  .field :global(svg) { color: var(--ink-2); flex: none; }
  .cal {
    position: absolute; top: calc(100% + 6px); left: 0; z-index: 20; width: 284px; padding: 12px;
    background: var(--paper); border: 1px solid var(--rule); border-radius: 12px; box-shadow: 0 10px 32px rgb(0 0 0 / 0.16);
    animation: in 160ms var(--ease);
  }
  @keyframes in { from { opacity: 0; transform: translateY(-4px); } }
  .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .head b { font-size: 14px; }
  .head button { width: 32px; height: 32px; padding: 0; justify-content: center; }
  .grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
  .wd { font-size: 11px; color: var(--ink-3); text-align: center; padding: 4px 0; }
  .day { height: 36px; padding: 0; justify-content: center; font-weight: 500; color: var(--ink); border-radius: 8px; }
  .day.today { box-shadow: inset 0 0 0 1px var(--rule-2); }
  .day.on, .day.on:hover { background: var(--ink); color: var(--paper); }
  .day:disabled { color: var(--ink-3); opacity: 0.45; background: none; }
</style>
