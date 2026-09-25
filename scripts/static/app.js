console.log("✅ SOLVI app.js v18 — búsqueda indexada y diagnóstico documental");

// ─── RED Y RESILIENCIA OFFLINE-FIRST ───────────────────────────────
function isOnline() {
    return typeof navigator !== "undefined" ? navigator.onLine : true;
}

const NetworkMonitor = {
    get online() { return isOnline(); },
    listeners: new Set(),
    subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
    notify(online) {
        for (const fn of this.listeners) {
            try { fn(online); } catch (e) { console.error("Error en listener de red:", e); }
        }
    }
};

let _wasOffline = false;
let _notesStorageReady = false;
let _isSyncingNotes = false;

function setNotesSyncStatus(text, tone = "muted") {
    const el = document.getElementById("notesSyncStatus");
    if (!el) return;
    el.textContent = "Estado: " + text;
    el.style.color = tone === "ok" ? "var(--green)" : tone === "warn" ? "var(--warn)" : "var(--muted)";
}

function safeLocalStorageGet(key, fallback = "") {
    try {
        const value = localStorage.getItem(key);
        return value === null ? fallback : value;
    } catch (_error) {
        return fallback;
    }
}

const _sessionFallback = new Map();
function safeSessionStorageGet(key, fallback = '') {
    try { return sessionStorage.getItem(key) ?? fallback; }
    catch(e) { return _sessionFallback.get(key) ?? fallback; }
}
function safeSessionStorageSet(key, value) {
    try { sessionStorage.setItem(key, value); }
    catch(e) { _sessionFallback.set(key, value); }
}

function safeStr(v) { return typeof v === 'string' ? v : (v != null ? String(v) : ''); }

function actualizarRed() {
    const el  = document.getElementById("estadoRed");
    const txt = document.getElementById("estadoTxt");
    const online = isOnline();
    if (el) el.className = online ? "online" : "offline";
    if (txt) txt.textContent = online ? "Conectado" : "Sin conexión";

    if (online) {
        if (_wasOffline) {
            _wasOffline = false;
            toast("Conexión restablecida. Sincronizando datos...", "ok");
        }
        if (_notesStorageReady) syncPendientes();
    } else {
        if (!_wasOffline) {
            _wasOffline = true;
            toast("Modo sin conexión activado. Las herramientas locales siguen operativas.", "warn");
        }
        setNotesSyncStatus("pendiente de conexión", "warn");
    }
    NetworkMonitor.notify(online);
}
window.addEventListener("online",  actualizarRed);
window.addEventListener("offline", actualizarRed);
actualizarRed();

// ─── DATOS ───────────────────────────────────────────────
let _r2url = safeLocalStorageGet("r2url") || (typeof window !== "undefined" && window._INITIAL_R2_URL) || "";
if (_r2url && !safeLocalStorageGet("r2url")) { try { localStorage.setItem("r2url", _r2url); } catch (_e) {} }
let _workerSequence = 0;
const _workerPending = new Map();
let _searchWorker = null;

function _iniciarSearchWorker() {
    if (typeof Worker === "undefined") return;
    try {
        if (_searchWorker) {
            try { _searchWorker.terminate(); } catch (_e) {}
        }
        _searchWorker = new Worker("/static/search-worker.js");
        _searchWorker.onmessage = event => {
            const pending = _workerPending.get(event.data.id);
            if (!pending) return;
            _workerPending.delete(event.data.id);
            if (event.data.ok) pending.resolve(event.data.data);
            else pending.reject(new Error(event.data.error || "Error en la búsqueda offline"));
        };
        _searchWorker.onerror = err => {
            console.error("Error en Search Worker offline:", err);
            for (const [id, pending] of _workerPending.entries()) {
                pending.reject(new Error("Fallo en la ejecución del worker offline"));
            }
            _workerPending.clear();
            // Reconstrucción del worker para recuperación de fallos
            setTimeout(_iniciarSearchWorker, 200);
        };
    } catch (err) {
        console.warn("No se pudo iniciar el worker offline:", err);
    }
}
_iniciarSearchWorker();

let _searchState = { query:"", manual:"", offset:0, limit:25, total:0, hasMore:false, mode:"offline" };
let _highlightQuery = "";  // palabra/s buscada/s para resaltar en el visor PDF

function workerRequest(type, payload) {
    return new Promise((resolve, reject) => {
        if (!_searchWorker) {
            return reject(new Error("Worker offline no disponible en este entorno"));
        }
        // Evitar fuga de memoria por acumulación de peticiones pendientes bajo ráfagas intensas
        if (_workerPending.size > 50) {
            return reject(new Error("Cola de búsqueda saturada. Por favor espera a que finalicen las consultas en curso."));
        }
        const id = ++_workerSequence;
        const timer = setTimeout(() => {
            if (_workerPending.has(id)) {
                _workerPending.delete(id);
                try {
                    _searchWorker.postMessage({ id, type: "cancel", payload: { id } });
                } catch (_e) {}
                reject(new Error("Tiempo de espera del proceso offline excedido"));
            }
        }, 15000);
        _workerPending.set(id, {
            resolve: val => { clearTimeout(timer); resolve(val); },
            reject: err => { clearTimeout(timer); reject(err); }
        });
        _searchWorker.postMessage({id, type, payload});
    });
}

async function apiRequest(url, options = {}) {
    const timeoutMs = options.timeout || (url.includes("/ai") ? 50000 : 15000);
    const controller = new AbortController();
    const timer = setTimeout(() => {
        try { controller.abort(new DOMException("Timeout", "TimeoutError")); } catch (_e) { controller.abort(); }
    }, timeoutMs);

    if (options.signal) {
        if (options.signal.aborted) {
            try { controller.abort(options.signal.reason); } catch (_e) { controller.abort(); }
        } else {
            options.signal.addEventListener("abort", () => {
                try { controller.abort(options.signal.reason); } catch (_e) { controller.abort(); }
            }, { once: true });
        }
    }

    const fetchOptions = { ...options, signal: controller.signal };
    delete fetchOptions.timeout;

    try {
        const response = await fetch(url, fetchOptions);
        let data = null;
        try { data = await response.json(); } catch { data = null; }

        // For Avanzado endpoint: if response is JSON with ok:true, return it even at odd status codes
        if (url.includes("/ai") && data && data.ok) return data;

        if (!response.ok) {
            // Always prefer the server's own message first
            const serverMsg = data && (data.message || data.error || null);
            const fallbackMsg = response.status === 429
                ? "Límite de consultas alcanzado. Espera unos segundos e intenta de nuevo."
                : response.status === 503
                    ? "Servicio temporalmente no disponible. Intenta de nuevo en unos momentos."
                    : `Error HTTP ${response.status}`;
            const error = new Error(serverMsg || fallbackMsg);
            error.status = response.status;
            error.data = data;
            throw error;
        }
        return data;
    } catch (err) {
        if (err && err.name === "AbortError") {
            throw new Error("Tiempo de espera agotado. Verifica tu conexión o intenta de nuevo.");
        }
        if (!isOnline() || (err && (err.name === "TypeError" || String(err.message).includes("fetch")))) {
            const netErr = new Error("Sin conexión con el servidor. Verifica tu conexión de red.");
            netErr.status = 0;
            netErr.isOffline = true;
            throw netErr;
        }
        throw err;
    }
 finally {
        clearTimeout(timer);
    }
}

