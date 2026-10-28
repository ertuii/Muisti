<script>
  // Renders card HTML/CSS (user content) isolated in a sandboxed iframe without same-origin,
  // so card scripts can't reach the app API. Media resolves from /media/. Keys are forwarded via postMessage.
  let { html, css, ord = 0, onkey = null, ontyped = null, autoplay = true, hideAudio = false } = $props()

  let frame = $state()
  const dark = document.documentElement.dataset.theme === 'dark'
  // Anki's MathJax delimiters, rendered with KaTeX; JSON keeps the backslashes intact inside the frame's script
  const MATH = JSON.stringify([{ left: '\\(', right: '\\)', display: false }, { left: '\\[', right: '\\]', display: true }])
  const katex = $derived(/\\\(|\\\[/.test(html) ? `<link rel="stylesheet" href="${location.origin}/katex/katex.min.css">
<script src="${location.origin}/katex/katex.min.js"><\/script><script src="${location.origin}/katex/contrib/auto-render.min.js"><\/script>
<script>addEventListener('DOMContentLoaded', () => renderMathInElement(document.body, { delimiters: ${MATH}, throwOnError: false }))<\/script>` : '')

  const srcdoc = $derived(`<!doctype html><html><head><meta charset="utf-8">
<base href="${location.origin}/media/">
<style>
  html,body{margin:0;min-height:100%}
  body{padding:56px 40px;font-family:system-ui,sans-serif;font-size:20px;line-height:1.5}
  @media (max-width:600px){body{padding:28px 18px}}
  .card.nightMode{color:#ecebe6;background-color:#222326}
  img{max-width:100%;height:auto}
  hr#answer{border:0;border-top:1px solid #8884;margin:28px 0}
  audio{display:block;margin:12px auto}
  .ba-tts{border:1px solid #8886;background:transparent;color:inherit;border-radius:8px;padding:4px 8px;cursor:pointer;vertical-align:middle}
  input#typeans{box-sizing:border-box;width:100%;font:inherit;padding:8px 12px;border:1px solid #8888;border-radius:8px;background:transparent;color:inherit}
  code#typeans{font-family:ui-monospace,monospace}
  .typeGood{background:#4c45}.typeBad{background:#e446}.typeMissed{background:#8885}
  #image-occlusion-container{position:relative;display:inline-block;max-width:100%}
  #image-occlusion-container img{display:block}
  #image-occlusion-canvas{position:absolute;left:0;top:0;pointer-events:none}
  ${hideAudio ? 'audio,.ba-tts{display:none}' : ''}
</style><style>${css}</style>${katex}
<script>
  addEventListener('keydown', (e) => {
    if (e.target.id === 'typeans' && e.key !== 'Enter' && e.key !== 'Escape') return // typing, not shortcuts
    if (!e.metaKey && !e.ctrlKey && (e.key.length === 1 || e.key === 'Escape' || e.key === 'Enter')) e.preventDefault() // macOS beeps on unhandled keys
    if ((e.metaKey || e.ctrlKey) && (/^[0-7]$/.test(e.key) || e.altKey || e.shiftKey)) e.preventDefault() // the reviewer's flag/menu shortcuts
    parent.postMessage({ key: e.key, code: e.code, meta: e.metaKey || e.ctrlKey, alt: e.altKey, shift: e.shiftKey }, '*')
  })
  addEventListener('input', (e) => e.target.id === 'typeans' && parent.postMessage({ typed: e.target.value }, '*'))
  addEventListener('load', () => document.getElementById('answer')?.scrollIntoView())
  addEventListener('load', () => document.getElementById('typeans')?.focus())
  const say = (b) => { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(b.dataset.text); u.lang = b.dataset.lang; speechSynthesis.speak(u) }
  addEventListener('click', (e) => { const b = e.target.closest('.ba-tts'); if (b) say(b) })
  const AUTOPLAY = ${autoplay}
  addEventListener('DOMContentLoaded', () => AUTOPLAY || document.querySelectorAll('audio').forEach((a) => { a.autoplay = false; a.pause() }))
  addEventListener('load', () => AUTOPLAY && document.querySelectorAll('.ba-tts[data-auto="1"]').forEach(say))

  // Anki's image occlusion template calls anki.imageOcclusion.setup(): draw the masks of the rendered
  // cloze divs (.cloze = asked, .cloze-highlight = answer side, .cloze-inactive = the others) over the image.
  // ponytail: rect, ellipse and polygon; text shapes are skipped
  window.anki = { imageOcclusion: { setup() {
    const img = document.querySelector('#image-occlusion-container img'), cv = document.getElementById('image-occlusion-canvas')
    if (!img || !cv) return
    const draw = () => {
      const w = img.clientWidth, h = img.clientHeight, r = devicePixelRatio || 1
      cv.width = w * r; cv.height = h * r; cv.style.width = w + 'px'; cv.style.height = h + 'px'
      const g = cv.getContext('2d'), css = getComputedStyle(cv), v = (n, d) => css.getPropertyValue(n).trim() || d
      g.scale(r, r)
      for (const el of document.querySelectorAll('[data-shape]')) {
        const active = el.classList.contains('cloze'), hl = el.classList.contains('cloze-highlight')
        if (!active && !hl && el.dataset.occludeinactive !== '1') continue
        const n = (k) => parseFloat(el.dataset[k] || '0')
        // since Anki 23.10 positions are fractions of the image; older notes store pixels of the original
        const px = ['left', 'top', 'width', 'height', 'rx'].some((k) => n(k) > 1)
        const sx = px ? w / img.naturalWidth : w, sy = px ? h / img.naturalHeight : h
        g.beginPath()
        if (el.dataset.shape === 'rect') g.rect(n('left') * sx, n('top') * sy, n('width') * sx, n('height') * sy)
        else if (el.dataset.shape === 'ellipse') {
          const rx = n('rx') || n('width') / 2, ry = n('ry') || n('height') / 2
          g.ellipse((n('left') + rx) * sx, (n('top') + ry) * sy, rx * sx, ry * sy, 0, 0, 2 * Math.PI)
        } else if (el.dataset.shape === 'polygon') {
          for (const p of (el.dataset.points || '').trim().split(/\\s+/)) { const [x, y] = p.split(',').map(Number); g.lineTo(x * sx, y * sy) }
          g.closePath()
        } else continue
        const kind = active ? 'active' : hl ? 'highlight' : 'inactive'
        g.fillStyle = v('--' + kind + '-shape-color', active ? '#ff8e8e' : hl ? 'transparent' : '#ffeba2')
        g.strokeStyle = v('--' + kind + '-shape-border', hl ? '1px #ff8e8e' : '1px #212121').split(' ').pop()
        g.lineWidth = hl ? 2 : 1
        g.fill(); g.stroke()
      }
    }
    img.complete ? draw() : img.addEventListener('load', draw)
    addEventListener('resize', draw)
    document.getElementById('toggle')?.addEventListener('click', () => { cv.style.visibility = cv.style.visibility ? '' : 'hidden' })
  } } }
<\/script></head>
<body class="card card${ord + 1}${dark ? ' nightMode night_mode' : ''}">${html}</body></html>`)

  function onMessage(e) {
    if (e.source !== frame?.contentWindow) return
    if (typeof e.data?.typed === 'string') return ontyped?.(e.data.typed)
    if (!onkey || typeof e.data?.key !== 'string') return
    onkey({ key: e.data.key, code: e.data.code, metaKey: e.data.meta, ctrlKey: false, altKey: e.data.alt, shiftKey: e.data.shift, preventDefault() {} })
  }
</script>

<svelte:window onmessage={onMessage} />

<iframe bind:this={frame} title="Karte" {srcdoc} sandbox="allow-scripts" allow="autoplay"></iframe>

<style>
  iframe { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
  :global(:root[data-theme='dark']) iframe { background: #222326; }
</style>
