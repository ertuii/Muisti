<script>
  import { ChevronRight, Ellipsis } from '@lucide/svelte'
  import { api, hueFor, total, web } from './api.js'
  import Strip from './Strip.svelte'
  import AnkiMigration from './AnkiMigration.svelte'
  import { lang, t } from './i18n.js'

  let { decks, flat, overview, run, notify, onStudy, onAdd, onOptions, onPrelearn, onPlan, onInbox } = $props()

  let menuFor = $state(null)
  let renaming = $state(null)
  let renameText = $state('')
  let creating = $state(false)
  let newName = $state('')
  let confirmDelete = $state(null)
  let confirmReset = $state(null)
  let filtered = $state(null) // form state for a new filtered deck
  let planMinutes = $state(30)
  let empty = $state(false) // no cards yet: offer to bring them over from Anki
  api.stats().then((s) => (empty = s.cards === 0))

  const ORDERS = [
    [1, 'Zufällig'], [6, 'Nach Fälligkeit'], [8, 'Am stärksten überfällig'], [2, 'Kleinstes Intervall zuerst'],
    [3, 'Größtes Intervall zuerst'], [4, 'Meiste Fehler zuerst'], [5, 'Reihenfolge des Hinzufügens'], [0, 'Am längsten nicht gesehen'],
  ].map(([v, l]) => [v, t(l)])

  async function createFiltered() {
    const f = filtered
    if (!f.name.trim() || !f.search.trim()) return notify(t('Name und Suche angeben'), true)
    const id = await run(() => api.create_filtered_deck(f.name, f.search, f.limit, f.order, f.resched), t('Gefilterter Stapel angelegt'))
    if (id) filtered = null
  }


  const dateLabel = new Date().toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'long' })

  // Hide children of collapsed decks.
  const rows = $derived.by(() => {
    const out = []
    let hideBelow = Infinity
    for (const d of flat) {
      if (d.depth > hideBelow) continue
      hideBelow = d.collapsed ? d.depth : Infinity
      out.push(d)
    }
    return out
  })

  const firstDue = $derived(flat.find((d) => d.depth === 0 && total(d) > 0))

  function onKey(e) {
    if ((e.target instanceof Element && e.target.closest('input, textarea, select')) || e.metaKey || e.ctrlKey) return
    if (e.key === ' ' && firstDue) {
      e.preventDefault()
      onStudy(firstDue)
    } else if (e.key === 'a') onAdd()
  }

  async function create() {
    if (newName.trim()) await run(() => api.create_deck(newName), t('Stapel angelegt'))
    creating = false
    newName = ''
  }

  async function rename(d) {
    if (renameText.trim() && renameText !== d.name) await run(() => api.rename_deck(d.id, renameText))
    renaming = null
  }

  async function exportDeck(d) {
    menuFor = null
    const path = await api.pick_export_file(d.short)
    if (path) await run(() => api.export_deck(path, d.id, true, true), (n) => t('{n} Notizen exportiert', { n }))
  }

  async function reset(d) {
    if (confirmReset !== d.id) return (confirmReset = d.id)
    menuFor = confirmReset = null
    await run(() => api.reset_deck(d.id), (n) => t(n === 1 ? '„{name}“: {n} Karte wieder neu' : '„{name}“: {n} Karten wieder neu', { name: d.name, n }))
  }

  async function remove(d) {
    if (confirmDelete !== d.id) {
      confirmDelete = d.id
      return
    }
    menuFor = confirmDelete = null
    await run(() => api.delete_deck(d.id), t('„{name}“ gelöscht', { name: d.name }))
  }
</script>

<svelte:window onkeydown={onKey} onclick={(e) => !(e.target instanceof Element && e.target.closest('.menu-wrap')) && (menuFor = confirmDelete = confirmReset = null)} />

