/* SOLVI — Explorador documental de señales.
 *
 * No es un editor de cableado ni una simulación clínica. Presenta únicamente
 * rutas funcionales y referencias cuyas afirmaciones enlazan con evidencia
 * local trazable (manual, página física y extracto).
 */
(function (window) {
    "use strict";

    const CATALOG_URL = "/data/verified_signal_paths.json";
    const TRACEABILITY_URL = "/data/documentary_traceability.json";
    let state = { catalog: null, evidence: new Map(), selectedId: null, filter: "", loaded: false };

    function esc(value) {
        return String(value ?? "").replace(/[&<>'"]/g, char => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
        })[char]);
    }

    async function fetchJson(url) {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) throw new Error(`No se pudo cargar ${url} (${response.status}).`);
        return response.json();
    }

    function records() {
        return Array.isArray(state.catalog?.catalog) ? state.catalog.catalog : [];
    }

    async function load() {
        if (state.loaded) return;
        const [catalog, traceability] = await Promise.all([fetchJson(CATALOG_URL), fetchJson(TRACEABILITY_URL)]);
        if (!Array.isArray(catalog?.catalog) || !Array.isArray(traceability?.entries)) {
            throw new Error("El catálogo documental tiene un formato inválido.");
        }
        for (const entry of traceability.entries) state.evidence.set(entry.id, entry);
        for (const item of catalog.catalog) {
            if (item.status !== "verified_text") throw new Error("El visor rechazó una entrada sin evidencia textual verificada.");
        }
        state.catalog = catalog;
        state.loaded = true;
    }

    function setMessage(message, type = "info") {
        const target = document.getElementById("cvStatus");
        if (!target) return;
        target.textContent = message;
        target.className = `cv-status ${type}`;
    }

    function findRecord(id) {
        return records().find(item => item.id === id) || null;
    }

    function recordMatches(item, query) {
        if (!query) return true;
        const haystack = [item.title, item.summary, ...(item.tags || [])].join(" ").toLocaleLowerCase();
        return query.split(/\s+/).every(term => haystack.includes(term));
    }

    function renderCatalog() {
        const target = document.getElementById("cvCatalog");
        if (!target) return;
        const query = state.filter.trim().toLocaleLowerCase();
        const visible = records().filter(item => recordMatches(item, query));
        if (!visible.length) {
            target.innerHTML = '<p class="cv-empty">No hay una ruta o referencia verificada para esa búsqueda. SOLVI no infiere cableado ni códigos de error.</p>';
            return;
        }
        target.innerHTML = visible.map(item => {
            const selected = item.id === state.selectedId ? " selected" : "";
            const type = item.kind === "verified_functional_path" ? "RUTA DOCUMENTADA" : "REFERENCIA DOCUMENTAL";
            return `<button type="button" class="cv-record${selected}" data-cv-record="${esc(item.id)}">
                <span class="cv-record-type">${type}</span>
                <strong>${esc(item.title)}</strong>
                <span>${esc(item.summary)}</span>
                <small>✓ evidencia textual verificable</small>
            </button>`;
        }).join("");
    }

    function evidenceButton(citationId, label = "Ver evidencia") {
        if (!citationId || !state.evidence.has(citationId)) return '<span class="cv-no-evidence">Evidencia no disponible</span>';
        return `<button type="button" class="cv-evidence-btn" data-cv-evidence="${esc(citationId)}">📖 ${esc(label)}</button>`;
    }

    function renderSteps(item) {
        const steps = item.steps || [];
        if (!steps.length) return "";
        return `<section class="cv-section"><h3>Recorrido funcional documentado</h3>
            <p class="cv-help">Lee de izquierda a derecha. Cada flecha representa solo la relación descrita por la fuente enlazada.</p>
            <ol class="cv-signal-path">${steps.map((step, index) => `<li>
                <button type="button" class="cv-path-step" data-cv-evidence="${esc(step.citation_id)}">
                    <span class="cv-step-number">${index + 1}</span>
                    <strong>${esc(step.label)}</strong>
                    <small>${esc(step.role)}</small>
                    <span>${esc(step.statement)}</span>
                </button>${step.measurement_id ? `<button type="button" class="btn btn-ghost btn-sm" data-cv-measurement="${esc(step.measurement_id)}">Registrar medición documentada</button>` : ""}
            </li>`).join("")}</ol>
        </section>`;
    }

    function renderFailureEffects(item) {
        const effects = item.failure_effects || [];
        if (!effects.length) return "";
        return `<section class="cv-section cv-effect-section"><h3>Si la señal o componente falla</h3>
            ${effects.map(effect => `<article class="cv-effect-card">
                <strong>Condición: ${esc(effect.condition)}</strong>
                <p>${esc(effect.documented_effect)}</p>
                ${evidenceButton(effect.citation_id, "Fuente del efecto")}
            </article>`).join("")}
        </section>`;
    }

    function renderFacts(item) {
        const facts = item.facts || [];
        if (!facts.length) return "";
        return `<section class="cv-section"><h3>Etiquetas presentes en la fuente</h3>
            <p class="cv-help">Estas etiquetas se leen de la hoja original. No se convierten en una ruta ni en una relación de causa y efecto sin una arista documentada.</p>
            <div class="cv-fact-grid">${facts.map(fact => `<article class="cv-fact-card"><strong>${esc(fact.label)}</strong>${evidenceButton(fact.citation_id)}</article>`).join("")}</div>
        </section>`;
    }

    function renderChecks(item) {
        const checks = item.checks || [];
        if (!checks.length) return "";
        return `<section class="cv-section"><h3>Comprobación documentada</h3>
            ${checks.map(check => `<article class="cv-check-card"><strong>${esc(check.label)}</strong><p>${esc(check.statement)}</p>${evidenceButton(check.citation_id, "Abrir procedimiento")}</article>`).join("")}
        </section>`;
    }

    function renderSelected() {
        const target = document.getElementById("circuitCanvasContainer");
        const item = findRecord(state.selectedId);
        if (!target) return;
        if (!item) {
            target.innerHTML = '<div class="cv-empty"><h3>Selecciona una ruta documentada</h3><p>El catálogo se limita deliberadamente a afirmaciones que pueden abrirse en el manual original.</p></div>';
            return;
        }
        const isPath = item.kind === "verified_functional_path";
        target.innerHTML = `<article class="cv-detail" aria-live="polite">
            <div class="cv-detail-header">
                <span class="cv-record-type">${isPath ? "RUTA DOCUMENTADA" : "REFERENCIA DOCUMENTAL"}</span>
                <h2>${esc(item.title)}</h2><p>${esc(item.summary)}</p>
            </div>
            ${renderSteps(item)}
            ${renderFacts(item)}
            ${renderFailureEffects(item)}
            ${renderChecks(item)}
            <section class="cv-section cv-policy"><h3>Errores y límites de interpretación</h3><p>${esc(item.error_code_policy || "No hay código de error publicado.")}</p></section>
            <aside class="cv-safety">⚠️ ${esc(item.safety_notice || "Consulta el manual antes de intervenir.")}</aside>
        </article>`;
    }

    function selectRecord(id, message = "") {
        if (!findRecord(id)) return;
        state.selectedId = id;
        renderCatalog();
        renderSelected();
        setMessage(message || "Ruta cargada. Abre cada paso para revisar su evidencia.", "ok");
    }

    function openEvidence(id) {
        const evidence = state.evidence.get(id);
        const drawer = document.getElementById("cvInspectorDrawer");
        if (!drawer || !evidence) return;
        drawer.innerHTML = `<article class="cv-evidence-card" role="dialog" aria-label="Evidencia documental">
            <button type="button" class="cv-close" data-cv-close aria-label="Cerrar evidencia">×</button>
            <span class="cv-record-type">EVIDENCIA VERIFICADA</span>
            <h3>${esc(evidence.claim)}</h3>
            <p class="cv-citation">${esc(evidence.manual)} · página física ${esc(evidence.physical_page || evidence.page)}</p>
            <blockquote>${esc(evidence.extract)}</blockquote>
            <div class="cv-evidence-actions">
                <button type="button" class="btn btn-primary btn-sm" data-cv-open-pdf="${esc(id)}">Abrir página del manual</button>
                <button type="button" class="btn btn-ghost btn-sm" data-cv-close>Cerrar</button>
            </div>
        </article>`;
        drawer.hidden = false;
    }

    function closeEvidence() {
        const drawer = document.getElementById("cvInspectorDrawer");
        if (drawer) { drawer.hidden = true; drawer.innerHTML = ""; }
    }

    function openPdfForEvidence(id) {
        const evidence = state.evidence.get(id);
        if (!evidence || typeof window.verPDF !== "function") return;
        window.verPDF(evidence.manual, Number(evidence.physical_page || evidence.page), "");
    }

    function search(text) {
        state.filter = String(text || "");
        renderCatalog();
    }

    function openFromTrace(trace) {
        const terms = Array.isArray(trace) ? trace : [
            ...(trace?.resolved_nodes || []), ...(trace?.pcbs || []), ...(trace?.test_points || []),
            ...(trace?.manual_references || []), trace?.hub_node || ""
        ];
        const raw = terms.join(" ").toLocaleLowerCase();
        const match = records().map(item => ({ item, score: (item.tags || []).filter(tag => raw.includes(String(tag).toLocaleLowerCase())).length }))
            .sort((a, b) => b.score - a.score || a.item.id.localeCompare(b.item.id))[0];
        if (match?.score) selectRecord(match.item.id, "Se abrió la referencia documental relacionada; no se asumió una ruta física a partir de la traza.");
        else setMessage("La traza no tiene una ruta documental verificada en el catálogo actual. Usa las referencias del resultado o busca en manuales.", "warn");
    }

    async function init() {
        try {
            await load();
            renderCatalog();
            if (!state.selectedId && records().length) selectRecord(records()[0].id);
        } catch (error) {
            const target = document.getElementById("circuitCanvasContainer");
            if (target) target.innerHTML = `<div class="cv-empty"><h3>No se pudo cargar el catálogo documental</h3><p>${esc(error.message)}</p><p>Reintenta con conexión o después de abrir la aplicación una vez para disponer del índice offline.</p></div>`;
            setMessage("Catálogo no disponible.", "err");
        }
    }

    function onActivate() { init(); }
    function onDeactivate() { closeEvidence(); }

    document.addEventListener("click", event => {
        const record = event.target.closest("[data-cv-record]");
        const evidence = event.target.closest("[data-cv-evidence]");
        const openPdf = event.target.closest("[data-cv-open-pdf]");
        const measurement = event.target.closest("[data-cv-measurement]");
        if (record) selectRecord(record.dataset.cvRecord);
        else if (evidence) openEvidence(evidence.dataset.cvEvidence);
        else if (openPdf) openPdfForEvidence(openPdf.dataset.cvOpenPdf);
        else if (measurement) {
            if (typeof window.irA === "function") window.irA("Multimeter");
            window.setTimeout(() => window.Multimeter && window.Multimeter.seleccionarPuntoDePrueba(measurement.dataset.cvMeasurement), 0);
        }
        else if (event.target.closest("[data-cv-close]")) closeEvidence();
    });

    window.CircuitVisualizer = {
        init, onActivate, onDeactivate, selectRecord, buscarEnEsquema: search,
        clearSearch: () => search(""), openEvidence, closeEvidence,
        openFromTrace, loadAndHighlightFromTrace: openFromTrace
    };
})(window);
