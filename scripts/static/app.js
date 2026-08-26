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
    const response = await fetch(url, options);
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
        const error = new Error((data && data.error) || `Error HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }
    return data;
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
    if (!window._pdfDoc || window._pdfRendering) return;
    window._pdfRendering = true;
    
    window._pdfDoc.getPage(numEntero).then(function(page) {
        const canvas  = document.getElementById("pdfCanvas");
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

        page.render({ canvasContext: ctx, viewport: vp }).promise.then(function() {
            window._pdfRendering = false;
            window._pdfPage = numEntero;
            
            const info = document.getElementById("pdfPagInfo");
            if (info) info.textContent = "Pág. " + numEntero + " / " + window._pdfDoc.numPages;
            
            const btnWeb = document.getElementById("btnWebPdf");
            if (btnWeb) {
                const baseUrl = btnWeb.href.split('#')[0];
                btnWeb.href = baseUrl + "#page=" + numEntero;
            }

            document.getElementById("pdfScroll").scrollTop = 0;

            // Resaltar términos buscados (no bloquea ni rompe la visualización si falla)
            resaltarEnPdf(page, vp, canvas);
        });
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

            // Priorizar la frase exacta buscada; si tiene varias palabras, incluir términos individuales no triviales
            const searchTerms = [rawQuery];
            const words = rawQuery.split(/[\s,;]+/).filter(w => w.length >= 3 && !["con", "del", "para", "por", "the", "and", "for"].includes(w));
            for (const w of words) {
                if (!searchTerms.includes(w)) searchTerms.push(w);
            }

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
    window._pdfDoc = null;
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
    card.style.animationDelay = (Math.min(index, 10) * 25) + "ms";

    const tags = isNote && Array.isArray(result.tags) && result.tags.length
        ? '<div class="card-tags">' + result.tags.map(tag => '<span class="tag">'+esc(tag)+'</span>').join("") + "</div>"
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

    results.forEach((result, index) => list.appendChild(crearTarjetaResultado(result, keyword, index)));
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
function notasGuardar(ns) { localStorage.setItem("interlocks_notas", JSON.stringify(Array.isArray(ns)?ns:[])); }
function notaSync(n) { const t = notasLocal().filter(x=>x.id!==n.id); t.push(n); notasGuardar(t); }
function notaBorrar(id) { notasGuardar(notasLocal().filter(n=>n.id!==id)); }
function pendLoad()    {
    try {
        const value=JSON.parse(localStorage.getItem("interlocks_pend")||"[]");
        if (!Array.isArray(value)) return [];
        return value.map(item => item.op ? item : {op:"create", id:item.id, payload:item});
    } catch { return []; }
}
function pendSave(p)   { localStorage.setItem("interlocks_pend", JSON.stringify(p)); }
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
