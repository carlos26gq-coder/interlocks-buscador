// Interlocks SW v15
// Solo cachea iconos y JSON de manuales
// NUNCA cachea HTML ni JS

const CACHE = "interlocks-v15";

self.addEventListener("install", e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll([
            "/static/icon-192.png",
            "/static/icon-512.png",
            "/data/all_manuals.json"
        ])).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", e => {
    const url = new URL(e.request.url);
    // Nunca interceptar: HTML, JS, API, externos
    if (url.pathname === "/" ||
        url.pathname.endsWith(".html") ||
        url.pathname.endsWith(".js") ||
        url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/notes") ||
        url.pathname.startsWith("/admin") ||
        url.pathname.startsWith("/reset") ||
        url.origin !== self.location.origin) {
        return;
    }
    // Solo cachear iconos y JSON
    e.respondWith(
        caches.match(e.request).then(cached => {
            if (cached) return cached;
            return fetch(e.request).then(res => {
                if (res && res.ok) {
                    const clone = res.clone();
                    caches.open(CACHE).then(c => c.put(e.request, clone));
                }
                return res;
            });
        })
    );
});
