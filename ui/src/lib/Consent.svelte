<script>
  // Web app only, at /oauth/consent: Supabase Auth sends claude.ai's sign-in here (its OAuth 2.1 server);
  // the user allows or denies access to their cards, then goes back to Claude. See web-api/connector.py.
  import { sb } from '../web/db.js'
  import './theme.js'
  import { t } from './i18n.js'

  const id = new URLSearchParams(location.search).get('authorization_id')
  let details = $state(null)
  let error = $state(id ? null : t('Diese Anfrage ist unvollständig. Starte die Verbindung in Claude neu.'))
  let busy = $state(false)

  if (id) {
    sb.auth.oauth.getAuthorizationDetails(id).then(({ data, error: err }) => {
      if (err) error = err.message
      else if (!('authorization_id' in data)) location.href = data.redirect_url // allowed before: straight back
      else details = data
    })
  }

  async function decide(allow) {
    busy = true
    const { error: err } = allow ? await sb.auth.oauth.approveAuthorization(id) : await sb.auth.oauth.denyAuthorization(id)
    if (err) {
      error = err.message
      busy = false
    } // otherwise the browser is on its way back to Claude
  }
</script>

<main>
  <div class="box">
    <img src="/icon.svg" alt="" width="44" height="44" />
    {#if error}
      <h1>{t('Verbindung nicht möglich')}</h1>
      <p class="error" role="alert">{error}</p>
    {:else if details}
      <h1>{t('{name} mit Muisti verbinden?', { name: details.client.name || 'Claude' })}</h1>
      <p class="muted">{t('{name} kann dann deine Stapel und Karten sehen, neue Karten anlegen und bestehende bearbeiten. Neue Karten warten im Eingang, bis du sie übernimmst.', { name: details.client.name || 'Claude' })}</p>
      <p class="muted small">{t('Angemeldet als {email}. Du kannst den Zugriff jederzeit in den Einstellungen entziehen.', { email: details.user.email })}</p>
      <div class="row">
        <button disabled={busy} onclick={() => decide(true)}>{t('Zulassen')}</button>
        <button class="ghost" disabled={busy} onclick={() => decide(false)}>{t('Ablehnen')}</button>
      </div>
    {:else}
      <p class="muted">{t('Einen Moment …')}</p>
    {/if}
  </div>
</main>

<style>
  main { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--paper); color: var(--ink); }
  .box { width: min(400px, 100%); display: flex; flex-direction: column; gap: 14px; }
  h1 { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; margin: 8px 0 0; }
  p { margin: 0; }
  .small { font-size: 13px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .error { color: var(--m-red); }
</style>
