import { mount } from 'svelte'
import '@fontsource-variable/archivo'
import './app.css'
import App from './App.svelte'
import { setLang } from './lib/i18n.js'

const target = document.getElementById('app')

// language before the first render: stored in the collection like the theme; the first start saves the browser's
async function start() {
  const { api } = await import('./lib/api.js')
  const saved = await api.language().catch(() => null)
  const lang = setLang(saved)
  if (lang !== saved) api.set_language(lang).catch(() => {})
  await import('./lib/theme.js')
  mount(App, { target })
}

if (import.meta.env.MODE === 'web') {
  // web: sign in first, then load the collection from Supabase (src/web/db.js)
  const { sb, open } = await import('./web/db.js')
  const { data } = await sb.auth.getSession()
  if (data.session) {
    await open(data.session.user.id)
    await start()
    // the worker loads the collection once per server instance: do it now, not when statistics are first opened
    setTimeout(() => import('./web/core.js').then((c) => c.worker('warm')).catch(() => {}), 1500)
  } else {
    setLang(null)
    const { default: Login } = await import('./lib/Login.svelte')
    mount(Login, { target })
  }
} else {
  await start()
}
