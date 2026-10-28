<script>
  import { ArrowLeft } from '@lucide/svelte'
  import { api } from './api.js'
  import { lang, t } from './i18n.js'

  let { deckId, notify, onBack } = $props()

  let o = $state(null)
  let steps = $state({ learn_steps: '', relearn_steps: '' })
  let saving = $state(false)
  let optimizing = $state(false)
  let newPreset = $state(null)
  let reschedule = $state(false)
  let toSubdecks = $state(false)

  // Anki stores steps in minutes; show them as "1m 10m 1d".
  const fmtSteps = (xs) => xs.map((m) => (m >= 1440 && m % 1440 === 0 ? `${m / 1440}d` : m >= 60 && m % 60 === 0 ? `${m / 60}h` : `${m}m`)).join(' ')
  function parseSteps(text) {
    return text.split(/[\s,]+/).filter(Boolean).map((s) => {
      const m = s.match(/^(\d+(?:[.,]\d+)?)\s*([smhd]?)$/i)
      if (!m) throw new Error(t('„{s}“ ist kein Schritt. Beispiele: 10m, 1h, 1d', { s }))
      const n = Number(m[1].replace(',', '.'))
      return { s: n / 60, m: n, h: n * 60, d: n * 1440 }[(m[2] || 'm').toLowerCase()]
    })
  }

  const SM2 = (x) => !x.fsrs
  const FSRS = (x) => x.fsrs
  const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7].map((d) => new Date(2024, 0, d).toLocaleDateString(lang, { weekday: 'short' })) // 1 Jan 2024: a Monday

  // Every option of an Anki preset, grouped like Anki's own options screen.
  const SECTIONS = [
    { title: 'Neue Karten', fields: [
      { k: 'learn_steps', label: 'Lernschritte', kind: 'steps', help: 'Abstände beim ersten Lernen, z. B. 1m 10m 1d.' },
      { k: 'graduating_interval_good', label: 'Abschlussintervall (Tage)', kind: 'int', show: SM2 },
      { k: 'graduating_interval_easy', label: 'Intervall bei „Einfach“ (Tage)', kind: 'int', show: SM2 },
      { k: 'new_card_insert_order', label: 'Einfügereihenfolge', kind: 'enum', opts: ['Nacheinander (älteste zuerst)', 'Zufällig'] },
    ] },
    { title: 'Vergessene Karten', fields: [
      { k: 'relearn_steps', label: 'Neulernschritte', kind: 'steps' },
      { k: 'minimum_lapse_interval', label: 'Minimales Intervall (Tage)', kind: 'int', show: SM2 },
      { k: 'leech_threshold', label: 'Lästling ab Fehlversuchen', kind: 'int' },
      { k: 'leech_action', label: 'Bei Lästlingen', kind: 'enum', opts: ['Karte aussetzen', 'Nur Tag „leech“ setzen'] },
    ] },
    { title: 'Anzeigereihenfolge', fields: [
      { k: 'new_card_gather_priority', label: 'Neue Karten sammeln', kind: 'enum',
        opts: ['Stapel für Stapel', 'Stapel für Stapel, darin zufällige Notizen', 'Aufsteigende Position', 'Absteigende Position', 'Zufällige Notizen (Unterstapel gemischt)', 'Zufällige Karten (Unterstapel gemischt)'],
        help: 'Beim Lernen eines Oberstapels: Unterstapel mischen oder nacheinander abarbeiten.' },
      { k: 'new_card_sort_order', label: 'Neue Karten sortieren', kind: 'enum',
        opts: ['Kartentyp, dann Sammelreihenfolge', 'Sammelreihenfolge', 'Kartentyp, dann zufällig', 'Zufällige Notiz, dann Kartentyp', 'Zufällig'] },
      { k: 'new_mix', label: 'Neue Karten / Wiederholungen', kind: 'enum', opts: ['Gemischt', 'Neue nach Wiederholungen', 'Neue vor Wiederholungen'] },
      { k: 'interday_learning_mix', label: 'Lernkarten (über Tage) / Wiederholungen', kind: 'enum', opts: ['Gemischt', 'Lernkarten danach', 'Lernkarten davor'] },
      { k: 'review_order', label: 'Wiederholungen sortieren', kind: 'enum',
        opts: ['Fälligkeit, dann zufällig', 'Fälligkeit, dann Stapel', 'Stapel, dann Fälligkeit', 'Aufsteigende Intervalle', 'Absteigende Intervalle',
          'Aufsteigende Leichtigkeit', 'Absteigende Leichtigkeit', 'Abrufbarkeit aufsteigend', 'Abrufbarkeit absteigend', 'Relative Überfälligkeit',
          'Zufällig', 'Reihenfolge des Hinzufügens', 'Umgekehrte Reihenfolge des Hinzufügens'] },
    ] },
    { title: 'Zurückstellen', help: 'Verwandte Karten derselben Notiz erst am nächsten Tag zeigen.', fields: [
      { k: 'bury_new', label: 'Neue verwandte Karten zurückstellen', kind: 'bool' },
      { k: 'bury_reviews', label: 'Verwandte Wiederholungen zurückstellen', kind: 'bool' },
      { k: 'bury_interday_learning', label: 'Verwandte Lernkarten (über Tage) zurückstellen', kind: 'bool' },
    ] },
    { title: 'Audio', fields: [
      { k: 'disable_autoplay', label: 'Audio nicht automatisch abspielen', kind: 'bool' },
    ] },
    { title: 'Timer', fields: [
      { k: 'cap_answer_time_to_secs', label: 'Maximale Antwortzeit (Sekunden)', kind: 'int', help: 'Längere Antworten zählen in der Statistik nur so lang.' },
      { k: 'show_timer', label: 'Timer beim Lernen anzeigen', kind: 'bool' },
      { k: 'stop_timer_on_answer', label: 'Timer beim Aufdecken anhalten', kind: 'bool' },
    ] },
    { title: 'Automatisch weiter', help: 'Beim Lernen mit A ein- und ausschalten.', fields: [
      { k: 'seconds_to_show_question', label: 'Frage zeigen für (Sekunden, 0 = aus)', kind: 'float' },
      { k: 'question_action', label: 'Danach', kind: 'enum', opts: ['Antwort zeigen', 'Nur erinnern'] },
      { k: 'seconds_to_show_answer', label: 'Antwort zeigen für (Sekunden, 0 = aus)', kind: 'float' },
      { k: 'answer_action', label: 'Danach', kind: 'enum', opts: ['Karte zurückstellen', 'Mit „Nochmal“ bewerten', 'Mit „Gut“ bewerten', 'Mit „Schwer“ bewerten', 'Nur erinnern'] },
    ] },
    { title: 'Erweitert', fields: [
      { k: 'maximum_review_interval', label: 'Maximales Intervall (Tage)', kind: 'int' },
      { k: 'new_per_day_minimum', label: 'Neue Karten pro Tag mindestens', kind: 'int', help: 'Auch wenn das Wiederholungslimit erreicht ist.' },
      { k: 'initial_ease', label: 'Anfangs-Leichtigkeit', kind: 'float', show: SM2 },
      { k: 'easy_multiplier', label: 'Bonus für „Einfach“', kind: 'float', show: SM2 },
      { k: 'interval_multiplier', label: 'Intervall-Faktor', kind: 'float', show: SM2 },
      { k: 'hard_multiplier', label: 'Intervall bei „Schwer“', kind: 'float', show: SM2 },
      { k: 'lapse_multiplier', label: 'Neues Intervall nach Fehler', kind: 'float', show: SM2 },
      { k: 'historical_retention', label: 'Frühere Erinnerung (für fehlende Historie)', kind: 'float', show: FSRS },
      { k: 'ignore_revlogs_before_date', label: 'Verlauf vor Datum ignorieren', kind: 'date', show: FSRS },
      { k: 'param_search', label: 'Suche für die Optimierung', kind: 'text', show: FSRS, help: 'Leer = alle Karten dieser Voreinstellung.' },
    ] },
  ]

  // Daily limits like Anki: the preset's value, this deck's own, or one for today only; the highest one set applies.
  const LIMITS = { new: ['new_per_day', 'new', 'new_today'], review: ['reviews_per_day', 'review', 'review_today'] }
  const SCOPES = ['Vorgabe', 'Dieser Stapel', 'Nur heute']
  let scope = $state({ new: 0, review: 0 })
  const limitAt = (kind, i) => (i ? o.limits[LIMITS[kind][i]] : o[LIMITS[kind][0]])
  function shownLimit(kind) {
    for (let i = scope[kind]; i >= 0; i--) if (limitAt(kind, i) != null) return limitAt(kind, i)
  }
  function setScope(kind, i) {
    const v = shownLimit(kind)
    for (let j = i + 1; j < 3; j++) o.limits[LIMITS[kind][j]] = null // a lower tab drops the ones above it
    if (i && o.limits[LIMITS[kind][i]] == null) o.limits[LIMITS[kind][i]] = v
    scope[kind] = i
  }
  function setLimit(kind, value) {
    const i = scope[kind], k = LIMITS[kind][i]
    if (i) o.limits[k] = value === '' ? null : Number(value)
    else o[k] = Number(value) || 0
  }

  async function load(presetId) {
    o = await api.deck_options(deckId, presetId ?? null)
    steps = { learn_steps: fmtSteps(o.learn_steps), relearn_steps: fmtSteps(o.relearn_steps) }
    for (const kind in LIMITS) scope[kind] = o.limits[LIMITS[kind][2]] != null ? 2 : o.limits[LIMITS[kind][1]] != null ? 1 : 0
  }

  async function save() {
    saving = true
    try {
      const data = { ...$state.snapshot(o), learn_steps: parseSteps(steps.learn_steps), relearn_steps: parseSteps(steps.relearn_steps), fsrs_reschedule: reschedule, limits_to_subdecks: toSubdecks }
      await api.save_deck_options(deckId, data)
      notify(toSubdecks ? t('Optionen gespeichert, Limits auch für die Unterstapel') : t('Optionen gespeichert'))
      toSubdecks = false
      await load()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    } finally {
      saving = false
    }
  }

  async function createPreset() {
    if (!newPreset?.trim()) return (newPreset = null)
    try {
      await api.new_preset(deckId, newPreset)
      notify(t('Voreinstellung „{name}“ angelegt', { name: newPreset }))
      newPreset = null
      await load()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
  }

  async function optimize() {
    optimizing = true
    try {
      const r = await api.optimize_fsrs(deckId)
      notify(r.changed ? t('FSRS an {n} Wiederholungen angepasst', { n: r.reviews }) : r.reviews < 400
        ? t('Erst {n} Wiederholungen – FSRS nutzt bis dahin Standardwerte', { n: r.reviews })
        : t('Parameter sind bereits optimal'))
      await load()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    } finally {
      optimizing = false
    }
  }

  load()
</script>

{#snippet limit(kind, label)}
  <div class="opt">
    <span class="lbl">{t(label)}</span>
    <div class="tabs" role="group" aria-label={t(label)}>
      {#each SCOPES as name, i}
        <button class:on={scope[kind] === i} aria-pressed={scope[kind] === i} onclick={() => setScope(kind, i)}>{t(name)}</button>
      {/each}
    </div>
    <input type="number" min="0" aria-label={t(label)} value={shownLimit(kind) ?? ''} oninput={(e) => setLimit(kind, e.currentTarget.value)} />
  </div>
{/snippet}

{#snippet field(f)}
  {#if !f.show || f.show(o)}
    {#if f.kind === 'bool'}
      <label class="check"><input type="checkbox" bind:checked={o[f.k]} />{t(f.label)}</label>
    {:else}
      <label>{t(f.label)}
        {#if f.kind === 'steps'}
          <input bind:value={steps[f.k]} placeholder="1m 10m" />
        {:else if f.kind === 'enum'}
          <select bind:value={o[f.k]}>{#each f.opts as label, i}<option value={i}>{t(label)}</option>{/each}</select>
        {:else if f.kind === 'int'}
          <input type="number" min="0" step="1" bind:value={o[f.k]} />
        {:else if f.kind === 'float'}
          <input type="number" min="0" step="0.05" bind:value={o[f.k]} />
        {:else if f.kind === 'date'}
          <input type="date" bind:value={o[f.k]} />
        {:else}
          <input bind:value={o[f.k]} />
        {/if}
        {#if f.help}<small>{t(f.help)}</small>{/if}
      </label>
    {/if}
  {/if}
{/snippet}

<div class="opts">
  <header>
    <button class="plain" onclick={onBack}><ArrowLeft size={17} />{t('Zurück')}</button>
  </header>
  {#if o}
    <h1>{t('Optionen für „{name}“', { name: o.deck_name })}</h1>

    <section>
      <h2>{t('Voreinstellung')}</h2>
      <p class="muted">{t('Optionen gehören zu einer Voreinstellung, die mehrere Stapel teilen können.')}</p>
      <div class="row">
        <select bind:value={o.preset_id} onchange={() => load(o.preset_id)}>
          {#each o.presets as p}<option value={p.id}>{p.name} · {t('{n} Stapel', { n: p.decks })}</option>{/each}
        </select>
        {#if newPreset === null}
          <button class="ghost" onclick={() => (newPreset = '')}>{t('Neue Voreinstellung')}</button>
        {:else}
          <!-- svelte-ignore a11y_autofocus -->
          <input bind:value={newPreset} placeholder={t('Name')} autofocus onkeydown={(e) => e.key === 'Enter' ? createPreset() : e.key === 'Escape' && (newPreset = null)} />
          <button class="ghost" onclick={createPreset}>{t('Anlegen')}</button>
        {/if}
      </div>
    </section>

    <section>
      <h2>{t('Tageslimits')}</h2>
      <div class="fields">
        {@render limit('new', 'Neue Karten pro Tag')}
        {@render limit('review', 'Wiederholungen pro Tag')}
      </div>
      <p class="muted">{t('„Vorgabe“ gilt für alle Stapel dieser Voreinstellung, „Dieser Stapel“ nur hier, „Nur heute“ bis morgen.')}</p>
      <div class="checks">
        {#if o.subdecks}
          <label class="check"><input type="checkbox" bind:checked={toSubdecks} />{t('Auch für alle {n} Unterstapel übernehmen', { n: o.subdecks })}</label>
        {/if}
        <label class="check"><input type="checkbox" bind:checked={o.new_cards_ignore_review_limit} />{t('Neue Karten ignorieren das Wiederholungslimit')} <span class="muted">{t('(alle Stapel)')}</span></label>
        <label class="check"><input type="checkbox" bind:checked={o.apply_all_parent_limits} />{t('Limits aller übergeordneten Stapel anwenden')} <span class="muted">{t('(alle Stapel)')}</span></label>
      </div>
    </section>

    <section>
      <h2>{t('Planung')}</h2>
      <label class="check"><input type="checkbox" bind:checked={o.fsrs} />{t('FSRS verwenden')} <span class="muted">{t('(alle Stapel)')}</span></label>
      <p class="muted">{t('FSRS plant Wiederholungen aus deinem Lernverlauf statt mit festen Faktoren und braucht meist weniger Wiederholungen für dieselbe Erinnerung.')}</p>
      {#if o.fsrs}
        <div class="fields">
          <label>{t('Gewünschte Erinnerung')}
            <span class="range"><input type="range" min="0.7" max="0.97" step="0.01" bind:value={o.desired_retention} /><b class="num">{Math.round(o.desired_retention * 100)} %</b></span>
            <small>{t('Höher = sicherer, aber mehr Wiederholungen pro Tag.')}</small>
          </label>
          <div class="opt">
            <span class="lbl">{t('Parameter')}</span>
            <button class="ghost" disabled={optimizing} onclick={optimize}>{optimizing ? t('Optimiere …') : t('An meinen Verlauf anpassen')}</button>
            <small>{o.fsrs_optimized ? t('Angepasst an deinen Verlauf.') : t('Noch Standardwerte.')}</small>
          </div>
        </div>
        <label class="check"><input type="checkbox" bind:checked={reschedule} />{t('Karten beim Speichern neu planen')} <span class="muted">{t('(nach Änderungen an FSRS)')}</span></label>
      {/if}
    </section>

    {#each SECTIONS as sec}
      <section>
        <h2>{t(sec.title)}</h2>
        {#if sec.help}<p class="muted">{t(sec.help)}</p>{/if}
        <div class="fields">
          {#each sec.fields.filter((f) => f.kind !== 'bool') as f}{@render field(f)}{/each}
        </div>
        {#if sec.fields.some((f) => f.kind === 'bool')}
          <div class="checks">{#each sec.fields.filter((f) => f.kind === 'bool') as f}{@render field(f)}{/each}</div>
        {/if}
      </section>
    {/each}

    <section>
      <h2>{t('Tage mit weniger Wiederholungen')}</h2>
      <p class="muted">{t('An diesen Tagen werden weniger Wiederholungen eingeplant, dafür an den anderen etwas mehr.')}</p>
      <div class="easy">
        <span></span><span class="scale"><small>{t('Minimum')}</small><small>{t('Reduziert')}</small><small>{t('Normal')}</small></span>
        {#each WEEKDAYS as day, i}
          <span class="day">{day}</span>
          <input type="range" min="0" max="1" step="0.01" list="easy-ticks" aria-label={day} bind:value={o.easy_days_percentages[i]} />
        {/each}
      </div>
      <datalist id="easy-ticks"><option value="0.5"></option></datalist>
    </section>

    <div class="bar">
      <button class="ghost" onclick={onBack}>{t('Abbrechen')}</button>
      <button disabled={saving} onclick={save}>{saving ? t('Speichere …') : t('Speichern')}</button>
    </div>
  {:else}
    <span class="skel" style="width:320px;max-width:100%;height:30px" aria-busy="true" aria-label={t('Optionen werden geladen')}></span>
    {#each [1, 4, 3] as rows}
      <section aria-hidden="true">
        <span class="skel" style="width:160px;height:18px"></span>
        {#each Array(rows) as _}<span class="skel" style="height:var(--control-h)"></span>{/each}
      </section>
    {/each}
  {/if}
</div>

<style>
  .opts { padding: 20px 40px 0; max-width: 860px; display: flex; flex-direction: column; gap: 28px; }
  header { margin-left: -8px; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; }
  section { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 1px solid var(--rule); }
  h2 { font-size: 16px; font-weight: 700; }
  section > p { font-size: 13px; max-width: 65ch; }
  .row { display: flex; gap: 8px; }
  .row select { width: 280px; }
  .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
  label, .opt { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--ink-2); }
  .lbl { font-size: 13px; }
  small { font-size: 12px; color: var(--ink-3); }
  .checks { display: flex; flex-direction: column; gap: 8px; }
  label.check { flex-direction: row; align-items: center; gap: 10px; font-size: 14px; color: var(--ink); }
  .range { display: flex; align-items: center; gap: 12px; }
  .range input { flex: 1; accent-color: var(--ink); height: auto; border: 0; padding: 0; }
  .range b { color: var(--ink); width: 44px; }
  .tabs { display: flex; gap: 2px; }
  .tabs button { flex: 1; height: auto; padding: 4px 6px; font-size: 12px; font-weight: 500; background: none; color: var(--ink-3); border: 0; border-bottom: 2px solid transparent; border-radius: 0; }
  .tabs button.on { color: var(--ink); border-bottom-color: var(--ink); }
  .easy { display: grid; grid-template-columns: 48px minmax(0, 1fr); align-items: center; gap: 10px 12px; }
  .scale { display: flex; justify-content: space-between; }
  .day { font-size: 13px; color: var(--ink-2); }
  .easy input { accent-color: var(--ink); height: auto; border: 0; padding: 0; }
  .bar { display: flex; justify-content: flex-end; gap: 8px; position: sticky; bottom: 0; padding: 16px 0; background: var(--paper); border-top: 1px solid var(--rule); }
  @media (max-width: 860px) {
    .opts { padding: 12px 16px 0; gap: 22px; }
    h1 { font-size: 22px; overflow-wrap: anywhere; }
    .row { flex-wrap: wrap; }
    .row select { width: auto; flex: 1 1 100%; }
    .fields { grid-template-columns: minmax(0, 1fr); }
    .bar { padding: 12px 0 calc(12px + env(safe-area-inset-bottom)); }
    .bar button { flex: 1; }
  }
</style>
