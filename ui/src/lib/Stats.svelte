<script module>
  const cache = new Map() // last result per deck and period: shown at once next time, then refreshed
</script>

<script>
  import { api } from './api.js'
  import Bars from './Bars.svelte'
  import { lang, t, tmsg } from './i18n.js'

  let { flat, notify, weak = false, onPractice } = $props()

  let deckId = $state(0)
  let days = $state(30)
  let s = $state(null)
  let spots = $state(null) // weak spots by tag and deck
  let starting = $state(null) // the weak spot whose practice deck is being built (the worker can take a while)

  async function practice(w) {
    if (starting) return
    starting = w
    try {
      await onPractice(w.kind, w.name, days)
    } finally {
      starting = null
    }
  }

  const PERIODS = [
    { d: 30, label: '1 Monat' },
    { d: 90, label: '3 Monate' },
    { d: 365, label: '1 Jahr' },
  ].map((p) => ({ ...p, label: t(p.label) }))

  const REVIEW_SERIES = [
    { key: 'young', label: 'Jung', color: 'var(--s-young)' },
    { key: 'learn', label: 'Lernen (Status)', color: 'var(--s-learn)' },
    { key: 'mature', label: 'Reif', color: 'var(--s-mature)' },
    { key: 'relearn', label: 'Neu lernen', color: 'var(--s-relearn)' },
  ].map((x) => ({ ...x, label: t(x.label) }))
  const COUNT_SERIES = [
    { key: 'new', label: 'Neu', color: 'var(--s-new)' },
    { key: 'young', label: 'Jung', color: 'var(--s-young)' },
    { key: 'learn', label: 'Lernen (Status)', color: 'var(--s-learn)' },
    { key: 'mature', label: 'Reif', color: 'var(--s-mature)' },
    { key: 'relearn', label: 'Neu lernen', color: 'var(--s-relearn)' },
    { key: 'suspended', label: 'Ausgesetzt', color: 'var(--s-muted)' },
    { key: 'buried', label: 'Zurückgestellt', color: 'var(--s-muted)' },
  ].map((x) => ({ ...x, label: t(x.label) }))
  const RET_ROWS = [
    ['today', 'Heute'], ['yesterday', 'Gestern'], ['week', 'Letzte Woche'],
    ['month', 'Letzter Monat'], ['year', 'Letztes Jahr'], ['allTime', 'Gesamt'],
  ].map(([k, l]) => [k, t(l)])
  const BUTTONS = ['Nochmal', 'Schwer', 'Gut', 'Einfach'].map((b) => t(b))

  async function load() {
    const key = `${deckId}:${days}`
    s = cache.get(key) ?? null
    try {
      const fresh = await api.statistics(deckId || null, days)
      cache.set(key, fresh)
      if (key === `${deckId}:${days}`) s = fresh
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
  }
  $effect(() => {
    void [deckId, days]
    load()
  })
  $effect(() => {
    if (weak) api.weak_spots(days).then((w) => (spots = w))
  })

  const DAY = 86400000
  const dayLabel = (offset) => new Date(Date.now() + offset * DAY).toLocaleDateString(lang, { day: 'numeric', month: 'short' })
  const tickEvery = $derived(days <= 30 ? 7 : days <= 90 ? 14 : 60)
  const sum = (arr) => arr.reduce((a, b) => a + b, 0)
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)} %` : '–')

  const futureRows = $derived(s ? s.future.map((n) => ({ n })) : [])
  const reviewTotal = $derived(s ? sum(s.reviews.map((r) => r.learn + r.relearn + r.young + r.mature)) : 0)
  const activeDays = $derived(s ? s.reviews.filter((r) => r.learn + r.relearn + r.young + r.mature > 0).length : 0)
  const cardTotal = $derived(s ? sum(Object.values(s.card_counts)) : 0)
</script>

<div class="stats">
  <header>
    <h1>{t('Statistik')}</h1>
    <div class="filters">
      <select bind:value={deckId} aria-label={t('Stapel')}>
        <option value={0}>{t('Alle Stapel')}</option>
        {#each flat as d}<option value={d.id}>{' '.repeat(d.depth)}{d.short}</option>{/each}
      </select>
      <div class="seg" role="radiogroup" aria-label={t('Zeitraum')}>
        {#each PERIODS as p}
          <button role="radio" aria-checked={days === p.d} class:on={days === p.d} onclick={() => (days = p.d)}>{p.label}</button>
        {/each}
      </div>
    </div>
  </header>

  {#if s}
    <dl class="facts">
      <div><dt class="num">{s.today.answered}</dt><dd>{t('Karten heute')}</dd></div>
      <div><dt class="num">{s.today.minutes} min</dt><dd>{t('Lernzeit heute')}</dd></div>
      <div><dt class="num">{s.today.correct_pct != null ? `${s.today.correct_pct} %` : '–'}</dt><dd>{t('heute richtig')}</dd></div>
      <div><dt class="num">{s.future[1] ?? 0}</dt><dd>{t('morgen fällig')}</dd></div>
      <div><dt class="num">{activeDays} / {days}</dt><dd>{t('Tage gelernt')}</dd></div>
    </dl>

    {#if weak && spots}
      <section class="weak">
        <h2>{t('Schwachstellen')}</h2>
        {#if spots.spots.length}
          <p class="muted">{t('Themen (Tags) und Stapel, bei denen du weniger Wiederholungen richtig beantwortest als im Durchschnitt ({n} %, der Strich). Schwächste zuerst.', { n: spots.overall })}</p>
          <ul>
            {#each spots.spots as w (w.kind + w.name)}
              <li>
                <span class="wname"><span class="kind">{w.kind === 'tag' ? t('Tag') : t('Stapel')}</span>{w.name}</span>
                <span class="meter" title={t('{p} % von {n} Wiederholungen', { p: w.retention, n: w.reviews })}>
                  <i style:width="{w.retention}%"></i>
                  <span class="avg" style:left="{spots.overall}%"></span>
                </span>
                <span class="num val">{w.retention} %</span>
                <span class="num muted cnt">{w.reviews}×</span>
                <button class="ghost sm" disabled={!!starting} onclick={() => practice(w)}>{starting === w ? t('Wird vorbereitet …') : t('Üben')}</button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">{spots.reviews ? t('Keine Ausreißer: Kein Thema liegt unter deinem Durchschnitt, oder es hat weniger als 10 Wiederholungen.') : t('Noch keine Wiederholungen in diesem Zeitraum.')}</p>
        {/if}
      </section>
    {/if}

    <div class="grid">
      <section class="wide">
        <h2>{t('Wiederholungen')}</h2>
        <p class="muted">{t('{n} Antworten in diesem Zeitraum, nach Kartenstatus.', { n: reviewTotal })}</p>
        <Bars rows={s.reviews} series={REVIEW_SERIES} labels={s.reviews.map((_, i) => dayLabel(i - days + 1))} {tickEvery}
          tip={(r, i) => `<b>${dayLabel(i - days + 1)}</b><br>${REVIEW_SERIES.filter((x) => r[x.key]).map((x) => `${x.label}: ${r[x.key]}`).join('<br>') || t('nichts gelernt')}`} />
      </section>

      <section class="wide">
        <h2>{t('Prognose')}</h2>
        <p class="muted">{t('Fällige Wiederholungen der nächsten {n} Tage, Rückstand zählt auf heute.', { n: days })}</p>
        <Bars rows={futureRows} series={[{ key: 'n', label: t('Fällig'), color: 'var(--s-mature)' }]} labels={futureRows.map((_, i) => dayLabel(i))} {tickEvery}
          tip={(r, i) => `<b>${i === 0 ? t('Heute') : dayLabel(i)}</b><br>${t('{n} fällig', { n: r.n })}`} />
      </section>

      <section>
        <h2>{t('Kartenzahlen')}</h2>
        <p class="muted">{t('{n} Karten insgesamt.', { n: cardTotal })}</p>
        <div class="hbar" role="img" aria-label={t('Verteilung der Karten nach Status')}>
          {#each COUNT_SERIES as c}
            {#if s.card_counts[c.key]}<span style:flex={s.card_counts[c.key]} style:background={c.color} title="{c.label}: {s.card_counts[c.key]}"></span>{/if}
          {/each}
        </div>
        <table class="small">
          <tbody>
            {#each COUNT_SERIES as c}
              <tr><td><i class="key" style:background={c.color}></i>{c.label}</td><td class="num">{s.card_counts[c.key]}</td><td class="num muted">{pct(s.card_counts[c.key], cardTotal)}</td></tr>
            {/each}
          </tbody>
        </table>
      </section>

      <section>
        <h2>{t('Intervalle')}</h2>
        <p class="muted">{t('Abstand bis zur nächsten Wiederholung, Karten in der Wiederholung.')}</p>
        <Bars rows={s.intervals} series={[{ key: 'n', label: t('Karten'), color: 'var(--s-young)' }]} labels={s.intervals.map((b) => tmsg(b.label))} tickEvery={2}
          tip={(r) => `<b>${tmsg(r.label)}</b><br>${t('{n} Karten', { n: r.n })}`} />
      </section>

      <section>
        <h2>{t('Tageszeit')}</h2>
        <p class="muted">{t('Wann du lernst; Tooltip zeigt die Trefferquote.')}</p>
        <Bars rows={s.hours} series={[{ key: 'total', label: t('Antworten'), color: 'var(--s-new)' }]} labels={s.hours.map((_, i) => `${i}`)} tickEvery={6}
          tip={(r, i) => `<b>${t('{a}–{b} Uhr', { a: i, b: i + 1 })}</b><br>${t('{n} Antworten', { n: r.total })}<br>${t('{p} richtig', { p: pct(r.correct, r.total) })}`} />
      </section>

      <section>
        <h2>{t('Erinnerung')}</h2>
        <p class="muted">{t('Anteil richtig beantworteter Wiederholungen (ohne Lernphase).')}</p>
        <table class="small">
          <thead><tr><th>{t('Zeitraum')}</th><th>{t('Richtig')}</th><th>{t('Wiederholungen')}</th></tr></thead>
          <tbody>
            {#each RET_ROWS as [k, label]}
              <tr><td>{label}</td><td class="num">{s.retention[k]?.pct != null ? `${s.retention[k].pct} %` : '–'}</td><td class="num muted">{s.retention[k]?.total ?? 0}</td></tr>
            {/each}
          </tbody>
        </table>
      </section>

      <section class="wide">
        <h2>{t('Antworttasten')}</h2>
        <p class="muted">{t('Wie oft du welche Taste gedrückt hast, im gewählten Zeitraum.')}</p>
        <table class="small">
          <thead><tr><th>{t('Kartenstatus')}</th>{#each BUTTONS as b}<th>{b}</th>{/each}<th>{t('Richtig')}</th></tr></thead>
          <tbody>
            {#each [['learning', 'Lernen (Status)'], ['young', 'Jung'], ['mature', 'Reif']] as [k, label]}
              {@const row = s.buttons[k] ?? [0, 0, 0, 0]}
              <tr><td>{t(label)}</td>{#each row as n}<td class="num">{n}</td>{/each}<td class="num muted">{pct(sum(row) - row[0] - (s.hard_wrong ? row[1] : 0), sum(row))}</td></tr>
            {/each}
          </tbody>
        </table>
      </section>
    </div>
  {:else}
    <div class="facts" aria-busy="true" aria-label={t('Statistik wird geladen')}>
      {#each Array(5) as _}<div><span class="skel" style="width:64px;height:30px"></span><span class="skel" style="width:90px;height:12px;margin-top:8px"></span></div>{/each}
    </div>
    <div class="grid" aria-hidden="true">
      {#each Array(4) as _, i}
        <section class:wide={i < 2}>
          <span class="skel" style="width:140px;height:18px"></span>
          <span class="skel" style="width:260px;max-width:100%;height:12px"></span>
          <span class="skel" style="height:{i < 2 ? 160 : 110}px;margin-top:8px"></span>
        </section>
      {/each}
    </div>
  {/if}
</div>

<style>
  .stats { padding: 32px 40px 56px; max-width: 1280px; display: flex; flex-direction: column; gap: 28px; }
  header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; margin-right: auto; }
  .filters { display: flex; gap: 8px; }
  .filters select { width: 220px; }
  .seg { display: inline-flex; border: 1px solid var(--rule-2); border-radius: var(--radius); padding: 2px; }
  .seg button { background: transparent; color: var(--ink-2); border: 0; height: 30px; padding: 0 12px; font-weight: 500; }
  .seg button.on { background: var(--ink); color: var(--paper); }
  .facts { display: flex; gap: 40px; flex-wrap: wrap; margin: 0; }
  .facts div { display: flex; flex-direction: column; }
  dt { font-size: 22px; font-weight: 700; }
  dd { margin: 0; color: var(--ink-2); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr)); gap: 40px 48px; }
  section { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  section.wide { grid-column: 1 / -1; }
  .weak ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; max-width: 900px; }
  .weak li { display: grid; grid-template-columns: minmax(140px, 1.4fr) 2fr 52px 52px auto; align-items: center; gap: 14px; padding: 6px 0; border-bottom: 1px solid var(--rule); font-size: 14px; }
  .wname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
  .kind { font-size: 11px; font-weight: 500; color: var(--ink-2); background: var(--paper-2); border-radius: 99px; padding: 1px 7px; margin-right: 8px; }
  .meter { position: relative; height: 10px; background: var(--paper-3); border-radius: 4px; }
  .meter i { position: absolute; inset: 0 auto 0 0; background: var(--heat-3); border-radius: 4px; }
  .meter .avg { position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--ink); }
  .val { font-weight: 650; text-align: right; }
  .cnt { text-align: right; font-size: 13px; }
  h2 { font-size: 16px; font-weight: 700; }
  section > p { font-size: 13px; margin-bottom: 10px; }
  .hbar { display: flex; height: 14px; gap: 2px; border-radius: 4px; overflow: hidden; margin-bottom: 8px; background: var(--paper-3); }
  table.small td, table.small th { padding: 7px 10px; font-size: 13px; }
  .key { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-right: 8px; vertical-align: -1px; }
  @media (max-width: 860px) {
    .stats { padding: 20px 16px 40px; gap: 24px; }
    .filters { width: 100%; flex-wrap: wrap; }
    .filters select { flex: 1 1 100%; width: auto; }
    .seg { width: 100%; }
    .seg button { flex: 1; padding: 0 6px; }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 12px; }
    dt { font-size: 20px; }
    .grid { gap: 32px; }
    .weak li { grid-template-columns: minmax(0, 1fr) 56px 40px auto; gap: 10px; }
    .weak .cnt { display: none; }
    .kind { display: none; }
    table.small td, table.small th { padding: 7px 6px; }
  }
</style>
