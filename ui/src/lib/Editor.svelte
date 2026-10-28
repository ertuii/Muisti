<script>
  import DOMPurify from 'dompurify'
  import { api } from './api.js'
  import IOEditor from './IOEditor.svelte'
  import { Bold, Italic, Underline, Strikethrough, List, ListOrdered, RemoveFormatting } from '@lucide/svelte'
  import { BLOCKS, closedInline, looksLikeMarkdown, toHtml } from './markdown.js'
  import { t } from './i18n.js'

  // Note HTML (imported decks, cards from Claude) runs in the app window here, unlike CardFrame's sandbox:
  // everything that reaches a field is sanitized, or it could call window.pywebview.api.
  const clean = (html) => DOMPurify.sanitize(html)

  // Add mode without noteId, edit mode with it.
  let { noteId = null, flat, notify, onSaved, onCancel = null } = $props()

  let types = $state([])
  let typeId = $state(null)
  let deckId = $state(null)
  let fields = $state({})
  let stored = {} // edit mode: field values as saved, and as shown after sanitizing
  let shown = {}
  let tags = $state('')
  let saving = $state(false)
  let editors = $state([])

  const type = $derived(types.find((t) => t.id === typeId))
  const names = $derived(Object.keys(fields))

  // like Anki: warn while typing when the first field already exists in a note of this type
  let dupe = $state(null)
  let dupeTimer
  $effect(() => {
    const first = names.length && !type?.io ? fields[names[0]] : ''
    clearTimeout(dupeTimer)
    if (!first) return void (dupe = null)
    dupeTimer = setTimeout(async () => (dupe = await api.duplicate_of(typeId, first, noteId)), 300)
  })

  const remember = (k, v) => { try { localStorage.setItem(k, String(v)) } catch {} }
  const recall = (k) => { try { return Number(localStorage.getItem(k)) || null } catch { return null } }

  async function load() {
    types = await api.note_types()
    if (noteId) {
      const n = await api.get_note(noteId)
      typeId = n.notetype_id
      deckId = n.deck_id
      stored = n.fields
      shown = Object.fromEntries(Object.entries(n.fields).map(([k, v]) => [k, clean(v)]))
      fields = { ...shown }
      tags = n.tags.join(' ')
    } else {
      typeId = types.some((t) => t.id === recall('ba.type')) ? recall('ba.type') : (types.find((t) => t.basic) ?? types[0])?.id
      deckId = flat.some((d) => d.id === recall('ba.deck')) ? recall('ba.deck') : flat[0]?.id
      resetFields()
    }
  }

  function resetFields() {
    const t = types.find((t) => t.id === typeId)
    fields = Object.fromEntries((t?.fields ?? []).map((f) => [f, '']))
  }

  async function save() {
    if (saving) return
    const tagList = tags.split(/\s+/).filter(Boolean)
    if (type?.io && !fields[names[1]]) return notify(t('Füge zuerst ein Bild ein.'), true)
    if (type?.io && !fields[names[0]]) return notify(t('Zieh auf dem Bild mindestens einen Bereich auf.'), true)
    saving = true
    try {
      if (noteId) {
        // fields left untouched keep their stored HTML; only edited ones are saved in sanitized form
        const out = Object.fromEntries(Object.entries($state.snapshot(fields)).map(([k, v]) => [k, v === shown[k] ? stored[k] : v]))
        await api.update_note(noteId, out, tagList, deckId)
        notify(t('Gespeichert'))
      } else {
        await api.add_note(typeId, deckId, $state.snapshot(fields), tagList)
        remember('ba.type', typeId)
        remember('ba.deck', deckId)
        notify(t('Karte hinzugefügt'))
        resetFields()
        editors[0]?.focus()
      }
      onSaved?.()
    } catch (e) {
      notify(String(e?.message ?? e), true)
    } finally {
      saving = false
    }
  }

  // Cmd/Ctrl+Shift+C wraps the selection in the next cloze number, like Anki.
  function cloze() {
    const used = [...Object.values(fields).join('').matchAll(/\{\{c(\d+)::/g)].map((m) => Number(m[1]))
    const n = (used.length ? Math.max(...used) : 0) + 1
    const text = getSelection()?.toString() ?? ''
    document.execCommand('insertText', false, `{{c${n}::${text}}}`)
  }

  let pasteStrips = false
  api.preferences().then((p) => (pasteStrips = p.editing.paste_strips_formatting))

  // Images (pasted or dropped) go into the collection's media folder like in Anki.
  async function insertFiles(files) {
    for (const f of files) {
      if (!f.type.startsWith('image/') && !f.type.startsWith('audio/')) continue
      const b64 = await new Promise((res) => {
        const r = new FileReader()
        r.onload = () => res(String(r.result).split(',')[1])
        r.readAsDataURL(f)
      })
      const name = await api.add_media(f.name || `bild-${Date.now()}.png`, b64)
      const html = f.type.startsWith('image/') ? `<img src="${name}">` : `[sound:${name}]`
      document.execCommand('insertHTML', false, clean(html)) // the file name is untrusted
    }
  }

  function onPaste(e) {
    const files = [...(e.clipboardData?.files ?? [])]
    if (files.length) {
      e.preventDefault()
      insertFiles(files)
    } else if (pasteStrips) {
      e.preventDefault()
      document.execCommand('insertText', false, e.clipboardData.getData('text/plain'))
    } else if (e.clipboardData?.types.includes('text/html')) {
      e.preventDefault()
      document.execCommand('insertHTML', false, clean(e.clipboardData.getData('text/html')))
    } else if (looksLikeMarkdown(e.clipboardData?.getData('text/plain') ?? '')) {
      e.preventDefault()
      document.execCommand('insertHTML', false, clean(toHtml(e.clipboardData.getData('text/plain'))))
    }
  }

  // Toolbar: works on the field being edited, or the last one that was
  const TOOLS = [
    [Bold, 'bold', t('Fett'), '⌘B'], [Italic, 'italic', t('Kursiv'), '⌘I'], [Underline, 'underline', t('Unterstrichen'), '⌘U'],
    [Strikethrough, 'strikeThrough', t('Durchgestrichen')], [List, 'insertUnorderedList', t('Aufzählung')],
    [ListOrdered, 'insertOrderedList', t('Nummerierte Liste')], [RemoveFormatting, 'removeFormat', t('Formatierung entfernen')],
  ]
  let lastEditor = null
  let active = $state({})
  function format(cmd) {
    if (!editors.includes(document.activeElement)) (lastEditor ?? editors.find(Boolean))?.focus()
    document.execCommand(cmd)
    onSelection()
  }
  function onSelection() {
    if (editors.includes(document.activeElement)) lastEditor = document.activeElement
    else return void (active = {})
    active = Object.fromEntries(TOOLS.map(([, cmd]) => [cmd, document.queryCommandState(cmd)]))
  }

  // Markdown while typing: "- " starts a list, "**fett**" turns bold once closed, and so on (see markdown.js)
  function onInput(e) {
    if (e.inputType !== 'insertText' || !e.data) return
    const sel = getSelection(), node = /** @type {Text} */ (sel.focusNode), at = sel.focusOffset
    if (!sel.isCollapsed || node?.nodeType !== Node.TEXT_NODE) return
    const select = (from, to) => { const r = document.createRange(); r.setStart(node, from); r.setEnd(node, to); sel.removeAllRanges(); sel.addRange(r) }
    if (e.data === ' ' && !node.previousSibling) {
      for (const { re, cmd } of BLOCKS) {
        const m = re.exec(node.data.slice(0, at - 1))
        if (!m) continue
        select(0, at)
        document.execCommand('delete')
        const [name, value] = cmd(m)
        return void document.execCommand(name, false, value)
      }
    }
    const hit = closedInline(node.data.slice(0, at))
    if (!hit) return
    select(hit.start, hit.start + hit.length)
    document.execCommand('insertHTML', false, clean(`<${hit.tag}>${hit.inner.replace(/[&<>]/g, (c) => `&#${c.charCodeAt(0)};`)}</${hit.tag}>`))
    // keep typing in plain text after the formatted word
    const cmd = { b: 'bold', i: 'italic', s: 'strikeThrough' }[hit.tag]
    if (cmd && document.queryCommandState(cmd)) document.execCommand(cmd)
  }

  function onDrop(e) {
    const files = [...(e.dataTransfer?.files ?? [])]
    if (!files.length && e.dataTransfer?.types.includes('text/html')) {
      e.preventDefault()
      e.stopPropagation()
      const at = document.caretRangeFromPoint?.(e.clientX, e.clientY) // insert where it was dropped
      if (at) getSelection().removeAllRanges(), getSelection().addRange(at)
      return document.execCommand('insertHTML', false, clean(e.dataTransfer.getData('text/html')))
    }
    if (!files.length) return
    e.preventDefault()
    e.stopPropagation() // not an import: keep it away from the window-level drop handler
    insertFiles(files)
  }

  function onKey(e) {
    const mod = e.metaKey || e.ctrlKey
    if (mod && e.key === 'Enter') return e.preventDefault(), save()
    if (mod && e.shiftKey && e.key.toLowerCase() === 'c') return e.preventDefault(), cloze()
    if (e.key === 'Escape' && onCancel) onCancel()
  }

  load()
</script>

<svelte:document onselectionchange={onSelection} />

<form class="editor" onsubmit={(e) => { e.preventDefault(); save() }}>
  <div class="meta">
    <label>{t('Notiztyp')}
      <select bind:value={typeId} onchange={resetFields} disabled={!!noteId}>
        {#each types as nt}<option value={nt.id}>{nt.name}</option>{/each}
      </select>
    </label>
    <label>{t('Stapel')}
      <select bind:value={deckId}>
        {#each flat as d}<option value={d.id}>{d.name}</option>{/each}
      </select>
    </label>
  </div>

  {#if type?.io && names.length >= 2}
    <IOEditor bind:occlusion={fields[names[0]]} bind:image={fields[names[1]]} {notify} />
  {/if}

  {#if !type?.io || names.length > 2}
    <div class="tools" role="toolbar" aria-label={t('Formatierung')}>
      {#each TOOLS as [Icon, cmd, label, key]}
        <!-- mousedown keeps the selection in the field -->
        <button type="button" class="plain" class:on={active[cmd]} aria-pressed={!!active[cmd]} title={key ? `${label} (${key})` : label}
          aria-label={label} onmousedown={(e) => e.preventDefault()} onclick={() => format(cmd)}><Icon size={17} /></button>
      {/each}
      <span class="mdhint muted">{t('Markdown geht auch: **fett**, *kursiv*, - Liste')}</span>
    </div>
  {/if}

  {#each names as name, i (name)}
    {#if !type?.io || i > 1}
    <div class="field">
      <span class="fname">{name}</span>
      <div class="rich" contenteditable="true" role="textbox" aria-multiline="true" aria-label={name} tabindex="0"
        bind:this={editors[i]} bind:innerHTML={fields[name]} oninput={onInput} onkeydown={onKey} onpaste={onPaste} ondrop={onDrop}></div>
      {#if i === 0 && dupe}<span class="dupe">{t('Eine Notiz mit diesem ersten Feld gibt es schon.')}</span>{/if}
    </div>
    {/if}
  {/each}

  <label class="field">
    <span class="fname">{t('Tags')}</span>
    <input bind:value={tags} placeholder={t('durch Leerzeichen getrennt')} onkeydown={onKey} />
  </label>

  <div class="bar">
    {#if type?.cloze}
      <!-- mousedown keeps the selection in the field; also the only way on a phone -->
      <button type="button" class="ghost hint" onmousedown={(e) => e.preventDefault()} onclick={cloze} title={t('Markierten Text zur Lücke machen')}>{t('Lücke setzen')} <kbd>⌘⇧C</kbd></button>
    {/if}
    {#if onCancel}<button type="button" class="ghost" onclick={onCancel}>{t('Abbrechen')}</button>{/if}
    <button type="submit" disabled={saving || !flat.length}>{noteId ? t('Speichern') : t('Hinzufügen')} <kbd class="inv">⌘↵</kbd></button>
  </div>
  {#if !flat.length}<p class="muted">{t('Lege zuerst einen Stapel an.')}</p>{/if}
</form>

<style>
  .editor { display: flex; flex-direction: column; gap: 16px; }
  .meta { display: flex; gap: 12px; flex-wrap: wrap; }
  label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--ink-2); min-width: 0; }
  .meta label { flex: 1 1 180px; }
  select { width: 100%; }
  .field { display: flex; flex-direction: column; gap: 6px; }
  .fname { font-size: 13px; color: var(--ink-2); font-weight: 500; }
  .rich {
    min-height: 64px; padding: 10px 12px; border: 1px solid var(--rule-2); border-radius: var(--radius);
    font-size: 16px; line-height: 1.5; background: var(--paper); outline: none; overflow-wrap: anywhere;
  }
  .rich:focus { border-color: var(--ink); }
  .rich :global(img) { max-width: 100%; }
  .rich :global(:is(ul, ol)) { margin: 4px 0; padding-left: 1.5em; }
  .rich :global(li::marker) { color: var(--ink-3); }
  .rich :global(:is(h1, h2, h3)) { margin: 6px 0; line-height: 1.25; }
  .rich :global(blockquote) { margin: 4px 0; padding-left: 12px; border-left: 3px solid var(--rule-2); color: var(--ink-2); }
  .rich :global(code) { font-family: ui-monospace, monospace; font-size: .9em; padding: 1px 4px; border-radius: 4px; background: var(--paper-2); }
  .tools { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; margin-bottom: -8px; }
  .tools button { padding: 6px; line-height: 0; }
  .tools button.on { color: var(--ink); background: var(--paper-2); }
  .mdhint { margin-left: auto; font-size: 12px; }
  @media (max-width: 720px) { .mdhint { display: none; } }
  .bar { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
  .hint { margin-right: auto; }
  .dupe { font-size: 13px; color: var(--m-red); }
  kbd.inv { color: var(--paper); border-color: color-mix(in srgb, var(--paper) 40%, transparent); }
</style>