// ─── HELPERS ─────────────────────────────────────────────
function esc(s) {
    if (s === undefined || s === null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function hi(txt, kw) {
    if (!kw) return esc(txt);
    const rawTerms = [...new Set(String(kw).trim().split(/\s+/).filter(Boolean))];
    if (!rawTerms.length) return esc(txt);

    const escapedTxt = esc(txt);
    const escapedFull = rawTerms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[\\W_]+");
    const phraseRe = new RegExp("\\b" + escapedFull + "\\b", "gi");
    if (phraseRe.test(escapedTxt)) {
        return escapedTxt.replace(phraseRe, m => "<mark>" + m + "</mark>");
    }

    const escapedWords = rawTerms
        .sort((a, b) => b.length - a.length)
        .map(term => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const wordRe = new RegExp("\\b(?:" + escapedWords.join("|") + ")\\b", "gi");
    return escapedTxt.replace(wordRe, m => "<mark>" + m + "</mark>");
}
function toast(msg, tipo) {
    document.querySelectorAll(".toast").forEach(t => t.remove());
    const t = document.createElement("div");
    t.className = "toast " + (tipo==="err" ? "terr" : tipo==="warn" ? "twarn" : "tok");
    t.setAttribute("role", tipo === "err" ? "alert" : "status");
    t.setAttribute("aria-live", tipo === "err" ? "assertive" : "polite");
    t.textContent = msg;
    if (document.body) {
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 3500);
    }
}


// ─── PDF VIEWER (PDF.js) ─────────────────────────────────
let _pdfJsLoaded = false;

function cargarPdfJs(cb) {
    if (_pdfJsLoaded) { cb(); return; }
    const s = document.createElement("script");
    s.src = "/static/pdf.min.js";
    s.onload = function() {
        pdfjsLib.GlobalWorkerOptions.workerSrc =
            "/static/pdf.worker.min.js";
        _pdfJsLoaded = true;
        cb();
    };
    s.onerror = function() {
        toast("❌ No se pudo cargar el visor PDF","err");
    };
    document.head.appendChild(s);
}

function verPDF(manual, page, keyword) {
    if (!_r2url) {
        const customUrl = prompt("Ingresa la URL base de Cloudflare R2 para los manuales PDF (ej. https://pub-xxx.r2.dev):");
        if (customUrl && customUrl.trim()) {
            _r2url = customUrl.trim().replace(/\/+$/, "");
            try { localStorage.setItem("r2url", _r2url); } catch (_e) {}
        } else {
            toast("⚠️ PDFs no configurados","err");
            return;
        }
    }
    _highlightQuery = (keyword || "").trim();
    const cleanManual = String(manual || "").trim();
    const pdfFile = cleanManual.toLowerCase().endsWith(".pdf") ? cleanManual : (cleanManual + ".pdf");
    const baseR2 = _r2url.replace(/\/+$/, "");
    const pdfUrl = baseR2 + "/" + encodeURIComponent(pdfFile);

    const pageInt = parseInt(page, 10) || 1;

    toast("📄 Abriendo visor...", "ok");

    cargarPdfJs(function() {
        abrirVisorPDF(pdfUrl, pageInt, manual);
    });
}

function abrirVisorPDF(pdfUrl, pageNum, manual) {
    // Liberar documento anterior si existía para prevenir saturación de RAM en móviles
    if (window._pdfDoc) {
        try { window._pdfDoc.destroy(); } catch (_e) {}
        window._pdfDoc = null;
    }
    if (window._pdfRenderTask) {
        try { window._pdfRenderTask.cancel(); } catch (_e) {}
        window._pdfRenderTask = null;
    }
    if (window._pdfLoadingTask) {
        try { window._pdfLoadingTask.destroy(); } catch (_e) {}
        window._pdfLoadingTask = null;
    }
    if (window._pdfLoadTimer) clearTimeout(window._pdfLoadTimer);
    const loadSequence = (window._pdfLoadSequence || 0) + 1;
    window._pdfLoadSequence = loadSequence;

    let modal = document.getElementById("pdfModal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "pdfModal";
        modal.style.cssText =
            "position:fixed;inset:0;z-index:9999;background:#1a1a2e;display:flex;flex-direction:column;";
        document.body.appendChild(modal);
    }

    modal.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#111827;border-bottom:1px solid #1e293b;flex-shrink:0;gap:8px;flex-wrap:wrap;">' +
            '<div style="font-size:.75rem;color:#00d4ff;font-family:monospace;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:45vw">📘 ' + esc(manual) + '</div>' +
            '<div style="display:flex;align-items:center;gap:5px;flex-shrink:0;flex-wrap:wrap;">' +
                '<button type="button" data-action="pdf-ant" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">◀</button>' +
                '<span id="pdfPagInfo" style="font-size:.75rem;color:#94a3b8;font-family:monospace;min-width:70px;text-align:center">Pág. ' + pageNum + '</span>' +
                '<button type="button" data-action="pdf-sig" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">▶</button>' +
                '<a id="btnWebPdf" href="' + pdfUrl + '#page=' + pageNum + '" target="_blank" style="background:#0077ff;border:none;color:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.75rem;text-decoration:none;white-space:nowrap;">🌐 Web</a>' +
                '<button type="button" data-action="descargar-pdf-offline" data-pdfurl="' + esc(pdfUrl) + '" data-manual="' + esc(manual) + '" style="background:#00d4ff;border:none;color:#000;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.75rem;font-weight:bold;text-decoration:none;white-space:nowrap;">💾 Offline</button>' +
                '<button type="button" data-action="pdf-cerrar" style="background:#ef4444;border:none;color:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">✕</button>' +
            '</div>' +
        '</div>' +
        '<div id="pdfScroll" style="flex:1;overflow-y:auto;overflow-x:auto;display:flex;flex-direction:column;align-items:flex-start;padding:10px 0;background:#1a1a2e;">' +
            '<canvas id="pdfCanvas" style="box-shadow:0 2px 12px rgba(0,0,0,.5); touch-action: pan-x pan-y; margin: 0 auto;"></canvas>' +
        '</div>';
    modal.style.display = "flex";

    window._pdfDoc      = null;
    window._pdfPage     = pageNum;
    window._pdfRendering = false;
    window._pdfLoadingTask = null;

    activarZoomCanvas();

    const isMobileOrTablet = /Android|iPhone|iPad|iPod|Mobile|Tablet/i.test(navigator.userAgent);
    const shouldDisableRange = isMobileOrTablet || !isOnline();

    const loadingTask = pdfjsLib.getDocument({
        url: pdfUrl,
        disableRange: shouldDisableRange,
        disableStream: false,
        disableAutoFetch: true,
        maxImageSize: 1024 * 1024 * 16
    });
    window._pdfLoadingTask = loadingTask;
    window._pdfLoadTimer = setTimeout(() => {
        try { loadingTask.destroy(); } catch (_e) {}
    }, 15000);
    loadingTask.promise.then(function(doc) {
            if (loadSequence !== window._pdfLoadSequence) {
                try { doc.destroy(); } catch (_e) {}
                return;
            }
            clearTimeout(window._pdfLoadTimer);
            window._pdfLoadingTask = null;
            window._pdfDoc = doc;
            document.getElementById("pdfPagInfo").textContent = "Pág. " + pageNum + " / " + doc.numPages;
            renderPdfPagina(pageNum);
        }).catch(function(err) {
            clearTimeout(window._pdfLoadTimer);
            if (loadSequence !== window._pdfLoadSequence) return;
            window._pdfLoadingTask = null;
            let errorTitulo = "Error al Cargar Documento";
            let errorDetalle = "No se pudo renderizar el archivo PDF solicitado.";
            const errName = (err && err.name) || "";
            const errMsg = String((err && err.message) || "");

            if (!isOnline() || errMsg.includes("Failed to fetch") || errMsg.includes("NetworkError") || errMsg.includes("Load failed") || errMsg.includes("503")) {
                errorTitulo = "Sin Conexión / Red Inestable";
                errorDetalle = "No se pudo recuperar el manual sin conexión a la red. Si lo descargaste previamente, ábrelo desde tu almacenamiento local.";
            } else if (errName === "MissingPDFException" || errMsg.includes("404")) {
                errorTitulo = "Documento No Encontrado (404)";
                errorDetalle = "El manual técnico no se encuentra disponible en el repositorio.";
            } else if (errMsg.includes("403") || errMsg.includes("CORS") || errMsg.includes("SecurityError")) {
                errorTitulo = "Acceso Restringido (CORS / 403)";
                errorDetalle = "El servidor de almacenamiento bloqueó el acceso por políticas de origen o permisos.";
            } else if (errName === "InvalidPDFException" || errMsg.includes("Invalid PDF")) {
                errorTitulo = "Archivo PDF Dañado";
                errorDetalle = "La estructura del archivo descargado no es válida o está incompleta.";
            }

            const scrollEl = document.getElementById("pdfScroll");
            if (scrollEl) {
                scrollEl.innerHTML =
                    '<div style="width:100%; margin:auto; padding:40px 20px; box-sizing:border-box; text-align:center; display:flex; flex-direction:column; align-items:center;">' +
                        '<div style="font-size:3.5rem;margin-bottom:10px;">📡</div>' +
                        '<p style="color:#ef4444;font-weight:bold;font-size:1.2rem;margin:0 0 10px 0;">' + esc(errorTitulo) + '</p>' +
                        '<p style="color:#94a3b8;font-size:0.95rem;max-width:340px;margin:0;line-height:1.5;">' + esc(errorDetalle) + '</p>' +
                    '</div>';
            }
        });
}

async function cacheManualOffline(pdfUrl, manualName) {
    toast(`💾 Guardando "${manualName}" para uso offline...`, "ok");
    try {
        if ("caches" in window) {
            const cacheKeys = await caches.keys();
            const activeCacheName = cacheKeys.find(k => k.startsWith("solvi-")) || "solvi-v28";
            const cache = await caches.open(activeCacheName);
            const existing = await cache.match(pdfUrl, { ignoreSearch: true });
            if (!existing) {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 30000);
                let resp;
                try { resp = await fetch(pdfUrl, { cache: "no-cache", signal: controller.signal }); }
                finally { clearTimeout(timeout); }
                if (resp && resp.ok) {
                    await cache.put(pdfUrl, resp.clone());
                    toast(`✅ "${manualName}" guardado en caché offline`, "ok");
                    return;
                } else {
                    toast(`❌ No se pudo descargar "${manualName}"`, "err");
                    return;
                }
            } else {
                toast(`ℹ️ "${manualName}" ya está disponible en caché offline`, "ok");
                return;
            }
        }
    } catch (e) {
        console.warn("No se pudo cachear proactivamente:", e);
        toast(`⚠️ Inconveniente al guardar "${manualName}" en caché`, "warn");
    }
}

function renderPdfPagina(num) {
    const numEntero = parseInt(num, 10);
    if (!window._pdfDoc) return;

    if (window._pdfRenderTask) {
        try { window._pdfRenderTask.cancel(); } catch (_e) {}
        window._pdfRenderTask = null;
    }
    window._pdfRendering = true;

    window._pdfDoc.getPage(numEntero).then(function(page) {
        const canvas  = document.getElementById("pdfCanvas");
        if (!canvas) { window._pdfRendering = false; return; }
        const ctx     = canvas.getContext("2d");

        canvas.dataset.currentZoom = 1;

        const vw      = Math.min(window.innerWidth - 20, 900);
        const vp0     = page.getViewport({ scale: 1 });
        const baseScale = vw / vp0.width;

        const isMobileOrTablet = /Android|iPhone|iPad|iPod|Mobile|Tablet/i.test(navigator.userAgent);
        const ratioInteligente = Math.min(window.devicePixelRatio || 1.5, isMobileOrTablet ? 1.5 : 2);
        const vp = page.getViewport({ scale: baseScale * ratioInteligente });

        canvas.width  = vp.width;
        canvas.height = vp.height;

        canvas.dataset.baseWidth = vw;
        canvas.style.width = vw + "px";

        const renderTask = page.render({ canvasContext: ctx, viewport: vp });
        window._pdfRenderTask = renderTask;

        renderTask.promise.then(function() {
            window._pdfRendering = false;
            window._pdfRenderTask = null;
            window._pdfPage = numEntero;

            try { if (typeof page.cleanup === "function") page.cleanup(); } catch (_e) {}

            const info = document.getElementById("pdfPagInfo");
            if (info) info.textContent = "Pág. " + numEntero + " / " + window._pdfDoc.numPages;

            const btnWeb = document.getElementById("btnWebPdf");
            if (btnWeb) {
                const baseUrl = btnWeb.href.split('#')[0];
                btnWeb.href = baseUrl + "#page=" + numEntero;
            }

            const scrollEl = document.getElementById("pdfScroll");
            if (scrollEl) scrollEl.scrollTop = 0;

            // Resaltar términos buscados
            resaltarEnPdf(page, vp, canvas);
        }).catch(function(err) {
            window._pdfRendering = false;
            window._pdfRenderTask = null;
            try { if (typeof page.cleanup === "function") page.cleanup(); } catch (_e) {}
            if (err && err.name !== "RenderingCancelledException") {
                console.warn("PDF render warning:", err);
            }
        });
    }).catch(function() {
        window._pdfRendering = false;
    });
}

function resaltarEnPdf(pdfPage, viewport, canvas) {
    if (!_highlightQuery || !window.pdfjsLib) return;
    const rawQuery = _highlightQuery.trim().toLowerCase()
        .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    if (!rawQuery || rawQuery.length < 2) return;

    pdfPage.getTextContent().then(function(textContent) {
        try {
            const ctx = canvas.getContext("2d");
            ctx.save();
            ctx.fillStyle = "rgba(255, 210, 0, 0.45)";

            // Solo resaltar la frase o término exacto buscado para evitar doble resaltado o palabras dispersas
            const searchTerms = [rawQuery];

            for (const item of textContent.items) {
                if (!item.str || item.str.trim().length === 0) continue;
                const itemStr = item.str.toLowerCase()
                    .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
                const strLen = item.str.length;
                if (!strLen) continue;

                const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
                const itemX = tx[4];
                const itemY = tx[5];
                const fontSize = Math.sqrt(item.transform[0] * item.transform[0] +
                                           item.transform[1] * item.transform[1]);
                const h = fontSize * viewport.scale;
                const totalW = (item.width || 0) * viewport.scale;
                if (totalW <= 2 || h <= 2) continue;

                // Buscar coincidencias exactas dentro de este bloque de texto
                for (const term of searchTerms) {
                    let searchPos = 0;
                    while (searchPos < itemStr.length) {
                        const idx = itemStr.indexOf(term, searchPos);
                        if (idx < 0) break;

                        // Verificar límites de palabra para no subrayar subcadenas falsas
                        const charBefore = idx > 0 ? itemStr[idx - 1] : " ";
                        const charAfter = (idx + term.length < itemStr.length) ? itemStr[idx + term.length] : " ";
                        const isWordBoundary = !/[a-z0-9]/i.test(charBefore) && !/[a-z0-9]/i.test(charAfter);
                        if (isWordBoundary) {
                            // Calcular exactamente la posición y ancho de la palabra buscada dentro del bloque
                            const startFraction = idx / strLen;
                            const widthFraction = Math.min(term.length, strLen - idx) / strLen;
                            const hlX = itemX + startFraction * totalW;
                            const hlW = Math.max(4, widthFraction * totalW);

                            ctx.fillRect(hlX, itemY - h * 0.9, hlW, h * 1.15);
                        }
                        searchPos = idx + Math.max(term.length, 1);
                    }
                }
            }
            ctx.restore();
        } catch (_e) { /* silencioso: visor PDF sigue visible */ }
    }).catch(function() { /* silencioso */ });
}

function pdfPagAnterior() {
    if (!window._pdfDoc || window._pdfPage <= 1) return;
    renderPdfPagina(window._pdfPage - 1);
}
function pdfPagSiguiente() {
    if (!window._pdfDoc || window._pdfPage >= window._pdfDoc.numPages) return;
    renderPdfPagina(window._pdfPage + 1);
}
function cerrarVisorPDF() {
    const m = document.getElementById("pdfModal");
    if (m) m.style.display = "none";
    if (window._pdfRenderTask) {
        try { window._pdfRenderTask.cancel(); } catch (_e) {}
        window._pdfRenderTask = null;
    }
    if (window._pdfLoadingTask) {
        try { window._pdfLoadingTask.destroy(); } catch (_e) {}
        window._pdfLoadingTask = null;
    }
    if (window._pdfLoadTimer) clearTimeout(window._pdfLoadTimer);
    window._pdfLoadSequence = (window._pdfLoadSequence || 0) + 1;
    const canvas = document.getElementById("pdfCanvas");
    if (canvas) {
        canvas.width = 1;
        canvas.height = 1;
        canvas.dataset.zoomInitialized = "";
        canvas.dataset.currentZoom = "1";
    }
    if (window._pdfDoc) {
        try { window._pdfDoc.destroy(); } catch (_e) {}
        window._pdfDoc = null;
    }
    window._pdfRendering = false;
}

// ─── LÓGICA DE ZOOM (Zoom Focal Optimizado) ──────────────────────
function activarZoomCanvas() {
    const canvas = document.getElementById("pdfCanvas");
    const container = document.getElementById("pdfScroll");
    if (!canvas || !container) return;
    if (canvas.dataset.zoomInitialized === "true") return;
    canvas.dataset.zoomInitialized = "true";

    let currentZoom = 1;
    let initialDistance = null;
    let isPinching = false;
    let animationFrameId = null;

    canvas.dataset.currentZoom = 1;

    canvas.addEventListener('touchstart', (e) => {
        currentZoom = parseFloat(canvas.dataset.currentZoom) || 1;
        if (e.touches.length === 2) {
            isPinching = true;
            initialDistance = Math.hypot(
                e.touches[0].pageX - e.touches[1].pageX,
                e.touches[0].pageY - e.touches[1].pageY
            );
        }
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
        if (e.touches.length === 2 && isPinching && initialDistance) {
            e.preventDefault();
            if (animationFrameId) return;

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];

            animationFrameId = requestAnimationFrame(() => {
                const currentDistance = Math.hypot(
                    touch1.pageX - touch2.pageX,
                    touch1.pageY - touch2.pageY
                );

                const pinchX = (touch1.clientX + touch2.clientX) / 2;
                const pinchY = (touch1.clientY + touch2.clientY) / 2;

                const scaleChange = currentDistance / initialDistance;
                let newZoom = currentZoom * scaleChange;

                newZoom = Math.max(1, Math.min(newZoom, 3));
                const actualScaleRatio = newZoom / currentZoom;

                if (actualScaleRatio !== 1) {
                    const rect = canvas.getBoundingClientRect();
                    const pointX = pinchX - rect.left;
                    const pointY = pinchY - rect.top;

                    const baseWidth = parseFloat(canvas.dataset.baseWidth || window.innerWidth);
                    canvas.style.width = (baseWidth * newZoom) + "px";

                    container.scrollLeft += pointX * (actualScaleRatio - 1);
                    container.scrollTop += pointY * (actualScaleRatio - 1);

                    currentZoom = newZoom;
                    canvas.dataset.currentZoom = newZoom;
                    initialDistance = currentDistance;
                }
                animationFrameId = null;
            });
        }
    }, { passive: false });

    canvas.addEventListener('touchend', (e) => {
        if (e.touches.length < 2) {
            isPinching = false;
            initialDistance = null;
            if (animationFrameId) {
                cancelAnimationFrame(animationFrameId);
                animationFrameId = null;
            }
        }
    });
}

// ─── UI STATE ────────────────────────────────────────────
function uiState(s) {
    document.getElementById("welcomeState").style.display  = s==="welcome"  ? "flex"  : "none";
    document.getElementById("spinnerState").style.display  = s==="loading"  ? "block" : "none";
    document.getElementById("emptyState").style.display    = s==="empty"    ? "flex"  : "none";
    document.getElementById("resultsList").style.display   = s==="results"  ? "block" : "none";
    document.getElementById("metaBar").style.display       = s==="results"  ? "flex"  : "none";
}

// ─── VISOR DE APUNTES EN GRANDE ──────────────────────────
async function verNotaEnGrande(id) {
    let nota = notasLocal().find(n => n.id === id);
    if (!nota && isOnline()) {
        try {
            const notas = await apiRequest("/notes");
            if (Array.isArray(notas)) {
                notasGuardar(notas);
                nota = notas.find(n => n.id === id);
            }
        } catch(e) {}
    }

    if (!nota) { toast("⚠️ Apunte no encontrado", "err"); return; }

    document.getElementById("viewNoteTitle").innerText = safeStr(nota.title);
    document.getElementById("viewNoteText").innerText = safeStr(nota.text);

    const tagsContainer = document.getElementById("viewNoteTags");
    tagsContainer.innerHTML = "";
    if (nota.tags && nota.tags.length > 0) {
        nota.tags.forEach(t => {
            const span = document.createElement("span");
            span.className = "tag";
            span.innerText = t;
            tagsContainer.appendChild(span);
        });
    }

    document.getElementById("noteViewer").style.display = "block";
}

function cerrarVisorNota() {
    document.getElementById("noteViewer").style.display = "none";
}

