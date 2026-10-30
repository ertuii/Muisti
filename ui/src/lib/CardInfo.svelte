<script>
  // Anki's card info (core.card_info): the facts, then the review history
  import { t, lang } from './i18n.js'

  let { info } = $props()

  const date = (s) => (s ? new Date(s * 1000).toLocaleDateString(lang, { day: 'numeric', month: 'short', year: 'numeric' }) : '–')
  const span = (secs) => secs < 3600 ? t('{n} min', { n: Math.round(secs / 60) })
    : secs < 86400 ? t('{n} h', { n: Math.round(secs / 3600) })
    : t('{n} T', { n: Math.round(secs / 86400) })
  const pct = (x) => `${Math.round(x * 100)} %`
  const KINDS = ['Lernen', 'Wiederholung', 'Neu lernen', 'Gefiltert', 'Manuell', 'Verschoben']
  const BUTTONS = ['', 'Nochmal', 'Schwer', 'Gut', 'Einfach']

  const rows = $derived([
    [t('Hinzugefügt'), date(info.added)],
    [t('Erste Wiederholung'), date(info.first_review)],
    [t('Letzte Wiederholung'), date(info.latest_review)],
    info.due_date ? [t('Fällig'), date(info.due_date)] : [t('Position (neu)'), info.due_position],
    info.interval && [t('Intervall'), span(info.interval * 86400)],
    info.ease && [t('Leichtigkeit'), `${info.ease / 10} %`],
    info.stability && [t('Stabilität'), span(info.stability * 86400)],
    info.difficulty && [t('Schwierigkeit'), pct(info.difficulty / 10)],
    info.retrievability && [t('Abrufbarkeit'), pct(info.retrievability)],
    [t('Wiederholungen'), info.reviews],
    [t('Fehler'), info.lapses],
    info.reviews && [t('Durchschnittliche Zeit'), `${info.average_secs.toFixed(1)} s`],
    info.reviews && [t('Gesamtzeit'), `${Math.round(info.total_secs)} s`],
    [t('Kartentyp'), info.card_type],
    [t('Notiztyp'), info.notetype],
    [t('Stapel'), info.original_deck ? `${info.deck} (${info.original_deck})` : info.deck],
    [t('Voreinstellung'), info.preset === 'Individuell' ? t('Individuell') : info.preset],
  ].filter(Boolean))
</script>

<dl>
  {#each rows as [k, v]}<dt>{k}</dt><dd class="num">{v}</dd>{/each}
</dl>

{#if info.revlog.length}
  <div class="log">
    <table>
      <thead><tr><th>{t('Datum')}</th><th>{t('Art')}</th><th>{t('Bewertung')}</th><th>{t('Intervall')}</th><th>{t('Zeit')}</th></tr></thead>
      <tbody>
        {#each info.revlog as r}
          <tr>
            <td class="num">{date(r.time)}</td>
            <td>{KINDS[r.kind] ? t(KINDS[r.kind]) : '–'}</td>
            <td class="b{r.button}">{r.button ? t(BUTTONS[r.button]) : '–'}</td>
            <td class="num">{r.interval ? span(Math.abs(r.interval)) : '–'}</td>
            <td class="num">{r.secs ? `${r.secs.toFixed(1)} s` : '–'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 20px; font-size: 14px; }
  dt { color: var(--ink-2); }
  .log { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th { text-align: left; font-weight: 600; color: var(--ink-2); }
  th, td { padding: 6px 12px 6px 0; border-bottom: 1px solid var(--rule); white-space: nowrap; }
  .b1 { color: var(--m-red); } .b2 { color: var(--m-ochre); } .b3 { color: var(--m-green); } .b4 { color: var(--m-blue); }
</style>
