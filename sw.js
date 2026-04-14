// SOLVI SW v20
// Offline robusto: Caché individual y manejo seguro de errores de red

const CACHE = "solvi-v20";

const PRECACHE = [
    "/",
    "/static/app.js",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/data/all_manuals.json",
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js"
];

self.addEventListener("install", e => {
    e.waitUntil(
        caches.open(CACHE).then(cache => {
            // MEJORA 1: Instalación resiliente (uno por uno).
            // Si el internet parpadea y un ícono falla, el JSON y la App sí se guardan.
            return Promise.all(
                PRECACHE.map(url => {
                    return cache.add(url).catch(err => console.warn("SW: Omitido por red ->", url));
                })
            );
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", e => {
    const url = new URL(e.request.url);

    // Nunca interceptar: API calls, reset y PDFs externos (Cloudflare R2)
    if (url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/notes")  ||
        url.pathname.startsWith("/admin")  ||
        url.pathname.startsWith("/reset")  ||
        url.hostname.includes("r2.dev")    ||
        url.pathname.endsWith(".pdf")) {
        return;
    }

    // Navegación al shell (/) → red primero, caché como fallback offline
    if (e.request.mode === "navigate" || url.pathname === "/") {
        e.respondWith(
            fetch(e.request)
                .then(res => {
                    if (res.ok) {
                        const clone = res.clone();
                        caches.open(CACHE).then(c => c.put(e.request, clone));
                    }
                    return res;
                })
                .catch(() => caches.match("/"))
        );
        return;
    }

    // Todo lo demás: caché primero, luego red, guardar en caché
    e.respondWith(
        caches.match(e.request).then(cached => {
            if (cached) return cached; // Si está en caché, lo devuelve instantáneo
            
            return fetch(e.request).then(res => {
                if (res && res.ok) {
                    const clone = res.clone();
                    caches.open(CACHE).then(c => c.put(e.request, clone));
                }
                return res;
            }).catch(() => {
                // MEJORA 2: Respuesta de seguridad en caso de Offline extremo
                // Evita que la app colapse mostrando un "Failed to fetch" rojo en consola
                if (url.pathname.endsWith(".json")) {
                    return new Response("[]", { headers: { "Content-Type": "application/json" } });
                }
                return new Response("Offline", { status: 503, statusText: "Offline" });
            });
        })
    );
});