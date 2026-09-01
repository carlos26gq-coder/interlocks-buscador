console.log("✅ SOLVI app.js v17 — búsqueda indexada, diagnóstico y diagrama de relaciones");

// ─── RED ──────────────────────────────────────────────────
function actualizarRed() {
    const el  = document.getElementById("estadoRed");
    const txt = document.getElementById("estadoTxt");
    if (navigator.onLine) {
        el.className = "online";
        txt.textContent = "Conectado";
        syncPendientes();
    } else {
        el.className = "offline";
        txt.textContent = "Sin conexión";
    }
}
window.addEventListener("online",  actualizarRed);
window.addEventListener("offline", actualizarRed);
actualizarRed();

// ─── DATOS ───────────────────────────────────────────────
let _r2url = localStorage.getItem("r2url") || "";
let _workerSequence = 0;
const _workerPending = new Map();
const _searchWorker = new Worker("/static/search-worker.js");
let _searchState = { query:"", manual:"", offset:0, limit:25, total:0, hasMore:false, mode:"offline" };
let _highlightQuery = "";  // palabra/s buscada/s para resaltar en el visor PDF

_searchWorker.onmessage = event => {
    const pending = _workerPending.get(event.data.id);
    if (!pending) return;
    _workerPending.delete(event.data.id);
    if (event.data.ok) pending.resolve(event.data.data);
    else pending.reject(new Error(event.data.error || "Error en la búsqueda offline"));
};

function workerRequest(type, payload) {
    return new Promise((resolve, reject) => {
        const id = ++_workerSequence;
        _workerPending.set(id, {resolve, reject});
        _searchWorker.postMessage({id, type, payload});
    });
}

async function apiRequest(url, options = {}) {
    const timeoutMs = options.timeout || (url.includes("/ai") ? 90000 : 15000);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const fetchOptions = { ...options, signal: options.signal || controller.signal };
    delete fetchOptions.timeout;

    try {
        const response = await fetch(url, fetchOptions);
        clearTimeout(timer);
        let data = null;
        try { data = await response.json(); } catch { data = null; }

        // For AI endpoint: if response is JSON with ok:true, return it even at odd status codes
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
        clearTimeout(timer);
        if (err && err.name === "AbortError") {
            throw new Error("Tiempo de espera agotado. Verifica tu conexión o intenta de nuevo.");
        }
        throw err;
    }
}

