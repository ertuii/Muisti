<script>
  // Web app only: sign in or create the Muisti account (Supabase Auth). The desktop signs in under Einstellungen.
  import { sb } from '../web/db.js'
  import './theme.js'
  import { t } from './i18n.js'

  let mode = $state('login') // 'login' | 'register' | 'reset'
  let email = $state('')
  let password = $state('')
  let busy = $state(false)
  let message = $state(null) // {text, error}

  const GERMAN = {
    'Invalid login credentials': 'E-Mail oder Passwort stimmt nicht.',
    'Email not confirmed': 'Bitte bestätige zuerst deine E-Mail über den Link im Postfach.',
    'User already registered': 'Für diese E-Mail gibt es schon ein Konto. Melde dich an.',
  }

  async function submit(e) {
    e.preventDefault()
    busy = true
    message = null
    try {
      const redirect = location.origin
      const { data, error } = mode === 'login' ? await sb.auth.signInWithPassword({ email, password })
        : mode === 'register' ? await sb.auth.signUp({ email, password, options: { emailRedirectTo: redirect } })
          : await sb.auth.resetPasswordForEmail(email, { redirectTo: redirect })
      if (error) throw error
      if (mode === 'login' || /** @type {any} */ (data)?.session) return location.reload()
      message = { text: mode === 'register' ? t('Fast geschafft: Bestätige deine E-Mail über den Link im Postfach.') : t('Wir haben dir einen Link zum Zurücksetzen geschickt.') }
    } catch (err) {
      message = { text: t(GERMAN[err.message] ?? err.message), error: true }
    } finally {
      busy = false
    }
  }
</script>

<main>
  <form onsubmit={submit}>
    <img src="/icon.svg" alt="" width="44" height="44" />
    <h1>{mode === 'register' ? t('Konto erstellen') : mode === 'reset' ? t('Passwort vergessen') : t('Bei Muisti anmelden')}</h1>
    <p class="muted">{t('Deine Karten, im Browser und in der Desktop-App abgeglichen.')}</p>
    <label>{t('E-Mail')}<input type="email" bind:value={email} required autocomplete="username" /></label>
    {#if mode !== 'reset'}
      <label>{t('Passwort')}<input type="password" bind:value={password} required minlength="8"
        autocomplete={mode === 'register' ? 'new-password' : 'current-password'} /></label>
    {/if}
    <button type="submit" disabled={busy}>{busy ? t('Einen Moment …') : mode === 'register' ? t('Konto erstellen') : mode === 'reset' ? t('Link schicken') : t('Anmelden')}</button>
    {#if message}<p class:error={message.error} role="status">{message.text}</p>{/if}
    <div class="links">
      {#if mode === 'login'}
        <button type="button" class="plain" onclick={() => (mode = 'register')}>{t('Neu hier? Konto erstellen')}</button>
        <button type="button" class="plain" onclick={() => (mode = 'reset')}>{t('Passwort vergessen')}</button>
      {:else}
        <button type="button" class="plain" onclick={() => (mode = 'login')}>{t('Zurück zur Anmeldung')}</button>
      {/if}
    </div>
  </form>
</main>

<style>
  main { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--paper); color: var(--ink); }
  form { width: min(360px, 100%); display: flex; flex-direction: column; gap: 14px; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; margin: 8px 0 0; }
  p { margin: 0; }
  label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 500; color: var(--ink-2); }
  input { width: 100%; }
  .error { color: var(--m-red); }
  .links { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px; margin-left: -8px; }
</style>
