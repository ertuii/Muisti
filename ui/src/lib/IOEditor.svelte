<script>
  import { X } from '@lucide/svelte'
  import { api } from './api.js'
  import { t } from './i18n.js'

  // Image occlusion in Anki's own format: the Image field holds <img src>, the Occlusion field one cloze per mask,
  // e.g. {{c1::image-occlusion:rect:left=.1:top=.2:width=.3:height=.1:oi=1}} (positions as fractions of the image).
  // ponytail: new masks are rectangles, one card each; ellipses/polygons from Anki are kept and shown as boxes or not at all
  let { occlusion = $bindable(''), image = $bindable(''), notify } = $props()

  const parse = (text) => [...(text || '').matchAll(/\{\{c(\d+)::image-occlusion:(\w+):?(.*?)\}\}/g)].map((m) => ({
    n: Number(m[1]), kind: m[2], props: Object.fromEntries(m[3].split(':').filter(Boolean).map((p) => [p.split('=')[0], p.split('=')[1] ?? ''])),
  }))
  const serialize = (list) => list.map((s) => `{{c${s.n}::image-occlusion:${s.kind}:${Object.entries(s.props).map(([k, v]) => (v === '' ? k : `${k}=${v}`)).join(':')}}}`).join('')

  let shapes = $state(parse(occlusion))
  // svelte-ignore state_referenced_locally
  let hideOthers = $state(shapes.length ? shapes.every((s) => s.props.oi === '1') : true)
  let selected = $state(null)
  let draft = $state(null)
  let natural = $state({ w: 1, h: 1 })
  let start = null
  let area = $state()
  let file = $state()

  const src = $derived(image.match(/src="([^"]+)"/)?.[1] ?? '')

  // pick up a different note (edit mode loads after mount, adding resets the fields)
  let last = occlusion
  $effect(() => {
    if (occlusion !== last) { shapes = parse(occlusion); last = occlusion }
  })
  function commit() {
    for (const s of shapes) hideOthers ? (s.props.oi = '1') : delete s.props.oi
    last = occlusion = serialize(shapes)
  }

  // box in fractions of the image for drawing; old Anki notes store pixels of the original image
  function box(s) {
    const p = Object.fromEntries(Object.entries(s.props).map(([k, v]) => [k, Number(v) || 0]))
    const w = p.width || 2 * (p.rx || 0), h = p.height || 2 * (p.ry || 0)
    const px = [p.left, p.top, w, h].some((v) => v > 1)
    return { left: px ? p.left / natural.w : p.left, top: px ? p.top / natural.h : p.top, width: px ? w / natural.w : w, height: px ? h / natural.h : h }
  }
  const pct = (b) => `left:${b.left * 100}%;top:${b.top * 100}%;width:${b.width * 100}%;height:${b.height * 100}%`

  function at(e) {
    const r = area.getBoundingClientRect()
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) }
  }
  function down(e) {
    if (e.target !== area) return
    start = at(e)
    selected = null
    area.setPointerCapture(e.pointerId)
  }
  function move(e) {
    if (!start) return
    const p = at(e)
    draft = { left: Math.min(start.x, p.x), top: Math.min(start.y, p.y), width: Math.abs(p.x - start.x), height: Math.abs(p.y - start.y) }
  }
  function up() {
    if (draft && draft.width > 0.01 && draft.height > 0.01) {
      const n = Math.max(0, ...shapes.map((s) => s.n)) + 1
      const f = (v) => v.toFixed(4)
      shapes.push({ n, kind: 'rect', props: { left: f(draft.left), top: f(draft.top), width: f(draft.width), height: f(draft.height) } })
      commit()
    }
    start = draft = null
  }
  function remove(s) {
    shapes = shapes.filter((x) => x !== s)
    selected = null
    commit()
  }
  function onKey(e) {
    if (selected && (e.key === 'Delete' || e.key === 'Backspace')) e.preventDefault(), remove(selected)
  }

  async function setImage(file) {
    if (!file?.type.startsWith('image/')) return notify(t('Das ist kein Bild.'), true)
    const b64 = await new Promise((res) => {
      const r = new FileReader()
      r.onload = () => res(String(r.result).split(',')[1])
      r.readAsDataURL(file)
    })
    const name = await api.add_media(file.name || `bild-${Date.now()}.png`, b64)
    image = `<img src="${name.replace(/["<>&]/g, '')}">` // the file name is untrusted
    shapes = []
    commit()
  }
  const onPaste = (e) => e.clipboardData?.files[0] && (e.preventDefault(), setImage(e.clipboardData.files[0]))
  function onDrop(e) {
    if (!e.dataTransfer?.files[0]) return
    e.preventDefault()
    e.stopPropagation() // not an import
    setImage(e.dataTransfer.files[0])
  }