// ─── RESULTADOS Y PAGINACIÓN ─────────────────────────────
function crearTarjetaResultado(result, keyword, index) {
    const isNote = result.type === "note";
    const card = document.createElement("article");
    card.className = "result-card" + (isNote ? " note-card" : "");
    const tags = isNote && Array.isArray(result.tags) && result.tags.length
        ? '<div class="card-tags">' + result.tags.map(tag => `<span class="tag">#${esc(tag)}</span>`).join("") + "</div>"
        : "";

    const manualLabel = isNote ? "📝 Apunte" : esc(result.manual);
    const pageLabel = isNote ? esc(result.page) : "Página " + Number(result.page);
    card.innerHTML =
        '<div class="card-header"><span class="card-manual '+(isNote ? "note-badge" : "manual-badge")+'">'+manualLabel+'</span>'+
        '<span class="card-page">📄 '+pageLabel+'</span></div>'+
        '<div class="card-ctx">'+hi(result.context, keyword)+'</div>'+tags;

    const footer = document.createElement("div");
    footer.className = "card-footer";
    footer.style.justifyContent = "flex-end";
    if (isNote) {
        const button = document.createElement("button");
        button.className = "btn-pdf note-open";
        button.textContent = "📖 Leer apunte";
        button.addEventListener("click", () => verNotaEnGrande(result.id));
        footer.appendChild(button);
    } else {
        const button = document.createElement("button");
        button.className = "btn-pdf";
        button.textContent = `📖 Ver pág. ${result.page}`;
        button.addEventListener("click", () => verPDF(result.manual, result.page, keyword));
        footer.appendChild(button);
    }
    card.appendChild(footer);
    return card;
}

function renderResultados(data, keyword, mode, append = false) {
    const list = document.getElementById("resultsList");
    const results = Array.isArray(data.results) ? data.results : [];
    if (!append) list.innerHTML = "";
    if (!results.length && !append) {
        document.getElementById("btnMasResultados").style.display = "none";
        uiState("empty");
        return;
    }

    const fragment = document.createDocumentFragment();
    results.forEach((result, index) => fragment.appendChild(crearTarjetaResultado(result, keyword, index)));
    list.appendChild(fragment);

    _searchState.total = Number(data.total) || 0;
    _searchState.hasMore = Boolean(data.has_more);
    _searchState.mode = mode;
    const shown = Math.min(_searchState.offset + results.length, _searchState.total);
    document.getElementById("countNum").textContent = `${shown} de ${_searchState.total}`;
    document.getElementById("modeTag").textContent = mode === "online" ? "ONLINE" : "OFFLINE";
    document.getElementById("btnMasResultados").style.display = _searchState.hasMore ? "block" : "none";
    uiState("results");
}

async function buscarOffline(keyword, manual, offset) {
    return workerRequest("search", {
        query: keyword,
        manual,
        offset,
        limit: _searchState.limit,
        notes: notasLocal()
    });
}

let _searchRequestId = 0;
let _searchAbortController = null;

async function buscarOnline(keyword, manual, offset, signal) {
    const params = new URLSearchParams({q: keyword, offset: String(offset), limit: String(_searchState.limit)});
    if (manual) params.set("manual", manual);
    const data = await apiRequest("/search?" + params.toString(), { signal });
    if (data.r2_url) {
        _r2url = data.r2_url;
        try { localStorage.setItem("r2url", _r2url); } catch (_e) {}
    }
    return data;
}

async function buscar(loadMore = false) {
    const inputQ = (document.getElementById("q").value || "").trim();
    const inputManual = (document.getElementById("manual").value || "").trim();
    const keyword = loadMore ? (_searchState.query || inputQ) : inputQ;
    const manual = loadMore ? (_searchState.manual || inputManual) : inputManual;
    const button = loadMore ? document.getElementById("btnMasResultados") : document.getElementById("btnBuscar");
    if (!keyword) {
        const input = document.getElementById("q");
        input.style.borderColor = "var(--danger)";
        setTimeout(() => input.style.borderColor = "", 1200);
        return;
    }
    if (keyword.length > 200) { toast("La búsqueda admite hasta 200 caracteres", "err"); return; }

    const currentReqId = ++_searchRequestId;
    if (!loadMore) {
        if (_searchAbortController) {
            try { _searchAbortController.abort(); } catch (_e) {}
        }
        _searchAbortController = new AbortController();
        _searchState = {..._searchState, query:keyword, manual, offset:0, total:0, hasMore:false};
        uiState("loading");
    } else {
        _searchState.offset += _searchState.limit;
    }
    const originalText = button ? button.textContent : "";
    if (button) { button.textContent = loadMore ? "Cargando..." : "Buscando..."; button.disabled = true; }

    try {
        let data;
        let mode = "offline";
        const signal = _searchAbortController ? _searchAbortController.signal : undefined;
        if (isOnline()) {
            try {
                data = await buscarOnline(keyword, manual, _searchState.offset, signal);
                mode = "online";
            } catch (onlineError) {
                if (onlineError && onlineError.name === "AbortError") return;
                console.warn("Búsqueda online no disponible; usando índice local", onlineError);
                data = await buscarOffline(keyword, manual, _searchState.offset);
            }
        } else {
            data = await buscarOffline(keyword, manual, _searchState.offset);
        }
        if (currentReqId !== _searchRequestId) return;
        renderResultados(data, keyword, mode, loadMore);
    } catch(error) {
        if (error && error.name === "AbortError") return;
        console.error(error);
        if (loadMore) _searchState.offset = Math.max(0, _searchState.offset - _searchState.limit);
        document.getElementById("resultsList").innerHTML = '<div class="result-card"><span style="color:var(--danger)">❌ '+esc(error.message)+'</span></div>';
        uiState("results");
    } finally {
        if (currentReqId === _searchRequestId && button) {
            button.textContent = originalText || (loadMore ? "Ver más" : "Buscar");
            button.disabled = false;
        }
    }
}

function cargarMasResultados() {
    if (_searchState.hasMore) buscar(true);
}

function dispararBusqueda() {
    return buscar(false);
}

// ─── MENSAJE DE BIENVENIDA ────────────────────────────────
function mostrarBienvenida() {
    if (safeSessionStorageGet("bienvenidaMostrada")) return;
    safeSessionStorageSet("bienvenidaMostrada", "true");

    const modal = document.createElement("div");
    modal.id = "modalBienvenida";
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px);";

    modal.innerHTML =
        '<div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:24px;text-align:center;max-width:80%;box-shadow:0 10px 25px rgba(0,0,0,0.5);">' +
            '<div style="font-size:2.5rem;margin-bottom:12px;">👋</div>' +
            '<p style="color:#e2e8f0;font-size:1.1rem;font-weight:bold;margin:0 0 20px 0;line-height:1.4;">Buscador técnico disponible online y offline</p>' +
            '<button type="button" data-action="modal-bienvenida-cerrar" style="background:#00d4ff;color:#0b0f1a;border:none;padding:10px 24px;border-radius:8px;font-weight:bold;font-size:1rem;cursor:pointer;">OK</button>' +
        '</div>';

    document.body.appendChild(modal);
}

// ─── CATÁLOGO Y DIAGNÓSTICO ──────────────────────────────
async function cargarCatalogoManuales() {
    try {
        const catalog = await workerRequest("catalog", {});
        const select = document.getElementById("manual");
        const current = select.value;
        select.innerHTML = '<option value="">Todos los manuales</option>' +
            (catalog.manuals || []).map(item => '<option value="'+esc(item.name)+'">'+esc(item.name)+' ('+item.pages+')</option>').join("") +
            '<option value="apuntes">📝 Apuntes</option>';
        if ([...select.options].some(option => option.value === current)) select.value = current;
        const offlineInfo = document.getElementById("offlineInfo");
        if (offlineInfo) offlineInfo.textContent = `${catalog.documents} páginas · ${catalog.manuals.length} manuales · índice ${catalog.version}`;
    } catch(error) {
        console.warn("Catálogo offline no disponible", error);
    }
}

// ─── GESTIÓN DE SÍNTOMAS (PESTAÑA RELACIONAR) ────────────
const SYMPTOM_NUMS = ["①","②","③","④","⑤"];
const SYMPTOM_HINTS = [
    "Ej: Interlock 283",
    "Ej: Error 66",
    "Ej: ITEM 409",
    "Ej: Leaf missing",
    "Ej: D_RATE 1"
];

function _setupSymptomEnter(input) {
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); analizarDiagnostico(); }
    });
}

function agregarSintoma() {
    const container = document.getElementById("symptomsContainer");
    const rows = container.querySelectorAll(".symptom-row");
    if (rows.length >= 5) { toast("Máximo 5 síntomas", "err"); return; }
    const idx = rows.length;
    const row = document.createElement("div");
    row.className = "symptom-row";
    row.dataset.index = idx;
    row.innerHTML =
        '<span class="symptom-num">' + SYMPTOM_NUMS[idx] + '</span>' +
        '<input type="text" class="symptom-input" maxlength="200" placeholder="' + SYMPTOM_HINTS[idx] + '" autocomplete="off" autocorrect="off" autocapitalize="off">' +
        '<button type="button" class="sym-del-btn" data-action="quitar-sintoma" onclick="quitarSintoma(this)" aria-label="Eliminar">✕</button>';
    container.appendChild(row);
    // Show delete buttons on all rows now that there are more than 1
    container.querySelectorAll(".sym-del-btn").forEach(b => b.style.display = "");
    _setupSymptomEnter(row.querySelector(".symptom-input"));
    row.querySelector(".symptom-input").focus();
    if (container.querySelectorAll(".symptom-row").length >= 5) {
        document.getElementById("btnAddSym").style.display = "none";
    }
}

function quitarSintoma(btn) {
    const container = document.getElementById("symptomsContainer");
    if (container.querySelectorAll(".symptom-row").length <= 1) return;
    btn.closest(".symptom-row").remove();
    // Renumber
    container.querySelectorAll(".symptom-row").forEach((row, i) => {
        row.dataset.index = i;
        row.querySelector(".symptom-num").textContent = SYMPTOM_NUMS[i];
    });
    document.getElementById("btnAddSym").style.display = "";
    if (container.querySelectorAll(".symptom-row").length <= 1) {
        container.querySelectorAll(".sym-del-btn").forEach(b => b.style.display = "none");
    }
}

function diagnosticoSymptoms() {
    return [...document.querySelectorAll(".symptom-input")]
        .map(inp => inp.value.trim())
        .filter(Boolean);
}

// ─── DIAGRAMA DE RELACIONES ───────────────────────────────
function renderDiagrama(results, symptoms) {
    const container = document.getElementById("diagDiagram");
    if (!results.length) { container.style.display = "none"; return; }
    const main   = results[0];
    const others = results.slice(1, 3);

    const symsHtml = symptoms.slice(0, 5).map(s =>
        '<div class="diag-sym-node" title="' + esc(s) + '">' +
        esc(s.length > 24 ? s.slice(0, 22) + "…" : s) + '</div>'
    ).join("");

    const confMap = { alta: { color: "var(--green)", label: "Alta probabilidad" }, media: { color: "var(--warn)", label: "Probabilidad media" }, baja: { color: "var(--muted)", label: "Baja probabilidad" } };
    const mainConf = confMap[main.confidence] || confMap.media;

    const mainTitle = main.associated_component || main.title || "Factor común identificado";

    const othersHtml = others.map(r => {
        const t = (r.associated_component || r.title || r.manual || "");
        const short = t.length > 28 ? t.slice(0, 26) + "…" : t;
        return '<div class="diag-other-node">' +
            '<span class="diag-other-title" title="' + esc(t) + '">' + esc(short) + '</span>' +
            '<span class="diag-other-meta">' + esc(r.manual) + ' · ' + r.relative_match + '%</span>' +
            '</div>';
    }).join("");

    container.innerHTML =
        '<div class="diag-diagram-wrap">' +
            '<div style="font-size:.58rem;font-family:var(--mono);color:var(--muted);text-align:center;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Señales / Síntomas analizados</div>' +
            '<div class="diag-sym-row">' + symsHtml + '</div>' +
            '<div class="diag-connector"></div>' +
            '<div class="diag-main-node no-link">' +
                '<div class="diag-main-label" style="color:var(--green)">⚡ Hipótesis Principal (Relación Priorizada) · Coincidencia Documental en Manuales</div>' +
                '<div class="diag-main-title">' + esc(mainTitle) + '</div>' +
                '<div class="diag-main-meta">Manual: <b>' + esc(main.manual) + '</b>' +
                ' · <b>' + main.relative_match + '% de compatibilidad</b>' +
                ' · <span style="color:' + mainConf.color + '">' + mainConf.label + '</span></div>' +
            '</div>' +
            (others.length
                ? '<div class="diag-connector-fan"></div>' +
                  '<div style="font-size:.58rem;font-family:var(--mono);color:var(--muted);text-align:center;margin-bottom:5px;text-transform:uppercase;letter-spacing:.06em">Otras secciones coincidentes en manuales</div>' +
                  '<div class="diag-others-row">' + othersHtml + '</div>'
                : "") +
        '</div>';
    container.style.display = "block";
}

// ─── UTILIDADES DE SANITIZACIÓN DE DIAGNÓSTICO (REGLA 1: CERO IA) ───────
function sanitizeUiExplanation(text) {
    if (!text) return "";
    let s = String(text).trim();
    s = s.replace(/^Contexto\s+Operativo:\s*En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta[^\.\n]*[\.\n]\s*/i, "");
    s = s.replace(/Contexto\s+Operativo:\s*En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta,\s*las\s+se[ñn]ales\s+analizadas\s+forman\s+parte\s+integral\s+del\s+Sistema\s+General\s+de\s+Interbloqueos\s+y\s+Seguridad\s*\(Elekta\s+LINAC\)\.?\s*/i, "");
    s = s.replace(/^En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta,\s*las\s+se[ñn]ales\s+analizadas\s+forman\s+parte\s+integral\s+del\s+Sistema\s+General\s+de\s+Interbloqueos\s+y\s+Seguridad\s*\(Elekta\s+LINAC\)\.?\s*/i, "");
    s = s.replace(/^Contexto\s+Operativo:\s*/i, "");
    s = s.replace(/^Análisis\s+documental\s+de\s+[^:]+:\s*/i, "");
    s = s.replace(/(?:La\s+documentaci[oó]n\s+(?:t[eé]cnica\s+)?(?:contrastada\s+)?en\s+[\w\s\-_,\.\(\)]*?(?:\.pdf|\(P[aá]gina\s*\d+\))[\w\s\-_,\.\(\)]*?\s*evidencia\s+que\s*)/gi, "El análisis del sistema evidencia que ");
    s = s.replace(/\s*(?:documentado\s+en|seg[uú]n|registrado\s+en|contrastada\s+en|conforme\s+a)\s+[a-z0-9_\-\s]+(?:\.pdf)?\s*(?:\(P[aá]gina\s*\d+\))?/gi, "");
    s = s.replace(/\b[a-z0-9_\-]+\.pdf\s*(?:\(P[aá]gina\s*\d+\))?/gi, "");
    s = s.replace(/\((?:planos?|esquemas?|drawings?)[^)]*\)/gi, "");
    s = s.replace(/\bPCB\s+72H\b/gi, "");
    s = s.replace(/\b(?:1024\d{3}|45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5})\b/g, "");
    s = s.replace(/\bAI\s*(\d+[A-Za-z\-]*)\b/gi, "AI$1");
    s = s.replace(/\b(?:Inteligencia\s+Artificial|IA|AI)\b/gi, "análisis técnico");
    s = s.replace(/,\s*,+/g, ", ");
    s = s.replace(/\(\s*,+\s*/g, "(");
    s = s.replace(/\s*,+\s*\)/g, ")");
    s = s.replace(/\(\s*\)/g, "");
    s = s.replace(/\bde\s*,\s*/g, "de ");
    s = s.replace(/\s+/g, " ");
    return s.trim();
}

