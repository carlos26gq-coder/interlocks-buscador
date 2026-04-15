console.log("✅ app.js v9");

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
let _data  = null;
let _r2url = localStorage.getItem("r2url") || "";

async function getData() {
    if (_data) return _data;
    const r = await fetch("/data/all_manuals.json");
    if (!r.ok) throw new Error("No se pudo cargar all_manuals.json");
    _data = await r.json();
    return _data;
}

// ─── HELPERS ─────────────────────────────────────────────
function esc(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function hi(txt, kw) {
    if (!kw) return esc(txt);
    const re = new RegExp(kw.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"),"gi");
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
// Carga PDF.js desde CDN de Mozilla al primer uso
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

function verPDF(manual, page) {
    if (!_r2url) { toast("⚠️ PDFs no configurados","err"); return; }
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
    
    // CORRECCIÓN ZOOM: Se cambió align-items a flex-start para no cortar el lado izquierdo.
    // Se añadió margin: 0 auto al canvas para mantenerlo centrado de forma segura.
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

    pdfjsLib.getDocument({ url: pdfUrl, cMapUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/", cMapPacked: true })
        .promise.then(function(doc) {
            window._pdfDoc = doc;
            document.getElementById("pdfPagInfo").textContent = "Pág. " + pageNum + " / " + doc.numPages;
            renderPdfPagina(pageNum);
        }).catch(function(err) {
            document.getElementById("pdfScroll").innerHTML =
                '<p style="color:#ef4444;padding:20px;text-align:center">❌ Error al cargar el PDF.<br><small style="color:#64748b">' + err.message + '</small></p>';
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
        });
    });
}

// CORRECCIÓN: Funciones restauradas para controlar el visor
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

// ─── LÓGICA DE ZOOM (Scroll Libre Nativo) ──────────────────────
function activarZoomCanvas() {
    const canvas = document.getElementById("pdfCanvas");
    if (!canvas) return;

    let currentZoom = 1;
    let initialDistance = null;
    canvas.dataset.currentZoom = 1;

    canvas.addEventListener('touchstart', (e) => {
        if (e.touches.length === 2) {
            initialDistance = Math.hypot(
                e.touches[0].pageX - e.touches[1].pageX,
                e.touches[0].pageY - e.touches[1].pageY
            );
        }
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
        if (e.touches.length === 2 && initialDistance) {
            e.preventDefault(); 
            const currentDistance = Math.hypot(
                e.touches[0].pageX - e.touches[1].pageX,
                e.touches[0].pageY - e.touches[1].pageY
            );
            
            const scaleChange = currentDistance / initialDistance;
            let newZoom = currentZoom * scaleChange;
            
            newZoom = Math.max(1, Math.min(newZoom, 3));
            canvas.dataset.currentZoom = newZoom;
            
            const baseWidth = parseFloat(canvas.dataset.baseWidth || window.innerWidth);
            canvas.style.width = (baseWidth * newZoom) + "px";
        }
    }, { passive: false });

    canvas.addEventListener('touchend', (e) => {
        if (e.touches.length < 2) {
            initialDistance = null;
            currentZoom = parseFloat(canvas.dataset.currentZoom || 1);
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

// ─── RENDER RESULTADOS ───────────────────────────────────
function renderResultados(results, kw, modo) {
    const lista = document.getElementById("resultsList");
    lista.innerHTML = "";
    if (!results || !results.length) { uiState("empty"); return; }
    document.getElementById("countNum").textContent = results.length;
    document.getElementById("modeTag").textContent  = modo === "online" ? "ONLINE" : "OFFLINE";
    uiState("results");
    results.forEach((r, i) => {
        const nota = r.type === "note";
        const card = document.createElement("div");
        card.className = "result-card" + (nota ? " note-card" : "");
        card.style.animationDelay = (i * 30) + "ms";
        const badge  = nota ? "note-badge" : "manual-badge";
        const mLabel = nota ? "📝 Apunte" : esc(r.manual);
        const pLabel = nota ? esc(r.page)  : "Página " + r.page;
        const tags   = nota && r.tags && r.tags.length
            ? '<div class="card-tags">' + r.tags.map(t => '<span class="tag">'+esc(t)+'</span>').join("") + "</div>" : "";
        const pdfBtn = (!nota && _r2url)
            ? '<button class="btn-pdf" onclick="verPDF(\''+esc(r.manual)+'\','+r.page+')">📖 Pág. '+r.page+'</button>' : "";
        card.innerHTML =
            '<div class="card-header"><span class="card-manual '+badge+'">'+mLabel+'</span><span class="card-page">📄 '+pLabel+'</span></div>'+
            '<div class="card-ctx">'+hi(r.context, kw)+'</div>'+
            '<div class="card-footer"><div class="card-action">'+esc(r.action)+'</div>'+pdfBtn+'</div>'+tags;
        lista.appendChild(card);
    });
}

// ─── BÚSQUEDA OFFLINE ────────────────────────────────────
async function buscarOffline(kw, mf) {
    const data = await getData();
    const res  = [];
    const kwl  = kw.toLowerCase();
    const mfl  = mf.toLowerCase();
    for (const p of data) {
        if (mfl && mfl !== "apuntes" && p.manual.toLowerCase() !== mfl) continue;
        const tl = p.text.toLowerCase();
        if (!tl.includes(kwl)) continue;
        const pos = tl.indexOf(kwl);
        const ctx = p.text.substring(Math.max(0,pos-80), Math.min(p.text.length,pos+120)).replace(/\n+/g," ").trim();
        res.push({ type:"manual", manual:p.manual, page:p.page, context:ctx, action:"Revisar sección completa del manual" });
    }
    if (!mfl || mfl === "apuntes") {
        notasLocal().forEach(n => {
            const b = (n.title+" "+n.text+" "+(n.tags||[]).join(" ")).toLowerCase();
            if (b.includes(kwl)) res.push({ type:"note", id:n.id, manual:"apuntes", page:n.title, context:n.text.substring(0,220), action:"Apunte personal", tags:n.tags||[] });
        });
    }
    return res;
}

// ─── BÚSQUEDA ONLINE ─────────────────────────────────────
async function buscarOnline(kw, mf) {
    let url = "/search?q=" + encodeURIComponent(kw);
    if (mf) url += "&manual=" + encodeURIComponent(mf);
    const r = await fetch(url);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.r2_url) { _r2url = d.r2_url; localStorage.setItem("r2url", _r2url); }
    return d.results || [];
}

// ─── BUSCAR ──────────────────────────────────────────────
// Esta función es llamada por onclick en el HTML Y por Enter en los inputs
async function buscar() {
    const kw  = (document.getElementById("q").value || "").trim();
    const mf  = (document.getElementById("manual").value || "").trim();
    const btn = document.getElementById("btnBuscar");
    if (!kw) {
        const el = document.getElementById("q");
        el.style.borderColor = "var(--danger)";
        setTimeout(() => el.style.borderColor = "", 1200);
        return;
    }
    uiState("loading");
    if (btn) { btn.textContent = "Buscando..."; btn.disabled = true; }
    try {
        let res, modo;
        if (navigator.onLine) {
            try   { res = await buscarOnline(kw, mf); modo = "online"; }
            catch { res = await buscarOffline(kw, mf); modo = "offline"; }
        } else {
            res = await buscarOffline(kw, mf); modo = "offline";
        }
        renderResultados(res, kw, modo);
    } catch(e) {
        console.error(e);
        document.getElementById("resultsList").innerHTML = '<div class="result-card"><span style="color:var(--danger)">❌ '+esc(e.message)+'</span></div>';
        uiState("results");
    } finally {
        if (btn) { btn.textContent = "Buscar"; btn.disabled = false; }
    }
}

// ─── INIT: solo registra Enter en inputs ─────────────────
// Los botones ya tienen onclick="funcion()" en el HTML
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
    uiState("welcome");
    if (navigator.onLine) syncPendientes();
});

// ─── NOTAS localStorage ──────────────────────────────────
function notasLocal() { try { return JSON.parse(localStorage.getItem("interlocks_notas")||"[]"); } catch { return []; } }
function notasGuardar(ns) { localStorage.setItem("interlocks_notas", JSON.stringify(ns)); }
function notaSync(n) { const t = notasLocal().filter(x=>x.id!==n.id); t.push(n); notasGuardar(t); }
function notaBorrar(id) { notasGuardar(notasLocal().filter(n=>n.id!==id)); }
function pendLoad()    { try { return JSON.parse(localStorage.getItem("interlocks_pend")||"[]"); } catch { return []; } }
function pendSave(p)   { localStorage.setItem("interlocks_pend", JSON.stringify(p)); }
function pendAdd(n)    { const p=pendLoad(); p.push(n); pendSave(p); }
function pendDel(id)   { pendSave(pendLoad().filter(n=>n.id!==id)); }

async function syncPendientes() {
    const pend = pendLoad();
    if (!pend.length) return;
    let ok = 0;
    for (const n of pend) {
        try {
            await fetch("/notes", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(n) });
            pendDel(n.id); ok++;
        } catch { break; }
    }
    if (ok > 0) toast("☁️ " + ok + " apunte(s) sincronizado(s)");
}

// ─── NOTAS cargar ────────────────────────────────────────
async function cargarNotas() {
    const lista = document.getElementById("listaNotas");
    const empty = document.getElementById("sinNotas");
    if (!lista) return;
    lista.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';
    if (empty) empty.style.display = "none";
    let notas = [];
    if (navigator.onLine) {
        try { const r = await fetch("/notes"); notas = await r.json(); notasGuardar(notas); }
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
              '<div class="note-item-title">'+esc(n.title)+(pend?' <span style="color:var(--warn);font-size:.7rem">⏳</span>':'')+'</div>'+
              '<div class="note-actions">'+
                '<button class="btn btn-ghost btn-sm" onclick="editarNota(\''+n.id+'\')">✏️</button>'+
                '<button class="btn btn-danger btn-sm" onclick="eliminarNota(\''+n.id+'\')">🗑</button>'+
              '</div>'+
            '</div>'+
            '<div class="note-item-text">'+esc(n.text)+'</div>'+
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
    const nota = { id: id || crypto.randomUUID(), title, text, tags };
    if (navigator.onLine) {
        try {
            const method = id ? "PUT" : "POST";
            const url    = id ? "/notes/"+id : "/notes";
            await fetch(url, { method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(nota) });
            pendDel(nota.id);
        } catch { if(!id) pendAdd(nota); }
    } else { if(!id) pendAdd(nota); toast("⚠️ Sin internet — se sincronizará al conectarte"); }
    notaSync(nota);
    cerrarFormNota();
    cargarNotas();
    toast(id ? "✅ Apunte actualizado" : "✅ Apunte guardado");
}
async function eliminarNota(id) {
    if (!confirm("¿Eliminar este apunte?")) return;
    if (navigator.onLine) { try { await fetch("/notes/"+id,{method:"DELETE"}); } catch {} }
    notaBorrar(id); pendDel(id);
    document.getElementById("ni-"+id)?.remove();
    const lista = document.getElementById("listaNotas");
    if (lista && !lista.children.length) { const e=document.getElementById("sinNotas"); if(e) e.style.display="flex"; }
    toast("🗑 Apunte eliminado");
}

// ─── ADMIN ───────────────────────────────────────────────
let _adminPw = "";

async function adminEntrar() {
    const pw = (document.getElementById("adminPw").value || "").trim();
    if (!pw) { toast("Ingresa la contraseña","err"); return; }
    try {
        const r = await fetch("/admin/check", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({password:pw}) });
        if (r.ok) {
            _adminPw = pw;
            document.getElementById("adminLock").style.display    = "none";
            document.getElementById("adminCont").style.display    = "block";
            cargarCfg(); cargarListaManuales();
        } else { toast("❌ Contraseña incorrecta","err"); }
    } catch { toast("❌ Sin conexión al servidor","err"); }
}

function adminSalir() {
    _adminPw = "";
    document.getElementById("adminLock").style.display = "flex";
    document.getElementById("adminCont").style.display = "none";
    document.getElementById("adminPw").value = "";
}

async function cargarCfg() {
    const el = document.getElementById("cfgInfo"); if(!el) return;
    try {
        const r = await fetch("/admin/config?password="+encodeURIComponent(_adminPw));
        const d = await r.json(); if(!r.ok) return;
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
        const r = await fetch("/admin/manuals?password="+encodeURIComponent(_adminPw));
        const d = await r.json();
        if (!r.ok) { div.innerHTML='<p style="color:var(--danger)">'+d.error+'</p>'; return; }
        div.innerHTML = d.map(m=>'<div class="manual-row"><span style="color:var(--text)">'+esc(m.manual)+'</span><span>'+m.pages+' págs.</span></div>').join("");
    } catch(e) { div.innerHTML='<p style="color:var(--danger)">Error: '+e.message+'</p>'; }
}