</script>

<div class="io" onpaste={onPaste} ondrop={onDrop} ondragover={(e) => e.preventDefault()} role="group" aria-label={t('Bild-Verdeckung')}>
  {#if !src}
    <button type="button" class="pick" onclick={() => file.click()}>
      {t('Bild hier einfügen')} (<kbd>⌘V</kbd>){t(', hineinziehen oder auswählen')}
    </button>
  {:else}
    <p class="muted hint">{t('Bereiche aufziehen, die verdeckt werden sollen. Jeder Bereich wird eine Karte. Auswählen und')} <kbd>⌫</kbd> {t('löscht.')}</p>
    <div class="stage">
      <img {src} alt="" onload={(e) => { const i = /** @type {HTMLImageElement} */ (e.currentTarget); natural = { w: i.naturalWidth, h: i.naturalHeight } }} />
      <div class="area" bind:this={area} onpointerdown={down} onpointermove={move} onpointerup={up} role="presentation">
        {#each shapes as s}
          {#if s.props.left !== undefined && s.kind !== 'polygon' && s.kind !== 'text'}
            <button type="button" class="mask" class:sel={selected === s} class:round={s.kind === 'ellipse'} style={pct(box(s))}
              onclick={() => (selected = s)} onkeydown={onKey} aria-label={t('Bereich {n}', { n: s.n })}>
              <span>{s.n}</span>
              {#if selected === s}<span class="del" role="presentation" onclick={(e) => { e.stopPropagation(); remove(s) }}><X size={12} /></span>{/if}
            </button>
          {/if}
        {/each}
        {#if draft}<div class="mask draft" style={pct(draft)}></div>{/if}
      </div>
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" bind:checked={hideOthers} onchange={commit} /> {t('Beim Abfragen auch die anderen Bereiche verdecken')}</label>
      <button type="button" class="ghost again" onclick={() => file.click()}>{t('Anderes Bild')}</button>
    </div>
    <p class="muted hint">{shapes.length ? t(shapes.length === 1 ? '{n} Bereich' : '{n} Bereiche', { n: shapes.length }) : t('Noch kein Bereich')}</p>
  {/if}
  <input type="file" accept="image/*" bind:this={file} onchange={(e) => { setImage(e.currentTarget.files?.[0]); e.currentTarget.value = '' }} hidden />
</div>

<style>
  .io { display: flex; flex-direction: column; gap: 8px; }
  .pick {
    height: auto; min-height: 160px; padding: 16px; background: transparent; font-weight: 500;
    border: 1px dashed var(--rule-2); border-radius: var(--radius); color: var(--ink-2);
  }
  .pick:focus-visible, .pick:hover { border-color: var(--ink); background: transparent; }
  .stage { position: relative; align-self: flex-start; max-width: 100%; user-select: none; }
  .stage img { display: block; max-width: 100%; border-radius: 4px; }
  .area { position: absolute; inset: 0; cursor: crosshair; touch-action: none; outline: none; }
  .mask {
    position: absolute; padding: 0; height: auto; border-radius: 2px; background: color-mix(in srgb, #ffeba2 85%, transparent);
    border: 1px solid #212121; color: #212121; font-size: 12px; font-weight: 650; display: flex; align-items: center; justify-content: center; cursor: pointer;
  }
  .mask.round { border-radius: 50%; }
  .mask.sel { background: color-mix(in srgb, #ff8e8e 85%, transparent); outline: 2px solid var(--ink); }
  .mask.draft { pointer-events: none; border-style: dashed; }
  .del { position: absolute; top: -9px; right: -9px; width: 18px; height: 18px; border-radius: 99px; background: var(--ink); color: var(--paper); display: flex; align-items: center; justify-content: center; }
  .row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .check { flex-direction: row; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-2); }
  .again { margin-left: auto; }
  .hint { font-size: 13px; }
</style>