<div class="today">
  <header>
    <div>
      <div class="muted">{dateLabel}</div>
      <div class="big num">{overview?.due ?? '–'}</div>
      <div class="muted">{overview?.due === 1 ? t('Karte fällig heute') : t('Karten fällig heute')}</div>
    </div>
    {#if overview}
      <dl>
        <div><dt class="num">{overview.minutes} min</dt><dd>{t('geschätzt')}</dd></div>
        <div><dt class="num">{t(overview.streak === 1 ? '{n} Tag' : '{n} Tage', { n: overview.streak })}</dt><dd>{t('Serie')}</dd></div>
        <div><dt class="num">{overview.retention != null ? `${overview.retention} %` : '–'}</dt><dd>{t('Erinnerung, 30 Tage')}</dd></div>
      </dl>
    {/if}
    <div class="actions">
      <button class="ghost" onclick={onAdd}>{t('Karten hinzufügen')} <kbd>A</kbd></button>
      <button disabled={!firstDue} onclick={() => onStudy(firstDue)}>
        {firstDue ? t('{name} lernen', { name: firstDue.name }) : t('Alles erledigt')} {#if firstDue}<kbd class="inv">{t('Leertaste')}</kbd>{/if}
      </button>
    </div>
  </header>

  {#if empty}
    <section class="welcome">
      <h2>{t('Schon Karten in Anki?')}</h2>
      {#if web}
        <p class="muted">{t('Exportiere sie in Anki (Datei → Exportieren, „Anki-Sammlungspaket (.colpkg)“) und importiere die Datei hier über „Importieren“ oder per Drag & Drop. Oder nutze die')} <a href="https://github.com/ertuii/Muisti/releases/latest">{t('Desktop-App')}</a>{t(': Sie übernimmt Anki direkt und gleicht über dein Konto ab.')}</p>
      {:else}
        <p class="muted">{t('Übernimm deine Sammlung mit Lernstand. Oder ziehe eine .apkg- oder .colpkg-Datei ins Fenster, bzw. bitte Claude, Karten zu erstellen.')}</p>
        <AnkiMigration {notify} compact onDone={() => { empty = false; run(async () => {}) }} />
      {/if}
    </section>
  {/if}

  {#if overview?.inbox}
    <div class="notice">
      <span><b>{t(overview.inbox === 1 ? '{n} Notiz von Claude' : '{n} Notizen von Claude', { n: overview.inbox })}</b> {overview.inbox === 1 ? t('wartet im Eingang darauf, dass du sie durchsiehst.') : t('warten im Eingang darauf, dass du sie durchsiehst.')}</span>
      <button class="ghost sm" onclick={onInbox}>{t('Ansehen')}</button>
    </div>
  {/if}

  {#if overview?.features.plan}
    <div class="notice plan">
      <span><b>{t('Lernplan')}</b> <span class="muted">{t('Mischt alle Stapel, nahe Prüfungen zuerst.')}</span></span>
      <span class="row">
        <select bind:value={planMinutes} aria-label={t('Dauer')}>
          {#each [10, 15, 20, 30, 45, 60, 90] as m}<option value={m}>{t('{n} Minuten', { n: m })}</option>{/each}
        </select>
        <button class="sm" disabled={!overview.due} onclick={() => onPlan(planMinutes)}>{t('Starten')}</button>
      </span>
    </div>
  {/if}

  {#if overview}
    <Strip past={overview.past} future={overview.future} exams={overview.exams} {onPrelearn} />
  {/if}

  <section>
    <table>
      <thead>
        <tr><th>{t('Stapel')}</th><th>{t('Neu')}</th><th>{t('Lernen (Status)')}</th><th><span class="long">{t('Wiederholen')}</span><span class="short">{t('Wdh.')}</span></th><th class="w"></th></tr>
      </thead>
      <tbody>
        {#each rows as d (d.id)}
          <tr>
            <td class="name-cell">
              <span class="deck" style:padding-left="{d.depth * 22}px">
                {#if d.children.length}
                  <button class="plain twist" class:open={!d.collapsed} aria-label={d.collapsed ? t('Aufklappen') : t('Zuklappen')}
                    onclick={() => run(() => api.set_collapsed(d.id, !d.collapsed))}><ChevronRight size={15} /></button>
                {:else}<span class="twist"></span>{/if}
                {#if d.depth === 0}<span class="chip" style:background={hueFor(d.top)}></span>{/if}
                {#if renaming === d.id}
                  <!-- svelte-ignore a11y_autofocus -->
                  <input bind:value={renameText} autofocus onblur={() => rename(d)}
                    onkeydown={(e) => e.key === 'Enter' ? rename(d) : e.key === 'Escape' && (renaming = null)} />
                {:else}
                  <button class="plain dname" class:top={d.depth === 0} onclick={() => onStudy(d)}>{d.short}</button>
                {/if}
                {#if overview?.overdue[d.id] && d.depth === 0}
                  <span class="warn">{t('{n} überfällig', { n: overview.overdue[d.id] })}</span>
                {/if}
              </span>
            </td>
            <td class="num c-new" class:zero={!d.new}>{d.new}</td>
            <td class="num c-learn" class:zero={!d.learn}>{d.learn}</td>
            <td class="num c-review" class:zero={!d.review}>{d.review}</td>
            <td class="w">
              <span class="row-actions">
                <button class={d.depth === 0 ? '' : 'ghost'} disabled={!total(d)} onclick={() => onStudy(d)}>{t('Lernen')}</button>
                <span class="menu-wrap">
                  <button class="plain" aria-label={t('Stapel-Aktionen')} onclick={() => (menuFor = menuFor === d.id ? null : d.id)}><Ellipsis size={18} /></button>
                  {#if menuFor === d.id}
                    <div class="menu" role="menu">
                      {#if d.filtered}
                        <button class="plain" onclick={() => { menuFor = null; run(() => api.rebuild_filtered_deck(d.id), (n) => t('{n} Karten gesammelt', { n })) }}>{t('Neu aufbauen')}</button>
                        <button class="plain" onclick={() => { menuFor = null; run(() => api.empty_filtered_deck(d.id), t('Karten zurück in ihre Stapel')) }}>{t('Leeren')}</button>
                      {:else}
                        <button class="plain" onclick={() => onOptions(d)}>{t('Optionen')}</button>
                        <button class="plain" onclick={() => { creating = true; newName = d.name + '::'; menuFor = null }}>{t('Unterstapel anlegen')}</button>
                        <button class="plain" onclick={() => exportDeck(d)}>{t('Als .apkg exportieren')}</button>
                        <button class="plain del" onclick={() => reset(d)} title={t('Alle Karten (auch in Unterstapeln) werden wieder neu, Lernverlauf bleibt in der Statistik')}>
                          {confirmReset === d.id ? t('Wirklich alles zurücksetzen?') : t('Lernstand zurücksetzen')}
                        </button>
                      {/if}
                      <button class="plain" onclick={() => { renaming = d.id; renameText = d.name; menuFor = null }}>{t('Umbenennen')}</button>
                      <button class="plain del" onclick={() => remove(d)}>{confirmDelete === d.id ? t('Wirklich löschen?') : t('Löschen')}</button>
                    </div>
                  {/if}
                </span>
              </span>
            </td>
          </tr>
        {:else}
          <tr><td colspan="5" class="empty">{t('Noch keine Stapel. Lege einen an, importiere eine .apkg-Datei, oder bitte Claude, Karten zu erstellen.')}</td></tr>
        {/each}
      </tbody>
    </table>
    <div class="new-deck">
      {#if creating}
        <!-- svelte-ignore a11y_autofocus -->
        <input bind:value={newName} placeholder={t('Name, z. B. Analysis II::Integrale')} autofocus
          onkeydown={(e) => e.key === 'Enter' ? create() : e.key === 'Escape' && (creating = false)} onblur={create} />
      {:else if !filtered}
        <button class="ghost" onclick={() => (creating = true)}>{t('Neuer Stapel')}</button>
        <button class="ghost" onclick={() => (filtered = { name: t('Gefilterter Stapel'), search: 'is:due', limit: 100, order: 1, resched: true })}>{t('Gefilterter Stapel')}</button>
      {/if}
    </div>
    {#if filtered}
      <form class="filtered" onsubmit={(e) => { e.preventDefault(); createFiltered() }}>
        <h2>{t('Gefilterter Stapel')}</h2>
        <p class="muted">{t('Sammelt Karten per Suche vorübergehend in einen eigenen Stapel, z. B. zum Pauken vor der Klausur. Leeren schickt sie zurück.')}</p>
        <div class="ff">
          <label>{t('Name')}<input bind:value={filtered.name} /></label>
          <label class="wide">{t('Suche (Anki-Syntax)')}<input bind:value={filtered.search} placeholder={'"deck:Analysis II" is:due'} /></label>
          <label>{t('Höchstens')}<input type="number" min="1" bind:value={filtered.limit} /></label>
          <label>{t('Reihenfolge')}
            <select bind:value={filtered.order}>{#each ORDERS as [v, l]}<option value={v}>{l}</option>{/each}</select>
          </label>
        </div>
        <label class="check"><input type="checkbox" bind:checked={filtered.resched} />{t('Antworten planen Karten um (sonst nur Übung)')}</label>
        <div class="fbar">
          <button type="button" class="ghost" onclick={() => (filtered = null)}>{t('Abbrechen')}</button>
          <button type="submit">{t('Anlegen')}</button>
        </div>
      </form>
    {/if}
  </section>
</div>

<style>
  .today { padding: 32px 40px 48px; display: flex; flex-direction: column; gap: 28px; max-width: 1280px; }
  header { display: flex; align-items: flex-end; gap: 40px; flex-wrap: wrap; }
  .big { font-size: clamp(72px, 9vw, 112px); font-weight: 800; line-height: 0.85; letter-spacing: -0.04em; margin: 6px 0 8px; }
  dl { display: flex; gap: 32px; margin: 0; }
  dl div { display: flex; flex-direction: column; }
  dt { font-size: 20px; font-weight: 700; }
  dd { margin: 0; color: var(--ink-2); font-size: 14px; }
  .actions { margin-left: auto; display: flex; gap: 8px; }
  kbd.inv { color: var(--paper); border-color: color-mix(in srgb, var(--paper) 40%, transparent); }
  .deck { display: flex; align-items: center; gap: 8px; }
  .twist { width: 26px; height: 26px; padding: 0; justify-content: center; flex: none; }
  .twist :global(svg) { transition: transform 160ms var(--ease); }
  .twist.open :global(svg) { transform: rotate(90deg); }
  /* the deck column takes what's left; long names wrap instead of widening the table */
  .name-cell { width: 100%; min-width: 9em; }
  .deck { min-width: 0; }
  .dname {
    color: var(--ink); font-size: 15px; font-weight: 500; padding: 4px 6px;
    height: auto; min-height: 30px; min-width: 0; white-space: normal; text-align: left; line-height: 1.3; overflow-wrap: break-word;
  }
  .short { display: none; }
  .dname.top { font-weight: 650; }
  td { font-size: 16px; padding: 10px 12px; }
  .c-new { color: var(--new); font-weight: 650; }
  .c-learn { color: var(--learn); font-weight: 650; }
  .c-review { color: var(--review); font-weight: 650; }
  .zero { color: var(--ink-3); font-weight: 400; }
  .warn { font-size: 12px; background: var(--warn-bg); color: var(--warn-ink); padding: 2px 8px; border-radius: 99px; font-weight: 500; white-space: nowrap; }
  .w { width: 1%; white-space: nowrap; }
  .row-actions { display: inline-flex; align-items: center; gap: 4px; }
  .menu-wrap { position: relative; }
  .menu {
    position: absolute; right: 0; top: calc(100% + 4px); z-index: 10; min-width: 200px;
    background: var(--paper); border: 1px solid var(--rule); border-radius: 10px; padding: 6px;
    box-shadow: 0 8px 28px rgb(0 0 0 / 0.14); display: flex; flex-direction: column;
  }
  .menu button { color: var(--ink); justify-content: flex-start; padding: 8px 10px; font-weight: 500; }
  .menu .del { color: var(--m-red); }
  .empty { text-align: left; color: var(--ink-2); padding: 32px 12px; }
  .new-deck { padding-top: 16px; display: flex; gap: 8px; }
  .welcome { border: 1px solid var(--rule); border-radius: 12px; padding: 18px 20px; display: flex; flex-direction: column; gap: 8px; max-width: 860px; }
  .welcome h2 { font-size: 16px; font-weight: 700; }
  .welcome p { font-size: 14px; }
  .filtered { margin-top: 20px; padding: 20px; border: 1px solid var(--rule); border-radius: 12px; display: flex; flex-direction: column; gap: 12px; max-width: 860px; }
  .filtered h2 { font-size: 16px; font-weight: 700; }
  .filtered p { font-size: 13px; }
  .ff { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .ff label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--ink-2); }
  .ff .wide { grid-column: span 2; }
  .check { display: flex; align-items: center; gap: 10px; font-size: 14px; }
  .fbar { display: flex; justify-content: flex-end; gap: 8px; }
  .new-deck input { width: 360px; }
  .notice { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 12px 16px; border-radius: 12px; background: var(--paper-2); font-size: 14px; max-width: 860px; }
  .notice .row { display: flex; gap: 8px; align-items: center; }
  .notice select { width: auto; }
  @media (max-width: 720px) {
    .today { padding: 20px 16px 32px; gap: 22px; }
    header { gap: 18px; }
    dl { gap: 20px; width: 100%; }
    dt { font-size: 17px; }
    dd { font-size: 12px; }
    .actions { margin-left: 0; width: 100%; }
    .actions button { flex: 1 1 0; min-width: 0; justify-content: center; }
    th { font-size: 11px; padding-left: 4px; padding-right: 4px; }
    .long { display: none; }
    .short { display: inline; }
    td { padding: 8px 4px; font-size: 15px; }
    .row-actions > button:first-child { display: none; } /* tapping the deck name starts studying */
    .warn { display: none; }
    .new-deck input { width: 100%; }
    .ff .wide { grid-column: auto; }
  }
</style>