function sanitizeUiStep(step) {
    if (!step) return "";
    let s = String(step).trim();
    s = s.replace(/^Diagn[oó]stico\s*\d+[:\-.]\s*/i, "");
    s = s.replace(/^(?:Paso\s*\d+\s*)?\((?:Probabilidad|Prioridad)\s*\d+[^)]*\):\s*/i, "");
    s = s.replace(/^(?:Probabilidad|Prioridad)\s*\d+[:\-]\s*/i, "");
    s = s.replace(/^Paso\s*\d+[:\-]\s*/i, "");
    return s.trim();
}

// ─── RENDER DIAGNÓSTICO ───────────────────────────────────
function renderDiagnostico(data, mode, symptoms) {
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const meta    = document.getElementById("diagMeta");
    const notice  = document.getElementById("diagNotice");
    if (list) list.innerHTML = "";

    const results = Array.isArray(data.results) ? data.results : [];
    if (meta) meta.textContent = (mode === "online" ? "ONLINE" : "OFFLINE") + " · " + results.length + " referencias documentales";
    if (notice) {
        notice.textContent = data.message || "";
        notice.style.display = (data.message && results.length) ? "block" : "none";
    }

    if (!results.length) {
        if (empty) {
            empty.style.display = "flex";
            const p = empty.querySelector("p");
            if (p) p.textContent = data.message || "No se encontraron referencias documentales suficientes en los manuales.";
        }
        return;
    }
    if (empty) empty.style.display = "none";

    const docBanner = document.createElement("div");
    docBanner.className = "diag-doc-banner";
    docBanner.style.cssText = "display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.25);border-radius:8px;margin-bottom:14px;";
    docBanner.innerHTML =
        '<span style="font-size:1.2rem">📚</span>' +
        '<div>' +
            '<div style="font-size:0.75rem;font-weight:700;color:#93c5fd;letter-spacing:0.05em;text-transform:uppercase;">Correlación Documental en los 19 Manuales Elekta</div>' +
            '<div style="font-size:0.72rem;color:var(--muted)">Referencias cruzadas, procedimientos de servicio y tablas de calibración indexadas textualmente.</div>' +
        '</div>';
    list.appendChild(docBanner);

    const allSymptoms = symptoms || (Array.isArray(data.signals) ? data.signals : []);
    const confColors = { alta: "var(--green)", media: "var(--warn)", baja: "var(--muted)" };
    const confLabels = { alta: "⬤ Alta probabilidad", media: "⬤ Probabilidad media", baja: "⬤ Baja probabilidad" };

    results.slice(0, 5).forEach((result, index) => {
        const conf     = result.confidence || "media";
        const confColor = confColors[conf] || "var(--muted)";
        const confLabel = confLabels[conf] || "Probabilidad media";

        const card = document.createElement("article");
        card.className = "diagnostic-card" + (conf === "baja" ? " diag-card-low" : "");

        let bodyText = "";
        if (result.associated_component) {
            bodyText += "Detalle técnico documentado: " + sanitizeUiExplanation(result.associated_component) + "\n\n";
        }
        if (result.context) {
            bodyText += sanitizeUiExplanation(result.context);
        }

        const pdfButton = (result.manual && result.page)
            ? '<div style="display:flex;justify-content:flex-end;margin-top:10px">' +
                '<button type="button" class="btn-pdf" data-action="ver-pdf" data-manual="' + esc(result.manual) + '" data-page="' + Number(result.page) + '" data-kw="' + esc(allSymptoms.join(' ')) + '">📖 Ver pág. ' + Number(result.page) + '</button>' +
              '</div>'
            : "";

        card.innerHTML =
            '<div class="diag-rank">' +
                '<span>⚡ DIAGNÓSTICO ' + (index + 1) + '</span>' +
                '<span style="color:' + confColor + ';font-size:.65rem">' + confLabel + '</span>' +
                '<b>' + Number(result.relative_match || 0) + "% · " + Number(result.matched_count || 0) + "/" + Number(result.signal_count || 0) + " términos</b>" +
            "</div>" +
            "<h3><strong>Diagnóstico " + (index + 1) + ":</strong> " + esc(sanitizeUiExplanation(result.title) || "Conexión técnica documentada") + "</h3>" +
            '<div class="card-header"><span class="card-manual manual-badge">📄 ' + esc(result.manual) + (result.page ? ' · Pág. ' + Number(result.page) : '') + "</span></div>" +
            '<div class="card-ctx" style="background:rgba(0,0,0,0.25);padding:10px;border-radius:6px;border-left:3px solid var(--border);margin:8px 0;font-size:.8rem;line-height:1.5;white-space:pre-line;">' +
                '<span style="font-size:.65rem;font-family:var(--mono);color:var(--muted);display:block;margin-bottom:4px;text-transform:uppercase;">Detalle técnico y evidencia documental:</span>' +
                esc(bodyText) +
            '</div>' +
            pdfButton;

        list.appendChild(card);
    });
}

function renderDiagramaAi(aiData, symptoms) {
    const container = document.getElementById("diagDiagram");
    if (!aiData || !symptoms.length) { container.style.display = "none"; return; }

    const symsHtml = symptoms.slice(0, 5).map(s =>
        '<div class="diag-sym-node" style="border-color:rgba(168,85,247,.4);color:#d8b4fe;background:rgba(168,85,247,.08)" title="' + esc(s) + '">' +
        esc(s.length > 24 ? s.slice(0, 22) + "…" : s) + '</div>'
    ).join("");

    const boardsList = (aiData.associated_boards || []).join(" · ");

    container.innerHTML =
        '<div class="diag-ai-diagram-wrap">' +
            '<div style="font-size:.58rem;font-family:var(--mono);color:var(--muted);text-align:center;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Señales / Síntomas analizados</div>' +
            '<div class="diag-sym-row">' + symsHtml + '</div>' +
            '<div style="display:flex;justify-content:center;margin:6px 0">' +
                '<span class="diag-ai-flow-badge">🧠 Deducción Causal de Causa Raíz</span>' +
            '</div>' +
            '<div class="diag-ai-main-node">' +
                '<div class="diag-main-label" style="color:#c084fc">⚡ Causa Raíz Más Probable</div>' +
                '<div class="diag-main-title" style="color:#f8fafc;font-size:.92rem">' + esc(aiData.root_cause || "Causa identificada") + '</div>' +
                (boardsList ? '<div style="font-size:.68rem;font-family:var(--mono);color:#c084fc;margin-top:2px">📍 Módulos / PCBs: <b>' + esc(boardsList) + '</b></div>' : '') +
            '</div>' +
        '</div>';
    container.style.display = "block";
}

function renderDiagnosticoAi(aiData, symptoms) {
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const meta    = document.getElementById("diagMeta");
    const notice  = document.getElementById("diagNotice");
    if (list) list.innerHTML = "";
    if (empty) empty.style.display = "none";

    if (meta) meta.textContent = "";
    if (notice) notice.style.display = "none";

    const card = document.createElement("article");
    card.className = "diag-ai-card";

    // Manuales con botón de apertura directa
    const symsKw = symptoms.join(" ");
    const manualsChips = (aiData.manual_references || []).map(m => {
        const mStr = String(m || "").trim();
        const match = mStr.match(/([a-z0-9_\s\-]+?)(?:\.pdf)?\s*(?:\([^\d]*(\d+)[^\)]*\))?$/i);
        if (match) {
            const manualName = match[1].trim().toLowerCase();
            const pageNum = parseInt(match[2], 10) || 1;
            return '<button type="button" class="diag-chip" data-action="ver-pdf" data-manual="' + esc(manualName) + '" data-page="' + pageNum + '" data-kw="' + esc(symsKw) + '" style="background:rgba(0,212,255,.08);border-color:rgba(0,212,255,.3);color:var(--accent);cursor:pointer">📖 ' + esc(mStr) + '</button>';
        }
        return '<span class="diag-chip" style="background:rgba(0,212,255,.08);border-color:rgba(0,212,255,.3);color:var(--accent)">📚 ' + esc(mStr) + "</span>";
    }).join("");

    const cleanExplanation = sanitizeUiExplanation(aiData.explanation || "");

    const warningHtml = aiData.safety_warning
        ? '<div class="diag-ai-warning"><strong>⚠️ PRECAUCIÓN DE SEGURIDAD:</strong> ' + esc(aiData.safety_warning) + '</div>'
        : "";

    let metaNoticeHtml = "";
    if (aiData._diagnostic_meta) {
        if (aiData._diagnostic_meta.failover) {
            metaNoticeHtml += '<div style="font-size:0.75rem;font-family:var(--mono);color:var(--accent);background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.3);padding:8px 12px;border-radius:6px;margin-bottom:10px;">📑 <strong>Modo Documental Autónomo:</strong> ' + esc(aiData._diagnostic_meta.failover_notice || "Conclusiones obtenidas a partir del catálogo técnico de 19 manuales Elekta.") + '</div>';
        }
        if (aiData._diagnostic_meta.truncated) {
            metaNoticeHtml += '<div style="font-size:0.72rem;font-family:var(--mono);color:var(--warn);background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);padding:6px 10px;border-radius:6px;margin-bottom:10px;">⚠️ Aviso: Diagnóstico ajustado por límite de longitud. Verifique los puntos de prueba clave indicados.</div>';
        }
        if (aiData._diagnostic_meta.degraded_parse) {
            metaNoticeHtml += '<div style="font-size:0.72rem;font-family:var(--mono);color:#94a3b8;background:rgba(148,163,184,.1);border:1px solid rgba(148,163,184,.25);padding:6px 10px;border-radius:6px;margin-bottom:10px;">ℹ️ Modo de compatibilidad sintáctica activo.</div>';
        }
    }

    // Hallazgos diagnósticos estructurados en bloque unificado (Diagnóstico 1..N, de mayor a menor probabilidad)
    const rawFindings = (Array.isArray(aiData.diagnostic_findings) && aiData.diagnostic_findings.length > 0)
        ? aiData.diagnostic_findings
        : (Array.isArray(aiData.differential_diagnoses) ? aiData.differential_diagnoses : []);
    const findings = rawFindings.slice(0, 5);

    let findingsHtml = "";
    if (findings.length > 0) {
        const findingEntries = findings.map((d, idx) => {
            const isObj = d && typeof d === "object";
            const rawTitle = isObj ? (d.title || d.hypothesis || "") : String(d || "");
            const titleClean = sanitizeUiStep(rawTitle);
            const causeText = isObj ? (d.cause_mechanism || d.rationale || "") : "";
            const solText = isObj ? (d.solution_procedure || d.solution || "") : "";

            let fullText = "";
            if (causeText && solText) {
                fullText = causeText.trim() + "\n\nProcedimiento de Solución e Intervención:\n" + solText.trim();
            } else {
                fullText = (causeText || solText || String(d || "")).trim();
            }
            fullText = sanitizeUiExplanation(fullText);

            return '<div class="diag-finding-entry">' +
                '<div class="diag-finding-title">' +
                    '<strong>Diagnóstico ' + (idx + 1) + ':</strong> ' + esc(titleClean) +
                '</div>' +
                '<div class="diag-finding-text">' + esc(fullText) + '</div>' +
            '</div>';
        }).join("");

        findingsHtml =
            '<div class="diag-ai-section">' +
                '<div class="diag-ai-sectit">🧭 Hallazgos Diagnósticos</div>' +
                '<div class="diag-findings-list">' + findingEntries + '</div>' +
            '</div>';
    }

    const subsystemHtml = aiData.subsystem
        ? '<div style="font-size:0.78rem;font-family:var(--mono);color:#94a3b8;margin-bottom:6px">Subsistema: <strong style="color:#e2e8f0">' + esc(aiData.subsystem) + '</strong></div>'
        : "";

    card.innerHTML =
        '<div class="diag-ai-top">' +
            '<span class="diag-ai-badge">INFORME DE CAUSA RAÍZ TÉCNICO</span>' +
        '</div>' +
        metaNoticeHtml +
        subsystemHtml +
        '<div class="diag-ai-root">' + esc(aiData.root_cause || "Causa no identificada") + '</div>' +
        '<div class="diag-ai-section">' +
            '<div class="diag-ai-sectit">🔬 Análisis y Deducción Causal Fundamentada</div>' +
            '<div class="diag-ai-body">' + esc(cleanExplanation) + '</div>' +
        '</div>' +
        findingsHtml +
        (manualsChips ?
            '<div class="diag-ai-section">' +
                '<div class="diag-ai-sectit">📖 Manuales de Referencia (Clic para abrir)</div>' +
                '<div class="diag-chips" style="gap:8px">' + manualsChips + '</div>' +
            '</div>'
        : '') +
        warningHtml;

    if (list) list.appendChild(card);

}

