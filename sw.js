// SOLVI Service Worker v23 — aplicación e índices offline por manual.
const CACHE = "solvi-v23";
const CORE = [
    "/",
    "/manifest.json",
    "/static/app.js",
    "/static/search-worker.js",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/data/search/catalog.json"
];

async function addResilient(cache, url) {
    try {
        const response = await fetch(url, {cache: "no-cache"});
        if (response.ok) await cache.put(url, response);
    } catch (error) {
        console.warn("SW: recurso no disponible", url);
    }
}

async function cacheOfflineManuals(cache) {
    try {
        const response = await fetch("/data/search/catalog.json", {cache: "no-cache"});
        if (!response.ok) return;
        const catalog = await response.clone().json();
        await cache.put("/data/search/catalog.json", response);
        await Promise.allSettled((catalog.manuals || []).map(item => addResilient(cache, item.file)));
    } catch (error) {
        console.warn("SW: no se pudo preparar el catálogo offline", error);
    }
}

self.addEventListener("install", event => {
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE);
        await Promise.allSettled(CORE.map(url => addResilient(cache, url)));
        await cacheOfflineManuals(cache);
        await self.skipWaiting();
    })());
});

self.addEventListener("activate", event => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter(key => key.startsWith("solvi-") && key !== CACHE).map(key => caches.delete(key)));
        await self.clients.claim();
    })());
});

async function networkFirst(request) {
    const cache = await caches.open(CACHE);
    try {
        const response = await fetch(request);
        if (response && response.ok) await cache.put(request, response.clone());
        return response;
    } catch (error) {
        const cached = await cache.match(request, {ignoreSearch: true});
        if (cached) return cached;
        if (request.mode === "navigate") return cache.match("/");
        throw error;
    }
}

async function cacheFirst(request) {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request, {ignoreSearch: true});
    if (cached) return cached;
    const response = await fetch(request);
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
}

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;
    const url = new URL(event.request.url);

    if (url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/diagnose") ||
        url.pathname.startsWith("/notes") ||
        url.pathname.startsWith("/admin") ||
        url.pathname.startsWith("/health") ||
        url.pathname.startsWith("/reset") ||
        url.hostname.includes("r2.dev") ||
        url.hostname.includes("supabase.co") ||
        url.pathname.endsWith(".pdf")) {
        return;
    }

    // Los fragmentos incluyen un hash en el nombre: son inmutables y solo se
    // descarga un archivo nuevo cuando cambia ese manual. El catálogo sí se
    // consulta primero en red para descubrir nuevas versiones.
    if (url.pathname.startsWith("/data/search/") && !url.pathname.endsWith("/catalog.json")) {
        event.respondWith(cacheFirst(event.request).catch(() => new Response("Offline", {status: 503})));
        return;
    }

    const isFreshContent = event.request.mode === "navigate" ||
        url.pathname === "/" ||
        url.pathname.endsWith(".js") ||
        url.pathname.endsWith(".json");

    event.respondWith(
        (isFreshContent ? networkFirst(event.request) : cacheFirst(event.request))
            .catch(() => new Response("Offline", {status: 503, statusText: "Offline"}))
    );
});
