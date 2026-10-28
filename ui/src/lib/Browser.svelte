<script>
  import { untrack } from 'svelte'
  import { Search, Flag, X } from '@lucide/svelte'
  import { api, FLAG_COLORS } from './api.js'
  import Editor from './Editor.svelte'
  import { t, tmsg } from './i18n.js'

  let { flat, run, notify } = $props()

  let query = $state('')
  api.preferences().then((p) => {
    if (p.editing.default_search_text && !query) {
      query = p.editing.default_search_text
      search()
    }
  })
  let deckFilter = $state('')
  let status = $state('')
  let debounce
  let searchSeq = 0
  let rows = $state([])
  let selected = $state(new Set())
  let active = $state(null) // row shown in the editor panel
  let confirmDelete = $state(false)
  let loading = $state(false)

  const FLAGS = FLAG_COLORS.map((f) => ({ ...f, label: t(f.label) }))

  const STATUS = [
    { q: '', label: 'Alle Karten' },
    { q: 'is:due', label: 'Heute fällig' },
    { q: 'is:new', label: 'Neu' },
    { q: 'is:learn', label: 'In Lernphase' },
    { q: 'is:review', label: 'Wiederholung' },
    { q: 'is:suspended', label: 'Ausgesetzt' },
    { q: '-flag:0', label: 'Markiert' },
    { q: 'rated:1', label: 'Heute gelernt' },
  ].map((s) => ({ ...s, label: t(s.label) }))

  const ids = $derived([...selected])
  const allSuspended = $derived(rows.filter((r) => selected.has(r.card_id)).every((r) => r.suspended))

  // Filters become plain Anki search terms, so the free-text field keeps full Anki syntax.
  const fullQuery = $derived(
    [query.trim(), deckFilter && `"deck:${deckFilter.replace(/["*_\\]/g, '\\$&')}"`, status].filter(Boolean).join(' '),
  )

  function searchSoon() {
    clearTimeout(debounce)
    debounce = setTimeout(search, 250)
  }

  async function search() {
    loading = true
    const mine = ++searchSeq
    try {
      const result = await api.search(fullQuery, 1000)
      if (mine !== searchSeq) return // a newer search is in flight; drop this stale answer
      rows = result
      selected = new Set([...selected].filter((id) => rows.some((r) => r.card_id === id)))
      if (active && !rows.some((r) => r.card_id === active.card_id)) active = null
    } catch (e) {
      notify(t('Suche fehlgeschlagen: {why}', { why: tmsg(e?.message ?? e) }), true)
    } finally {
      loading = false
    }
  }

  function pick(r, e) {
    if (e.metaKey || e.ctrlKey) {
      const s = new Set(selected)
      s.has(r.card_id) ? s.delete(r.card_id) : s.add(r.card_id)
      selected = s
    } else {
      selected = new Set([r.card_id])
      active = r
    }
  }

  function toggle(r) {
    const s = new Set(selected)
    s.has(r.card_id) ? s.delete(r.card_id) : s.add(r.card_id)
    selected = s
  }

  const bulk = async (fn, msg) => { await run(fn, msg); await search() }

  const allSelected = $derived(rows.length > 0 && rows.every((r) => selected.has(r.card_id)))
  function toggleAll() {
    selected = allSelected ? new Set() : new Set(rows.map((r) => r.card_id))
  }

  let confirmReset = $state(false)
  async function forget() {
    if (!confirmReset) return (confirmReset = true)
    confirmReset = false
    await bulk(() => api.forget_cards(ids), (n) => t(n === 1 ? '{n} Karte zurückgesetzt' : '{n} Karten zurückgesetzt', { n }))
  }

  function onKey(e) {
    const typing = e.target instanceof Element && e.target.closest('input, textarea, select, [contenteditable]')
    if ((e.metaKey || e.ctrlKey) && e.key === 'a' && !typing) {
      e.preventDefault()
      selected = new Set(rows.map((r) => r.card_id))
    }
  }

  async function remove() {
    if (!confirmDelete) return (confirmDelete = true)
    confirmDelete = false
    const noteIds = [...new Set(rows.filter((r) => selected.has(r.card_id)).map((r) => r.note_id))]
    selected = new Set()
    active = null
    await bulk(() => api.delete_notes(noteIds), (n) => t('{n} Notizen gelöscht', { n }))
  }

  const flagColor = (n) => FLAGS[n]?.color
  const ivl = (r) => (r.due != null ? t('neu') : r.interval ? t('{n} T', { n: r.interval }) : t('lernt'))

  // Re-run whenever a filter select changes (the text field is debounced separately).
  $effect(() => {
    void [deckFilter, status]
    untrack(search) // only the selects trigger this; typing goes through searchSoon
  })