let _isAnalyzingAi = false;
async function analizarDiagnosticoAi() {
    if (_isAnalyzingAi) return;
    const symptoms = diagnosticoSymptoms();
    if (!symptoms.length) {
        toast("Ingresa al menos un síntoma, error o descripción de falla", "err");
        return;
    }
    if (symptoms.length > 5) {
        toast("Máximo 5 síntomas permitidos", "err");
        return;
    }

    if (!isOnline()) {
        toast("El análisis causal avanzado requiere internet. Mostrando diagnóstico local...", "warn");
        return analizarDiagnostico();
    }

    _isAnalyzingAi = true;
    const btnAi   = document.getElementById("btnDiagnoseAi");
    const btnDiag = document.getElementById("btnDiagnose");
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const diagram = document.getElementById("diagDiagram");

    if (empty) empty.style.display   = "none";
    if (diagram) diagram.style.display = "none";
    if (list) {
        list.innerHTML =
            '<div class="diag-ai-loading">' +
                '<div class="spinner"></div>' +
                '<p>🧠 Analizando y deduciendo causas con los manuales...</p>' +
                '<span style="font-size:.68rem;color:var(--muted);font-family:var(--mono)">Correlacionando síntomas con la arquitectura técnica de Elekta</span>' +
            '</div>';
    }

    if (btnAi)   { btnAi.disabled = true; btnAi.textContent = "Analizando..."; }
    if (btnDiag) { btnDiag.disabled = true; }

    try {
        let customModel = "";
        try {
            customModel = (localStorage.getItem("solvi_gemini_model") || "").trim();
            if (customModel.includes("2.5") || customModel.includes("1.5") || customModel.includes("3.7")) {
                localStorage.removeItem("solvi_gemini_model");
                customModel = "";
            }
        } catch (_e) {}
        const headers = {"Content-Type": "application/json"};
        if (customModel) {
            headers["X-Gemini-Model"] = customModel;
        }

        const res = await apiRequest("/diagnose/ai", {
            method: "POST",
            headers,
            body: JSON.stringify({ symptoms, model: customModel })
        });

        if (res && res.ok && res.data) {
            window._lastAiDiagnosis = res.data;
            renderDiagnosticoAi(res.data, symptoms);
        } else {
            throw new Error((res && (res.message || res.error)) || "Inconveniente al procesar el análisis causal.");
        }
    } catch (error) {
        const errMsg = String((error && error.message) || "Inconveniente al procesar el análisis causal.");
        const errLower = errMsg.toLowerCase();
        const errType = (error && error.data && error.data.error) || "";
        const isOfflineOrNetworkFail = !isOnline() || (error && error.isOffline) ||
            errLower.includes("failed to fetch") ||
            errLower.includes("networkerror") ||
            errLower.includes("load failed") ||
            errLower.includes("network request failed");


        if (isOfflineOrNetworkFail) {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">📴 MODO BÚNKER / SIN CONEXIÓN EXTERNA</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.95rem;line-height:1.4;margin:6px 0">El análisis causal avanzado requiere acceso a internet.</h3>' +
                    '<p style="font-size:.8rem;color:var(--muted);margin:8px 0 14px;line-height:1.5">' +
                        'En el búnker de radioterapia o sin salida a internet, utiliza el <strong>Diagnóstico Local</strong>, ' +
                        'que busca las referencias indexadas disponibles en el navegador.' +
                    '</p>' +
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
                        '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">⚡ Diagnóstico local offline</button>' +
                    '</div>' +
                '</div>';
        } else if (errType === "no_api_key" || errLower.includes("clave de api") || errMsg.includes("API_KEY") || errType === "invalid_api_key") {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:#a855f7">' +
                    '<div class="diag-ai-badge" style="margin-bottom:8px">CONFIGURACIÓN DE SERVICIO</div>' +
                    '<h3 style="color:#f8fafc">Se requiere Clave de Servicio en el Servidor</h3>' +
                    '<p style="font-size:.8rem;color:#cbd5e1;line-height:1.5;margin-bottom:12px">' +
                        'La variable <code>GEMINI_API_KEY</code> debe estar configurada en el entorno del servidor. ' +
                        'Por directiva de seguridad técnica, no se permite ingresar secretos de infraestructura en el navegador.' +
                    '</p>' +
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
                        '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">⚡ Diagnóstico local offline</button>' +
                    '</div>' +
                '</div>';
        } else if (errType === "quota_exceeded" || errLower.includes("429") || errLower.includes("cuota") || errLower.includes("límite")) {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⏳ CUOTA TEMPORAL ALCANZADA</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">' + esc(errMsg) + '</h3>' +
                    '<p style="font-size:.78rem;color:var(--muted);margin:8px 0 12px">Espera 30 segundos y vuelve a intentar, o ejecuta el diagnóstico local ahora.</p>' +
                    '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">⚡ Diagnóstico local instantáneo</button>' +
                    ' <button type="button" class="btn btn-ghost btn-sm" style="margin-left:6px" data-action="diagnostico-ai">🔄 Reintentar análisis</button>' +
                '</div>';
        } else if (errType === "service_unavailable" || errLower.includes("503") || errLower.includes("unavailable") || errLower.includes("high demand") || errLower.includes("saturad") || errLower.includes("500") || errType === "server_error" || errType === "server_exception") {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⏳ SERVICIO TEMPORALMENTE SATURADO</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">El análisis remoto no está disponible en este momento.</h3>' +
                    '<p style="font-size:.78rem;color:var(--muted);margin:8px 0 12px">Puedes continuar ahora con el diagnóstico documental local. Reintenta más tarde si necesitas el análisis remoto.</p>' +
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
                        '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">⚡ Diagnóstico local instantáneo</button>' +
                        '<button type="button" class="btn btn-ghost btn-sm" data-action="diagnostico-ai">🔄 Reintentar análisis</button>' +
                    '</div>' +
                '</div>';
        } else if (errType === "timeout" || errLower.includes("agotado") || errMsg.includes("AbortError") || errLower.includes("timeout") || errLower.includes("timed out") || errLower.includes("read operation") || errLower.includes("deadline exceeded")) {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⏱ TIEMPO DE RESPUESTA EXCEDIDO</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">El servidor tardó más de lo esperado en responder.</h3>' +
                    '<p style="font-size:.78rem;color:var(--muted);margin:8px 0 12px">El análisis causal avanzado puede completarse en el siguiente intento. Puedes consultar de inmediato la correlación documental en manuales.</p>' +
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
                        '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">🔍 Relacionar en manuales</button>' +
                        '<button type="button" class="btn btn-ghost btn-sm" data-action="diagnostico-ai">🔄 Reintentar análisis</button>' +
                    '</div>' +
                '</div>';
        } else {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⚠️ ERROR DE ANÁLISIS</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">' + esc(errMsg) + '</h3>' +
                    '<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">' +
                        '<button type="button" class="btn btn-primary btn-sm" data-action="diagnostico-local">⚡ Diagnóstico local</button>' +
                        '<button type="button" class="btn btn-ghost btn-sm" data-action="diagnostico-ai">🔄 Reintentar análisis</button>' +
                    '</div>' +
                '</div>';
        }
    } finally {
        _isAnalyzingAi = false;
        if (btnAi)   { btnAi.disabled = false; btnAi.textContent = "🧠 Diagnóstico Causal Avanzado"; }
        if (btnDiag) { btnDiag.disabled = false; }
        const btnTrans = document.getElementById("btnTransferToReport");
        if (btnTrans && list && list.innerHTML.trim() !== "") { btnTrans.style.display = "block"; }
    }
}
function transferToReport() {
    const diagOut = document.getElementById("diagResults") || document.getElementById("diagnosticoContent");
    if (!diagOut) return;

    const symptoms = typeof diagnosticoSymptoms === "function" ? diagnosticoSymptoms() : [];
    const incidentStr = symptoms.length > 0 ? symptoms.join(", ") : "";

    const incTarget = document.getElementById("reportIncident");
    if (incTarget && incidentStr) {
        incTarget.value = incidentStr;
    }

    const diagTarget = document.getElementById("reportDiagnosis");
    let diagText = "";

    if (window._lastAiDiagnosis) {
        const d = window._lastAiDiagnosis;
        const firstFinding = (Array.isArray(d.diagnostic_findings) && d.diagnostic_findings[0]) ||
                             (Array.isArray(d.differential_diagnoses) && d.differential_diagnoses[0]);
        if (firstFinding) {
            diagText = (firstFinding.title || firstFinding.hypothesis || "").trim();
        }
        if (!diagText && d.root_cause) {
            diagText = d.root_cause.trim();
        }
    }

    if (!diagText && diagOut) {
        const rootEl = diagOut.querySelector(".diag-ai-root, .diag-finding-title strong, .diagnostic-card h3");
        if (rootEl) {
            diagText = rootEl.textContent.trim().replace(/^Diagnóstico\s*\d+:\s*/i, "");
        }
    }

    if (!diagText && incidentStr) {
        diagText = "Revisión técnica e inspección de " + incidentStr;
    }

    if (diagTarget && diagText) {
        diagTarget.value = diagText;
    }

    if (typeof irA === "function") {
        irA("Reports");
    }

    if (typeof redactarTrabajoRealizado === "function" && incidentStr) {
        redactarTrabajoRealizado();
    }

    toast("Diagnóstico transferido al informe técnico", "ok");
}
window.transferToReport = transferToReport;

function guardarYReintentarAi() {
    toast("Configura la variable GEMINI_API_KEY en el servidor", "warn");
    analizarDiagnostico();
}

async function analizarDiagnostico() {
    const symptoms = diagnosticoSymptoms();
    if (!symptoms.length) {
        toast("Ingresa al menos un síntoma o error", "err");
        return;
    }
    if (symptoms.length > 5) {
        toast("Máximo 5 síntomas permitidos", "err");
        return;
    }
    const button  = document.getElementById("btnDiagnose");
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    empty.style.display   = "none";
    list.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div>' +
        '<p style="font-size:.8rem;color:var(--muted);margin-top:10px">Relacionando síntomas en manuales...</p></div>';
    if (button) {
        button.disabled    = true;
        button.textContent = "Relacionando...";
    }
    try {
        let data, mode = "offline";
        if (isOnline()) {
            try {
                data = await apiRequest("/diagnose", {
                    method:  "POST",
                    headers: {"Content-Type": "application/json"},
                    body:    JSON.stringify({symptoms})
                });
                mode = "online";
                if (data.r2_url) { _r2url = data.r2_url; try { localStorage.setItem("r2url", _r2url); } catch (_e) {} }
            } catch (onlineError) {
                console.warn("Diagnóstico online no disponible; usando índice local", onlineError);
                data = await workerRequest("diagnose", {signals: {symptoms}});
            }
        } else {
            data = await workerRequest("diagnose", {signals: {symptoms}});
        }
        renderDiagnostico(data, mode, symptoms);
    } catch(error) {
        list.innerHTML = '<div class="result-card"><span style="color:var(--danger)">❌ ' + esc(error.message) + "</span></div>";
    } finally {
        if (button) {
            button.disabled    = false;
            button.textContent = "🔍 Relacionar en Manuales (Documental)";
        }
        const btnTrans = document.getElementById("btnTransferToReport");
        if (btnTrans && list && list.innerHTML.trim() !== "") { btnTrans.style.display = "block"; }
    }
}

// ─── INIT ────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async function() {
    const addReportPart = () => {
        const target = document.getElementById("reportParts");
        if (!target) return;
        const row = document.createElement("div");
        row.className = "field";
        row.style.display = "grid";
        row.style.gridTemplateColumns = "1fr 2fr 80px auto";
        row.style.gap = "6px";
        row.innerHTML = '<input aria-label="P/N" placeholder="P/N" maxlength="80"><input aria-label="Descripción" placeholder="Descripción" maxlength="300"><input aria-label="Cantidad" type="number" min="1" value="1"><button type="button" class="btn btn-danger btn-sm" data-action="report-remove-part">×</button>';
        target.appendChild(row);
    };
    addReportPart();
    const q = document.getElementById("q");
    if (q) {
        q.addEventListener("keydown", function(event) {
            if (event.key !== "Enter") return;
            event.preventDefault();
            dispararBusqueda();
        });
    }
    document.getElementById("adminPw")?.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();adminEntrar();} });
    document.getElementById("notaTit")?.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();guardarNota();} });

    // Symptom inputs — Enter triggers analysis
    document.querySelectorAll(".symptom-input").forEach(_setupSymptomEnter);

    // Delegación central de eventos para acciones dinámicas (eliminación de handlers inline)
    document.addEventListener("click", function(event) {
        const el = event.target.closest("[data-action]");
        if (!el) return;
        const action = el.dataset.action;
        if (action === "ver-pdf") {
            event.preventDefault();
            verPDF(el.dataset.manual, parseInt(el.dataset.page, 10) || 1, el.dataset.kw || "");
        } else if (action === "descargar-pdf-offline") {
            event.preventDefault();
            const pdfUrl = el.dataset.pdfurl;
            const manual = el.dataset.manual || "Manual";
            if (pdfUrl) {
                cacheManualOffline(pdfUrl, manual);
            }
        } else if (action === "ver-nota-grande") {
            event.preventDefault();
            verNotaEnGrande(el.dataset.id);
        } else if (action === "cargar-mas-notas") {
            event.preventDefault();
            cargarMasNotas();
        } else if (action === "editar-nota") {
            event.preventDefault();
            editarNota(el.dataset.id);
        } else if (action === "eliminar-nota") {
            event.preventDefault();
            eliminarNota(el.dataset.id);
        } else if (action === "diagnostico-local") {
            event.preventDefault();
            analizarDiagnostico();
        } else if (action === "transfer-to-report") {
            event.preventDefault();
            transferToReport();
        } else if (action === "report-add-part") {
            event.preventDefault();
            addReportPart();
        } else if (action === "report-remove-part") {
            event.preventDefault();
            el.closest(".field")?.remove();
        } else if (action === "diagnostico-ai") {
            event.preventDefault();
            analizarDiagnosticoAi();
        } else if (action === "pdf-ant") {
            event.preventDefault();
            pdfPagAnterior();
        } else if (action === "pdf-sig") {
            event.preventDefault();
            pdfPagSiguiente();
        } else if (action === "pdf-cerrar") {
            event.preventDefault();
            cerrarVisorPDF();
        } else if (action === "modal-bienvenida-cerrar") {
            event.preventDefault();
            const mb = document.getElementById("modalBienvenida");
            if (mb) mb.remove();
        } else if (action === "quitar-sintoma") {
            event.preventDefault();
            quitarSintoma(el);
        }
    });

    uiState("welcome");
    mostrarBienvenida();
    cargarCatalogoManuales();
    await initNotesStorage();
    _notesStorageReady = true;

    if (isOnline()) {
        await syncPendientes();
        apiRequest("/notes?page=1&limit=100").then(data => {
            if (Array.isArray(data) || Array.isArray(data?.notes)) mergeCloudNotes(data);
        }).catch(() => setNotesSyncStatus("pendiente de reintento", "warn"));
    }
});

// ─── PERSISTENCIA INDEXEDDB (SolviNotesDB) Y FALLBACK LOCALSTORAGE ───
const IDB_NAME = "SolviNotesDB";
const IDB_VERSION = 1;
let _idbPromise = null;
let _memNotes = null;
let _memPending = null;
let _lastQuotaToast = 0;

