/* SOLVI — registro de lectura manual con evidencia documental.
 * No conecta hardware, no inyecta señales y no emite OK/FALLA sin umbral publicado.
 */
(function (window, document) {
    "use strict";

    const CATALOG_URL = "/data/verified_measurement_catalog.json";
    const TRACEABILITY_URL = "/data/documentary_traceability.json";
    const MAX_HISTORY_RECORDS = 20;
    const state = { catalog: [], evidence: new Map(), selectedId: null, history: [], loaded: false };

    function esc(value) {
        return String(value == null ? "" : value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
    function getScreen() { return document.getElementById("screenMultimeter"); }
    function selected() { return state.catalog.find(item => item.id === state.selectedId) || null; }
    function format(value) { return Number(value).toLocaleString("es-PE", { maximumFractionDigits: 4 }); }

    async function fetchJson(url) {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 12000);
        try {
            const response = await fetch(url, { signal: controller.signal, cache: "no-cache" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } finally { window.clearTimeout(timer); }
    }

    function shell() {
        const screen = getScreen();
        if (!screen) return;
        screen.innerHTML = `<section class="cv-header" aria-labelledby="dmmTitle">
          <div class="cv-title-group"><h2 id="dmmTitle">📟 Registro de medición documentada</h2>
          <span class="cv-subsystem-badge">LECTURA MANUAL · EVIDENCIA PRIMERO</span>
          <p style="font-size:.78rem;color:var(--muted);margin-top:4px;line-height:1.45">Registra una lectura tomada por personal autorizado y compárala con una referencia documental. SOLVI no se conecta a instrumentos, no inyecta tensión/corriente y no da veredictos OK/FALLA sin un rango publicado.</p></div>
        </section>
        <div id="dmmStatus" role="status" aria-live="polite" style="margin:10px 0;font-size:.78rem;color:var(--muted)">Cargando catálogo verificable…</div>
        <section id="dmmWorkspace" hidden>
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:12px">
            <label for="dmmMeasurementSelect" style="font-family:var(--mono);font-size:.72rem;color:var(--accent);font-weight:700;text-transform:uppercase">Medición documentada disponible</label>
            <select id="dmmMeasurementSelect" aria-describedby="dmmProcedure" style="margin-top:8px;padding-left:10px"></select>
            <div id="dmmProcedure" style="font-size:.78rem;color:var(--muted);line-height:1.5;margin-top:10px"></div>
          </div>
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:12px">
            <label for="dmmReadingInput" style="font-family:var(--mono);font-size:.72rem;color:var(--accent);font-weight:700;text-transform:uppercase">Lectura observada (V DC)</label>
            <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
              <input id="dmmReadingInput" inputmode="decimal" autocomplete="off" placeholder="Ej.: -320.0" aria-describedby="dmmInputHelp" style="max-width:210px;padding-left:10px;font-family:var(--mono)">
              <button type="button" class="btn btn-primary" data-dmm-action="evaluate">Registrar y comparar</button>
            </div>
            <p id="dmmInputHelp" style="font-size:.72rem;color:var(--muted);margin:8px 0 0">Acepta coma o punto decimal. La lectura no modifica ningún equipo.</p>
          </div>
          <div id="dmmResultBox" aria-live="polite" style="display:none;margin-bottom:12px"></div>
          <div id="dmmEvidencePanel" hidden></div>
          <section style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><h3 style="font-size:.8rem;color:var(--accent);font-family:var(--mono)">HISTORIAL DE ESTA SESIÓN</h3><button type="button" class="btn btn-ghost btn-sm" data-dmm-action="clear-history">Limpiar</button></div>
            <div id="dmmHistoryList"><p style="font-size:.75rem;color:var(--muted)">No hay lecturas registradas.</p></div>
          </section>
        </section>`;
    }

    function renderSelection() {
        const item = selected(); const select = document.getElementById("dmmMeasurementSelect");
        if (!item || !select) return;
        select.innerHTML = state.catalog.map(record => `<option value="${esc(record.id)}">${esc(record.title)} · ${esc(record.unit)}</option>`).join("");
        select.value = item.id;
        document.getElementById("dmmProcedure").innerHTML = `<strong>Referencia documentada: ${format(item.documented_reference_value)} ${esc(item.unit)}</strong><br>${esc(item.measurement_location)}<br><span style="color:var(--warn)">${esc(item.evaluation_notice)}</span><br><span style="font-size:.72rem">${esc(item.procedure_context)}</span>`;
    }
    function renderHistory() {
        const target = document.getElementById("dmmHistoryList"); if (!target) return;
        target.innerHTML = state.history.length ? state.history.map(row => `<div style="border-top:1px solid var(--border);padding:8px 0;font-size:.75rem"><b>${esc(row.title)}</b> · ${format(row.measured_value)} ${esc(row.unit)} <span style="color:var(--muted)">Δ ${format(row.delta_from_reference)} ${esc(row.unit)}</span></div>`).join("") : '<p style="font-size:.75rem;color:var(--muted)">No hay lecturas registradas.</p>';
    }
    function renderEvidence(id) {
        const evidence = state.evidence.get(id); const panel = document.getElementById("dmmEvidencePanel");
        if (!evidence || !panel) return;
        panel.hidden = false;
        panel.innerHTML = `<article class="cv-evidence-card" role="region" aria-label="Evidencia documental"><button type="button" class="cv-close" data-dmm-action="close-evidence" aria-label="Cerrar evidencia">×</button><span class="cv-record-type">EVIDENCIA VERIFICADA</span><h3>${esc(evidence.claim)}</h3><p>${esc(evidence.manual)} · pág. ${esc(evidence.page)}</p><blockquote>${esc(evidence.extract)}</blockquote><div class="cv-evidence-actions"><button type="button" class="btn btn-primary btn-sm" data-dmm-pdf="${esc(id)}">Abrir página del manual</button><button type="button" class="btn btn-ghost btn-sm" data-dmm-action="close-evidence">Cerrar</button></div></article>`;
    }
    function resultLocally(item, measured) {
        return { test_point_id:item.id, test_point_name:item.title, unit:item.unit, measured_value:measured, documented_reference_value:Number(item.documented_reference_value), delta_from_reference:measured-Number(item.documented_reference_value), status:"REFERENCE_ONLY", status_badge:"SIN UMBRAL", status_label:"REGISTRADA · SIN UMBRAL PUBLICADO", is_pass_fail:false, recommendation:item.evaluation_notice, measurement_location:item.measurement_location, procedure_context:item.procedure_context, route_id:item.route_id, citations:item.citations, safety_notice:item.safety_notice };
    }
    async function evaluate() {
        const item = selected(); const input = document.getElementById("dmmReadingInput"); const result = document.getElementById("dmmResultBox");
        if (!item || !input || !result) return;
        const value = Number(String(input.value).trim().replace(",", "."));
        if (!Number.isFinite(value)) { result.style.display="block"; result.innerHTML='<div class="alert alert-error">Ingrese una lectura numérica finita.</div>'; return; }
        let evaluation = resultLocally(item, value); let source = "registro local verificable";
        try {
            const response = await fetch("/multimeter/evaluate", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({test_point_id:item.id, measured_value:value, unit:item.unit})});
            const data = await response.json(); if (response.ok && data.ok) { evaluation=data.evaluation; source="servidor SOLVI"; }
        } catch (_) { /* La misma política reference_only funciona con el catálogo precacheado. */ }
        state.history.unshift({title:item.title, ...evaluation}); state.history.length=MAX_HISTORY_RECORDS;
        result.style.display="block";
        result.innerHTML = `<article style="background:var(--surface);border:1px solid var(--warn);border-radius:10px;padding:14px"><div style="font-family:var(--mono);color:var(--warn);font-weight:700">${esc(evaluation.status_label)}</div><h3 style="margin:8px 0">${format(evaluation.measured_value)} ${esc(evaluation.unit)}</h3><p>Referencia documentada: <b>${format(evaluation.documented_reference_value)} ${esc(evaluation.unit)}</b> · Δ: <b>${format(evaluation.delta_from_reference)} ${esc(evaluation.unit)}</b></p><p style="color:var(--muted);font-size:.78rem">${esc(evaluation.recommendation)}</p><p style="font-size:.72rem;color:var(--muted)">Origen: ${esc(source)}. ${esc(evaluation.safety_notice)}</p><div style="display:flex;gap:7px;flex-wrap:wrap">${(evaluation.citations||[]).map(id=>`<button type="button" class="btn btn-ghost btn-sm" data-dmm-evidence="${esc(id)}">Ver evidencia</button>`).join("")}<button type="button" class="btn btn-primary btn-sm" data-dmm-action="route">Ver ruta documentada</button></div></article>`;
        renderHistory();
    }
    function openRoute() {
        const item = selected(); if (!item) return;
        if (typeof window.irA === "function") window.irA("Circuits");
        window.setTimeout(() => window.CircuitVisualizer && window.CircuitVisualizer.openFromTrace(["ion chamber"]), 0);
    }
    async function init() {
        shell();
        try {
            const [catalogPayload, evidencePayload] = await Promise.all([fetchJson(CATALOG_URL), fetchJson(TRACEABILITY_URL)]);
            const catalog = catalogPayload && catalogPayload.catalog;
            if (!Array.isArray(catalog) || !catalog.length) throw new Error("Catálogo vacío");
            for (const citation of evidencePayload.entries || []) state.evidence.set(citation.id, citation);
            for (const item of catalog) if (!item.citations || item.citations.some(id => !state.evidence.has(id))) throw new Error("Cita documental ausente");
            state.catalog=catalog; state.selectedId=state.selectedId || catalog[0].id; state.loaded=true;
            document.getElementById("dmmStatus").textContent="Catálogo verificable cargado. Solo se muestran mediciones con evidencia.";
            document.getElementById("dmmWorkspace").hidden=false; renderSelection();
        } catch (_) { document.getElementById("dmmStatus").textContent="No se pudo cargar el catálogo verificable. No se publica ninguna medición."; }
    }
    document.addEventListener("change", event => { if (event.target && event.target.id === "dmmMeasurementSelect") { state.selectedId=event.target.value; renderSelection(); } });
    document.addEventListener("click", event => {
        const evidence = event.target.closest("[data-dmm-evidence]"); const pdf = event.target.closest("[data-dmm-pdf]"); const action=event.target.closest("[data-dmm-action]");
        if (evidence) renderEvidence(evidence.dataset.dmmEvidence);
        else if (pdf) { const item=state.evidence.get(pdf.dataset.dmmPdf); if (item && typeof window.verPDF === "function") window.verPDF(item.manual, item.page); }
        else if (action && action.dataset.dmmAction === "evaluate") evaluate();
        else if (action && action.dataset.dmmAction === "route") openRoute();
        else if (action && action.dataset.dmmAction === "clear-history") { state.history=[]; renderHistory(); }
        else if (action && action.dataset.dmmAction === "close-evidence") { const p=document.getElementById("dmmEvidencePanel"); if(p) p.hidden=true; }
    });
    window.Multimeter = { init, onActivate:init, onDeactivate:()=>{}, seleccionarPuntoDePrueba(id) { if (!state.loaded) { state.selectedId=id; return; } const found=state.catalog.find(item=>item.id===id); if (found) { state.selectedId=found.id; renderSelection(); } }, resolveMeasurement(id) { return state.catalog.find(item => item.id===id) || null; } };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true}); else init();
})(window, document);
