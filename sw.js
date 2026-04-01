// ⚠️ Cambia este número cada vez que quieras forzar actualización
const CACHE_NAME = "interlocks-v11";

const STATIC_ASSETS = [
    "/",
    "/manifest.json",
    "/static/app.js",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/data/all_manuals.json"
];

// ── SKIP WAITING cuando la página lo pide ──
self.addEventListener("message", event => {
    if (event.data?.type === "SKIP_WAITING") {
        self.skipWaiting();
    }
});

// ── INSTALL: cachea assets estáticos ──
self.addEventListener("install", event => {
    console.log("[SW] Instalando:", CACHE_NAME);
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// ── ACTIVATE: elimina cachés viejos ──
self.addEventListener("activate", event => {
    console.log("[SW] Activando:", CACHE_NAME);
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(k => k !== CACHE_NAME)
                    .map(k => {
                        console.log("[SW] Eliminando caché viejo:", k);
                        return caches.delete(k);
                    })
            )
        ).then(() => self.clients.claim())
    );
});

// ── FETCH ──
self.addEventListener("fetch", event => {
    const url = new URL(event.request.url);

    // 🔴 NUNCA interceptar llamadas a la API /search
    if (url.pathname.startsWith("/search")) {
        return; // deja pasar directo a la red
    }

    // 🔴 NUNCA interceptar requests a otros orígenes (ej: fonts)
    if (url.origin !== self.location.origin) {
        return;
    }

    // Navegación HTML → servir desde caché (permite offline)
    if (event.request.mode === "navigate") {
        event.respondWith(
            caches.match("/").then(cached => cached || fetch(event.request))
        );
        return;
    }

    // Estrategia: Cache first, luego red
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                // Cachear nuevos assets válidos
                if (response && response.status === 200 && response.type === "basic") {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            });
        }).catch(() => {
            // Sin red y sin caché: para navegación devolver el shell
            if (event.request.mode === "navigate") {
                return caches.match("/");
            }
        })
    );
});
