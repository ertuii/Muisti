<script>
  import { X } from '@lucide/svelte'
  import { api } from './api.js'
  import { t, tmsg } from './i18n.js'

  let { path, flat, notify, onDone, onClose } = $props()

  let info = $state(null)
  let types = $state([])
  let deck = $state('')
  let notetypeId = $state(null)
  let fieldColumns = $state([])
  let tagsColumn = $state(0)
  let busy = $state(false)
  let error = $state(null)

  const type = $derived(types.find((t) => t.id === notetypeId))

  async function load() {
    try {
      ;[info, types] = await Promise.all([api.inspect_import(path), api.note_types()])
      if (info.kind === 'csv') {
        notetypeId = info.notetype_id
        fieldColumns = info.field_columns
        tagsColumn = info.tags_column
        deck = info.name.replace(/\.[^.]+$/, '') // file name as deck name; existing names are suggested
      }
    } catch (e) {
      error = tmsg(e?.message ?? e)
    }
  }

  // New note type: map columns onto its fields in order.
  function changeType() {
    fieldColumns = (type?.fields ?? []).map((_, i) => (i < info.columns ? i + 1 : 0))
    if (tagsColumn && fieldColumns.includes(tagsColumn)) tagsColumn = 0
  }

  async function go() {
    busy = true
    try {
      const msg = info.kind === 'csv'
        ? await api.import_file(path, deck.trim() || 'Standard', notetypeId, $state.snapshot(fieldColumns), tagsColumn)
        : await api.import_file(path)
      notify(t('Importiert: {msg}', { msg: tmsg(msg) }))
      onDone()
    } catch (e) {
      error = tmsg(e?.message ?? e)
    } finally {
      busy = false
    }
  }

  load()
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
  <div class="dialog" role="dialog" aria-modal="true" aria-label={t('Importieren')}>
    <header>
      <h2>{t('Importieren')}</h2>
      <button class="plain sm" aria-label={t('Schließen')} onclick={onClose}><X size={18} /></button>
    </header>
    <p class="file">{path.split(/[\\/]/).pop().replace(/^storage:[0-9a-f]{8}-/, '')}</p>

    {#if error}
      <p class="err" role="alert">{error}</p>
    {:else if !info}
      <p class="muted">{t('Lese Datei …')}</p>
    {:else if info.kind === 'apkg'}
      <p>{t('Anki-Stapelpaket: Stapel, Karten, Lernstand und Medien werden übernommen. Vorhandene Karten werden nicht doppelt angelegt.')}</p>
    {:else if info.kind === 'colpkg'}
      <p class="warn">{t('Eine .colpkg ist eine komplette Sammlung und')} <b>{t('ersetzt alle deine Karten')}</b>. {t('Dein aktueller Stand wird vorher als Sicherung abgelegt (Einstellungen → Sicherungen).')}</p>
    {:else}
      <div class="grid">
        <label>{t('In Stapel')}
          <input list="ba-decks" bind:value={deck} placeholder={t('Name, neu oder vorhanden')} />
          <datalist id="ba-decks">{#each flat.filter((d) => !d.filtered) as d}<option value={d.name}></option>{/each}</datalist>
        </label>
        <label>{t('Notiztyp')}
          <select bind:value={notetypeId} onchange={changeType}>
            {#each types as nt}<option value={nt.id}>{nt.name}</option>{/each}
          </select>
        </label>
      </div>

      <div class="map">
        {#each type?.fields ?? [] as f, i}
          <label>{f}
            <select bind:value={fieldColumns[i]}>
              <option value={0}>{t('(leer)')}</option>
              {#each Array(info.columns) as _, c}<option value={c + 1}>{t('Spalte {n}', { n: c + 1 })}</option>{/each}
            </select>
          </label>
        {/each}
        <label>{t('Tags')}
          <select bind:value={tagsColumn}>
            <option value={0}>{t('(keine)')}</option>
            {#each Array(info.columns) as _, c}<option value={c + 1}>{t('Spalte {n}', { n: c + 1 })}</option>{/each}
          </select>
        </label>
      </div>

      <div class="preview">
        <table>
          <thead><tr>{#each Array(info.columns) as _, c}<th>{t('Spalte {n}', { n: c + 1 })}</th>{/each}</tr></thead>
          <tbody>
            {#each info.preview as row}
              <tr>{#each Array(info.columns) as _, c}<td>{row[c] ?? ''}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    <footer>
      <button class="ghost" onclick={onClose}>{t('Abbrechen')}</button>
      <button class:danger-fill={info?.kind === 'colpkg'} disabled={!info || busy || !!error} onclick={go}>
        {busy ? t('Importiere …') : info?.kind === 'colpkg' ? t('Sammlung ersetzen') : t('Importieren')}
      </button>
    </footer>
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgb(0 0 0 / 0.32); display: grid; place-items: center; z-index: 30; padding: 24px; }
  .dialog {
    width: min(720px, 100%); max-height: 100%; overflow: auto; background: var(--paper); border-radius: 14px;
    padding: 22px 24px; display: flex; flex-direction: column; gap: 14px; box-shadow: 0 20px 60px rgb(0 0 0 / 0.25);
    animation: pop 200ms var(--ease);
  }
  @keyframes pop { from { transform: translateY(8px); opacity: 0; } }
  header { display: flex; align-items: center; justify-content: space-between; }
  h2 { font-size: 20px; font-weight: 750; }
  .file { font-weight: 600; overflow-wrap: anywhere; }
  p { font-size: 14px; max-width: 65ch; }
  .err { color: var(--m-red); }
  .warn { background: var(--warn-bg); color: var(--warn-ink); padding: 12px 14px; border-radius: 10px; }
  .grid, .map { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--ink-2); }
  .preview { border: 1px solid var(--rule); border-radius: 10px; overflow: auto; max-height: 220px; }
  .preview td, .preview th { font-size: 13px; padding: 6px 10px; text-align: left; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
  footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 4px; }
  .danger-fill { background: var(--m-red); border-color: var(--m-red); color: #fff; }
</style>
