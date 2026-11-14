<script>
  // The very first start: choose the optional features, then a short tour that points at the real screen.
  // Both can be skipped; "Einführung ansehen" in the settings shows the tour again.
  import { api, EXTRAS } from './api.js'
  import { t } from './i18n.js'

  let { features: saved, choose = true, refresh, notify, onDone } = $props()

  let features = $state({ ...saved })
  let step = $state(choose ? -1 : 0) // -1: the features, then the tour
  let rect = $state(null) // where the current step points; null: nothing to point at, the card sits in the middle
  let resized = $state(0)
  let dialog

  // sel: the first of these that is on screen (phones keep some entries behind "Mehr")
  const STEPS = $derived([
    { sel: '.today header', title: t('Dein Tag'), text: t('Hier steht, wie viele Karten heute fällig sind und wie lange das etwa dauert. Die Leertaste startet den ersten Stapel.') },
    { sel: '.strip-wrap', title: t('Zeitstrahl'), text: t('Ein Kästchen pro Tag: links, was du gelernt hast, rechts, was kommt. Ein Klick auf einen künftigen Tag lernt dessen Karten schon heute.') },
    { sel: '.today table', title: t('Stapel'), text: t('Ein Klick auf den Namen startet das Lernen. Am Griff links ziehst du einen Stapel an eine andere Stelle, in einen anderen Stapel oder ins Archiv.') },
    { sel: '[data-tour=add]', title: t('Karten hinzufügen'), text: t('Schreib eigene Karten, importiere eine Anki-Datei (.apkg) oder bitte Claude, Karten für dich zu erstellen.') },
    { sel: '[data-tour=browse]', title: t('Browser'), text: t('Alle Karten durchsuchen, bearbeiten, verschieben oder aussetzen.') },
    { sel: '[data-tour=stats]', title: t('Statistik'), text: t('Dein Lernverlauf, die Prognose und wie gut du dich erinnerst.') },
    ...(features.exams ? [{ sel: '[data-tour=exams], [data-tour=more]', title: t('Prüfungen'), text: t('Trag ein, wann eine Klausur ist. Muisti rechnet aus, wie viele neue Karten du pro Tag brauchst, und passt das Limit auf Wunsch von selbst an.') }] : []),
    { sel: '[data-tour=settings], [data-tour=more]', title: t('Einstellungen'), text: t('Hier verbindest du Claude, schaltest Zusatzfunktionen ein oder aus und änderst Darstellung und Sprache.') },
  ])
  const current = $derived(STEPS[step])

  $effect(() => {
    dialog.showModal()
  })

  $effect(() => {
    resized
    if (!current) return
    const el = [...document.querySelectorAll(current.sel)].find((e) => e.getClientRects().length)
    el?.scrollIntoView({ block: 'nearest' })
    const r = el?.getBoundingClientRect()
    rect = r ? { top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 } : null
  })

  // the card: beside narrow targets (the rail), else below or above, else over the lower edge of a tall one
  const place = $derived.by(() => {
    resized
    if (!rect) return ''
    const vw = innerWidth, vh = innerHeight, w = Math.min(340, vw - 32)
    const right = rect.left + rect.width, bottom = rect.top + rect.height
    if (rect.height < 80 && vw - right > w + 28) return `width:${w}px;left:${right + 12}px;top:${Math.max(16, Math.min(rect.top, vh - 240))}px`
    const left = Math.max(16, Math.min(rect.left, vw - w - 16))
    return `width:${w}px;left:${left}px;` + (vh - bottom > 230 ? `top:${bottom + 12}px` : rect.top > 230 ? `bottom:${vh - rect.top + 12}px` : 'bottom:16px')
  })

  async function saveFeatures(thenTour) {
    try {
      await api.save_features($state.snapshot(features)) // saved even when skipped: that is what ends the first start
      await refresh()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
    if (thenTour) step = 0
    else onDone()
  }
  const next = () => (step < STEPS.length - 1 ? step++ : onDone())
</script>

<svelte:window onresize={() => resized++} />

<!-- keys stay in here: "Heute" behind it listens for the space bar and A -->
<dialog bind:this={dialog} class="onboard" class:dim={!rect} onkeydown={(e) => e.stopPropagation()}
  oncancel={(e) => { e.preventDefault(); step < 0 ? saveFeatures(false) : onDone() }}>
  {#if step < 0}
    <div class="card wide">
      <img src="/icon.svg" alt="" width="40" height="40" />
      <h1>{t('Willkommen bei Muisti')}</h1>
      <p class="muted">{t('Welche Zusatzfunktionen möchtest du nutzen? Du kannst sie jederzeit in den Einstellungen ändern.')}</p>
      <div class="extras">
        {#each EXTRAS as x}
          <label class="extra"><input type="checkbox" bind:checked={features[x.key]} />
            <span><b>{t(x.name)}</b><small class="muted">{t(x.hint)}</small></span>
          </label>
        {/each}
      </div>
      <div class="bar">
        <button class="ghost" onclick={() => saveFeatures(false)}>{t('Ohne Einführung starten')}</button>
        <!-- svelte-ignore a11y_autofocus -->
        <button autofocus onclick={() => saveFeatures(true)}>{t('Weiter zur Einführung')}</button>
      </div>
    </div>
  {:else}
    {#if rect}<div class="spot" style="top:{rect.top}px;left:{rect.left}px;width:{rect.width}px;height:{rect.height}px"></div>{/if}
    {#key step}
      <div class="card" style={place}>
        <span class="muted small num">{step + 1} / {STEPS.length}</span>
        <h2>{current.title}</h2>
        <p>{current.text}</p>
        <div class="bar">
          <button class="plain sm" onclick={onDone}>{t('Einführung beenden')}</button>
          {#if step > 0}<button class="ghost sm" onclick={() => step--}>{t('Zurück')}</button>{/if}
          <!-- svelte-ignore a11y_autofocus -->
          <button class="sm" autofocus onclick={next}>{step < STEPS.length - 1 ? t('Weiter') : t('Fertig')}</button>
        </div>
      </div>
    {/key}
  {/if}
</dialog>

<style>
  /* the dialog only blocks the page behind; what is seen are the spotlight and the card */
  .onboard { position: fixed; inset: 0; width: 100%; height: 100%; max-width: none; max-height: none; margin: 0; padding: 0; border: 0; background: none; color: var(--ink); overflow: hidden; }
  .onboard::backdrop { background: none; }
  .onboard.dim { background: rgb(0 0 0 / 0.45); }
  .spot { position: fixed; border-radius: 12px; box-shadow: 0 0 0 200vmax rgb(0 0 0 / 0.45); pointer-events: none; transition: all 220ms var(--ease); }
  .card {
    position: fixed; display: flex; flex-direction: column; gap: 8px; padding: 16px 18px; max-height: calc(100% - 32px); overflow: auto;
    background: var(--paper); border-radius: 14px; box-shadow: 0 16px 48px rgb(0 0 0 / 0.28); animation: in 200ms var(--ease);
  }
  .dim .card { left: 50%; top: 50%; translate: -50% -50%; width: min(340px, calc(100% - 32px)); }
  .dim .card.wide { width: min(560px, calc(100% - 32px)); padding: 24px; gap: 12px; }
  @keyframes in { from { opacity: 0; } }
  h1 { font-size: 24px; font-weight: 750; letter-spacing: -0.02em; }
  h2 { font-size: 17px; font-weight: 700; }
  p { font-size: 14px; line-height: 1.45; }
  .small { font-size: 12px; }
  .extras { display: flex; flex-direction: column; gap: 14px; margin: 6px 0; }
  .extra { display: flex; gap: 12px; align-items: flex-start; font-size: 14px; cursor: pointer; }
  .extra input { margin-top: 3px; }
  .extra span { display: flex; flex-direction: column; gap: 2px; }
  .extra small { font-size: 13px; line-height: 1.4; }
  .bar { display: flex; justify-content: flex-end; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
  .bar .plain { margin-right: auto; padding-left: 0; }
  .bar .plain:hover { background: none; }
</style>