function safeLocalStorageSet(key, value) {
    try {
        localStorage.setItem(key, value);
        return true;
    } catch (e) {
        console.warn(`Storage warning: no se pudo escribir '${key}' en localStorage (posible cuota excedida). Persistiendo en IndexedDB.`, e);
        const now = Date.now();
        if (typeof toast === "function" && now - _lastQuotaToast > 5000) {
            _lastQuotaToast = now;
            toast("⚠️ Almacenamiento rápido lleno. Apuntes guardados en base de datos local (IndexedDB).", "warn");
        }
        return false;
    }
}

function getNotesDB() {
    if (_idbPromise) return _idbPromise;
    if (typeof indexedDB === "undefined") return Promise.resolve(null);
    _idbPromise = new Promise((resolve) => {
        try {
            const req = indexedDB.open(IDB_NAME, IDB_VERSION);
            req.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains("notes")) {
                    db.createObjectStore("notes", { keyPath: "id" });
                }
                if (!db.objectStoreNames.contains("pending")) {
                    db.createObjectStore("pending", { keyPath: "id" });
                }
            };
            req.onsuccess = (e) => resolve(e.target.result);
            req.onerror = () => resolve(null);
        } catch (_e) {
            resolve(null);
        }
    });
    return _idbPromise;
}

async function idbPut(storeName, item) {
    const db = await getNotesDB();
    if (!db) return;
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(storeName, "readwrite");
            tx.objectStore(storeName).put(item);
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        } catch (_e) { resolve(); }
    });
}

async function idbDelete(storeName, id) {
    const db = await getNotesDB();
    if (!db) return;
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(storeName, "readwrite");
            tx.objectStore(storeName).delete(id);
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        } catch (_e) { resolve(); }
    });
}

async function idbClearAndPutAll(storeName, items) {
    const db = await getNotesDB();
    if (!db) return;
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(storeName, "readwrite");
            const store = tx.objectStore(storeName);
            store.clear();
            for (const it of items) store.put(it);
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        } catch (_e) { resolve(); }
    });
}

async function initNotesStorage() {
    const db = await getNotesDB();
    if (!db) {
        _memNotes = notasLocal();
        _memPending = pendLoad();
        return;
    }
    return new Promise((resolve) => {
        try {
            const tx = db.transaction(["notes", "pending"], "readonly");
            const notesReq = tx.objectStore("notes").getAll();
            const pendReq = tx.objectStore("pending").getAll();
            tx.oncomplete = () => {
                const idbNotes = notesReq.result || [];
                const idbPend = pendReq.result || [];
                if (idbNotes.length > 0) {
                    _memNotes = idbNotes;
                    safeLocalStorageSet("interlocks_notas", JSON.stringify(idbNotes));
                } else {
                    const lsNotes = notasLocal();
                    _memNotes = lsNotes;
                    if (lsNotes.length > 0) idbClearAndPutAll("notes", lsNotes);
                }
                if (idbPend.length > 0) {
                    _memPending = idbPend.map(item => item.op ? item : { op: "create", id: item.id, payload: item });
                    safeLocalStorageSet("interlocks_pend", JSON.stringify(_memPending));
                } else {
                    const lsPend = pendLoad();
                    _memPending = lsPend;
                    if (lsPend.length > 0) idbClearAndPutAll("pending", lsPend);
                }
                resolve();
            };
            tx.onerror = () => {
                _memNotes = notasLocal();
                _memPending = pendLoad();
                resolve();
            };
        } catch (_e) {
            _memNotes = notasLocal();
            _memPending = pendLoad();
            resolve();
        }
    });
}

function notasLocal() {
    if (_memNotes !== null) return _memNotes;
    try {
        const value = JSON.parse(localStorage.getItem("interlocks_notas") || "[]");
        const arr = Array.isArray(value) ? value : [];
        _memNotes = arr;
        return arr;
    } catch { return []; }
}

function notasGuardar(ns) {
    const items = Array.isArray(ns) ? ns : [];
    _memNotes = items;
    safeLocalStorageSet("interlocks_notas", JSON.stringify(items));
    idbClearAndPutAll("notes", items);
}

function notaSync(n) {
    const t = notasLocal().filter(x => x.id !== n.id);
    t.push(n);
    notasGuardar(t);
    idbPut("notes", n);
}

function notaBorrar(id) {
    const t = notasLocal().filter(n => n.id !== id);
    notasGuardar(t);
    idbDelete("notes", id);
}

function pendLoad() {
    if (_memPending !== null) return _memPending;
    try {
        const value = JSON.parse(localStorage.getItem("interlocks_pend") || "[]");
        if (!Array.isArray(value)) return [];
        const arr = value.map(item => item.op ? item : { op: "create", id: item.id, payload: item });
        _memPending = arr;
        return arr;
    } catch { return []; }
}

function pendSave(p) {
    const items = Array.isArray(p) ? p : [];
    _memPending = items;
    safeLocalStorageSet("interlocks_pend", JSON.stringify(items));
    idbClearAndPutAll("pending", items);
}

function pendAdd(n) {
    const p = pendLoad().filter(item => item.id !== n.id);
    const entry = { op: "create", id: n.id, payload: n };
    p.push(entry);
    pendSave(p);
    idbPut("pending", entry);
}

function pendDel(id) {
    const p = pendLoad().filter(n => n.id !== id);
    pendSave(p);
    idbDelete("pending", id);
}

function pendAddDelete(id) {
    const p = pendLoad().filter(item => item.id !== id);
    const entry = { op: "delete", id };
    p.push(entry);
    pendSave(p);
    idbPut("pending", entry);
}

function mergeCloudNotes(cloudNotes) {
    // Acepta la respuesta histórica (array) y la respuesta paginada
    // {notes: [...], has_more: bool} sin perder apuntes offline pendientes.
    if (!Array.isArray(cloudNotes)) cloudNotes = cloudNotes?.notes || [];
    const pends = pendLoad();
    const deletedIds = new Set(pends.filter(p => p.op === "delete").map(p => p.id));
    const merged = notasLocal().filter(note => !deletedIds.has(note.id));
    for (const cloudNote of (Array.isArray(cloudNotes) ? cloudNotes : [])) {
        if (deletedIds.has(cloudNote.id)) continue;
        const index = merged.findIndex(note => note.id === cloudNote.id);
        if (index >= 0) merged[index] = cloudNote;
        else merged.push(cloudNote);
    }
    for (const pending of pends) {
        if (pending.op === "create" && !merged.some(note => note.id === pending.id)) {
            merged.push(pending.payload);
        }
    }
    notasGuardar(merged);
    return merged;
}


async function syncPendientes() {
    if (_isSyncingNotes) return;
    const runSync = async () => {
        const pend = pendLoad();
        if (!pend.length) { setNotesSyncStatus("sincronizado", "ok"); return; }
        setNotesSyncStatus("sincronizando…");
        let ok = 0;

        const creates = pend.filter(item => item.op === "create");
        const deletes = pend.filter(item => item.op === "delete");
        const others = pend.filter(item => item.op !== "create" && item.op !== "delete");

        for (const item of others) {
            pendDel(item.id);
        }

        for (let i = 0; i < creates.length; i += 50) {
            const batch = creates.slice(i, i + 50);
            try {
                const res = await apiRequest("/notes/batch", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({notes: batch.map(c => c.payload)})
                });
                for (const item of batch) {
                    notaBorrar(item.id);
                    pendDel(item.id);
                    ok++;
                }
                if (res && res.notes) {
                    res.notes.forEach(n => notaSync(n));
                }
            } catch(error) {
                const status = error?.status ?? error?.response?.status;
                if (status === 409) {
                    for (const item of batch) {
                        const newId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2);
                        const oldId = item.id;
                        item.payload = { ...item.payload, id: newId };
                        item.id = newId;
                        pendDel(oldId);
                        pendAdd(item.payload);
                    }
                    continue;
                }
                console.warn('[sync] Error de red en batch:', error);
                setNotesSyncStatus("pendiente de reintento", "warn");
                break;
            }
        }

        for (const item of deletes) {
            try {
                if (_adminPw) {
                    await apiRequest("/notes/" + item.id, {
                        method: "DELETE",
                        headers: { "X-Admin-Password": _adminPw }
                    });
                    pendDel(item.id);
                    ok++;
                }
            } catch(error) {
                const status = error?.status ?? error?.response?.status;
                if (status === 404 || status === 400) {
                    pendDel(item.id);
                }
            }
        }
        if (ok > 0) toast("☁️ " + ok + " apunte(s) sincronizado(s)");
        if (!pendLoad().length) setNotesSyncStatus("sincronizado", "ok");
    };

    _isSyncingNotes = true;
    try {
        if (typeof navigator !== "undefined" && navigator.locks && typeof navigator.locks.request === "function") {
            await navigator.locks.request("solvi_notes_sync", { ifAvailable: true }, async lock => {
                if (lock) await runSync();
            });
        } else {
            await runSync();
        }
    } finally {
        _isSyncingNotes = false;
    }
}

// ─── ADMIN ───────────────────────────────────────────────
let _adminPw = "";
let _notesPage = 1;
let _notesHasMore = false;

// ─── NOTAS cargar ────────────────────────────────────────
async function cargarNotas(reset = true) {
    const lista = document.getElementById("listaNotas");
    const empty = document.getElementById("sinNotas");
    if (!lista) return;
    if (reset) {
        _notesPage = 1;
        _notesHasMore = false;
        lista.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';
    }
    if (empty) empty.style.display = "none";
    let notas = [];
    if (isOnline()) {
        try {
            const cloudData = await apiRequest("/notes?page=" + _notesPage + "&limit=100");
            _notesHasMore = !Array.isArray(cloudData) && cloudData.has_more === true;
            notas = mergeCloudNotes(Array.isArray(cloudData) ? cloudData : (cloudData.notes || []));
        }
        catch { notas = notasLocal(); }
    } else { notas = notasLocal(); }
    lista.innerHTML = "";
    if (!notas || !notas.length) {
        if(empty) empty.style.display="flex";
        const more = document.getElementById("notesLoadMore");
        if (more) more.style.display = "none";
        return;
    }

    notas.forEach(n => {
        const d = document.createElement("div");
        d.className = "note-item"; d.id = "ni-"+n.id;
        const tags = (n.tags||[]).map(t=>'<span class="tag">'+esc(t)+'</span>').join("");
        const pend = pendLoad().some(p=>p.id===n.id);

        const textoSeguro = safeStr(n.text);
        d.innerHTML =
            '<div class="note-item-header">'+
              '<div class="note-item-title" style="cursor:pointer; color:var(--accent);" data-action="ver-nota-grande" data-id="'+esc(n.id)+'">'+
                 esc(n.title)+(pend?' <span style="color:var(--warn);font-size:.7rem">⏳</span>':'')+
              '</div>'+
              '<div class="note-actions">'+
                '<button type="button" class="btn btn-ghost btn-sm" data-action="editar-nota" data-id="'+esc(n.id)+'">✏️</button>'+
                '<button type="button" class="btn btn-danger btn-sm" data-action="eliminar-nota" data-id="'+esc(n.id)+'">🗑</button>'+
              '</div>'+
            '</div>'+
            '<div class="note-item-text" style="cursor:pointer;" data-action="ver-nota-grande" data-id="'+esc(n.id)+'">'+esc(textoSeguro.substring(0, 100))+(textoSeguro.length > 100 ? '...' : '')+'</div>'+
            (tags?'<div class="card-tags">'+tags+'</div>':"");
        lista.appendChild(d);
    });
    const more = document.getElementById("notesLoadMore");
    if (more) more.style.display = _notesHasMore ? "block" : "none";
}

async function cargarMasNotas() {
    if (!_notesHasMore || !isOnline()) return;
    _notesPage += 1;
    await cargarNotas(false);
}

// ─── NOTAS formulario ────────────────────────────────────
function abrirFormNota() {
    const f = document.getElementById("formNota");
    if (!f) return;
    f.style.display = "block";
    document.getElementById("formTit").textContent = "✏️ NUEVO APUNTE";
    ["editId","notaTit","notaTxt","notaTags"].forEach(id => { const e=document.getElementById(id); if(e) e.value=""; });
    setTimeout(() => document.getElementById("notaTit")?.focus(), 100);
}

function cerrarFormNota() { const f=document.getElementById("formNota"); if(f) f.style.display="none"; }

function editarNota(id) {
    if (!_adminPw) {
        toast("🔒 Acceso denegado: Inicia sesión como Admin para editar", "err");
        return;
    }

    const n = notasLocal().find(x=>x.id===id); if(!n) return;
    const f = document.getElementById("formNota"); if(!f) return;
    f.style.display="block";
    document.getElementById("formTit").textContent="✏️ EDITAR APUNTE";
    document.getElementById("editId").value=id;
    document.getElementById("notaTit").value=n.title;
    document.getElementById("notaTxt").value=n.text;
    document.getElementById("notaTags").value=(n.tags||[]).join(", ");
    setTimeout(()=>document.getElementById("notaTit")?.focus(),100);
    f.scrollIntoView({behavior:"smooth"});
}

function generarUUID() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        try { return crypto.randomUUID(); } catch (_e) {}
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
        const r = Math.random() * 16 | 0;
        const v = c === "x" ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

async function guardarNota() {
    const id    = document.getElementById("editId").value.trim();
    const title = document.getElementById("notaTit").value.trim();
    const text  = document.getElementById("notaTxt").value.trim();
    const tags  = document.getElementById("notaTags").value.split(",").map(t=>t.trim()).filter(Boolean);

    if (!title) { toast("El título es obligatorio","err"); return; }
    if (title.length > 200 || text.length > 20000 || tags.length > 20 || tags.some(tag => tag.length > 50)) {
        toast("El apunte supera los límites permitidos", "err");
        return;
    }
    if (id && !isOnline()) {
        toast("La edición administrativa requiere conexión para evitar conflictos", "err");
        return;
    }
    const nota = { id: id || generarUUID(), title, text, tags };
    let savedAsPending = false;

    if (isOnline()) {

        try {
            const method = id ? "PUT" : "POST";
            const url    = id ? "/notes/"+id : "/notes";
            const headers = {"Content-Type":"application/json"};
            if (id) headers["X-Admin-Password"] = _adminPw;
            const saved = await apiRequest(url, {method, headers, body:JSON.stringify(nota)});
            notaSync(saved);
            pendDel(nota.id);
        } catch(error) {
            if (!id && (!error.status || error.status >= 500)) {
                pendAdd(nota);
                notaSync(nota);
                savedAsPending = true;
                toast("⚠️ Servidor no disponible — el apunte quedó pendiente");
            } else {
                toast(error.message, "err");
                return;
            }
        }
    } else {
        pendAdd(nota);
        notaSync(nota);
        savedAsPending = true;
        toast("⚠️ Sin internet — se sincronizará al conectarte");
    }

    cerrarFormNota();
    cargarNotas();
    if (!savedAsPending) toast(id ? "✅ Apunte actualizado" : "✅ Apunte guardado");
}