// ─── HELPERS ─────────────────────────────────────────────
function esc(s) {
    if (s === undefined || s === null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function hi(txt, kw) {
    if (!kw) return esc(txt);
    const terms = [...new Set(String(kw).trim().split(/\s+/).filter(Boolean))]
        .sort((a,b) => b.length-a.length)
        .map(term => term.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
    if (!terms.length) return esc(txt);
    const re = new RegExp(terms.join("|"),"gi");
    return esc(txt).replace(re, m => "<mark>"+m+"</mark>");
}
function toast(msg, tipo) {
    document.querySelectorAll(".toast").forEach(t => t.remove());
    const t = document.createElement("div");
    t.className = "toast " + (tipo==="err" ? "terr" : "tok");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
}

// ─── PDF VIEWER (PDF.js) ─────────────────────────────────
let _pdfJsLoaded = false;

function cargarPdfJs(cb) {
    if (_pdfJsLoaded) { cb(); return; }
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
    s.onload = function() {
        pdfjsLib.GlobalWorkerOptions.workerSrc =
            "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
        _pdfJsLoaded = true;
        cb();
    };
    s.onerror = function() {
        toast("❌ No se pudo cargar el visor PDF","err");
    };
    document.head.appendChild(s);
}

function verPDF(manual, page, keyword) {
    if (!_r2url) { toast("⚠️ PDFs no configurados","err"); return; }
    _highlightQuery = (keyword || "").trim();
    const pdfUrl = _r2url + "/" + encodeURIComponent(manual + ".pdf");
    
    const pageInt = parseInt(page, 10) || 1;

    if (!navigator.onLine) {
        alert("📴 Sin conexión a internet.\n\nPara ver este documento, busca el archivo '" + manual + ".pdf' que descargaste previamente en tu carpeta de Descargas.");
        return; 
    } else {
        toast("📄 Cargando PDF...", "ok");
    }
    
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
                '<button onclick="pdfPagAnterior()" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">◀</button>' +
                '<span id="pdfPagInfo" style="font-size:.75rem;color:#94a3b8;font-family:monospace;min-width:70px;text-align:center">Pág. ' + pageNum + '</span>' +
                '<button onclick="pdfPagSiguiente()" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">▶</button>' +
                '<a id="btnWebPdf" href="' + pdfUrl + '#page=' + pageNum + '" target="_blank" style="background:#0077ff;border:none;color:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.75rem;text-decoration:none;white-space:nowrap;">🌐 Web</a>' +
                '<a href="' + pdfUrl + '" download style="background:#00d4ff;border:none;color:#000;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.75rem;font-weight:bold;text-decoration:none;white-space:nowrap;">💾 Offline</a>' +
                '<button onclick="cerrarVisorPDF()" style="background:#ef4444;border:none;color:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.8rem">✕</button>' +
            '</div>' +
        '</div>' +
        '<div id="pdfScroll" style="flex:1;overflow-y:auto;overflow-x:auto;display:flex;flex-direction:column;align-items:flex-start;padding:10px 0;background:#1a1a2e;">' +
            '<canvas id="pdfCanvas" style="box-shadow:0 2px 12px rgba(0,0,0,.5); touch-action: pan-x pan-y; margin: 0 auto;"></canvas>' +
        '</div>';
    modal.style.display = "flex";

    window._pdfDoc      = null;
    window._pdfPage     = pageNum;
    window._pdfRendering = false;

    activarZoomCanvas();

    const isAndroid = /Android/i.test(navigator.userAgent);

    pdfjsLib.getDocument({ 
        url: pdfUrl, 
        disableRange: isAndroid, 
        disableStream: isAndroid,
        cMapUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/", 
        cMapPacked: true 
    })
        .promise.then(function(doc) {
            window._pdfDoc = doc;
            document.getElementById("pdfPagInfo").textContent = "Pág. " + pageNum + " / " + doc.numPages;
            renderPdfPagina(pageNum);
        }).catch(function(err) {
            document.getElementById("pdfScroll").innerHTML =
                '<div style="width:100%; margin:auto; padding:40px 20px; box-sizing:border-box; text-align:center; display:flex; flex-direction:column; align-items:center;">' +
                    '<div style="font-size:3.5rem;margin-bottom:10px;">📡</div>' +
                    '<p style="color:#ef4444;font-weight:bold;font-size:1.2rem;margin:0 0 10px 0;">Error de Red</p>' +
                    '<p style="color:#94a3b8;font-size:0.95rem;max-width:320px;margin:0;line-height:1.5;">La conexión de red es inestable.</p>' +
                '</div>';
        });
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

        const ratioInteligente = Math.min(window.devicePixelRatio || 1.5, 2);
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
                        const isWordBoundary = /[\s\W_]/.test(charBefore) && /[\s\W_]/.test(charAfter);

                        if (isWordBoundary || term === rawQuery) {
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
    const canvas = document.getElementById("pdfCanvas");
    if (canvas) {
        canvas.width = 1;
        canvas.height = 1;
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

    let currentZoom = 1;
    let initialDistance = null;
    let isPinching = false;
    let animationFrameId = null;

    canvas.dataset.currentZoom = 1;

    canvas.addEventListener('touchstart', (e) => {
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
    if (!nota && navigator.onLine) {
        try {
            const notas = await apiRequest("/notes");
            if (Array.isArray(notas)) {
                notasGuardar(notas);
                nota = notas.find(n => n.id === id);
            }
        } catch(e) {}
    }
    
    if (!nota) { toast("⚠️ Apunte no encontrado", "err"); return; }
    
    document.getElementById("viewNoteTitle").innerText = nota.title;
    document.getElementById("viewNoteText").innerText = nota.text;
    
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
    } else if (_r2url) {
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

async function buscarOnline(keyword, manual, offset) {
    const params = new URLSearchParams({q: keyword, offset: String(offset), limit: String(_searchState.limit)});
    if (manual) params.set("manual", manual);
    const data = await apiRequest("/search?" + params.toString());
    if (data.r2_url) {
        _r2url = data.r2_url;
        localStorage.setItem("r2url", _r2url);
    }
    return data;
}

async function buscar(loadMore = false) {
    const keyword = (document.getElementById("q").value || "").trim();
    const manual = (document.getElementById("manual").value || "").trim();
    const button = loadMore ? document.getElementById("btnMasResultados") : document.getElementById("btnBuscar");
    if (!keyword) {
        const input = document.getElementById("q");
        input.style.borderColor = "var(--danger)";
        setTimeout(() => input.style.borderColor = "", 1200);
        return;
    }
    if (keyword.length > 200) { toast("La búsqueda admite hasta 200 caracteres", "err"); return; }

    if (!loadMore) {
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
        if (navigator.onLine) {
            try {
                data = await buscarOnline(keyword, manual, _searchState.offset);
                mode = "online";
            } catch (onlineError) {
                console.warn("Búsqueda online no disponible; usando índice local", onlineError);
                data = await buscarOffline(keyword, manual, _searchState.offset);
            }
        } else {
            data = await buscarOffline(keyword, manual, _searchState.offset);
        }
        renderResultados(data, keyword, mode, loadMore);
    } catch(error) {
        console.error(error);
        if (loadMore) _searchState.offset = Math.max(0, _searchState.offset - _searchState.limit);
        document.getElementById("resultsList").innerHTML = '<div class="result-card"><span style="color:var(--danger)">❌ '+esc(error.message)+'</span></div>';
        uiState("results");
    } finally {
        if (button) { button.textContent = originalText || (loadMore ? "Ver más" : "Buscar"); button.disabled = false; }
    }
}

function cargarMasResultados() {
    if (_searchState.hasMore) buscar(true);
}

// ─── MENSAJE DE BIENVENIDA ────────────────────────────────
function mostrarBienvenida() {
    if (sessionStorage.getItem("bienvenidaMostrada")) return;
    sessionStorage.setItem("bienvenidaMostrada", "true");

    const modal = document.createElement("div");
    modal.id = "modalBienvenida";
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px);";
    
    modal.innerHTML = 
        '<div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:24px;text-align:center;max-width:80%;box-shadow:0 10px 25px rgba(0,0,0,0.5);">' +
            '<div style="font-size:2.5rem;margin-bottom:12px;">👋</div>' +
            '<p style="color:#e2e8f0;font-size:1.1rem;font-weight:bold;margin:0 0 20px 0;line-height:1.4;">Buscador técnico disponible online y offline</p>' +
            '<button onclick="document.getElementById(\'modalBienvenida\').remove()" style="background:#00d4ff;color:#0b0f1a;border:none;padding:10px 24px;border-radius:8px;font-weight:bold;font-size:1rem;cursor:pointer;">OK</button>' +
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
const SYMPTOM_NUMS = ["①","②","③","④"];
const SYMPTOM_HINTS = [
    "Ej: Interlock 283",
    "Ej: Error 66",
    "Ej: Leaf missing",
    "Ej: Gantry movement issue"
];

function _setupSymptomEnter(input) {
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); analizarDiagnostico(); }
    });
}

function agregarSintoma() {
    const container = document.getElementById("symptomsContainer");
    const rows = container.querySelectorAll(".symptom-row");
    if (rows.length >= 4) { toast("Máximo 4 síntomas", "err"); return; }
    const idx = rows.length;
    const row = document.createElement("div");
    row.className = "symptom-row";
    row.dataset.index = idx;
    row.innerHTML =
        '<span class="symptom-num">' + SYMPTOM_NUMS[idx] + '</span>' +
        '<input type="text" class="symptom-input" maxlength="200" placeholder="' + SYMPTOM_HINTS[idx] + '" autocomplete="off" autocorrect="off" autocapitalize="off">' +
        '<button class="sym-del-btn" onclick="quitarSintoma(this)" aria-label="Eliminar">✕</button>';
    container.appendChild(row);
    // Show delete buttons on all rows now that there are more than 2
    container.querySelectorAll(".sym-del-btn").forEach(b => b.style.display = "");
    _setupSymptomEnter(row.querySelector(".symptom-input"));
    row.querySelector(".symptom-input").focus();
    if (container.querySelectorAll(".symptom-row").length >= 4) {
        document.getElementById("btnAddSym").style.display = "none";
    }
}

function quitarSintoma(btn) {
    const container = document.getElementById("symptomsContainer");
    if (container.querySelectorAll(".symptom-row").length <= 2) return;
    btn.closest(".symptom-row").remove();
    // Renumber
    container.querySelectorAll(".symptom-row").forEach((row, i) => {
        row.dataset.index = i;
        row.querySelector(".symptom-num").textContent = SYMPTOM_NUMS[i];
    });
    document.getElementById("btnAddSym").style.display = "";
    if (container.querySelectorAll(".symptom-row").length <= 2) {
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

    const symsHtml = symptoms.slice(0, 4).map(s =>
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
                '<div class="diag-main-label">⚡ Factor Común / Causa Raíz</div>' +
                '<div class="diag-main-title">' + esc(mainTitle) + '</div>' +
                '<div class="diag-main-meta">Manual: <b>' + esc(main.manual) + '</b>' +
                ' · <b>' + main.relative_match + '% de compatibilidad</b>' +
                ' · <span style="color:' + mainConf.color + '">' + mainConf.label + '</span></div>' +
            '</div>' +
            (others.length
                ? '<div class="diag-connector-fan"></div>' +
                  '<div style="font-size:.58rem;font-family:var(--mono);color:var(--muted);text-align:center;margin-bottom:5px;text-transform:uppercase;letter-spacing:.06em">Otras relaciones posibles</div>' +
                  '<div class="diag-others-row">' + othersHtml + '</div>'
                : "") +
        '</div>';
    container.style.display = "block";
}

// ─── RENDER DIAGNÓSTICO ───────────────────────────────────
function renderDiagnostico(data, mode, symptoms) {
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const meta    = document.getElementById("diagMeta");
    const notice  = document.getElementById("diagNotice");
    const diagram = document.getElementById("diagDiagram");
    list.innerHTML = "";
    diagram.style.display = "none";

    const results = Array.isArray(data.results) ? data.results : [];
    meta.textContent = (mode === "online" ? "ONLINE" : "OFFLINE") + " · " + results.length + " relaciones encontradas";
    notice.textContent = data.message || "";
    notice.style.display = (data.message && results.length) ? "block" : "none";

    if (!results.length) {
        empty.style.display = "flex";
        empty.querySelector("p").textContent = data.message || "No se encontraron relaciones suficientes.";
        return;
    }
    empty.style.display = "none";

    const allSymptoms = symptoms || (Array.isArray(data.signals) ? data.signals : []);
    renderDiagrama(results, allSymptoms);

    const confColors = { alta: "var(--green)", media: "var(--warn)", baja: "var(--muted)" };
    const confLabels = { alta: "⬤ Alta probabilidad", media: "⬤ Probabilidad media", baja: "⬤ Baja probabilidad" };

    results.slice(0, 3).forEach((result, index) => {
        const conf     = result.confidence || "media";
        const confColor = confColors[conf] || "var(--muted)";
        const confLabel = confLabels[conf] || "Probabilidad media";

        const card = document.createElement("article");
        card.className = "diagnostic-card" + (conf === "baja" ? " diag-card-low" : "");

        const matches = (result.matched_signals || []).map(item =>
            '<span class="diag-chip">' + esc(item.value) + " · " + Math.round((item.coverage || 0) * 100) + "%</span>"
        ).join("");

        const componentHtml = result.associated_component
            ? '<div class="diag-component-box"><span class="diag-comp-label">📍 Factor Común / Componente Asociado</span>' +
              esc(result.associated_component) + '</div>'
            : "";

        card.innerHTML =
            '<div class="diag-rank">' +
                '<span>RELACIÓN ' + (index + 1) + '</span>' +
                '<span style="color:' + confColor + ';font-size:.65rem">' + confLabel + '</span>' +
                '<b>' + Number(result.relative_match || 0) + "% · " + Number(result.matched_count || 0) + "/" + Number(result.signal_count || 0) + " señales</b>" +
            "</div>" +
            "<h3>" + esc(result.title || "Conexión técnica documentada") + "</h3>" +
            '<div class="card-header"><span class="card-manual manual-badge">' + esc(result.manual) + "</span></div>" +
            '<div class="diag-chips">' + matches + "</div>" +
            componentHtml +
            '<div class="card-ctx">' + esc(result.context) + "</div>";

        list.appendChild(card);
    });
}

function renderDiagramaAi(aiData, symptoms) {
    const container = document.getElementById("diagDiagram");
    if (!aiData || !symptoms.length) { container.style.display = "none"; return; }

    const symsHtml = symptoms.slice(0, 4).map(s =>
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
    list.innerHTML = "";
    empty.style.display = "none";

    meta.textContent = "";
    notice.style.display = "none";

    const confMap = {
        alta: { color: "var(--green)", label: "⬤ Alta probabilidad" },
        media: { color: "var(--warn)", label: "⬤ Probabilidad media" },
        baja: { color: "var(--muted)", label: "⬤ Probabilidad media" }
    };
    const conf = confMap[aiData.confidence] || confMap.alta;

    // Renderizar diagrama dedicado para IA (exclusivo para la causa raíz de IA)
    renderDiagramaAi(aiData, symptoms);

    const card = document.createElement("article");
    card.className = "diag-ai-card";

    const boardsChips = (aiData.associated_boards || []).map(b =>
        '<span class="diag-chip" style="background:rgba(168,85,247,.12);border-color:rgba(168,85,247,.35);color:#d8b4fe">📍 ' + esc(b) + "</span>"
    ).join("");

    const manualsChips = (aiData.manual_references || []).map(m =>
        '<span class="diag-chip" style="background:rgba(0,212,255,.08);border-color:rgba(0,212,255,.3);color:var(--accent)">📚 ' + esc(m) + "</span>"
    ).join("");

    const stepsHtml = (aiData.action_steps || []).map((step, idx) =>
        '<li data-step="' + (idx + 1) + '">' + esc(step) + "</li>"
    ).join("");

    const warningHtml = aiData.safety_warning
        ? '<div class="diag-ai-warning"><strong>⚠️ PRECAUCIÓN DE SEGURIDAD:</strong> ' + esc(aiData.safety_warning) + '</div>'
        : "";

    card.innerHTML =
        '<div class="diag-ai-top">' +
            '<span class="diag-ai-badge">INFORME DE CAUSA RAÍZ</span>' +
            '<span style="font-size:.65rem;font-family:var(--mono);color:' + conf.color + '">' + conf.label + '</span>' +
        '</div>' +
        '<div class="diag-ai-root">' + esc(aiData.root_cause || "Causa no identificada") + '</div>' +
        (boardsChips ? '<div class="diag-chips" style="margin-bottom:12px">' + boardsChips + '</div>' : '') +
        '<div class="diag-ai-section">' +
            '<div class="diag-ai-sectit">🧠 Análisis y Deducción Causal</div>' +
            '<div class="diag-ai-body">' + esc(aiData.explanation || "") + '</div>' +
        '</div>' +
        (stepsHtml ?
            '<div class="diag-ai-section">' +
                '<div class="diag-ai-sectit">🔧 Procedimiento de Inspección Sugerido</div>' +
                '<ul class="diag-ai-steps">' + stepsHtml + '</ul>' +
            '</div>'
        : '') +
        (manualsChips ?
            '<div class="diag-ai-section">' +
                '<div class="diag-ai-sectit">📖 Manuales de Referencia</div>' +
                '<div class="diag-chips">' + manualsChips + '</div>' +
            '</div>'
        : '') +
        warningHtml;

    list.appendChild(card);
}

let _isAnalyzingAi = false;
async function analizarDiagnosticoAi() {
    if (_isAnalyzingAi) return;
    const symptoms = diagnosticoSymptoms();
    if (!symptoms.length) {
        toast("Ingresa al menos un síntoma, error o descripción de falla", "err");
        return;
    }

    if (!navigator.onLine) {
        toast("El análisis con IA requiere internet. Mostrando diagnóstico local...", "warn");
        return analizarDiagnostico();
    }

    _isAnalyzingAi = true;
    const btnAi   = document.getElementById("btnDiagnoseAi");
    const btnDiag = document.getElementById("btnDiagnose");
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const diagram = document.getElementById("diagDiagram");

    empty.style.display   = "none";
    diagram.style.display = "none";
    list.innerHTML =
        '<div class="diag-ai-loading">' +
            '<div class="spinner"></div>' +
            '<p>🧠 Analizando y deduciendo causas con los manuales...</p>' +
            '<span style="font-size:.68rem;color:var(--muted);font-family:var(--mono)">Correlacionando síntomas con la arquitectura técnica de Elekta</span>' +
        '</div>';

    if (btnAi)   { btnAi.disabled = true; btnAi.textContent = "Analizando..."; }
    if (btnDiag) { btnDiag.disabled = true; }

    try {
        const customKey = localStorage.getItem("solvi_gemini_key") || "";
        let customModel = (localStorage.getItem("solvi_gemini_model") || "").trim();
        if (customModel.includes("2.5") || customModel.includes("1.5") || customModel.includes("3.7")) {
            localStorage.removeItem("solvi_gemini_model");
            customModel = "";
        }
        const headers = {"Content-Type": "application/json"};
        if (customKey) {
            headers["X-Gemini-Key"] = customKey;
        }
        if (customModel) {
            headers["X-Gemini-Model"] = customModel;
        }

        const res = await apiRequest("/diagnose/ai", {
            method: "POST",
            headers,
            body: JSON.stringify({ symptoms, api_key: customKey, model: customModel })
        });

        if (res && res.ok && res.data) {
            renderDiagnosticoAi(res.data, symptoms);
        } else {
            throw new Error((res && (res.message || res.error)) || "Inconveniente al procesar con IA.");
        }
    } catch (error) {
        const errMsg = error.message || String(error);
        const errData = error.data || {};
        const errType = errData.error || "";

        if (errType === "no_api_key" || errMsg.includes("clave de API") || errMsg.includes("API_KEY") || errType === "invalid_api_key") {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:#a855f7">' +
                    '<div class="diag-ai-badge" style="margin-bottom:8px">CONFIGURACIÓN DE IA</div>' +
                    '<h3 style="color:#f8fafc">Se requiere una Clave de API de Gemini</h3>' +
                    '<p style="font-size:.8rem;color:#cbd5e1;line-height:1.5;margin-bottom:12px">' +
                        'La variable <code>GEMINI_API_KEY</code> no está configurada en Render o la clave no es válida.' +
                    '</p>' +
                    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
                        '<input id="promptGeminiKey" type="password" placeholder="Pega tu clave AIzaSy..." style="flex:1;min-width:200px;background:var(--s2);border:1px solid var(--border);color:var(--text);padding:8px 10px;border-radius:6px;font-family:var(--mono);font-size:.8rem">' +
                        '<button class="btn btn-ai" onclick="guardarYReintentarAi()">Guardar y Analizar</button>' +
                    '</div>' +
                '</div>';
        } else if (errType === "quota_exceeded" || errMsg.includes("429") || errMsg.includes("cuota") || errMsg.includes("Límite")) {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⏳ CUOTA TEMPORAL ALCANZADA</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">' + esc(errMsg) + '</h3>' +
                    '<p style="font-size:.78rem;color:var(--muted);margin:8px 0 12px">Espera 30 segundos y vuelve a intentar, o ejecuta el diagnóstico local ahora.</p>' +
                    '<button class="btn btn-primary btn-sm" onclick="analizarDiagnostico()">⚡ Diagnóstico local instantáneo</button>' +
                    ' <button class="btn btn-ghost btn-sm" style="margin-left:6px" onclick="analizarDiagnosticoAi()">🔄 Reintentar IA</button>' +
                '</div>';
        } else if (errMsg.includes("agotado") || errMsg.includes("AbortError") || errMsg.includes("timeout")) {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⏱ TIEMPO DE RESPUESTA EXCEDIDO</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">La IA tardó más de lo esperado en responder.</h3>' +
                    '<p style="font-size:.78rem;color:var(--muted);margin:8px 0 12px">El análisis puede completarse en el siguiente intento. El diagnóstico local está disponible de inmediato.</p>' +
                    '<button class="btn btn-primary btn-sm" onclick="analizarDiagnostico()">⚡ Diagnóstico local instantáneo</button>' +
                    ' <button class="btn btn-ghost btn-sm" style="margin-left:6px" onclick="analizarDiagnosticoAi()">🔄 Reintentar IA</button>' +
                '</div>';
        } else {
            list.innerHTML =
                '<div class="diagnostic-card" style="border-left-color:var(--warn)">' +
                    '<div class="diag-rank"><span style="color:var(--warn)">⚠️ ERROR DE ANÁLISIS</span></div>' +
                    '<h3 style="color:#f8fafc;font-size:.92rem;line-height:1.4;margin:6px 0">' + esc(errMsg) + '</h3>' +
                    '<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">' +
                        '<button class="btn btn-primary btn-sm" onclick="analizarDiagnostico()">⚡ Diagnóstico local</button>' +
                        '<button class="btn btn-ghost btn-sm" onclick="analizarDiagnosticoAi()">🔄 Reintentar IA</button>' +
                    '</div>' +
                '</div>';
        }
    } finally {
        _isAnalyzingAi = false;
        if (btnAi)   { btnAi.disabled = false; btnAi.textContent = "🧠 Analizar causas"; }
        if (btnDiag) { btnDiag.disabled = false; }
    }
}

function guardarYReintentarAi() {
    const input = document.getElementById("promptGeminiKey");
    if (!input) return;
    const key = input.value.trim();
    if (!key) {
        toast("Ingresa una clave válida", "err");
        return;
    }
    localStorage.setItem("solvi_gemini_key", key);
    toast("Clave guardada con éxito", "ok");
    analizarDiagnosticoAi();
}

async function analizarDiagnostico() {
    const symptoms = diagnosticoSymptoms();
    if (!symptoms.length) {
        toast("Ingresa al menos un síntoma o error", "err");
        return;
    }
    const button  = document.getElementById("btnDiagnose");
    const list    = document.getElementById("diagResults");
    const empty   = document.getElementById("diagEmpty");
    const diagram = document.getElementById("diagDiagram");
    empty.style.display   = "none";
    diagram.style.display = "none";
    list.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div>' +
        '<p style="font-size:.8rem;color:var(--muted);margin-top:10px">Relacionando síntomas...</p></div>';
    button.disabled    = true;
    button.textContent = "Analizando...";
    try {
        let data, mode = "offline";
        if (navigator.onLine) {
            try {
                data = await apiRequest("/diagnose", {
                    method:  "POST",
                    headers: {"Content-Type": "application/json"},
                    body:    JSON.stringify({symptoms})
                });
                mode = "online";
                if (data.r2_url) { _r2url = data.r2_url; localStorage.setItem("r2url", _r2url); }
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
        button.disabled    = false;
        button.textContent = "Relacionar";
    }
}

// ─── INIT ────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function() {
    const q = document.getElementById("q");
    const m = document.getElementById("manual");
    if (q) {
        q.disabled = false; q.readOnly = false;
        q.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();buscar();} });
    }
    if (m) {
        m.disabled = false;
        m.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();buscar();} });
    }
    document.getElementById("adminPw")?.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();adminEntrar();} });
    document.getElementById("notaTit")?.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();guardarNota();} });

    // Symptom inputs — Enter triggers analysis
    document.querySelectorAll(".symptom-input").forEach(_setupSymptomEnter);

    uiState("welcome");
    mostrarBienvenida();
    cargarCatalogoManuales();

    if (navigator.onLine) {
        syncPendientes();
        apiRequest("/notes").then(data => { if (Array.isArray(data)) notasGuardar(data); }).catch(()=>{});
    }
});

