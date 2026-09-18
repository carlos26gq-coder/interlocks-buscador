// SOLVI Service Worker v27 — aplicación, índices offline, esquemas de circuitos SVG, multímetro y manuales PDF.
const CACHE = "solvi-v27";
const CORE = [
    "/",
    "/manifest.json",
    "/static/app.js",
    "/static/circuit-visualizer.js",
    "/static/multimeter.js",
    "/static/log-parser.js",
    "/static/circuit_schematics.json",
    "/static/multimeter_catalog.json",
    "/static/search-worker.js",
    "/static/linac_graph.json",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/data/search/catalog.json",
    "/static/pdf.min.js",
    "/static/pdf.worker.min.js"
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

// Estrategia especializada para PDFs de manuales (Cloudflare R2 o rutas locales).
// Soporta cabeceras de rango HTTP 206 y caching resiliente para modo offline.
let _lastPdfUrl = "";
let _lastPdfBuffer = null;

function filterHeadersWithoutRange(headers) {
    const newHeaders = new Headers(headers);
    newHeaders.delete("range");
    return newHeaders;
}

async function cacheFirstPdf(request) {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request, { ignoreSearch: true });

    if (cached) {
        const rangeHeader = request.headers.get("range");
        if (rangeHeader) {
            return returnPartialContent(request.url, cached, rangeHeader);
        }
        return cached;
    }

    try {
        const rangeHeader = request.headers.get("range");
        // Si la petición tiene cabecera Range y no está en caché, descargamos el archivo completo
        // (sin Range) para almacenarlo en CacheStorage (status 200) y luego servir el rango solicitado (206).
        if (rangeHeader) {
            try {
                const cleanRequest = new Request(request.url, {
                    method: "GET",
                    headers: filterHeadersWithoutRange(request.headers),
                    mode: request.mode,
                    credentials: request.credentials
                });
                const fullResponse = await fetch(cleanRequest);
                if (fullResponse && fullResponse.status === 200) {
                    await cache.put(cleanRequest, fullResponse.clone());
                    return returnPartialContent(request.url, fullResponse, rangeHeader);
                }
            } catch (_errRangeFetch) {
                // Si la descarga completa falla, intentamos la petición directa original
            }
        }

        const response = await fetch(request);
        // CacheStorage solo acepta status 200; no intentar cache.put con 206 Partial Content
        if (response && response.status === 200) {
            await cache.put(request, response.clone());
        }
        return response;
    } catch (_error) {
        return new Response("Manual PDF no disponible sin conexión", {
            status: 503,
            statusText: "Offline",
            headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
    }
}

async function returnPartialContent(url, cachedResponse, rangeHeader) {
    try {
        let buffer;
        if (_lastPdfUrl === url && _lastPdfBuffer) {
            buffer = _lastPdfBuffer;
        } else {
            buffer = await cachedResponse.arrayBuffer();
            _lastPdfUrl = url;
            _lastPdfBuffer = buffer;
        }
        const total = buffer.byteLength;
        const match = rangeHeader.match(/bytes=(\d+)-(\d*)/);
        if (!match) {
            return new Response(buffer, {
                status: 200,
                headers: cachedResponse.headers
            });
        }
        const start = parseInt(match[1], 10);
        const end = match[2] ? parseInt(match[2], 10) : total - 1;
        if (start >= total || end >= total || start > end) {
            return new Response("Range Not Satisfiable", {
                status: 416,
                headers: { "Content-Range": `bytes */${total}` }
            });
        }
        const slice = buffer.slice(start, end + 1);
        const headers = new Headers(cachedResponse.headers);
        headers.set("Content-Range", `bytes ${start}-${end}/${total}`);
        headers.set("Content-Length", String(slice.byteLength));
        headers.set("Accept-Ranges", "bytes");
        return new Response(slice, {
            status: 206,
            statusText: "Partial Content",
            headers: headers
        });
    } catch (_e) {
        return cachedResponse;
    }
}

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") return;
    const url = new URL(event.request.url);

    if (url.pathname.startsWith("/search") ||
        url.pathname.startsWith("/diagnose") ||
        url.pathname.startsWith("/circuits") ||
        url.pathname.startsWith("/multimeter") ||
        url.pathname.startsWith("/notes") ||
        url.pathname.startsWith("/admin") ||
        url.pathname.startsWith("/health") ||
        url.pathname.startsWith("/reset")) {
        return;
    }

    // PDFs de manuales técnicos (Cloudflare R2 o rutas locales)
    if (url.pathname.endsWith(".pdf") || url.hostname.includes("r2.dev")) {
        event.respondWith(cacheFirstPdf(event.request));
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
