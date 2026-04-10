// SOLVI SW v16
// Cachea: iconos, JSON manuales, app.js y PDF.js para uso offline completo

const CACHE = "solvi-v16";

self.addEventListener("install", e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll([
            "/static/icon-192.png",
            "/static/icon-512.png",
            "/data/all_manuals.json",
            "/static/app.js",
            "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js"
        ])).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", e => {
    const url = new URL(e.request.url);

    // Nunca interceptar: HTML principal, API, reset
    if (url.pathname === "/" ||
        url.pathname.endsWith(".html") ||
        url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/notes") ||
        url.pathname.startsWith("/admin") ||
        url.pathname.startsWith("/reset")) {
        return;
    }

    // Cache first para todo lo demás (app.js, PDF.js desde CDN, iconos, JSON)
    e.respondWith(
        caches.match(e.request).then(cached => {
            if (cached) return cached;
            return fetch(e.request).then(res => {
                if (res && res.ok) {
                    const clone = res.clone();
                    caches.open(CACHE).then(c => c.put(e.request, clone));
                }
                return res;
            }).catch(() => caches.match(e.request));
        })
    );
});
