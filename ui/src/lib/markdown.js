// Markdown in the note editor: typed shortcuts turn into formatting as you go, pasted Markdown text into HTML.
// ponytail: the common subset (lists, headings, quotes, bold/italic/strike/code), no tables, links or nesting

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

const INLINE = [
  { re: /\*\*(?=\S)(.+?)\*\*/g, tag: 'b' },
  { re: /__(?=\S)(.+?)__/g, tag: 'b' },
  { re: /~~(?=\S)(.+?)~~/g, tag: 's' },
  { re: /(?<![*\w])\*(?=\S)([^*]+?)\*(?!\*)/g, tag: 'i' },
  { re: /(?<![_\w])_(?=\S)([^_]+?)_(?![_\w])/g, tag: 'i' },
  { re: /`([^`]+)`/g, tag: 'code' },
]

export function inline(text) {
  let html = esc(text)
  for (const { re, tag } of INLINE) html = html.replace(re, `<${tag}>$1</${tag}>`)
  return html
}

// Block markers typed at the start of a line, followed by a space: the editor command they become.
export const BLOCKS = [
  { re: /^[-*+]$/, cmd: () => ['insertUnorderedList'] },
  { re: /^1[.)]$/, cmd: () => ['insertOrderedList'] },
  { re: /^(#{1,3})$/, cmd: (m) => ['formatBlock', `h${m[1].length}`] },
  { re: /^>$/, cmd: () => ['formatBlock', 'blockquote'] },
]

// Text right before the caret that just closed an inline marker: what to replace and with which tag.
export function closedInline(before) {
  for (const { re, tag } of INLINE) {
    const m = new RegExp(`(?:${re.source})$`).exec(before)
    if (m) return { start: m.index, length: m[0].length, inner: m[1], tag }
  }
  return null
}

const LIST = { ul: /^\s*[-*+]\s+(.*)$/, ol: /^\s*\d+[.)]\s+(.*)$/ }

export const looksLikeMarkdown = (text) =>
  /^\s*([-*+]|\d+[.)]|#{1,3}|>)\s/m.test(text) || INLINE.some(({ re }) => new RegExp(re.source).test(text))

export function toHtml(text) {
  const out = []
  let list = null // the open <ul>/<ol>
  const close = () => list && (out.push(`</${list}>`), (list = null))
  for (const line of text.replace(/\r\n?/g, '\n').split('\n')) {
    const kind = Object.keys(LIST).find((k) => LIST[k].test(line))
    if (kind) {
      if (list !== kind) close(), out.push(`<${kind}>`), (list = kind)
      out.push(`<li>${inline(line.match(LIST[kind])[1])}</li>`)
      continue
    }
    close()
    const h = line.match(/^(#{1,3})\s+(.*)$/)
    const q = line.match(/^>\s?(.*)$/)
    if (h) out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`)
    else if (q) out.push(`<blockquote>${inline(q[1])}</blockquote>`)
    else out.push(`<div>${line.trim() ? inline(line) : '<br>'}</div>`)
  }
  close()
  return out.join('')
}
