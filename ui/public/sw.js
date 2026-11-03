// Offline shell for the web app (registered in src/main.js). The collection itself is offline already
// (IndexedDB + write queue in src/web/db.js); this only makes the page load without a network.
// The build (vite.config.js) fills in the version and the app's files: a new deploy changes this file, the browser
// installs it and the old cache goes. KaTeX (3 MB) is cached when a card first uses it.
const VERSION = 'dev'
const ASSETS = []
const CACHE = `muisti-${VERSION}`

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/', '/icon.svg', ...ASSETS])))
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))))
  self.clients.claim()
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname === '/version.json') return
  if (e.request.mode === 'navigate') {
    // network first: a new deploy shows up right away; offline the last page
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put('/', copy)) }
      return r
    }).catch(() => caches.match('/', { ignoreVary: true })))
  } else if (/^\/(assets|katex)\/|^\/icon/.test(url.pathname)) {
    // hashed or versioned with the app: cache first
    // ignoreVary: servers send Vary: Origin, module requests carry an Origin the cached copy may lack
    e.respondWith(caches.match(e.request, { ignoreVary: true }).then((hit) => hit || fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)) }
      return r
    })))
  }
})
