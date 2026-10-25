<script>
  import { ArrowUp, ArrowDown, ArrowLeft, X, Plus } from '@lucide/svelte'
  import { api } from './api.js'
  import CardFrame from './CardFrame.svelte'
  import { t } from './i18n.js'

  let { notify } = $props()

  let types = $state([])
  let selId = $state(null)
  let nt = $state(null) // editable copy
  let original = '' // JSON of the loaded state, to detect unsaved changes
  let tab = $state('fields')
  let tIndex = $state(0)
  let side = $state('q')
  let preview = $state(null)
  let creating = $state(null)
  let confirmDelete = $state(false)
  let saving = $state(false)
  let previewTimer
  let detail = $state(false) // phones: list or editor, one at a time

  const dirty = $derived(nt && JSON.stringify(nt) !== original)

  async function loadTypes(selectId) {
    types = await api.note_types()
    await select(selectId ?? selId ?? types[0]?.id)
  }

  async function select(id) {
    if (id == null) return
    selId = id
    nt = null
    try {
      const got = await api.notetype(id)
      if (selId !== id) return // another one was picked meanwhile
      nt = got
    } catch (e) {
      if (selId !== id) return
      selId = null
      detail = false
      return notify(String(e?.message ?? e), true)
    }
    original = JSON.stringify(nt)
    tIndex = 0
    confirmDelete = false
  }

  // Live preview, debounced; renders through Anki's own template engine.
  $effect(() => {
    if (!nt || tab === 'fields') return
    const snap = $state.snapshot(nt)
    const i = Math.min(tIndex, snap.templates.length - 1)
    clearTimeout(previewTimer)
    previewTimer = setTimeout(async () => {
      try {
        preview = await api.preview_template(snap, i)
      } catch (e) {
        preview = { question: `<p style="color:#d93a28">${e?.message ?? e}</p>`, answer: '', css: '', ord: 0 }
      }
    }, 300)
  })

  function move(list, i, d) {
    const j = i + d
    if (j < 0 || j >= list.length) return
    ;[list[i], list[j]] = [list[j], list[i]]
  }

  async function save() {
    const names = nt.fields.map((f) => f.name.trim())
    if (names.some((n) => !n)) return notify(t('Felder brauchen einen Namen'), true)
    if (new Set(names).size !== names.length) return notify(t('Feldnamen müssen eindeutig sein'), true)
    saving = true
    try {
      await api.save_notetype($state.snapshot(nt))
      notify(t('Notiztyp gespeichert'))
      await loadTypes(nt.id)
    } catch (e) {
      notify(String(e?.message ?? e), true)
    } finally {
      saving = false
    }
  }

  async function create() {
    if (!creating?.trim()) return (creating = null)
    try {
      const id = await api.add_notetype(selId, creating)
      notify(t('„{name}“ angelegt', { name: creating }))
      creating = null
      await loadTypes(id)
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
  }

  async function remove() {
    if (!confirmDelete) return (confirmDelete = true)
    try {
      await api.delete_notetype(selId)
      notify(t('„{name}“ gelöscht', { name: nt.name }))
      selId = null
      await loadTypes()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    }
  }

  loadTypes()
</script>

<div class="nts" class:detail>
  <aside class="list">
    <h1>{t('Notiztypen')}</h1>
    <nav>
      {#each types as ty (ty.id)}
        <button class="item" class:on={ty.id === selId} onclick={() => { detail = true; select(ty.id) }}>{ty.name}</button>
      {/each}
    </nav>
    {#if creating === null}
      <button class="ghost" onclick={() => (creating = '')}><Plus size={16} />{t('Neuer Notiztyp')}</button>
    {:else}
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={creating} placeholder={t('Name (Kopie des gewählten)')} autofocus
        onkeydown={(e) => e.key === 'Enter' ? create() : e.key === 'Escape' && (creating = null)} onblur={create} />
    {/if}
  </aside>

  {#if nt}
    <section class="edit">
      <button class="plain back" onclick={() => (detail = false)}><ArrowLeft size={17} />{t('Alle Notiztypen')}</button>
      <div class="head">
        <input class="name" bind:value={nt.name} aria-label={t('Name des Notiztyps')} />
        <span class="muted">{t(nt.use_count === 1 ? '{n} Notiz' : '{n} Notizen', { n: nt.use_count })}</span>
        <button class="danger sm" onclick={remove} onblur={() => (confirmDelete = false)}>
          {confirmDelete ? t('Mit {n} Notizen löschen?', { n: nt.use_count }) : t('Löschen')}
        </button>
      </div>

      <div class="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'fields'} class:on={tab === 'fields'} onclick={() => (tab = 'fields')}>{t('Felder')}</button>
        <button role="tab" aria-selected={tab === 'templates'} class:on={tab === 'templates'} onclick={() => (tab = 'templates')}>{t('Kartenvorlagen')}</button>
        <button role="tab" aria-selected={tab === 'css'} class:on={tab === 'css'} onclick={() => (tab = 'css')}>{t('Stil')}</button>
      </div>

      {#if tab === 'fields'}
        <ol class="fields">
          {#each nt.fields as f, i (f)}
            <li>
              <span class="idx num muted">{i + 1}</span>
              <input bind:value={f.name} aria-label={t('Feldname {n}', { n: i + 1 })} />
              <button class="plain sm" aria-label={t('Nach oben')} disabled={i === 0} onclick={() => move(nt.fields, i, -1)}><ArrowUp size={16} /></button>
              <button class="plain sm" aria-label={t('Nach unten')} disabled={i === nt.fields.length - 1} onclick={() => move(nt.fields, i, 1)}><ArrowDown size={16} /></button>
              <button class="plain sm" aria-label={t('Feld entfernen')} disabled={nt.fields.length === 1} onclick={() => nt.fields.splice(i, 1)}><X size={16} /></button>
            </li>
          {/each}
        </ol>
        <div><button class="ghost sm" onclick={() => nt.fields.push({ ord: null, name: t('Feld {n}', { n: nt.fields.length + 1 }) })}><Plus size={15} />{t('Feld hinzufügen')}</button></div>
        <p class="muted note">{t('Entfernte Felder löschen ihren Inhalt in allen {n} Notizen. Umbenennungen werden in den Vorlagen übernommen.', { n: nt.use_count })}</p>
      {:else}
        <div class="tpl-bar">
          {#if tab === 'templates' && !nt.cloze}
            <select class="sm" bind:value={tIndex} aria-label={t('Kartenvorlage')}>
              {#each nt.templates as tpl, i}<option value={i}>{tpl.name}</option>{/each}
            </select>
            <input class="sm tname" bind:value={nt.templates[tIndex].name} aria-label={t('Name der Vorlage')} />
            <button class="ghost sm" onclick={() => { nt.templates.push({ ord: null, name: t('Karte {n}', { n: nt.templates.length + 1 }), qfmt: '{{' + nt.fields[0].name + '}}', afmt: '{{FrontSide}}\n\n<hr id=answer>\n\n' }); tIndex = nt.templates.length - 1 }}><Plus size={15} />{t('Vorlage')}</button>
            <button class="plain sm" disabled={nt.templates.length === 1} onclick={() => { nt.templates.splice(tIndex, 1); tIndex = 0 }}>{t('Vorlage entfernen')}</button>
          {/if}
          <div class="seg">
            <button class:on={side === 'q'} onclick={() => (side = 'q')}>{t('Vorderseite')}</button>
            <button class:on={side === 'a'} onclick={() => (side = 'a')}>{t('Rückseite')}</button>
          </div>
        </div>
        <div class="split">
          {#if tab === 'templates'}
            {#if side === 'q'}
              <textarea class="code" bind:value={nt.templates[tIndex].qfmt} spellcheck="false" aria-label={t('Vorlage Vorderseite')}></textarea>
            {:else}
              <textarea class="code" bind:value={nt.templates[tIndex].afmt} spellcheck="false" aria-label={t('Vorlage Rückseite')}></textarea>
            {/if}
          {:else}
            <textarea class="code" bind:value={nt.css} spellcheck="false" aria-label="CSS"></textarea>
          {/if}
          <div class="preview">
            {#if preview}<CardFrame html={side === 'q' ? preview.question : preview.answer} css={preview.css} ord={preview.ord} />{/if}
          </div>
        </div>
        <p class="muted note">{t('Felder einsetzen mit')} <code>{`{{${t('Feldname')}}}`}</code>{t(', Vorderseite auf der Rückseite mit')} <code>{'{{FrontSide}}'}</code>{t(', Vorlesen mit')} <code>{`{{tts ${t('de_DE')}:${t('Feldname')}}}`}</code>.</p>
      {/if}

      <div class="bar">
        {#if dirty}<span class="muted">{t('Ungespeicherte Änderungen')}</span>{/if}
        <button class="ghost" disabled={!dirty} onclick={() => select(selId)}>{t('Verwerfen')}</button>
        <button disabled={!dirty || saving} onclick={save}>{saving ? t('Speichere …') : t('Speichern')}</button>
      </div>
    </section>
  {:else if selId != null}
    <section class="edit" aria-busy="true" aria-label={t('Notiztyp wird geladen')}>
      <button class="plain back" onclick={() => (detail = false)}><ArrowLeft size={17} />{t('Alle Notiztypen')}</button>
      <span class="skel" style="width:280px;max-width:100%;height:var(--control-h)"></span>
      <span class="skel" style="width:220px;height:30px"></span>
      {#each Array(4) as _}<span class="skel" style="max-width:560px;height:var(--control-h)"></span>{/each}
    </section>
  {/if}
</div>

<style>
  .nts { display: flex; height: 100%; }
  .list { width: 240px; flex: none; border-right: 1px solid var(--rule); padding: 28px 16px; display: flex; flex-direction: column; gap: 12px; overflow: auto; }
  h1 { font-size: 22px; font-weight: 750; letter-spacing: -0.02em; padding: 0 8px; }
  nav { display: flex; flex-direction: column; gap: 2px; }
  .item { background: transparent; color: var(--ink); border: 0; justify-content: flex-start; font-weight: 500; padding: 0 10px; text-align: left; white-space: normal; height: auto; min-height: 34px; }
  .item:hover { background: var(--paper-2); opacity: 1; }
  .item.on { background: var(--paper-3); font-weight: 650; }
  .edit { flex: 1; min-width: 0; padding: 28px 32px 0; display: flex; flex-direction: column; gap: 16px; overflow: auto; }
  .head { display: flex; align-items: center; gap: 12px; }
  .name { font-size: 18px; font-weight: 650; flex: 1; max-width: 420px; }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--rule); }
  .tabs button { background: transparent; color: var(--ink-2); border: 0; border-bottom: 2px solid transparent; border-radius: 0; font-weight: 500; }
  .tabs button.on { color: var(--ink); border-bottom-color: var(--ink); font-weight: 650; }
  .fields { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; max-width: 560px; }
  .fields li { display: flex; align-items: center; gap: 6px; }
  .fields input { flex: 1; }
  .idx { width: 20px; text-align: right; font-size: 13px; }
  .note { font-size: 13px; max-width: 70ch; }
  code { font-size: 12px; background: var(--paper-2); padding: 1px 5px; border-radius: 4px; }
  .tpl-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .tpl-bar select { width: 200px; }
  .tname { width: 180px; }
  .seg { display: inline-flex; border: 1px solid var(--rule-2); border-radius: var(--radius); padding: 2px; margin-left: auto; }
  .seg button { background: transparent; color: var(--ink-2); border: 0; height: 26px; padding: 0 12px; font-weight: 500; font-size: 13px; }
  .seg button.on { background: var(--ink); color: var(--paper); }
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; min-height: 340px; flex: 1; }
  .code { font: 13px/1.5 ui-monospace, 'SF Mono', Menlo, Consolas, monospace; resize: none; height: 100%; min-height: 340px; }
  .preview { border: 1px solid var(--rule); border-radius: 12px; overflow: hidden; min-height: 340px; }
  .bar { display: flex; justify-content: flex-end; align-items: center; gap: 8px; position: sticky; bottom: 0; padding: 14px 0; background: var(--paper); border-top: 1px solid var(--rule); margin-top: auto; }
  .bar span { margin-right: auto; font-size: 13px; }
  .back { display: none; }
  @media (max-width: 1000px) { .split { grid-template-columns: 1fr; } }
  @media (max-width: 860px) {
    .list { width: 100%; border-right: 0; padding: 20px 8px; }
    .nts.detail .list, .nts:not(.detail) .edit { display: none; }
    .item { min-height: 44px; font-size: 16px; }
    .edit { padding: 12px 16px 0; }
    .back { display: inline-flex; align-self: flex-start; margin-left: -8px; }
    .head { flex-wrap: wrap; }
    .name { flex: 1 1 100%; max-width: none; }
    .tabs { overflow-x: auto; }
    .tpl-bar select, .tname { width: auto; flex: 1 1 140px; }
    .seg { margin-left: 0; }
    .split { flex: none; }
    .code, .preview { min-height: 260px; }
  }
</style>
