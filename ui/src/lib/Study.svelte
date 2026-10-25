<script>
  import { ArrowLeft, Pencil, Undo2, FastForward, Pause } from '@lucide/svelte'
  import { api } from './api.js'
  import Editor from './Editor.svelte'
  import CardFrame from './CardFrame.svelte'
  import { t, tmsg } from './i18n.js'

  // temporary: a pre-learn/practice deck, removed again when the session ends
  // plan: the study plan across all decks (nearest exam first) for `minutes`
  let { deckId, deckName, flat, notify, onExit, temporary = false, plan = false, minutes = 0 } = $props()

  let card = $state(null)
  let done = $state(false)
  let revealed = $state(false)
  let typed = '' // {{type:Field}}: what was typed into the card
  let answerHtml = $state('')
  let editing = $state(false)
  let busy = false
  let prefs = $state({ show_remaining_due_counts: true, show_intervals_on_buttons: true, time_limit_secs: 0, hide_audio_play_buttons: false })
  let elapsed = $state(0) // seconds the current card has been shown
  let shownAt = Date.now()
  let autoAdvance = $state(false)
  let advanceTimer
  let boxStart = Date.now()
  let boxCount = 0
  const sessionStart = Date.now()
  let answered = $state(0)
  let timeUp = $state(false)
  // svelte-ignore state_referenced_locally
  let left = $state(minutes) // plan: minutes left, fixed per session

  const fetchCard = () => (plan ? api.plan_next() : api.next_card(deckId))

  api.preferences().then((p) => (prefs = p.reviewing))

  const tick = setInterval(() => {
    if (plan && minutes) left = Math.max(0, minutes - Math.floor((Date.now() - sessionStart) / 60000))
    if (!card || (revealed && card.study.stop_timer_on_answer)) return
    elapsed = Math.min(card.study.cap_secs, Math.floor((Date.now() - shownAt) / 1000))
  }, 1000)
  $effect(() => () => {
    clearInterval(tick)
    clearTimeout(advanceTimer)
    api.leave_study()
  })
  $effect(() => {
    window.addEventListener('ba-note-changed', reload)
    return () => window.removeEventListener('ba-note-changed', reload)
  })

  // Claude changed a note (MCP), maybe this one: show the new version without losing the place
  async function reload() {
    if (!card || editing || busy) return
    const fresh = await fetchCard()
    if (fresh?.card_id === card.card_id && (fresh.question !== card.question || fresh.answer !== card.answer)) await show(fresh)
  }

  async function show(fresh) {
    card = fresh
    if (revealed && card) await reveal()
  }
  const clock = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

  // Anki's "auto advance": toggled with A, timings and actions come from the deck's preset.
  $effect(() => {
    clearTimeout(advanceTimer)
    if (!autoAdvance || !card) return
    const st = card.study
    // ponytail: wait_for_audio is ignored, the timer starts when the card is shown
    if (!revealed && st.seconds_question > 0) {
      advanceTimer = setTimeout(() => (st.question_action === 0 ? reveal() : notify(t('Zeit, die Antwort aufzudecken'))), st.seconds_question * 1000)
    } else if (revealed && st.seconds_answer > 0) {
      const act = [() => bury(), () => answer(1), () => answer(3), () => answer(2), () => notify(t('Zeit, die Karte zu bewerten'))][st.answer_action]
      advanceTimer = setTimeout(act, st.seconds_answer * 1000)
    }
  })

  async function exit() {
    clearTimeout(advanceTimer)
    if (temporary) await api.end_prelearn(deckId)
    onExit()
  }

  const BUTTONS = [
    { ease: 1, label: t('Nochmal'), cls: 'again' },
    { ease: 2, label: t('Schwer'), cls: 'hard' },
    { ease: 3, label: t('Gut'), cls: 'good' },
    { ease: 4, label: t('Einfach'), cls: 'easy' },
  ]

  async function next() {
    timeUp = plan && minutes > 0 && Date.now() - sessionStart >= minutes * 60000
    card = timeUp ? null : await fetchCard()
    revealed = false
    typed = ''
    done = !card
    shownAt = Date.now()
    elapsed = 0
  }

  async function reveal() {
    const cmp = card.type_answer ? await api.compare_answer(card.card_id, typed) : ''
    answerHtml = card.answer.replace('[[typeans]]', () => cmp)
    revealed = true
  }

  async function answer(ease) {
    if (busy || !card) return
    busy = true
    try {
      await api.answer(card.card_id, ease)
      boxCount++
      answered++
      if (prefs.time_limit_secs && Date.now() - boxStart >= prefs.time_limit_secs * 1000) {
        notify(t('Zeitlimit erreicht: {n} Karten in {m} Minuten', { n: boxCount, m: Math.round((Date.now() - boxStart) / 60000) }))
        boxStart = Date.now()
        boxCount = 0
      }
      await next()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    } finally {
      busy = false
    }
  }

  async function undo() {
    const name = await api.undo()
    notify(name ? t('Rückgängig: {name}', { name: tmsg(name) }) : t('Nichts rückgängig zu machen'))
    await next()
  }

  async function bury() {
    await api.bury_card(card.card_id)
    notify(t('Karte bis morgen zurückgestellt'))
    await next()
  }

  // Anki: @ suspends the card, ! the whole note (all its cards)
  async function suspend(note = false) {
    await (note ? api.suspend_note(card.note_id) : api.suspend([card.card_id]))
    notify(note ? t('Notiz ausgesetzt (im Browser wieder aktivierbar)') : t('Karte ausgesetzt (im Browser wieder aktivierbar)'))
    await next()
  }

  function onKey(e) {
    if (editing) return
    if ((e.metaKey || e.ctrlKey) && e.key === 'z') return e.preventDefault(), undo()
    if (e.key === 'Escape') return exit()
    if (!card) return
    if (e.key === 'a' || e.key === 'A') return toggleAuto()
    if (e.key === 'e') return (editing = true)
    if (e.key === '-') return bury()
    if (e.key === '@') return suspend()
    if (e.key === '!') return suspend(true)
    if (!revealed && (e.key === ' ' || e.key === 'Enter')) return e.preventDefault(), reveal()
    if (revealed && (e.key === ' ' || e.key === 'Enter')) return e.preventDefault(), answer(3)
    if (revealed && ['1', '2', '3', '4'].includes(e.key)) answer(Number(e.key))
  }

  function toggleAuto() {
    if (!card.study.seconds_question && !card.study.seconds_answer) return notify(t('„Automatisch weiter“ ist in den Stapel-Optionen nicht eingestellt'))
    autoAdvance = !autoAdvance
    notify(autoAdvance ? t('Automatisch weiter: an') : t('Automatisch weiter: aus'))
  }

  next()
