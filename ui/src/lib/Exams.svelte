<script>
  import { api, hueFor } from './api.js'
  import { lang, t } from './i18n.js'

  // Exam dates per deck and the new-cards pace each one needs.
  let { flat, overview, run, notify } = $props()

  let examForm = $state(null) // { deckId, date } while adding an exam
  async function saveExam() {
    if (!examForm.deckId || !examForm.date) return notify(t('Stapel und Datum wählen'), true)
    await run(() => api.set_exam(examForm.deckId, examForm.date), t('Prüfung eingetragen'))
    examForm = null
  }

  const examDate = (iso) => new Date(iso + 'T12:00').toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'long' })
  const until = (days) => (days === 0 ? t('heute') : days === 1 ? t('morgen') : days < 0 ? t('vorbei') : t('in {d} Tagen', { d: days }))
</script>

<div class="exams">
  <h1>{t('Prüfungen')}</h1>
  <p class="muted intro">{t('Trag ein, wann die Klausur zu einem Stapel ist. Die App rechnet aus, wie viele neue Karten du pro Tag lernen musst, und markiert die Prüfung im Zeitstrahl auf der Heute-Seite.')}</p>
  {#each overview.exams as e (e.deck_id)}
      <div class="exam">
        <span class="ename">
          <span class="chip" style:background={hueFor(flat.find((d) => d.id === e.deck_id)?.top ?? e.deck_id)}></span>
          <b>{e.name}</b>
          <span class="muted">{examDate(e.date)}, {until(e.days)}</span>
        </span>
        <span class="pace">
          {#if e.days <= 0}
            <span class="muted">{t('Vorbei')}</span>
          {:else if !e.new_left}
            <span class="muted">{t('Alle Karten gelernt, jetzt nur noch wiederholen')}</span>
          {:else}
            <span class="num">{t(e.new_left === 1 ? '{n} neue Karte übrig' : '{n} neue Karten übrig', { n: e.new_left })} · <b>{t('{n} pro Tag', { n: e.per_day })}</b> {t('nötig')}</span>
            {#if e.current !== e.per_day}
              <button class="ghost sm" title={t('Setzt das Limit für neue Karten nur dieses Stapels (aktuell {n})', { n: e.current })}
                onclick={() => run(() => api.apply_exam_pace(e.deck_id), (n) => t('{name}: ab jetzt {n} neue Karten pro Tag', { name: e.name, n }))}>{t('Tempo übernehmen')}</button>
            {:else}
              <span class="muted">{t('eingestellt')}</span>
            {/if}
          {/if}
          <button class="plain sm" aria-label={t('Prüfung entfernen')} onclick={() => run(() => api.set_exam(e.deck_id, null))}>{t('Entfernen')}</button>
        </span>
      </div>
    {/each}
    {#if examForm}
      <form class="exam-form" onsubmit={(e) => { e.preventDefault(); saveExam() }}>
        <select bind:value={examForm.deckId} aria-label={t('Stapel')}>
          <option value={null}>{t('Stapel wählen …')}</option>
          {#each flat.filter((d) => !d.filtered) as d}<option value={d.id}>{d.name}</option>{/each}
        </select>
        <input type="date" bind:value={examForm.date} aria-label={t('Datum')} min={new Date().toISOString().slice(0, 10)} />
        <button type="submit" class="sm">{t('Eintragen')}</button>
        <button type="button" class="ghost sm" onclick={() => (examForm = null)}>{t('Abbrechen')}</button>
      </form>
    {:else}
      <div><button class="ghost sm" onclick={() => (examForm = { deckId: null, date: '' })}>{t('Prüfung eintragen')}</button></div>
    {/if}
    {#if overview.exams.length}
      <p class="muted small">{t('Das Tempo verteilt die neuen Karten so, dass die letzten Tage vor der Prüfung nur noch zum Wiederholen bleiben.')}</p>
    {/if}
</div>

<style>
  .exams { padding: 32px 40px 56px; max-width: 980px; display: flex; flex-direction: column; gap: 4px; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; }
  .intro { font-size: 14px; max-width: 65ch; margin: 6px 0 18px; }
  .exam { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 10px 0; border-bottom: 1px solid var(--rule); }
  .ename, .pace { display: flex; align-items: center; gap: 10px; font-size: 14px; }
  .exam-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding-top: 10px; }
  .exam-form select, .exam-form input { width: auto; }
  .small { font-size: 13px; margin-top: 6px; }
  @media (max-width: 860px) {
    .exams { padding: 20px 16px 40px; }
    .exam-form select, .exam-form input { flex: 1 1 100%; }
  }
</style>
