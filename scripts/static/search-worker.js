"use strict";

const STOP_WORDS = new Set([
    "a", "al", "and", "are", "as", "at", "be", "by", "con", "de", "del", "el",
    "en", "es", "for", "from", "in", "is", "la", "las", "los", "of", "on", "or",
    "para", "por", "que", "se", "the", "to", "un", "una", "y"
]);
const ACTION_WORDS = new Set([
    "adjust", "calibrate", "check", "connect", "correct", "disconnect", "ensure",
    "examine", "inspect", "install", "measure", "remove", "replace", "reset",
    "restart", "restore", "set", "verify", "ajustar", "calibrar", "comprobar",
    "corregir", "desconectar", "examinar", "inspeccionar", "reemplazar", "reiniciar",
    "restablecer", "verificar"
]);

let catalog = null;
const loadedManuals = new Set();
const documents = [];
const postings = new Map();
const manuals = new Map();

function normalize(value) {
    return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function tokenize(value) {
    return normalize(value).match(/[a-z0-9]+/g) || [];
}

function queryTokens(value) {
    return [...new Set(tokenize(value).filter(token =>
        !STOP_WORDS.has(token) && (token.length >= 3 || /^\d+$/.test(token))
    ))];
}

async function ensureCatalog() {
    if (catalog) return catalog;
    const response = await fetch("/data/search/catalog.json");
    if (!response.ok) throw new Error("No se pudo cargar el catálogo offline");
    catalog = await response.json();
    return catalog;
}

async function loadManual(entry) {
    if (loadedManuals.has(entry.name)) return;
    const response = await fetch(entry.file);
    if (!response.ok) throw new Error("No se pudo cargar el índice de " + entry.name);
    const payload = await response.json();
    const manualIds = manuals.get(entry.name) || [];
    for (const row of payload.documents || []) {
        const text = String(row[1] || "");
        const tokenSet = new Set(tokenize(text));
        const id = documents.length;
        documents.push({ id, manual: entry.name, page: Number(row[0]), text, normalized: normalize(text), tokenSet });
        manualIds.push(id);
        for (const token of tokenSet) {
            if (token.length < 2) continue;
            if (!postings.has(token)) postings.set(token, []);
            postings.get(token).push(id);
        }
    }
    manuals.set(entry.name, manualIds);
    loadedManuals.add(entry.name);
}

async function ensureManuals(manualFilter) {
    const data = await ensureCatalog();
    const entries = manualFilter
        ? data.manuals.filter(item => item.name === manualFilter)
        : data.manuals;
    await Promise.all(entries.map(loadManual));
}

function candidateIds(query, manualFilter) {
    const terms = queryTokens(query);
    let ids = terms.length && postings.has(terms[0]) ? [...postings.get(terms[0])]
        : documents.map(document => document.id);
    if (manualFilter) {
        const allowed = new Set(manuals.get(manualFilter) || []);
        ids = ids.filter(id => allowed.has(id));
    }
    return ids;
}

function queryMatchInfo(text, query) {
    const normalizedQuery = normalize(query).trim();
    const rawPosition = text.indexOf(normalizedQuery);
    if (rawPosition >= 0) {
        return {matched:true, position:rawPosition, occurrences:text.split(normalizedQuery).length - 1};
    }
    const parts = tokenize(query);
    if (!parts.length) return {matched:false, position:-1, occurrences:0};
    const escaped = parts.map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp("\\b" + escaped.join("[\\W_]+") + "\\b", "g");
    const matches = [...text.matchAll(pattern)];
    return {matched:Boolean(matches.length), position:matches.length ? matches[0].index : -1, occurrences:matches.length};
}

function makeContext(text, query, before = 180, after = 380) {
    const normalizedText = normalize(text);
    const normalizedQuery = normalize(query);
    let position = normalizedText.indexOf(normalizedQuery);
    if (position < 0) {
        const positions = queryTokens(query).map(token => normalizedText.indexOf(token)).filter(pos => pos >= 0);
        position = positions.length ? Math.min(...positions) : 0;
    }
    const start = Math.max(0, position - before);
    const end = Math.min(text.length, position + Math.max(query.length, 1) + after);
    let context = text.substring(start, end).replace(/\s+/g, " ").trim();
    if (start) context = "... " + context;
    if (end < text.length) context += " ...";
    return context;
}

function searchNotes(notes, query) {
    const normalizedQuery = normalize(query);
    return (Array.isArray(notes) ? notes : []).filter(note => {
        const blob = `${note.title || ""} ${note.text || ""} ${(note.tags || []).join(" ")}`;
        return normalize(blob).includes(normalizedQuery);
    }).map(note => ({
        type: "note",
        id: note.id,
        manual: "apuntes",
        page: note.title || "Sin título",
        context: String(note.text || "").substring(0, 300),
        tags: Array.isArray(note.tags) ? note.tags : []
    }));
}

async function searchOffline(payload) {
    const query = String(payload.query || "").trim();
    const manualFilter = String(payload.manual || "").trim().toLowerCase();
    const offset = Math.max(0, Number(payload.offset) || 0);
    const limit = Math.min(50, Math.max(1, Number(payload.limit) || 25));
    let manualResults = [];

    if (manualFilter !== "apuntes") {
        await ensureManuals(manualFilter);
        manualResults = candidateIds(query, manualFilter).map(id => {
            const document = documents[id];
            return {document, match:queryMatchInfo(document.normalized, query)};
        }).filter(item => item.match.matched).map(item => ({
            document:item.document,
            score:item.match.occurrences * 10 + Math.max(0, 5 - item.match.position / 1000)
        })).sort((a, b) => b.score - a.score || a.document.manual.localeCompare(b.document.manual) || a.document.page - b.document.page)
          .map(item => ({
              type: "manual",
              manual: item.document.manual,
              page: item.document.page,
              context: makeContext(item.document.text, query)
          }));
    }

    const noteResults = (!manualFilter || manualFilter === "apuntes") ? searchNotes(payload.notes, query) : [];
    const combined = manualFilter === "apuntes" ? noteResults : manualResults.concat(noteResults);
    return {
        results: combined.slice(offset, offset + limit),
        total: combined.length,
        offset,
        limit,
        has_more: offset + limit < combined.length
    };
}

function bestLine(text, signalTokens) {
    const lines = text.split(/\r?\n/).map(line => line.replace(/\s+/g, " ").trim())
        .filter(line => line.length >= 5 && line.length <= 180);
    if (!lines.length) return "Evidencia relacionada";
    let best = lines[0];
    let bestScore = -1;
    for (const line of lines) {
        const lineTokens = new Set(tokenize(line));
        const score = [...signalTokens].filter(token => lineTokens.has(token)).length;
        if (score > bestScore || (score === bestScore && line.length < best.length)) {
            best = line;
            bestScore = score;
        }
    }
    return best.substring(0, 140);
}

function codeNearLabel(text, field, valueTokens) {
    const codes = [...valueTokens].filter(token => /^\d+$/.test(token));
    if (!codes.length || !["interlock", "error"].includes(field)) return false;
    const labels = field === "interlock" ? "(?:interlock|inhibit)" : "(?:error|fault)";
    return codes.some(code => {
        const escapedCode = code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const codePattern = `(?:i|e)?\\s*${escapedCode}`;
        return new RegExp(`\\b${labels}\\b[\\W_]{0,20}\\b${codePattern}\\b`).test(text) ||
            new RegExp(`\\b${codePattern}\\b[\\W_]{0,20}\\b${labels}\\b`).test(text);
    });
}

function codeNearAnyLabel(text, valueTokens) {
    const codes = [...valueTokens].filter(token => /^\d+$/.test(token));
    if (!codes.length) return false;
    const labels = "(?:interlock|inhibit|error|fault|alarm|code)";
    return codes.some(code => {
        const escapedCode = code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const codePattern = `(?:i|e)?\\s*${escapedCode}`;
        return new RegExp(`\\b${labels}\\b[\\W_]{0,25}\\b${codePattern}\\b`).test(text) ||
            new RegExp(`\\b${codePattern}\\b[\\W_]{0,25}\\b(?:interlock|inhibit|error|fault|alarm)\\b`).test(text);
    });
}

// ─── DIAGNOSE OFFLINE ─────────────────────────────────────
async function diagnoseOffline(payload) {
    await ensureManuals("");
    const rawSignals = payload.signals || {};

    // Detect new format: {symptoms: [...]} vs legacy: {interlock, error, message, observations}
    if (Array.isArray(rawSignals.symptoms)) {
        return _diagnoseSymptomsOffline(rawSignals.symptoms);
    }
    return _diagnoseLegacyOffline(rawSignals);
}

function isNoisePage(normalizedText) {
    if (normalizedText.substring(0, 500).includes("table of contents")) return true;
    const dotDotCount = (normalizedText.substring(0, 500).match(/\. \. \./g) || []).length;
    if (dotDotCount >= 3) return true;
    return false;
}

function tokenFrequency(token) {
    // Fraction of docs that contain this token (0–1)
    return (postings.get(token) || []).length / Math.max(documents.length, 1);
}

function extractActionSentences(text, signalTokens, maxSentences) {
    const actionPat = /\b(?:check|verify|replace|reset|calibrate|inspect|ensure|adjust|connect|disconnect|remove|install|restore|should|must|cause[ds]?|due to|result[s]? from|indicates?|suggest[s]?)\b/i;
    const sentences = text.split(/(?<=[.!?])\s+|\n/).map(s => s.replace(/\s+/g, " ").trim()).filter(s => s.length >= 18 && s.length <= 320);
    const scored = [];
    for (const s of sentences) {
        const sToks = new Set(tokenize(s));
        const tokenHits = [...signalTokens].filter(t => sToks.has(t)).length;
        const actionHits = (s.match(actionPat) || []).length;
        const diagHits = [...DIAGNOSTIC_WORDS].filter(w => sToks.has(w)).length;
        const total = tokenHits * 4 + actionHits * 3 + diagHits * 2;
        if (total >= 4) scored.push([total, s]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    const seen = new Set(), unique = [];
    for (const [, s] of scored) {
        const key = normalize(s.substring(0, 40));
        if (!seen.has(key)) { seen.add(key); unique.push(s); }
        if (unique.length >= maxSentences) break;
    }
    return unique.join(" ");
}

async function _diagnoseSymptomsOffline(symptomList) {
    const weightsByPosition = [1.4, 1.3, 1.2, 1.1];
    const prepared = [];
    const allSignalTokens = new Set();
    const candidates = new Set();

    for (let i = 0; i < Math.min(symptomList.length, 4); i++) {
        const value = String(symptomList[i] || "").trim();
        if (!value) continue;
        const allToks = new Set(queryTokens(value));
        if (!allToks.size) continue;

        // Filter out overly common tokens (appear in >60% of docs)
        const specificTokens = new Set([...allToks].filter(t => tokenFrequency(t) <= 0.60));
        if (!specificTokens.size) continue;

        prepared.push({
            name: `symptom_${i + 1}`,
            value,
            normalizedValue: normalize(value),
            valueTokens: allToks,
            specificTokens,
            weight: weightsByPosition[i] || 1.0
        });
        for (const token of specificTokens) {
            allSignalTokens.add(token);
            for (const id of postings.get(token) || []) candidates.add(id);
        }
    }

    if (!prepared.length) return {
        results: [], signals: [],
        message: "Los sintomas ingresados son demasiado genericos. Ingresa codigos de error, interlocks o terminos tecnicos especificos."
    };

    const ranked = [];
    for (const id of candidates) {
        const doc = documents[id];
        if (isNoisePage(doc.normalized)) continue;

        let score = 0;
        const matchedSignals = [];
        const matchedTokens = new Set();

        for (const signal of prepared) {
            const hitsSpecific = [...signal.specificTokens].filter(t => doc.tokenSet.has(t));
            if (!hitsSpecific.length) continue;

            const coverageSpecific = hitsSpecific.length / signal.specificTokens.size;
            const exactPhrase = doc.normalized.includes(signal.normalizedValue);
            const hasNumeric = [...signal.specificTokens].some(t => /^\d+$/.test(t));
            const codeMatch = hasNumeric ? codeNearAnyLabel(doc.normalized, signal.specificTokens) : false;

            // Strict acceptance rules
            if (hasNumeric && signal.specificTokens.size <= 3) {
                if (!exactPhrase && !codeMatch) continue;
            } else if (hasNumeric && signal.specificTokens.size > 3) {
                if (!exactPhrase && !codeMatch && coverageSpecific < 0.55) continue;
            } else {
                if (coverageSpecific < 0.55) continue;
            }

            let signalScore = hitsSpecific.length * 5 + coverageSpecific * 15;
            if (exactPhrase) signalScore += 40;
            else if (codeMatch) signalScore += 32;
            score += signalScore * signal.weight;
            matchedSignals.push({ field: signal.name, value: signal.value, coverage: Math.round(coverageSpecific * 100) / 100 });
            hitsSpecific.forEach(t => matchedTokens.add(t));
        }
        if (!matchedSignals.length) continue;

        score += Math.max(0, matchedSignals.length - 1) * 30;
        score += Math.min([...ACTION_WORDS].filter(w => doc.tokenSet.has(w)).length, 8) * 2.5;
        score += Math.min([...DIAGNOSTIC_WORDS].filter(w => doc.tokenSet.has(w)).length, 6) * 1.8;
        ranked.push({ score, document: doc, matchedSignals, matchedTokens });
    }

    ranked.sort((a, b) => b.score - a.score || b.matchedSignals.length - a.matchedSignals.length || a.document.page - b.document.page);

    const selected = [];
    const seen = new Set();
    for (const item of ranked) {
        const title = bestLine(item.document.text, allSignalTokens);
        const key = item.document.manual + "|" + normalize(title).substring(0, 90);
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push({ ...item, title });
        if (selected.length >= 6) break;
    }

    if (!selected.length) return {
        results: [], signals: prepared.map(p => p.value),
        message: "No se encontro evidencia suficientemente especifica en los manuales para estos sintomas."
    };

    const maxScore = selected[0].score;
    const totalSignals = prepared.length;
    const results = [];

    for (const item of selected) {
        const completeness = item.matchedSignals.length / totalSignals;
        const relative = Math.max(1, Math.min(99, Math.round(item.score / maxScore * (45 + 54 * completeness))));
        if (relative < MIN_RELATIVE_MATCH_DIAGNOSE) continue;

        const confidence = relative >= 75 ? "alta" : relative >= PDF_CONFIDENCE_THRESHOLD ? "media" : "baja";
        const pdfRelevant = relative >= MIN_RELATIVE_MATCH_DIAGNOSE && confidence !== "baja";
        const actionSummary = extractActionSentences(item.document.text, allSignalTokens, 2);

        results.push({
            type: "manual",
            title: item.title,
            manual: item.document.manual,
            page: item.document.page,
            context: makeContext(item.document.text, [...item.matchedTokens].join(" "), 260, 480),
            action_summary: actionSummary,
            matched_signals: item.matchedSignals,
            relative_match: relative,
            confidence,
            pdf_relevant: pdfRelevant,
            matched_count: item.matchedSignals.length,
            signal_count: totalSignals
        });
    }

    if (!results.length) return {
        results: [], signals: prepared.map(p => p.value),
        message: "Las coincidencias encontradas no tienen suficiente relevancia diagnostica. Intenta con codigos de error mas especificos."
    };

    const bestMatchedCount = results.reduce((b, r) => Math.max(b, r.matched_count), 0);
    return {
        results,
        signals: prepared.map(p => p.value),
        message: bestMatchedCount === totalSignals ? ""
            : results.length > 1 ? "No todas las paginas reunen todos los sintomas; se muestran las mas relevantes."
            : ""
    };
}

async function _diagnoseLegacyOffline(rawSignals) {
    const weights = { interlock: 1.5, error: 1.5, message: 1.15, observations: 0.8 };
    const prepared = [];
    const allSignalTokens = new Set();
    const candidates = new Set();

    for (const [name, raw] of Object.entries(rawSignals)) {
        const value = String(raw || "").trim();
        if (!value) continue;
        const semanticValue = (name === "interlock" && !/interlock/i.test(value)) ? `interlock ${value}`
            : (name === "error" && !/(error|fault)/i.test(value)) ? `error ${value}` : value;
        const valueTokens = new Set(queryTokens(semanticValue));
        if (!valueTokens.size) continue;
        prepared.push({ name, value, normalizedValue: normalize(semanticValue), valueTokens, weight: weights[name] || 1 });
        for (const token of valueTokens) {
            allSignalTokens.add(token);
            for (const id of postings.get(token) || []) candidates.add(id);
        }
    }
    if (!prepared.length) return { results: [], signals: [], message: "Ingresa al menos un código o síntoma." };

    const ranked = [];
    for (const id of candidates) {
        const document = documents[id];
        let score = 0;
        const matchedSignals = [];
        const matchedTokens = new Set();
        for (const signal of prepared) {
            const hits = [...signal.valueTokens].filter(token => document.tokenSet.has(token));
            if (!hits.length) continue;
            const specificTokens = [...signal.valueTokens].filter(token => !["interlock", "error", "fault"].includes(token));
            if (specificTokens.length && !hits.some(token => specificTokens.includes(token))) continue;
            const coverage = hits.length / signal.valueTokens.size;
            const exactPhrase = document.normalized.includes(signal.normalizedValue);
            const codeMatch = codeNearLabel(document.normalized, signal.name, signal.valueTokens);
            if (["interlock", "error"].includes(signal.name) && [...signal.valueTokens].some(token => /^\d+$/.test(token))) {
                if (!exactPhrase && !codeMatch) continue;
            } else if (signal.name === "message" && signal.valueTokens.size > 1 && coverage < 0.5) {
                continue;
            } else if (signal.name === "observations" && signal.valueTokens.size > 2 && coverage < 0.34) {
                continue;
            }
            let signalScore = hits.length * 4 + coverage * 12;
            if (exactPhrase) signalScore += 35;
            else if (codeMatch) signalScore += 28;
            score += signalScore * signal.weight;
            matchedSignals.push({ field: signal.name, value: signal.value, coverage: Math.round(coverage * 100) / 100 });
            hits.forEach(token => matchedTokens.add(token));
        }
        if (!matchedSignals.length) continue;
        score += Math.max(0, matchedSignals.length - 1) * 28;
        score += Math.min([...ACTION_WORDS].filter(word => document.tokenSet.has(word)).length, 5) * 1.5;
        if ((document.text.match(/\. \. \./g) || []).length >= 5 || document.normalized.substring(0, 500).includes("table of contents")) score *= 0.35;
        ranked.push({ score, document, matchedSignals, matchedTokens });
    }
    ranked.sort((a, b) => b.score - a.score || b.matchedSignals.length - a.matchedSignals.length || a.document.page - b.document.page);

    const selected = [];
    const seen = new Set();
    for (const item of ranked) {
        const title = bestLine(item.document.text, allSignalTokens);
        const key = item.document.manual + "|" + normalize(title).substring(0, 90);
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push({ ...item, title });
        if (selected.length >= 6) break;
    }
    const maxScore = selected.length ? selected[0].score : 1;
    const totalSignals = prepared.length;
    const bestMatchedCount = selected.reduce((best, item) => Math.max(best, item.matchedSignals.length), 0);
    return {
        results: selected.map(item => ({
            type: "manual",
            title: item.title,
            manual: item.document.manual,
            page: item.document.page,
            context: makeContext(item.document.text, [...item.matchedTokens].join(" "), 260, 480),
            matched_signals: item.matchedSignals,
            relative_match: Math.max(1, Math.min(99, Math.round(item.score / maxScore * (45 + 54 * item.matchedSignals.length / totalSignals)))),
            matched_count: item.matchedSignals.length,
            signal_count: totalSignals
        })),
        signals: prepared.map(item => item.value),
        message: selected.length && bestMatchedCount === totalSignals ? ""
            : selected.length ? "No se encontró una página que reúna todos los datos; se muestran coincidencias parciales."
            : "No se encontró una relación suficiente en los manuales."
    };
}

self.onmessage = async event => {
    const { id, type, payload } = event.data || {};
    try {
        let data;
        if (type === "search") data = await searchOffline(payload || {});
        else if (type === "diagnose") data = await diagnoseOffline(payload || {});
        else if (type === "catalog") data = await ensureCatalog();
        else throw new Error("Operación offline desconocida");
        self.postMessage({ id, ok: true, data });
    } catch (error) {
        self.postMessage({ id, ok: false, error: error.message || "Error en el índice offline" });
    }
};
