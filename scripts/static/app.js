console.log("✅ app.js v3");

/* ══════════════════════════════════════════
   RED
══════════════════════════════════════════ */
function actualizarRed() {
    const el  = document.getElementById("estadoRed");
    const txt = document.getElementById("estadoTxt");
    if (navigator.onLine) { el.className = "online";  txt.textContent = "Conectado"; }
    else                  { el.className = "offline"; txt.textContent = "Sin conexión"; }
}
window.addEventListener("online",  actualizarRed);
window.addEventListener("offline", actualizarRed);
actualizarRed();

/* ══════════════════════════════════════════
   CACHÉ OFFLINE
══════════════════════════════════════════ */
let manualsData = null;

async function cargarManuales() {
    if (manualsData) return manualsData;
    const r = await fetch("/data/all_manuals.json");
    if (!r.ok) throw new Error("No se pudo cargar all_manuals.json");
    manualsData = await r.json();
    return manualsData;
}

/* ══════════════════════════════════════════
   HELPERS
══════════════════════════════════════════ */
function esc(s) {
    return String(s)
        .replace(/&/g,"&amp;").replace(/</g,"&lt;")
        .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"); }

function highlight(text, kw) {
    if (!kw) return esc(text);
    return esc(text).replace(new RegExp(escRe(kw),"gi"), m => `<mark>${m}</mark>`);
}

function toast(msg, type="ok") {
    const t = document.createElement("div");
    t.className = `toast ${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

/* ══════════════════════════════════════════
   UI STATES (BÚSQUEDA)
══════════════════════════════════════════ */
function showState(state) {
    const ids = ["welcomeState","spinnerState","emptyState","resultsList","metaBar"];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
    });
    if (state === "welcome")  { document.getElementById("welcomeState").style.display  = "flex"; }
    if (state === "loading")  { document.getElementById("spinnerState").style.display  = "block"; }
    if (state === "empty")    { document.getElementById("emptyState").style.display    = "flex"; }
    if (state === "results")  {
        document.getElementById("resultsList").style.display = "block";
        document.getElementById("metaBar").style.display     = "flex";
    }
}

/* ══════════════════════════════════════════
   RENDER RESULTADOS
══════════════════════════════════════════ */
function renderResultados(results, keyword, mode) {
    const list = document.getElementById("resultsList");
    list.innerHTML = "";

    if (!results || results.length === 0) { showState("empty"); return; }

    document.getElementById("countNum").textContent = results.length;
    document.getElementById("modeTag").textContent  = mode === "online" ? "ONLINE" : "OFFLINE";
    showState("results");

    results.forEach((r, i) => {
        const isNote  = r.type === "note";
        const card    = document.createElement("div");
        card.className = `result-card${isNote ? " note-card" : ""}`;
        card.style.animationDelay = `${i * 35}ms`;

        const badgeClass = isNote ? "note-badge" : "manual-badge";
        const manualLabel = isNote ? "📝 Apunte" : esc(r.manual);
        const pageLabel   = isNote ? esc(r.page) : `Página ${r.page}`;

        const tagsHtml = isNote && r.tags && r.tags.length
            ? `<div class="card-tags">${r.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>`
            : "";

        card.innerHTML = `
            <div class="card-header">
                <span class="card-manual ${badgeClass}">${manualLabel}</span>
                <span class="card-page">📄 ${pageLabel}</span>
            </div>
            <div class="card-ctx">${highlight(r.context, keyword)}</div>
            <div class="card-action">${esc(r.action)}</div>
            ${tagsHtml}
        `;
        list.appendChild(card);
    });
}

/* ══════════════════════════════════════════
   BÚSQUEDA OFFLINE
══════════════════════════════════════════ */
async function buscarOffline(kw, mf) {
    const data = await cargarManuales();
    const results = [];
    const kwl = kw.toLowerCase();
    const mfl = mf.toLowerCase();

    for (const page of data) {
        if (mfl && mfl !== "apuntes" && page.manual.toLowerCase() !== mfl) continue;
        const tl = page.text.toLowerCase();
        if (!tl.includes(kwl)) continue;
        const pos = tl.indexOf(kwl);
        const ctx = page.text.substring(Math.max(0,pos-80), Math.min(page.text.length,pos+120))
                              .replace(/\n+/g," ").trim();
        results.push({ type:"manual", manual:page.manual, page:page.page,
                       context:ctx, action:"Revisar sección completa del manual" });
    }

    // Apuntes offline: intentar desde localStorage como fallback
    if (!mfl || mfl === "apuntes") {
        const localNotes = JSON.parse(localStorage.getItem("interlocks_notes") || "[]");
        for (const note of localNotes) {
            const blob = (note.title+" "+note.text+" "+(note.tags||[]).join(" ")).toLowerCase();
            if (blob.includes(kwl)) {
                results.push({ type:"note", id:note.id, manual:"apuntes",
                               page:note.title, context:note.text.substring(0,220),
                               action:"Apunte personal", tags:note.tags||[] });
            }
        }
    }

    return results;
}

/* ══════════════════════════════════════════
   BÚSQUEDA ONLINE
══════════════════════════════════════════ */
async function buscarOnline(kw, mf) {
    let url = `/search?q=${encodeURIComponent(kw)}`;
    if (mf) url += `&manual=${encodeURIComponent(mf)}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()).results || [];
}

/* ══════════════════════════════════════════
   CONTROLADOR PRINCIPAL BÚSQUEDA
══════════════════════════════════════════ */
async function iniciarBusqueda() {
    const kw = document.getElementById("q").value.trim();
    const mf = document.getElementById("manual").value.trim();
    if (!kw) {
        const inp = document.getElementById("q");
        inp.style.borderColor = "var(--danger)";
        setTimeout(() => inp.style.borderColor = "", 1200);
        return;
    }

    showState("loading");
    const btn = document.getElementById("btnBuscar");
    btn.classList.add("loading");
    btn.textContent = "Buscando...";

    try {
        let results, mode;
        if (navigator.onLine) {
            try   { results = await buscarOnline(kw, mf); mode = "online"; }
            catch { results = await buscarOffline(kw, mf); mode = "offline"; }
        } else {
            results = await buscarOffline(kw, mf); mode = "offline";
        }
        renderResultados(results, kw, mode);
    } catch(e) {
        console.error(e);
        document.getElementById("resultsList").innerHTML =
            `<div class="result-card"><span style="color:var(--danger)">❌ ${esc(e.message)}</span></div>`;
        showState("results");
    } finally {
        btn.classList.remove("loading");
        btn.textContent = "Buscar";
    }
}

/* ══════════════════════════════════════════
   EVENTOS BÚSQUEDA
══════════════════════════════════════════ */
window.addEventListener("load", () => {
    const q = document.getElementById("q");
    const m = document.getElementById("manual");
    if (q) { q.disabled = false; q.readOnly = false; setTimeout(() => q.focus(), 300); }
    if (m) m.disabled = false;
    showState("welcome");

    document.getElementById("btnBuscar")?.addEventListener("click", iniciarBusqueda);
    [q, m].forEach(el => {
        el?.addEventListener("keydown", e => { if(e.key==="Enter"){e.preventDefault();iniciarBusqueda();} });
        el?.addEventListener("keyup",   e => { if(e.key==="Enter"){e.preventDefault();iniciarBusqueda();} });
    });
});

/* ══════════════════════════════════════════
   APUNTES — helpers localStorage (offline)
══════════════════════════════════════════ */
function localNotesLoad() {
    return JSON.parse(localStorage.getItem("interlocks_notes") || "[]");
}
function localNotesSave(notes) {
    localStorage.setItem("interlocks_notes", JSON.stringify(notes));
}
function localNoteSync(note) {
    const notes = localNotesLoad().filter(n => n.id !== note.id);
    notes.push(note);
    localNotesSave(notes);
}
function localNoteDelete(id) {
    localNotesSave(localNotesLoad().filter(n => n.id !== id));
}

/* ══════════════════════════════════════════
   APUNTES — cargar y renderizar
══════════════════════════════════════════ */
async function loadNotes() {
    const list  = document.getElementById("notesList");
    const empty = document.getElementById("notesEmpty");
    list.innerHTML = `<div class="spinner-wrap"><div class="spinner"></div></div>`;
    empty.style.display = "none";

    let notes = [];
    if (navigator.onLine) {
        try {
            const r = await fetch("/notes");
            notes = await r.json();
            // Sincronizar al localStorage para offline
            localNotesSave(notes);
        } catch { notes = localNotesLoad(); }
    } else {
        notes = localNotesLoad();
    }

    renderNotes(notes);
}

function renderNotes(notes) {
    const list  = document.getElementById("notesList");
    const empty = document.getElementById("notesEmpty");
    list.innerHTML = "";

    if (!notes || notes.length === 0) {
        empty.style.display = "flex";
        return;
    }
    empty.style.display = "none";

    notes.forEach(note => {
        const div = document.createElement("div");
        div.className = "note-item";
        div.id = `note-${note.id}`;
        const tagsHtml = (note.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join("");
        div.innerHTML = `
            <div class="note-item-header">
                <div class="note-item-title">${esc(note.title)}</div>
                <div class="note-actions">
                    <button class="btn btn-ghost btn-sm" onclick="editNote('${note.id}')">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteNote('${note.id}')">🗑</button>
                </div>
            </div>
            <div class="note-item-text">${esc(note.text)}</div>
            ${tagsHtml ? `<div class="card-tags">${tagsHtml}</div>` : ""}
        `;
        list.appendChild(div);
    });
}

/* ══════════════════════════════════════════
   APUNTES — formulario
══════════════════════════════════════════ */
function toggleNoteForm() {
    const form = document.getElementById("noteForm");
    const visible = form.style.display !== "none";
    if (visible) { cancelNoteForm(); } else {
        form.style.display = "block";
        document.getElementById("noteFormTitle").textContent = "✏️ NUEVO APUNTE";
        document.getElementById("editingId").value = "";
        document.getElementById("noteTitle").value = "";
        document.getElementById("noteText").value  = "";
        document.getElementById("noteTags").value  = "";
        document.getElementById("noteTitle").focus();
    }
}

function cancelNoteForm() {
    document.getElementById("noteForm").style.display = "none";
}

function editNote(id) {
    const notes = localNotesLoad();
    const note  = notes.find(n => n.id === id);
    if (!note) return;
    document.getElementById("noteForm").style.display = "block";
    document.getElementById("noteFormTitle").textContent = "✏️ EDITAR APUNTE";
    document.getElementById("editingId").value = id;
    document.getElementById("noteTitle").value = note.title;
    document.getElementById("noteText").value  = note.text;
    document.getElementById("noteTags").value  = (note.tags||[]).join(", ");
    document.getElementById("noteTitle").focus();
    document.getElementById("noteForm").scrollIntoView({ behavior:"smooth" });
}

async function saveNote() {
    const id    = document.getElementById("editingId").value.trim();
    const title = document.getElementById("noteTitle").value.trim();
    const text  = document.getElementById("noteText").value.trim();
    const tags  = document.getElementById("noteTags").value.split(",").map(t=>t.trim()).filter(Boolean);

    if (!title) { toast("El título es obligatorio","err"); return; }

    const body = JSON.stringify({ title, text, tags });

    try {
        let note;
        if (navigator.onLine) {
            const method = id ? "PUT" : "POST";
            const url    = id ? `/notes/${id}` : "/notes";
            const r = await fetch(url, { method, headers:{"Content-Type":"application/json"}, body });
            note = await r.json();
            if (id) note.id = id;
        } else {
            // Guardar solo en localStorage cuando offline
            note = { id: id || crypto.randomUUID(), title, text, tags };
            toast("⚠️ Guardado localmente (sin internet). Se sincronizará al conectarte.","ok");
        }
        localNoteSync(note);
        cancelNoteForm();
        loadNotes();
        toast(id ? "✅ Apunte actualizado" : "✅ Apunte guardado");
    } catch(e) {
        console.error(e);
        toast("❌ Error al guardar: " + e.message, "err");
    }
}

async function deleteNote(id) {
    if (!confirm("¿Eliminar este apunte?")) return;
    try {
        if (navigator.onLine) await fetch(`/notes/${id}`, { method:"DELETE" });
        localNoteDelete(id);
        document.getElementById(`note-${id}`)?.remove();
        const list = document.getElementById("notesList");
        if (!list.children.length) document.getElementById("notesEmpty").style.display = "flex";
        toast("🗑 Apunte eliminado");
    } catch(e) { toast("❌ Error al eliminar","err"); }
}

/* ══════════════════════════════════════════
   ADMIN — login
══════════════════════════════════════════ */
let adminPassword = "";

function adminLogin() {
    const pw = document.getElementById("adminPass").value.trim();
    if (!pw) { toast("Ingresa la contraseña","err"); return; }
    adminPassword = pw;
    // Verificar con el servidor
    fetch(`/admin/manuals?password=${encodeURIComponent(pw)}`)
        .then(r => {
            if (r.ok) {
                document.getElementById("adminLock").style.display    = "none";
                document.getElementById("adminContent").style.display = "block";
                loadManualList();
            } else {
                toast("❌ Contraseña incorrecta","err");
                adminPassword = "";
            }
        })
        .catch(() => toast("❌ Sin conexión — no se puede verificar","err"));
}

function adminLogout() {
    adminPassword = "";
    document.getElementById("adminLock").style.display    = "flex";
    document.getElementById("adminContent").style.display = "none";
    document.getElementById("adminPass").value = "";
}

/* ══════════════════════════════════════════
   ADMIN — upload PDF
══════════════════════════════════════════ */
let selectedFile = null;

function onFileSelected(input) {
    selectedFile = input.files[0] || null;
    document.getElementById("uploadLabel").textContent =
        selectedFile ? `📄 ${selectedFile.name}` : "Toca aquí para seleccionar un PDF";
}

async function uploadPDF() {
    if (!selectedFile) { toast("Selecciona un PDF primero","err"); return; }
    const name = document.getElementById("uploadName").value.trim();
    const status = document.getElementById("uploadStatus");

    const fd = new FormData();
    fd.append("password", adminPassword);
    fd.append("pdf", selectedFile);
    if (name) fd.append("manual_name", name);

    status.textContent = "⏳ Subiendo y procesando...";
    status.style.color = "var(--accent)";

    try {
        const r    = await fetch("/admin/upload", { method:"POST", body:fd });
        const data = await r.json();
        if (r.ok) {
            status.textContent = `✅ ${data.manual}: ${data.pages} páginas agregadas (total: ${data.total_pages})`;
            status.style.color = "var(--green)";
            selectedFile = null;
            document.getElementById("fileInput").value = "";
            document.getElementById("uploadLabel").textContent = "Toca aquí para seleccionar un PDF";
            document.getElementById("uploadName").value = "";
            loadManualList();
            // Recargar manuales offline
            manualsData = null;
            toast(`✅ Manual "${data.manual}" agregado`);
        } else {
            status.textContent = `❌ ${data.error}`;
            status.style.color = "var(--danger)";
        }
    } catch(e) {
        status.textContent = `❌ Error: ${e.message}`;
        status.style.color = "var(--danger)";
    }
}

async function loadManualList() {
    const div = document.getElementById("manualList");
    div.innerHTML = `<div class="spinner-wrap" style="padding:20px 0"><div class="spinner"></div></div>`;
    try {
        const r    = await fetch(`/admin/manuals?password=${encodeURIComponent(adminPassword)}`);
        const data = await r.json();
        if (!r.ok) { div.innerHTML = `<p style="color:var(--danger)">${data.error}</p>`; return; }
        div.innerHTML = data.map(m => `
            <div class="manual-row">
                <span style="color:var(--text)">${esc(m.manual)}</span>
                <span>${m.pages} págs.</span>
            </div>`).join("");
    } catch(e) {
        div.innerHTML = `<p style="color:var(--danger)">Error: ${e.message}</p>`;
    }
}
