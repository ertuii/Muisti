<script>
  import { api, hueFor } from './api.js'
  import Editor from './Editor.svelte'
  import { t } from './i18n.js'

  // Cards Claude created wait here (suspended) until they are accepted, edited or thrown away.
  let { flat, notify, refresh } = $props()

  let notes = $state(null)
  let editing = $state(null)
  let confirmReject = $state(null)

  async function load() {
    notes = await api.inbox()
  }

  async function act(fn, text) {
    try {
      notify(text(await fn()))
      confirmReject = null
      await Promise.all([load(), refresh()])
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
  }

  const accept = (ids) => act(() => api.accept_inbox(ids), (n) => (n === 1 ? t('Übernommen, die Karte wird jetzt gelernt') : t('{n} Notizen übernommen', { n })))
  function reject(id) {
    if (confirmReject !== id) return (confirmReject = id)
    act(() => api.reject_inbox([id]), () => t('Verworfen'))
  }

  // "{{c1::Berlin::Hauptstadt}}" -> text parts with the cloze answers marked
  const parts = (text) => text.split(/(\{\{c\d+::.*?\}\})/).map((p) => {
    const m = p.match(/^\{\{c\d+::(.*?)(?:::.*)?\}\}$/)
    return m ? { cloze: m[1] } : { text: p }
  })

  const hue = (deck) => hueFor(flat.find((d) => d.name === deck)?.top ?? 0)

  load()
  // new cards from Claude arrive while this page is open
  $effect(() => {
    const prev = /** @type {any} */ (window).__baRefresh
    ;/** @type {any} */ (window).__baRefresh = () => (load(), prev?.())
    return () => (/** @type {any} */ (window).__baRefresh = prev)
  })
</script>

<div class="inbox">
  <header>
    <div>
      <h1>{t('Eingang')}</h1>
      <p class="muted">{t('Karten, die Claude für dich erstellt hat. Sie werden erst gelernt, wenn du sie übernimmst.')}</p>
    </div>
    {#if notes?.length > 1}
      <button onclick={() => accept(notes.map((n) => n.note_id))}>{t('Alle {n} übernehmen', { n: notes.length })}</button>
    {/if}
  </header>

  {#if notes && !notes.length}
    <div class="empty">
      <b>{t('Alles geprüft.')}</b>
      <p class="muted">{t('Bitte Claude zum Beispiel: „Erstelle Karten aus meinem Skript zu Kapitel 3“. In Claude gibt es dafür auch den fertigen Ablauf')} <i>{t('Karten aus Material erstellen')}</i>.</p>
    </div>
  {/if}

  <ul>
    {#each notes ?? [] as n (n.note_id)}
      <li>
        {#if editing === n.note_id}
          <Editor noteId={n.note_id} {flat} {notify} onSaved={() => { editing = null; load() }} onCancel={() => (editing = null)} />
        {:else}
          <div class="meta">
            <span class="chip" style:background={hue(n.deck)}></span>{n.deck}
            <span class="muted">· {n.notetype}{n.cards > 1 ? ` · ${t('{n} Karten', { n: n.cards })}` : ''}</span>
            {#each n.tags as tag}<span class="tag">{tag}</span>{/each}
          </div>
          <div class="fields">
            {#each n.fields.filter(([, v]) => v) as [name, value], i}
              <div class:first={i === 0}><span class="fname">{name}</span>{#each parts(value) as p}{#if p.cloze}<mark>{p.cloze}</mark>{:else}{p.text}{/if}{/each}</div>
            {/each}
          </div>
          <div class="actions">
            <button class="sm" onclick={() => accept([n.note_id])}>{t('Übernehmen')}</button>
            <button class="ghost sm" onclick={() => (editing = n.note_id)}>{t('Bearbeiten')}</button>
            <button class="plain sm del" onclick={() => reject(n.note_id)} onblur={() => (confirmReject = null)}>
              {confirmReject === n.note_id ? t('Wirklich verwerfen?') : t('Verwerfen')}
            </button>
          </div>
        {/if}
      </li>
    {/each}
  </ul>
</div>

<style>
  .inbox { padding: 32px 40px 56px; max-width: 880px; display: flex; flex-direction: column; gap: 24px; }
  header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; }
  header p { font-size: 14px; margin-top: 6px; max-width: 60ch; }
  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; }
  li { padding: 16px 0; border-top: 1px solid var(--rule); display: flex; flex-direction: column; gap: 10px; }
  .meta { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; flex-wrap: wrap; }
  .meta .muted { font-weight: 400; }
  .tag { font-size: 12px; font-weight: 500; background: var(--paper-2); color: var(--ink-2); padding: 2px 8px; border-radius: 99px; }
  .fields { display: flex; flex-direction: column; gap: 4px; font-size: 15px; max-width: 70ch; }
  .fields .first { font-weight: 650; font-size: 16px; }
  .fname { display: inline-block; min-width: 90px; margin-right: 10px; font-size: 12px; font-weight: 500; color: var(--ink-3); }
  .actions { display: flex; gap: 8px; }
  mark { background: var(--heat-1); color: inherit; border-radius: 4px; padding: 0 3px; }
  .del { color: var(--m-red); }
  .empty { border: 1px dashed var(--rule-2); border-radius: 12px; padding: 24px; display: flex; flex-direction: column; gap: 6px; }
  .empty p { font-size: 14px; max-width: 62ch; }
  @media (max-width: 720px) { .inbox { padding: 20px 16px 40px; } .fname { display: block; min-width: 0; } .actions { flex-wrap: wrap; } }
</style>