// ─── NOTAS localStorage ──────────────────────────────────
function notasLocal() { try { const value=JSON.parse(localStorage.getItem("interlocks_notas")||"[]"); return Array.isArray(value)?value:[]; } catch { return []; } }
function notasGuardar(ns) { try { localStorage.setItem("interlocks_notas", JSON.stringify(Array.isArray(ns)?ns:[])); } catch (_e) {} }
function notaSync(n) { const t = notasLocal().filter(x=>x.id!==n.id); t.push(n); notasGuardar(t); }
function notaBorrar(id) { notasGuardar(notasLocal().filter(n=>n.id!==id)); }
function pendLoad()    {
    try {
        const value=JSON.parse(localStorage.getItem("interlocks_pend")||"[]");
        if (!Array.isArray(value)) return [];
        return value.map(item => item.op ? item : {op:"create", id:item.id, payload:item});
    } catch { return []; }
}
function pendSave(p)   { try { localStorage.setItem("interlocks_pend", JSON.stringify(p)); } catch (_e) {} }
function pendAdd(n)    { const p=pendLoad().filter(item=>item.id!==n.id); p.push({op:"create",id:n.id,payload:n}); pendSave(p); }
function pendDel(id)   { pendSave(pendLoad().filter(n=>n.id!==id)); }

