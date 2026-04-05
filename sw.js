const CACHE_NAME = "interlocks-v13";

const STATIC_ASSETS = [
    "/",
    "/manifest.json",
    "/static/app.js",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/data/all_manuals.json"
];

self.addEventListener("message", event => {
    if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

// INSTALL
self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// ACTIVATE — limpiar cachés viejos
self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// FETCH
self.addEventListener("fetch", event => {
    const url = new URL(event.request.url);

    // ❌ Nunca interceptar API ni recursos externos
    if (url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/notes")  ||
        url.pathname.startsWith("/admin")  ||
        url.pathname.startsWith("/reset")  ||
        url.origin !== self.location.origin) {
        return;
    }

    // Navegación HTML → cache first, luego red
    if (event.request.mode === "navigate") {
        event.respondWith(
            caches.match("/")
                .then(cached => cached || fetch(event.request))
                .catch(() => caches.match("/"))
        );
        return;
    }

    // Assets estáticos → cache first, luego red, sin reload automático
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                if (response?.status === 200 && response.type === "basic") {
                    caches.open(CACHE_NAME)
                        .then(c => c.put(event.request, response.clone()));
                }
                return response;
            }).catch(() => caches.match("/"));
        })
    );
});