</script>

<svelte:window onkeydown={onKey} />

<div class="study">
  <header>
    <button class="plain" onclick={exit}><ArrowLeft size={17} />{tmsg(deckName)}{plan && card ? ` · ${card.deck}` : ''} <kbd>Esc</kbd></button>
    {#if card}
      <div class="mid">
        {#if prefs.show_remaining_due_counts}
          <div class="counts num" aria-label={t('Verbleibend')}>
            <span class="c-new" class:cur={card.queue === 0}>{card.counts.new}</span>
            <span class="c-learn" class:cur={card.queue === 1 || card.queue === 3}>{card.counts.learn}</span>
            <span class="c-review" class:cur={card.queue === 2}>{card.counts.review}</span>
          </div>
        {/if}
        {#if plan && minutes}<span class="timer num">{t('noch {n} min', { n: left })}</span>{/if}
        {#if card.study.show_timer}<span class="timer num" class:capped={elapsed >= card.study.cap_secs}>{clock(elapsed)}</span>{/if}
      </div>
      <div class="tools">
        {#if card.study.seconds_question || card.study.seconds_answer}
          <button class="plain" class:active={autoAdvance} onclick={toggleAuto} title={t('Automatisch weiter (A)')}><FastForward size={17} /></button>
        {/if}
        <button class="plain" onclick={() => suspend()} title={t('Karte aussetzen (@), ganze Notiz: !')}><Pause size={17} /></button>
        <button class="plain" onclick={undo} title={t('Rückgängig (⌘Z)')}><Undo2 size={17} /></button>
        <button class="plain" onclick={() => (editing = true)} title={t('Bearbeiten (E)')}><Pencil size={17} /></button>
      </div>
    {/if}
  </header>

  {#if done}
    <div class="done">
      {#if plan}
        <h1>{timeUp ? t('Lernplan geschafft.') : t('Alles erledigt.')}</h1>
        <p class="muted">{t(answered === 1 ? '{n} Karte in {m} Minuten.' : '{n} Karten in {m} Minuten.', { n: answered, m: Math.max(1, Math.round((Date.now() - sessionStart) / 60000)) })} {timeUp ? t('Was noch fällig ist, kannst du später oder morgen lernen.') : t('In keinem Stapel ist gerade noch etwas fällig.')}</p>
      {:else}
        <h1>{temporary ? t('Geschafft.') : t('Fertig für heute.')}</h1>
        <p class="muted">{temporary ? t('Die Karten sind neu eingeplant. Lernkarten, die noch offen sind, kehren in ihre Stapel zurück.') : t('In „{name}“ ist gerade nichts mehr fällig. Lernkarten kommen nach ihrer Lernstufe zurück.', { name: deckName })}</p>
      {/if}
      <div class="row">
        <button onclick={exit}>{t('Zur Übersicht')}</button>
        <button class="ghost" onclick={undo}>{t('Letzte Antwort rückgängig')}</button>
      </div>
    </div>
  {:else if card}
    <div class="card-area">
      <CardFrame html={revealed ? answerHtml : card.question} css={card.css} ord={card.ord} onkey={onKey} ontyped={(t) => (typed = t)}
        autoplay={card.study.autoplay} hideAudio={prefs.hide_audio_play_buttons} />
    </div>
    <footer>
      {#if !revealed}
        <button class="reveal" onclick={reveal}>{t('Antwort zeigen')} <kbd class="inv">{t('Leertaste')}</kbd></button>
      {:else}
        <div class="answers">
          {#each BUTTONS as b, i}
            <button class="ans {b.cls}" onclick={() => answer(b.ease)}>
              {#if prefs.show_intervals_on_buttons}<span class="ivl num">{card.buttons[i]}</span>{/if}
              <span>{b.label}</span>
              <kbd>{b.ease}</kbd>
            </button>
          {/each}
        </div>
      {/if}
    </footer>
  {/if}
</div>

{#if editing && card}
  <div class="sheet-backdrop" onclick={(e) => e.target === e.currentTarget && (editing = false)} role="presentation">
    <div class="sheet" role="dialog" aria-label={t('Karte bearbeiten')}>
      <h2>{t('Notiz bearbeiten')}</h2>
      <Editor noteId={card.note_id} {flat} {notify} onSaved={async () => { editing = false; await show(await fetchCard()) }} onCancel={() => (editing = false)} />
    </div>
  </div>
{/if}

<style>
  .study { height: 100%; display: flex; flex-direction: column; }
  header { display: flex; align-items: center; padding: 14px 20px; gap: 16px; }
  .mid { margin: 0 auto; display: flex; align-items: center; gap: 20px; }
  .counts { display: flex; gap: 14px; font-weight: 650; font-size: 15px; }
  .timer { font-size: 14px; color: var(--ink-2); font-weight: 500; }
  .timer.capped { color: var(--m-red); }
  .tools .active { color: var(--paper); background: var(--ink); }
  .counts span { padding-bottom: 2px; border-bottom: 2px solid transparent; }
  .counts .cur { border-bottom-color: currentColor; }
  .c-new { color: var(--new); } .c-learn { color: var(--learn); } .c-review { color: var(--review); }
  .tools { display: flex; gap: 4px; }
  .card-area { flex: 1; display: flex; justify-content: center; padding: 8px 32px 0; min-height: 0; }
  .card-area :global(iframe) {
    width: min(860px, 100%); border-radius: 14px 14px 0 0;
    box-shadow: 0 2px 4px rgb(0 0 0 / 0.04), 0 12px 40px rgb(0 0 0 / 0.08);
  }
  footer { display: flex; justify-content: center; padding: 20px 32px 28px; border-top: 1px solid var(--rule); }
  .reveal { height: 46px; padding: 0 28px; font-size: 15px; }
  kbd.inv { color: var(--paper); border-color: color-mix(in srgb, var(--paper) 40%, transparent); }
  .answers { display: grid; grid-template-columns: repeat(4, minmax(120px, 160px)); gap: 10px; }
  .ans {
    flex-direction: column; gap: 4px; height: auto; padding: 10px 12px; background: var(--paper);
    color: var(--ink); border: 1px solid var(--rule-2); font-weight: 650;
  }
  .ans:hover { background: var(--paper-2); opacity: 1; }
  .ivl { font-size: 13px; font-weight: 500; color: var(--ink-2); }
  .ans kbd { margin-top: 2px; }
  .again { border-bottom: 3px solid var(--m-red); }
  .hard { border-bottom: 3px solid var(--m-ochre); }
  .good { border-bottom: 3px solid var(--m-green); }
  .easy { border-bottom: 3px solid var(--m-blue); }
  .done { margin: auto; max-width: 52ch; display: flex; flex-direction: column; gap: 12px; padding: 32px; }
  .done h1 { font-size: 40px; font-weight: 800; letter-spacing: -0.03em; }
  .row { display: flex; gap: 8px; margin-top: 12px; }
  .sheet-backdrop { position: fixed; inset: 0; background: rgb(0 0 0 / 0.28); display: flex; justify-content: flex-end; z-index: 20; }
  .sheet { width: min(640px, 100%); height: 100%; background: var(--paper); padding: 28px 32px; overflow: auto; display: flex; flex-direction: column; gap: 20px; animation: slide 240ms var(--ease); }
  .sheet h2 { font-size: 20px; font-weight: 750; }
  @keyframes slide { from { transform: translateX(32px); opacity: 0; } }
  @media (max-width: 720px) {
    header { padding: 6px 6px 6px 2px; gap: 6px; }
    header > :global(button:first-child) { min-width: 0; max-width: 34vw; overflow: hidden; text-overflow: ellipsis; }
    .mid { gap: 10px; }
    .counts { gap: 10px; }
    .card-area { padding: 0; }
    .card-area :global(iframe) { border-radius: 0; box-shadow: none; }
    footer { padding: 10px 10px calc(10px + env(safe-area-inset-bottom)); }
    .reveal { width: 100%; justify-content: center; height: 52px; }
    .answers { grid-template-columns: repeat(4, 1fr); width: 100%; gap: 6px; }
    .ans { padding: 10px 2px; }
    .done { padding: 24px 16px; }
    .done h1 { font-size: 32px; }
    .row { flex-wrap: wrap; }
    .sheet { padding: 20px 16px calc(20px + env(safe-area-inset-bottom)); }
  }
</style>