function mergeCloudNotes(cloudNotes) {
    const merged = Array.isArray(cloudNotes) ? cloudNotes.slice() : [];
    for (const pending of pendLoad()) {
        if (pending.op === "create" && !merged.some(note => note.id === pending.id)) merged.push(pending.payload);
    }
    notasGuardar(merged);
    return merged;
}

async function syncPendientes() {
    const pend = pendLoad();
    if (!pend.length) return;
    let ok = 0;
    for (const item of pend) {
        try {
            if (item.op !== "create") { pendDel(item.id); continue; }
            const created = await apiRequest("/notes", {
                method:"POST",
                headers:{"Content-Type":"application/json"},
                body:JSON.stringify(item.payload)
            });
            notaBorrar(item.id);
            notaSync(created);
            pendDel(item.id);
            ok++;
        } catch(error) {
            console.warn("Sincronización pendiente", error);
            break;
        }
    }
    if (ok > 0) toast("☁️ " + ok + " apunte(s) sincronizado(s)");
}

// ─── ADMIN ───────────────────────────────────────────────
let _adminPw = ""; 

// ─── NOTAS cargar ────────────────────────────────────────
async function cargarNotas() {
    const lista = document.getElementById("listaNotas");
    const empty = document.getElementById("sinNotas");
    if (!lista) return;
    lista.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';
    if (empty) empty.style.display = "none";
    let notas = [];
    if (navigator.onLine) {
        try { notas = mergeCloudNotes(await apiRequest("/notes")); }
        catch { notas = notasLocal(); }
    } else { notas = notasLocal(); }
    lista.innerHTML = "";
    if (!notas || !notas.length) { if(empty) empty.style.display="flex"; return; }
    
    notas.forEach(n => {
        const d = document.createElement("div");
        d.className = "note-item"; d.id = "ni-"+n.id;
        const tags = (n.tags||[]).map(t=>'<span class="tag">'+esc(t)+'</span>').join("");
        const pend = pendLoad().some(p=>p.id===n.id);
        
        d.innerHTML =
            '<div class="note-item-header">'+
              '<div class="note-item-title" style="cursor:pointer; color:var(--accent);" onclick="verNotaEnGrande(\''+n.id+'\')">'+
                 esc(n.title)+(pend?' <span style="color:var(--warn);font-size:.7rem">⏳</span>':'')+
              '</div>'+
              '<div class="note-actions">'+
                '<button class="btn btn-ghost btn-sm" onclick="editarNota(\''+n.id+'\')">✏️</button>'+
                '<button class="btn btn-danger btn-sm" onclick="eliminarNota(\''+n.id+'\')">🗑</button>'+
              '</div>'+
            '</div>'+
            '<div class="note-item-text" style="cursor:pointer;" onclick="verNotaEnGrande(\''+n.id+'\')">'+esc(n.text.substring(0, 100))+(n.text.length > 100 ? '...' : '')+'</div>'+
            (tags?'<div class="card-tags">'+tags+'</div>':"");
        lista.appendChild(d);
    });
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
    if (id && !navigator.onLine) {
        toast("La edición administrativa requiere conexión para evitar conflictos", "err");
        return;
    }
    const nota = { id: id || crypto.randomUUID(), title, text, tags };
    let savedAsPending = false;

    if (navigator.onLine) {
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
    if (!_adminPw) { 
        toast("🔒 Acceso denegado: Inicia sesión como Admin para eliminar", "err"); 
        return; 
    }
    
    if (!navigator.onLine) { toast("La eliminación requiere conexión", "err"); return; }
    if (!confirm("¿Eliminar este apunte de forma permanente?")) return;
    try {
        await apiRequest("/notes/"+id, {method:"DELETE", headers:{"X-Admin-Password":_adminPw}});
    } catch(error) {
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
        if (d.r2_url && d.r2_url!=="No configurada") { _r2url=d.r2_url; localStorage.setItem("r2url",_r2url); }
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