async function eliminarNota(id) {
    const isLocalPending = pendLoad().some(p => p.id === id && p.op === "create");

    if (!isLocalPending && !_adminPw) {
        toast("🔒 Acceso denegado: Inicia sesión como Admin para eliminar", "err");
        return;
    }

    if (!confirm("¿Eliminar este apunte de forma permanente?")) return;

    if (isLocalPending) {
        notaBorrar(id);
        pendDel(id);
        document.getElementById("ni-"+id)?.remove();
        const lista = document.getElementById("listaNotas");
        if (lista && !lista.children.length) { const e=document.getElementById("sinNotas"); if(e) e.style.display="flex"; }
        toast("🗑 Apunte local eliminado");
        return;
    }

    if (!isOnline()) {
        notaBorrar(id);
        pendAddDelete(id);
        document.getElementById("ni-"+id)?.remove();
        const lista = document.getElementById("listaNotas");
        if (lista && !lista.children.length) { const e=document.getElementById("sinNotas"); if(e) e.style.display="flex"; }
        toast("🗑 Apunte eliminado localmente (se sincronizará al conectar)");
        return;
    }

    try {
        await apiRequest("/notes/"+id, {method:"DELETE", headers:{"X-Admin-Password":_adminPw}});
    } catch(error) {
        if (!error.status || error.status >= 500) {
            notaBorrar(id);
            pendAddDelete(id);
            document.getElementById("ni-"+id)?.remove();
            const lista = document.getElementById("listaNotas");
            if (lista && !lista.children.length) { const e=document.getElementById("sinNotas"); if(e) e.style.display="flex"; }
            toast("🗑 Apunte eliminado localmente (pendiente de sincronizar)");
            return;
        }
        toast(error.message, "err");
        return;
    }


    notaBorrar(id); pendDel(id);
    document.getElementById("ni-"+id)?.remove();
    const lista = document.getElementById("listaNotas");
    if (lista && !lista.children.length) { const e=document.getElementById("sinNotas"); if(e) e.style.display="flex"; }
    toast("🗑 Apunte eliminado");
}

async function adminEntrar() {
    if (!isOnline()) {
        toast("El área de administración requiere conexión al servidor", "err");
        return;
    }
    const pw = (document.getElementById("adminPw").value || "").trim();
    if (!pw) { toast("Ingresa la contraseña","err"); return; }
    try {
        await apiRequest("/admin/check", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({password:pw}) });
        _adminPw = pw;
        document.getElementById("adminLock").style.display    = "none";
        document.getElementById("adminCont").style.display    = "block";
        cargarCfg(); cargarListaManuales();
        toast("🔓 Modo Administrador Activado", "ok");
    } catch(error) { toast("❌ "+error.message,"err"); }
}

function adminSalir() {
    _adminPw = "";
    document.getElementById("adminLock").style.display = "flex";
    document.getElementById("adminCont").style.display = "none";
    document.getElementById("adminPw").value = "";
    toast("🔒 Sesión cerrada", "ok");
}

async function cargarCfg() {
    const el = document.getElementById("cfgInfo"); if(!el) return;
    try {
        const d = await apiRequest("/admin/config", {headers:{"X-Admin-Password":_adminPw}});
        if (d.r2_url && d.r2_url!=="No configurada") { _r2url=d.r2_url; try { localStorage.setItem("r2url",_r2url); } catch (_e) {} }
        el.innerHTML =
            '<div class="config-row"><span>📚 Total páginas</span><span>'+d.total_pages+'</span></div>'+
            '<div class="config-row"><span>📘 Manuales</span><span>'+d.total_manuals+'</span></div>'+
            '<div class="config-row"><span>📝 Apuntes</span><span>'+d.notes_count+'</span></div>'+
            '<div class="config-row"><span>☁️ Cloudflare R2</span><span style="color:'+(d.r2_configured?'var(--green)':'var(--warn)')+'">'+
            (d.r2_configured?'✅ Configurado':'⚠️ No configurado')+'</span></div>';
    } catch { if(el) el.innerHTML='<p style="color:var(--danger);font-size:.78rem">Error al cargar</p>'; }
}

async function cargarListaManuales() {
    const div = document.getElementById("listaManuales"); if(!div) return;
    div.innerHTML='<div class="spinner-wrap" style="padding:10px 0"><div class="spinner"></div></div>';
    try {
        const d = await apiRequest("/admin/manuals", {headers:{"X-Admin-Password":_adminPw}});
        div.innerHTML = d.map(m=>'<div class="manual-row"><span style="color:var(--text)">'+esc(m.manual)+'</span><span>'+m.pages+' págs.</span></div>').join("");
    } catch(e) { div.innerHTML='<p style="color:var(--danger)">Error: '+esc(e.message)+'</p>'; }
}

// ─── MÓDULO DE INFORMES TÉCNICOS DE SERVICIO ─────────────────────────────────

function escapeHtml(unsafe) {
    return esc(unsafe);
}

function addReportPart(pn = "", desc = "", qty = "01") {
    const container = document.getElementById("reportParts");
    if (!container) return;
    const row = document.createElement("div");
    row.className = "report-part-row";
    row.style.cssText = "display:grid; grid-template-columns: 1fr 2fr 80px 36px; gap:6px; margin-bottom:6px; align-items:center;";
    row.innerHTML = `
        <input type="text" placeholder="P/N" class="part-pn" aria-label="P/N" value="${escapeHtml(pn)}" maxlength="60">
        <input type="text" placeholder="Descripción" class="part-desc" aria-label="Descripción" value="${escapeHtml(desc)}" maxlength="160">
        <input type="text" placeholder="Cant." class="part-qty" aria-label="Cantidad" value="${escapeHtml(qty)}" maxlength="20" style="text-align:center;">
        <button type="button" class="btn btn-ghost btn-sm" aria-label="Eliminar repuesto" title="Eliminar repuesto" onclick="this.closest('.report-part-row').remove()" style="padding:4px 8px; color:var(--danger, #ef4444); font-size:16px; font-weight:bold; cursor:pointer;">×</button>
    `;
    container.appendChild(row);
}

let _reportImages = [];
let _reportImgSeq = 0;

function handleReportImagesChange(event) {
    const files = event?.target?.files || document.getElementById("reportImages")?.files;
    if (!files || files.length === 0) return;

    const readPromises = Array.from(files).map((file) => {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                resolve({
                    id: "img_" + (++_reportImgSeq),
                    name: file.name.replace(/\.[^/.]+$/, "").substring(0, 80),
                    dataUrl: e.target.result
                });
            };
            reader.onerror = () => resolve(null);
            reader.readAsDataURL(file);
        });
    });

    Promise.all(readPromises).then((results) => {
        for (const item of results) {
            if (item) _reportImages.push(item);
        }
        renderReportImagesList();
        if (event?.target) event.target.value = "";
    });
}

function renderReportImagesList() {
    const container = document.getElementById("reportImagesList");
    if (!container) return;
    if (_reportImages.length === 0) {
        container.innerHTML = '<span style="font-size:0.8rem; color:var(--muted);">No hay imágenes adjuntas actualmente.</span>';
        return;
    }
    container.innerHTML = _reportImages.map((img) => `
        <div class="report-img-card" id="${img.id}">
            <img src="${img.dataUrl}" alt="${escapeHtml(img.name)}" title="${escapeHtml(img.name)}">
            <input type="text" value="${escapeHtml(img.name)}" placeholder="Pie de foto" aria-label="Pie de imagen" onchange="actualizarNombreImagenReporte('${img.id}', this.value)">
            <button type="button" class="btn btn-ghost btn-sm" onclick="eliminarImagenReporte('${img.id}')" style="font-size:0.75rem; padding:2px 6px; width:100%; color:var(--danger, #ef4444); margin-top:4px;">✕ Quitar</button>
        </div>
    `).join("");
}

function actualizarNombreImagenReporte(id, newName) {
    const img = _reportImages.find(x => x.id === id);
    if (img) {
        img.name = (newName || "").trim() || "Imagen adjunta";
    }
}

function eliminarImagenReporte(id) {
    _reportImages = _reportImages.filter(x => x.id !== id);
    renderReportImagesList();
    toast("Imagen eliminada del informe");
}

function calcularDownTimeInforme() {
    const sDate = document.getElementById("reportWorkStartDate")?.value?.trim();
    const sTime = document.getElementById("reportWorkStartTime")?.value?.trim();
    const eDate = document.getElementById("reportWorkEndDate")?.value?.trim();
    const eTime = document.getElementById("reportWorkEndTime")?.value?.trim();
    const out = document.getElementById("reportDownTime");
    if (!out || !sTime || !eTime) return;

    const parseTime = (t) => {
        const m = t.match(/(\d{1,2}):(\d{2})/);
        return m ? { h: parseInt(m[1], 10), min: parseInt(m[2], 10) } : null;
    };
    const tStart = parseTime(sTime);
    const tEnd = parseTime(eTime);
    if (!tStart || !tEnd) return;

    let diffMinutes = (tEnd.h * 60 + tEnd.min) - (tStart.h * 60 + tStart.min);
    if (sDate && eDate && sDate !== eDate) {
        const pDate = (d) => {
            const parts = d.split("/");
            return parts.length === 3 ? new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10)) : null;
        };
        const dStart = pDate(sDate);
        const dEnd = pDate(eDate);
        if (dStart && dEnd) {
            const dayDiff = Math.round((dEnd - dStart) / (1000 * 60 * 60 * 24));
            diffMinutes += dayDiff * 24 * 60;
        }
    }
    if (diffMinutes >= 0) {
        const hrs = Math.floor(diffMinutes / 60);
        const mins = diffMinutes % 60;
        out.value = `${hrs}:${mins < 10 ? '0' : ''}${mins} h`;
    }
}

async function redactarTrabajoRealizado() {
    const incident = (document.getElementById("reportIncident")?.value || "").trim();
    if (!incident) {
        toast("Ingresa el incidente para redactar el informe", "warn");
        return;
    }
    const equipment = (document.getElementById("reportEquipment")?.value || "").trim() || "ACELERADOR LINEAL";
    const brand = (document.getElementById("reportBrand")?.value || "").trim() || "ELEKTA";
    const model = (document.getElementById("reportModel")?.value || "").trim() || "SYNERGY FULL";
    const diagnosis = (document.getElementById("reportDiagnosis")?.value || "").trim();
    const imageDescriptions = _reportImages.map(img => img.name);
    const apiKey = safeLocalStorageGet("geminiApiKey", "");

    const spinner = document.getElementById("reportWorkSpinner");
    const btn = document.getElementById("btnDraftReportBody");
    if (spinner) spinner.style.display = "block";
    if (btn) btn.disabled = true;

    try {
        const res = await apiRequest("/reports/generate-body", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                incident,
                equipment,
                brand,
                model,
                diagnosis,
                image_descriptions: imageDescriptions,
                api_key: apiKey
            })
        });

        if (res && res.body) {
            const workEl = document.getElementById("reportWork");
            if (workEl) workEl.value = res.body;

            const diagEl = document.getElementById("reportDiagnosis");
            if (diagEl && res.suggested_diagnosis && (!diagEl.value.trim() || diagEl.value.trim() === "Reemplazo de Switch Assembly y DIE HTB")) {
                diagEl.value = res.suggested_diagnosis;
            }

            const concEl = document.getElementById("reportConclusion");
            if (concEl && res.suggested_conclusions) {
                concEl.value = res.suggested_conclusions;
            }

            if (Array.isArray(res.suggested_parts) && res.suggested_parts.length > 0) {
                const partsContainer = document.getElementById("reportParts");
                if (partsContainer) {
                    partsContainer.innerHTML = "";
                    for (const p of res.suggested_parts) {
                        addReportPart(p.pn || "", p.description || "", p.quantity || "01");
                    }
                }
            }

            toast("Propuesta técnica redactada con base en manuales", "ok");
        } else {
            toast("No se pudo obtener la redacción técnica", "warn");
        }
    } catch (err) {
        toast("Error al generar propuesta técnica: " + (err.message || err), "err");
    } finally {
        if (spinner) spinner.style.display = "none";
        if (btn) btn.disabled = false;
    }
}

function getReportFormData() {
    const getVal = (id) => (document.getElementById(id)?.value || "").trim();
    const isChecked = (id) => Boolean(document.getElementById(id)?.checked);

    const pns = document.querySelectorAll("#reportParts .part-pn");
    const descs = document.querySelectorAll("#reportParts .part-desc");
    const qtys = document.querySelectorAll("#reportParts .part-qty");
    const parts = [];
    for (let i = 0; i < pns.length; i++) {
        const pn = (pns[i]?.value || "").trim();
        const desc = (descs[i]?.value || "").trim();
        const qty = (qtys[i]?.value || "01").trim();
        if (pn || desc) {
            parts.push({ pn, description: desc, quantity: qty });
        }
    }

    return {
        client: getVal("reportClient"),
        number: getVal("reportNumber"),
        service: getVal("reportService"),
        date: getVal("reportDate"),
        equipment: getVal("reportEquipment"),
        dept: getVal("reportDept"),
        brand: getVal("reportBrand"),
        model: getVal("reportModel"),
        serial: getVal("reportSerial"),
        incident: getVal("reportIncident"),
        diagnosis: getVal("reportDiagnosis"),
        isProgrammed: isChecked("reportProgrammed"),
        isSuspTto: isChecked("reportSuspTto"),
        clientDate: getVal("reportClientDate"),
        clientTime: getVal("reportClientTime"),
        workStartDate: getVal("reportWorkStartDate"),
        workStartTime: getVal("reportWorkStartTime"),
        workEndDate: getVal("reportWorkEndDate"),
        workEndTime: getVal("reportWorkEndTime"),
        downTime: getVal("reportDownTime"),
        work: getVal("reportWork"),
        conclusion: getVal("reportConclusion"),
        parts,
        images: _reportImages.map((img) => ({
            name: img.name,
            dataUrl: img.dataUrl,
        })),
    };
}