</script>

<svelte:window onkeydown={onKey} />

<div class="browser">
  <div class="list">
    <form class="filters" onsubmit={(e) => { e.preventDefault(); search() }}>
      <label class="search">
        <Search size={16} />
        <input bind:value={query} oninput={searchSoon} placeholder={t('Suchen … (Anki-Syntax, z. B. tag:formel)')} aria-label={t('Karten suchen')} />
      </label>
      <select bind:value={deckFilter} aria-label={t('Nach Stapel filtern')}>
        <option value="">{t('Alle Stapel')}</option>
        {#each flat as d}<option value={d.name}>{'\u2003'.repeat(d.depth)}{d.short}</option>{/each}
      </select>
      <select bind:value={status} aria-label={t('Nach Status filtern')}>
        {#each STATUS as s}<option value={s.q}>{s.label}</option>{/each}
      </select>
      <span class="count muted num">{t(rows.length === 1 ? '{n} Karte' : '{n} Karten', { n: rows.length })}</span>
    </form>

    <div class="selection" class:on={selected.size}>
      {#if selected.size}
        <span class="num sel-count">{t('{n} ausgewählt', { n: selected.size })}</span>
        <button class="ghost sm" onclick={() => bulk(() => api.suspend(ids, !allSuspended), allSuspended ? t('Fortgesetzt') : t('Ausgesetzt'))}>
          {allSuspended ? t('Fortsetzen') : t('Aussetzen')}
        </button>
        <select class="sm" aria-label={t('Markierung setzen')} onchange={(e) => { bulk(() => api.flag(ids, Number(e.currentTarget.value)), t('Markiert')); e.currentTarget.value = '' }}>
          <option value="">{t('Markieren')}</option>
          {#each FLAGS as f}<option value={f.n}>{f.label}</option>{/each}
        </select>
        <select class="sm" aria-label={t('In Stapel verschieben')} onchange={(e) => { bulk(() => api.move_cards(ids, Number(e.currentTarget.value)), t('Verschoben')); e.currentTarget.value = '' }}>
          <option value="">{t('Verschieben nach')}</option>
          {#each flat as d}<option value={d.id}>{'\u2003'.repeat(d.depth)}{d.short}</option>{/each}
        </select>
        <button class="ghost sm" onclick={forget} onblur={() => (confirmReset = false)} title={t('Karten wieder als neu einplanen (Anki: Vergessen)')}>{confirmReset ? t('Wirklich zurücksetzen?') : t('Zurücksetzen')}</button>
        <button class="danger sm" onclick={remove} onblur={() => (confirmDelete = false)}>{confirmDelete ? t('Wirklich löschen?') : t('Löschen')}</button>
        <button class="plain sm clear" aria-label={t('Auswahl aufheben')} onclick={() => { selected = new Set(); active = null }}><X size={16} /></button>
      {:else}
        <span class="muted hint">{t('Klick wählt eine Karte,')} <kbd>⌘</kbd>{t('-Klick mehrere,')} <kbd>⌘A</kbd> {t('alle.')}</span>
      {/if}
    </div>

    <div class="table-wrap" class:loading>
      <table>
        <thead>
          <tr><th class="cb"><input type="checkbox" checked={allSelected} indeterminate={selected.size > 0 && !allSelected} onclick={toggleAll} aria-label={t('Alle auswählen')} /></th><th>{t('Sortierfeld')}</th><th class="c-deck">{t('Stapel')}</th><th class="opt">{t('Notiztyp')}</th><th class="opt">{t('Tags')}</th><th class="r c-ivl">{t('Intervall')}</th><th class="r c-reps opt">{t('Wdh.')}</th></tr>
        </thead>
        <tbody>
          {#each rows as r (r.card_id)}
            <tr class:sel={selected.has(r.card_id)} class:susp={r.suspended} onclick={(e) => pick(r, e)}>
              <td class="cb"><input type="checkbox" checked={selected.has(r.card_id)} onclick={(e) => { e.stopPropagation(); toggle(r) }} aria-label={t('Auswählen')} /></td>
              <td class="sort">
                {#if r.flag}<Flag size={13} fill={flagColor(r.flag)} color={flagColor(r.flag)} />{/if}
                {r.sort || t('(leer)')}
              </td>
              <td class="muted">{r.deck}</td>
              <td class="muted opt">{r.notetype}</td>
              <td class="muted opt">{r.tags.join(' ')}</td>
              <td class="num r">{ivl(r)}</td>
              <td class="num r opt">{r.reps}</td>
            </tr>
          {:else}
            <tr><td colspan="7" class="empty">{loading ? t('Suche …') : fullQuery ? t('Keine Karten für diese Filter.') : t('Die Sammlung ist leer.')}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>

  {#if active}
    <aside class="panel">
      {#key active.note_id}
        <Editor noteId={active.note_id} {flat} {notify} onSaved={search} onCancel={() => (active = null)} />
      {/key}
    </aside>
  {/if}
</div>

<style>
  .browser { display: flex; height: 100%; }
  .list { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 24px 32px 0; container-type: inline-size; }
  .filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .search { position: relative; flex: 1 1 260px; display: flex; align-items: center; }
  .search :global(svg) { position: absolute; left: 12px; color: var(--ink-3); pointer-events: none; }
  .search input { width: 100%; padding-left: 36px; }
  .filters select { flex: 0 1 190px; }
  .count { margin-left: 8px; font-size: 13px; white-space: nowrap; }
  .selection {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    min-height: 48px; margin-top: 12px; padding: 8px 8px 8px 14px; border-radius: 10px;
  }
  .selection.on { background: var(--paper-2); }
  .sel-count { font-weight: 650; font-size: 13px; margin-right: 6px; }
  .selection select { width: auto; }
  .clear { margin-left: auto; width: 32px; padding: 0; justify-content: center; }
  .hint { font-size: 13px; }
  .table-wrap { flex: 1; overflow: auto; margin-top: 8px; }
  .table-wrap.loading { opacity: 0.6; }
  thead th { position: sticky; top: 0; background: var(--paper); z-index: 1; }
  th, td { text-align: left; }
  th.r, td.r { text-align: right; }
  td { padding: 9px 12px; font-size: 14px; cursor: default; }
  table { table-layout: fixed; }
  td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .c-deck { width: 22%; } th.opt { width: 14%; } .c-ivl { width: 84px; } .c-reps { width: 60px; }
  tr:hover td { background: var(--paper-2); }
  tr.sel td { background: color-mix(in srgb, var(--m-blue) 12%, var(--paper)); }
  tr.susp td { color: var(--ink-3); font-style: italic; }
  .sort { font-weight: 500; }
  .sort :global(svg) { vertical-align: -1px; margin-right: 4px; }
  .cb { width: 40px; padding-right: 0; }
  .cb input { vertical-align: middle; }
  .empty { color: var(--ink-2); padding: 32px 12px; }
  .panel { width: min(420px, 40%); border-left: 1px solid var(--rule); padding: 24px 28px; overflow: auto; }
  @container (max-width: 640px) { .opt { display: none; } .c-deck { width: 32%; } .c-ivl { width: 64px; } }
  @container (max-width: 420px) { .hint { display: none; } td { padding: 10px 6px; } .cb { width: 32px; } }
  @media (max-width: 720px) {
    .list { padding: 14px 12px 0; }
    .filters select { flex: 1 1 140px; }
    .count { width: 100%; margin: 0; }
    .selection:not(.on) { display: none; }
    /* the editor takes the whole screen; "Abbrechen" closes it */
    .panel { position: fixed; inset: 0; z-index: 25; width: auto; border: 0; background: var(--paper); padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); }
  }
</style>