function previewInforme() {
    const data = getReportFormData();

    const client = escapeHtml(data.client);
    const number = escapeHtml(data.number);
    const service = escapeHtml(data.service);
    const date = escapeHtml(data.date);
    const equipment = escapeHtml(data.equipment);
    const dept = escapeHtml(data.dept);
    const brand = escapeHtml(data.brand);
    const model = escapeHtml(data.model);
    const serial = escapeHtml(data.serial);

    const incident = escapeHtml(data.incident);
    const diagnosis = escapeHtml(data.diagnosis);
    const isProgrammed = data.isProgrammed;
    const isSuspTto = data.isSuspTto;

    const clientDate = escapeHtml(data.clientDate);
    const clientTime = escapeHtml(data.clientTime);
    const workStartDate = escapeHtml(data.workStartDate);
    const workStartTime = escapeHtml(data.workStartTime);
    const workEndDate = escapeHtml(data.workEndDate);
    const workEndTime = escapeHtml(data.workEndTime);
    const downTime = escapeHtml(data.downTime);

    const work = escapeHtml(data.work);
    const conclusion = escapeHtml(data.conclusion);

    // Repuestos con formato Word oficial
    let partsRowsHtml = "";
    for (let i = 0; i < data.parts.length; i++) {
        const p = data.parts[i];
        partsRowsHtml += `
            <tr style="background: #FFFFFF;">
                <td style="border: 1px solid #4472C4; padding: 4px 8px; font-weight: bold; font-family: Calibri, sans-serif;">${escapeHtml(p.pn)}</td>
                <td style="border: 1px solid #4472C4; padding: 4px 8px; font-family: Calibri, sans-serif;">${escapeHtml(p.description)}</td>
                <td style="border: 1px solid #4472C4; padding: 4px 8px; text-align: center; font-family: Calibri, sans-serif;">${escapeHtml(p.quantity)}</td>
            </tr>
        `;
    }

    let partsTableHtml = "";
    if (data.parts.length > 0) {
        partsTableHtml = `
            <div style="margin-top: 10px;">
                <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-size: 10pt; page-break-inside: avoid;">
                    <thead>
                        <tr style="background: #B4C6E7; color: #000000; font-family: 'Tahoma', Calibri, sans-serif; font-weight: bold;">
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: left; width: 28%;">P/N</th>
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: left; width: 57%;">Descripción</th>
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: center; width: 15%;">Cant.</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${partsRowsHtml}
                    </tbody>
                </table>
            </div>
        `;
    }

    // Imágenes adjuntas
    let imagesHtml = "";
    if (_reportImages.length > 0) {
        imagesHtml = `
            <div style="margin-top: 10px; padding: 10px; border-top: 1px solid #4472C4; background: #F8FAFC;">
                <div style="display: flex; flex-wrap: wrap; gap: 14px; justify-content: center; align-items: flex-start;">
                    ${_reportImages.map((img, idx) => `
                        <div style="border: 1px solid #4472C4; padding: 6px; background: #ffffff; text-align: center; max-width: 340px; flex: 1 1 260px; page-break-inside: avoid; box-sizing: border-box;">
                            <img src="${img.dataUrl}" alt="${escapeHtml(img.name)}" style="max-width: 100%; max-height: 220px; object-fit: contain; display: block; margin: 0 auto 6px auto;">
                            <div style="font-size: 9.5pt; font-weight: bold; font-family: Calibri, sans-serif; color: #2F5496; padding: 2px; border-top: 1px solid #D9E2F3;">Fig. ${idx + 1}: ${escapeHtml(img.name)}</div>
                        </div>
                    `).join("")}
                </div>
            </div>
        `;
    }

    const docHtml = `
        <div style="font-family: Calibri, Arial, sans-serif; color: #000000; line-height: 1.35; max-width: 820px; margin: 0 auto; background: #ffffff; padding: 6px;">
            <!-- Encabezado / Banner Superior Estilo Word -->
            <div style="background: #2F5496; color: #FFFFFF; font-family: 'Candara', Calibri, sans-serif; font-size: 16pt; font-weight: bold; text-align: center; padding: 6px 0; border: 1.5px solid #2F5496; margin-bottom: 8px; letter-spacing: 0.5px;">
                | INFORME TÉCNICO
            </div>

            <!-- Tabla 1 y 2: Metadatos -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; width: 14%; padding: 4px 6px;">Cliente:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; width: 36%; padding: 4px 6px;">${client}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; width: 14%; padding: 4px 6px;">Informe:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; width: 36%; padding: 4px 6px; font-weight: bold;">${number}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Servicio:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${service}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Fecha:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${date}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Equipo:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${equipment}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Departamento:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${dept}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Marca:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${brand}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Modelo:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">${model}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Serie:</td>
                        <td colspan="3" style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px; font-weight: bold;">${serial}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Tabla 3: Incidente -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">INCIDENTE QUE MANIFIESTA EL USUARIO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 6px 10px; font-size: 10.5pt; min-height: 22px;">${incident || "-"}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Tabla 4: Diagnóstico -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 6px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">DIAGNOSTICO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 6px 10px; font-size: 10.5pt; min-height: 22px;">${diagnosis || "-"}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Casillas de Verificación Estilo Word -->
            <div style="font-family: Calibri, sans-serif; font-size: 10.5pt; font-weight: bold; margin: 6px 0 8px 4px; color: #000000;">
                PROGRAMADO &nbsp;&nbsp; <span style="font-size: 13pt; vertical-align: middle;">${isProgrammed ? '☒' : '☐'}</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; SUSP TTO &nbsp;&nbsp; <span style="font-size: 13pt; vertical-align: middle;">${isSuspTto ? '☒' : '☐'}</span>
            </div>

            <!-- Tabla 5: Cronograma de Atención -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px; text-align: center; page-break-inside: avoid;">
                <thead>
                    <tr style="background: #2F5496; color: #FFFFFF; font-weight: bold;">
                        <th colspan="2" style="border: 1px solid #4472C4; padding: 4px;">Reporte de cliente</th>
                        <th colspan="5" style="border: 1px solid #4472C4; padding: 4px;">Revisión realizada</th>
                    </tr>
                    <tr style="background: #B4C6E7; color: #000000; font-weight: bold; font-size: 9.5pt;">
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 14%;">Fecha</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 12%;">Hora</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 15%;">Fecha Inicio</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 13%;">Hora Inicio</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 15%;">Fecha Fin</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 13%;">Hora Fin</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 18%;">Down Time</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="background: #D9E2F3; color: #000000;">
                        <td style="border: 1px solid #4472C4; padding: 4px;">${clientDate || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">${clientTime || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">${workStartDate || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">${workStartTime || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">${workEndDate || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">${workEndTime || "-"}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px; font-weight: bold;">${downTime || "-"}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Tabla 6: Trabajo Realizado -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10.5pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">TRABAJO REALIZADO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #FFFFFF; color: #000000; padding: 10px 12px; line-height: 1.5; text-align: justify; white-space: pre-wrap;">${work || "No se ha ingresado el detalle del trabajo realizado."}</td>
                    </tr>
                </tbody>
            </table>
            ${imagesHtml}

            <!-- Tabla 7 y 8: Conclusiones y Repuestos Requeridos -->
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10.5pt; margin-bottom: 10px; page-break-inside: avoid;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">CONCLUSIONES:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #FFFFFF; color: #000000; padding: 8px 12px; line-height: 1.4; white-space: pre-wrap;">${conclusion || "-"}${partsTableHtml}</td>
                    </tr>
                </tbody>
            </table>

            <!-- Firmas y Sellos Institucionales -->
            <div style="margin-top: 36px; display: flex; justify-content: space-between; align-items: flex-start; padding: 0 40px; page-break-inside: avoid;">
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #2F5496; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold; color: #2F5496;">Firma / Sello Técnico</div>
                    <div style="font-size: 9.5px; color: #334155;">Servicio Técnico Especializado</div>
                </div>
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #2F5496; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold; color: #2F5496;">Conformidad del Cliente</div>
                    <div style="font-size: 9.5px; color: #334155;">Responsable de Servicio / Física Médica</div>
                </div>
            </div>
        </div>
    `;

    const contentEl = document.getElementById("informePreviewContent");
    const modalEl = document.getElementById("informePreviewModal");
    if (contentEl) contentEl.innerHTML = docHtml;
    if (modalEl) modalEl.style.display = "block";
}

function closeReportPreview() {
    const modal = document.getElementById("informePreviewModal");
    if (modal) modal.style.display = "none";
}

async function exportDocx() {
    const data = getReportFormData();
    try {
        toast("Generando documento Word (.docx) idéntico a la plantilla...", "info");
        const resp = await fetch("/reports/export-docx", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const errJson = await resp.json().catch(() => ({}));
            throw new Error(errJson.message || `Error ${resp.status} al exportar DOCX`);
        }
        const blob = await resp.blob();
        const cleanNumber = (data.number || "INFORME_TECNICO").replace(/[^a-zA-Z0-9_\-\.]/g, "_") || "INFORME_TECNICO";
        const filename = `${cleanNumber}.docx`;

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast("Documento Word (.docx) descargado exitosamente", "ok");
    } catch (err) {
        console.error("Error exportando DOCX:", err);
        toast("No se pudo exportar el documento Word: " + (err.message || err), "err");
    }
}

function exportInforme() {
    previewInforme();
    setTimeout(() => {
        window.print();
    }, 350);
}

function resetReportForm() {
    const defaultFields = {
        reportClient: "INEN",
        reportNumber: "260915_154574_ CG HT PSU OT",
        reportService: "Radioterapia",
        reportDate: "15 de Septiembre del 2026",
        reportEquipment: "ACELERADOR LINEAL",
        reportDept: "LIMA",
        reportBrand: "ELEKTA",
        reportModel: "SYNERGY FULL",
        reportSerial: "154574",
        reportIncident: "HT PSU OT",
        reportDiagnosis: "Reemplazo de Switch Assembly y DIE HTB",
        reportClientDate: "15/09/2026",
        reportClientTime: "19:00",
        reportWorkStartDate: "15/09/2026",
        reportWorkStartTime: "19:00",
        reportWorkEndDate: "15/09/2026",
        reportWorkEndTime: "21:00 h",
        reportDownTime: "2:00 h",
        reportConclusion: "- Equipo operativo\n- Se requiere los siguientes repuestos"
    };

    for (const [id, val] of Object.entries(defaultFields)) {
        const el = document.getElementById(id);
        if (el) el.value = val;
    }

    const progEl = document.getElementById("reportProgrammed");
    if (progEl) progEl.checked = true;
    const suspEl = document.getElementById("reportSuspTto");
    if (suspEl) suspEl.checked = false;

    _reportImages = [];
    renderReportImagesList();

    const partsContainer = document.getElementById("reportParts");
    if (partsContainer) {
        partsContainer.innerHTML = "";
        addReportPart("45133308377", "Switch Assembly", "01");
        addReportPart("1573801", "Digital input & encoding board (DIE-HTB, DIE-B)", "01");
    }

    const fileInput = document.getElementById("reportImages");
    if (fileInput) fileInput.value = "";

    toast("Formulario de informe restablecido");
}

function initReportMediaHandlers() {
    window.addEventListener("paste", (e) => {
        const screenReports = document.getElementById("screenReports");
        if (!screenReports || !screenReports.classList.contains("active")) return;
        const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type && item.type.indexOf("image") !== -1) {
                const blob = item.getAsFile();
                if (blob) {
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        const count = _reportImages.length + 1;
                        _reportImages.push({
                            id: "img_" + (++_reportImgSeq),
                            name: "Captura de inspección " + count,
                            dataUrl: event.target.result
                        });
                        renderReportImagesList();
                        toast("Imagen adjuntada desde el portapapeles", "ok");
                    };
                    reader.readAsDataURL(blob);
                }
            }
        }
    });

    const dropZone = document.getElementById("reportImagesDropZone");
    if (dropZone) {
        dropZone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--accent, #38bdf8)";
        });
        dropZone.addEventListener("dragleave", (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--border, #334155)";
        });
        dropZone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--border, #334155)";
            if (e.dataTransfer && e.dataTransfer.files) {
                handleReportImagesChange({ target: { files: e.dataTransfer.files } });
            }
        });
    }
}

function initReportDefaults() {
    const partsContainer = document.getElementById("reportParts");
    if (partsContainer && partsContainer.children.length === 0) {
        addReportPart("45133308377", "Switch Assembly", "01");
        addReportPart("1573801", "Digital input & encoding board (DIE-HTB, DIE-B)", "01");
    }
    renderReportImagesList();
    initReportMediaHandlers();
}

if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initReportDefaults);
    } else {
        initReportDefaults();
    }
}

// ─── EXPORTACIONES GLOBALES PARA MANEJADORES DE INTERFAZ ─────────────────────
window.toast = toast;
window.verPDF = verPDF;
window.buscar = buscar;
window.cargarMasResultados = cargarMasResultados;
window.quitarSintoma = quitarSintoma;
window.agregarSintoma = agregarSintoma;
window.analizarDiagnostico = analizarDiagnostico;
window.analizarDiagnosticoAi = analizarDiagnosticoAi;
window.guardarYReintentarAi = guardarYReintentarAi;
window.cargarNotas = cargarNotas;
window.abrirFormNota = abrirFormNota;
window.guardarNota = guardarNota;
window.cerrarFormNota = cerrarFormNota;
window.editarNota = editarNota;
window.eliminarNota = eliminarNota;
window.verNota = verNotaEnGrande;
window.verNotaEnGrande = verNotaEnGrande;
window.cerrarVisorNota = cerrarVisorNota;
window.pdfPagAnterior = pdfPagAnterior;
window.pdfPagSiguiente = pdfPagSiguiente;
window.cerrarVisorPDF = cerrarVisorPDF;
window.adminEntrar = adminEntrar;
window.adminSalir = adminSalir;
window.cargarListaManuales = cargarListaManuales;
window.isOnline = isOnline;
window.addReportPart = addReportPart;
window.previewInforme = previewInforme;
window.exportInforme = exportInforme;
window.exportDocx = exportDocx;
window.closeReportPreview = closeReportPreview;
window.redactarTrabajoRealizado = redactarTrabajoRealizado;
window.handleReportImagesChange = handleReportImagesChange;
window.actualizarNombreImagenReporte = actualizarNombreImagenReporte;
window.eliminarImagenReporte = eliminarImagenReporte;
window.resetReportForm = resetReportForm;
window.calcularDownTimeInforme = calcularDownTimeInforme;
