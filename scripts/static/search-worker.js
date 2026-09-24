"use strict";

const STOP_WORDS = new Set([
    "a", "al", "and", "are", "as", "at", "be", "by", "con", "de", "del", "el",
    "en", "es", "for", "from", "in", "is", "la", "las", "los", "of", "on", "or",
    "para", "por", "que", "se", "the", "to", "un", "una", "y"
]);
const DIAGNOSTIC_WORDS = new Set([
    "interlock", "inhibit", "error", "fault", "alarm", "failure", "failed",
    "calibration", "encoder", "motor", "beam", "dose", "mlc", "leaf", "gantry",
    "collimator", "monitor", "sensor", "cable", "board", "driver", "power",
    "supply", "voltage", "current", "temperature", "pressure", "vacuum",
    "rf", "klystron", "modulator", "gun", "dose1", "dose2", "pcb", "card",
    "tarjeta", "area", "module", "circuit", "switch", "relay", "valve"
]);

const MIN_RELATIVE_MATCH_DIAGNOSE = 25;
const PDF_CONFIDENCE_THRESHOLD = 50;
const LEGACY_SIGNAL_FIELDS = ["interlock", "error", "message", "observations"];

let catalog = null;
const loadedManuals = new Set();
const documents = [];
const postings = new Map();
const manuals = new Map();

function normalize(value) {
    return String(value || "").toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
}

function compareText(left, right) {
    return left < right ? -1 : left > right ? 1 : 0;
}

function tokenize(value) {
    return normalize(value).match(/[a-z0-9]+/g) || [];
}

function queryTokens(value) {
    return [...new Set(tokenize(value).filter(token =>
        !STOP_WORDS.has(token) && (token.length >= 2 || /^\d+$/.test(token))
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
            if (token.length < 2 && !/^\d+$/.test(token)) continue;
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
    const terms = queryTokens(query).length ? queryTokens(query) : tokenize(query);
    let ids = [];
    if (terms.length) {
        const termLists = [];
        for (const t of terms) {
            if (postings.has(t)) {
                termLists.push(postings.get(t));
            } else {
                // Si alguna palabra exacta no existe en los manuales, no hay coincidencia exacta
                return [];
            }
        }

        termLists.sort((a, b) => a.length - b.length);
        let intersection = new Set(termLists[0]);
        for (let i = 1; i < termLists.length; i++) {
            const nextSet = new Set(termLists[i]);
            intersection = new Set([...intersection].filter(id => nextSet.has(id)));
            if (!intersection.size) break;
        }
        ids = [...intersection];
    } else {
        ids = documents.map(d => d.id);
    }
    if (manualFilter) {
        const allowed = new Set(manuals.get(manualFilter) || []);
        ids = ids.filter(id => allowed.has(id));
    }
    return ids;
}

function phrasePattern(query) {
    const parts = tokenize(query);
    if (!parts.length) return null;
    const escaped = parts.map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const sep = "(?:[\\W_]+|[\\W_]+(?:the|a|an|of|in|to|and|or|de|la|el|del|y|en)[\\W_]+)";
    return new RegExp("\\b" + escaped.join(sep) + "\\b", "gi");
}

function queryMatchInfo(document, query) {
    const text = document.normalized;
    const pattern = phrasePattern(query);
    if (!pattern) return { matched: false, score: 0 };

    const matches = [...text.matchAll(pattern)];
    if (!matches.length) {
        return { matched: false, score: 0 };
    }

    const occurrences = matches.length;
    let score = occurrences * 50;

    const firstPos = matches[0].index;
    if (firstPos >= 0) {
        score += Math.max(0, 10 - firstPos / 500);
    }

    return { matched: true, score };
}

function makeContext(text, query, before = 160, after = 320) {
    const cleaned = text.replace(/[\x00-\x1f\x7f-\x9f]+/g, " ")
        .replace(/[^\p{L}\p{N}_\s.,:;()\/-]/gu, " ")
        .replace(/\s+/g, " ").trim();

    const normalizedText = normalize(cleaned);
    const pattern = phrasePattern(query);
    let position = -1;
    let matchLen = query.length;

    if (pattern) {
        const m = pattern.exec(normalizedText);
        if (m) {
            position = m.index;
            matchLen = m[0].length;
        }
    }

    if (position < 0) {
        const normQuery = normalize(query).trim();
        position = normalizedText.indexOf(normQuery);
        if (position < 0) {
            const positions = queryTokens(query)
                .map(token => normalizedText.indexOf(token))
                .filter(index => index >= 0);
            position = positions.length ? Math.min(...positions) : 0;
        }
    }

    const start = Math.max(0, position - before);
    const end = Math.min(cleaned.length, position + Math.max(matchLen, 1) + after);
    let context = cleaned.substring(start, end).trim();
    if (start > 0) context = "... " + context;
    if (end < cleaned.length) context += " ...";
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
    const manualFilter = normalize(payload.manual).trim();
    const offset = Math.max(0, Number(payload.offset) || 0);
    const limit = Math.min(50, Math.max(1, Number(payload.limit) || 25));
    let manualResults = [];

    if (manualFilter !== "apuntes") {
        await ensureManuals(manualFilter);
        manualResults = candidateIds(query, manualFilter).map(id => {
            const document = documents[id];
            return { document, match: queryMatchInfo(document, query) };
        }).filter(item => item.match.matched).map(item => ({
            document: item.document,
            score: item.match.score
        })).sort((a, b) => b.score - a.score || compareText(a.document.manual, b.document.manual) || a.document.page - b.document.page)
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
    const cleaned = String(text || "").replace(/[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, " ");
    const lines = cleaned.split(/\r?\n/).map(line => line.replace(/\s+/g, " ").trim())
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

function codeNearAnyLabel(text, valueTokens) {
    const codes = [...valueTokens].filter(token => /^\d+$/.test(token));
    if (!codes.length) return false;
    const labels = "(?:interlock|inhibit|error|fault|alarm|code|item|i\\d{1,4}|e\\d{1,4})";
    return codes.some(code => {
        const escapedCode = code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const codePattern = `(?:i|e|item)?\\s*${escapedCode}`;
        return new RegExp(`\\b${labels}\\b[\\W_]{0,30}\\b${codePattern}\\b`).test(text) ||
            new RegExp(`\\b${codePattern}\\b[\\W_]{0,30}\\b${labels}\\b`).test(text);
    });
}

// ─── DIAGNOSE OFFLINE ─────────────────────────────────────
async function diagnoseOffline(payload) {
    await ensureManuals("");
    const rawSignals = payload.signals || {};

    // Detect new format: {symptoms: [...]} vs legacy: {interlock, error, message, observations}
    if (Array.isArray(rawSignals.symptoms)) {
        return _diagnoseSymptomsOffline(rawSignals.symptoms, payload.limit);
    }
    return _diagnoseLegacyOffline(rawSignals, payload.limit);
}

function isNoisePage(normalizedText) {
    if (normalizedText.substring(0, 400).includes("table of contents") && normalizedText.length < 400) return true;
    const dotDotCount = (normalizedText.substring(0, 300).match(/\. \. \./g) || []).length;
    if (dotDotCount >= 5) return true;
    return false;
}

function tokenFrequency(token) {
    // Fraction of docs that contain this token (0–1)
    return (postings.get(token) || []).length / Math.max(documents.length, 1);
}

function extractAssociatedComponents(text) {
    const cleaned = String(text || "").slice(0, 12000).replace(/[\x00-\x1f\x7f-\x9f]/g, " ");

    // 1. Items y Números de Parte
    const itemMatches = cleaned.match(/\b(?:ITEM\s*\d+|P\/N\s*[A-Z0-9\-]+|PART\s*NO\.?\s*[A-Z0-9\-]+|45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5})\b/gi) || [];
    const items = [];
    for (const it of itemMatches) {
        const itClean = it.replace(/\s+/g, " ").trim().toUpperCase();
        if (!items.includes(itClean)) items.push(itClean);
    }

    // 2. Tarjetas / PCBs
    const boardMatches = cleaned.match(/\b(?:PCB\s+[A-Z0-9]+|AO\d+|AI\s*\d+[A-Z]?|DO\s*\d+|DI\s*\d+|PWA\s+[A-Z0-9]+|PWB\s+[A-Z0-9]+|DIE-[A-Z0-9]+|SCC-[A-Z0-9]+|CPU-[A-Z0-9]+|MOT-[A-Z0-9]+|DRV-[A-Z0-9]+|TMC\b|RTD\b|MLC\b|XVI\b)\b/gi) || [];
    const boards = [];
    for (const b of boardMatches) {
        const bClean = b.replace(/\s+/g, " ").trim().toUpperCase();
        if (!boards.includes(bClean) && bClean.length >= 3 && !["PCB", "PWA", "PWB"].includes(bClean)) {
            boards.push(bClean);
        }
    }

    // 3. Cables y Conectores
    const cableMatches = cleaned.match(/\b(?:CABLE\s*[A-Z0-9\-]+|HARNESS\s*[A-Z0-9\-]+|PL\d{1,3}|SK\d{1,3}|TB\d{1,3}|J\d{1,3}|W\d{1,3})\b/gi) || [];
    const cables = [];
    for (const c of cableMatches) {
        const cClean = c.replace(/\s+/g, " ").trim().toUpperCase();
        if (!cables.includes(cClean) && cClean.length >= 2) cables.push(cClean);
    }

    // 4. Puntos de Prueba (TP) y Voltajes
    const tpMatches = cleaned.match(/\b(?:TP\d{1,3}|TP_[A-Z0-9]+|RL[AB]?\d{1,3}|FS\d{1,3}|FUSE\s*[A-Z0-9]+|[+\-]?\d+(?:\.\d+)?\s*(?:VDC|VAC|kV))\b/gi) || [];
    const tps = [];
    for (const tp of tpMatches) {
        const tpClean = tp.replace(/\s+/g, " ").trim().toUpperCase();
        if (!tps.includes(tpClean)) tps.push(tpClean);
    }

    // 5. Áreas y Racks
    const areaMatches = cleaned.match(/\b(?:(?:HTCA\s+)?AREA\s+\d+[A-Z]?|RACK\s+[A-Z0-9]+|CABINET\s+[A-Z0-9]+|GANTRY\s+DRUM|PEDESTAL)\b/gi) || [];
    const areas = [];
    for (const a of areaMatches) {
        const aClean = a.replace(/\s+/g, " ").trim().toUpperCase();
        if (!areas.includes(aClean)) areas.push(aClean);
    }

    const titleMatch = cleaned.match(/(?:^|\n)\s*(?:(?:\d+\.\d+\s+)?([A-Za-z0-9\s\-]+(?:system|interlock[s]?|control|circuit|power|supply|assembly|module|sheet\s+\d+)))/i);
    let subsystem = "";
    if (titleMatch && titleMatch[1]) {
        const sub = titleMatch[1].replace(/\s+/g, " ").trim();
        if (sub.length >= 5 && sub.length <= 70) subsystem = sub;
    }

    const parts = [];
    if (boards.length) parts.push("Tarjeta: " + boards.slice(0, 3).join(", "));
    if (items.length) parts.push("Señal/Item: " + items.slice(0, 3).join(", "));
    if (cables.length) parts.push("Conector/Cable: " + cables.slice(0, 3).join(", "));
    if (tps.length) parts.push("TP/Medición: " + tps.slice(0, 2).join(", "));
    if (areas.length) parts.push("Ubicación: " + areas.slice(0, 2).join(", "));
    if (subsystem) parts.push("Subsistema: " + subsystem);

    return parts.length ? parts.join(" · ") : "Componente documentado en manual";
}

async function _diagnoseSymptomsOffline(symptomList, requestedLimit = 3) {
    const resultLimit = Math.min(50, Math.max(1, Number(requestedLimit) || 3));
    // Todas las informaciones y síntomas ingresados tienen prioridad equitativa y alta (peso 1.0)
    const prepared = [];
    const allSignalTokens = new Set();
    const candidates = new Set();

    for (let i = 0; i < Math.min(symptomList.length, 5); i++) {
        const value = String(symptomList[i] || "").trim();
        if (!value) continue;
        const allToks = new Set(queryTokens(value));
        if (!allToks.size) continue;

        // Filter out overly common tokens (appear in >65% of docs)
        const specificTokens = new Set([...allToks].filter(t => tokenFrequency(t) <= 0.65));
        const activeTokens = specificTokens.size ? specificTokens : allToks;

        prepared.push({
            name: `symptom_${i + 1}`,
            value,
            normalizedValue: normalize(value),
            valueTokens: allToks,
            specificTokens: activeTokens,
            weight: 1.0
        });
        for (const token of activeTokens) {
            allSignalTokens.add(token);
            for (const id of postings.get(token) || []) candidates.add(id);
        }
    }

    if (!prepared.length) return {
        results: [], signals: [],
        message: "Ingresa al menos un código, señal o síntoma específico."
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
            const hitsAll = [...signal.valueTokens].filter(t => doc.tokenSet.has(t));
            if (!hitsSpecific.length && !hitsAll.length) continue;

            const hits = hitsSpecific.length ? hitsSpecific : hitsAll;
            const coverageSpecific = hits.length / signal.specificTokens.size;
            const exactPhrase = doc.normalized.includes(signal.normalizedValue);
            const hasNumeric = [...signal.specificTokens].some(t => /^\d+$/.test(t));
            const codeMatch = hasNumeric ? codeNearAnyLabel(doc.normalized, signal.specificTokens) : false;

            let signalScore = hits.length * 6 + coverageSpecific * 16;
            if (exactPhrase) signalScore += 45;
            else if (codeMatch) signalScore += 35;
            score += signalScore * signal.weight;
            matchedSignals.push({ field: signal.name, value: signal.value, coverage: Math.round(coverageSpecific * 100) / 100 });
            hits.forEach(t => matchedTokens.add(t));
        }
        if (!matchedSignals.length) continue;

        // Massive convergence bonus for multi-signal intersection on same page
        if (matchedSignals.length > 1) {
            score += (matchedSignals.length - 1) * 60;
        }
        score += Math.min([...DIAGNOSTIC_WORDS].filter(w => doc.tokenSet.has(w)).length, 8) * 2.0;
        ranked.push({ score, document: doc, matchedSignals, matchedTokens });
    }

    ranked.sort((a, b) => b.score - a.score || b.matchedSignals.length - a.matchedSignals.length || compareText(a.document.manual, b.document.manual) || a.document.page - b.document.page);

    const selected = [];
    const seen = new Set();
    for (const item of ranked) {
        const title = bestLine(item.document.text, allSignalTokens);
        const key = item.document.manual + "|" + item.document.page;
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push({ ...item, title });
        if (selected.length >= resultLimit) break;
    }

    if (!selected.length) return {
        results: [], signals: prepared.map(p => p.value),
        message: "No se encontraron relaciones directas en los manuales para las señales ingresadas."
    };

    const maxScore = (selected.length && selected[0].score > 0) ? selected[0].score : 1.0;
    const totalSignals = prepared.length;
    const results = [];

    for (const item of selected) {
        const completeness = item.matchedSignals.length / totalSignals;
        const relative = Math.max(1, Math.min(99, Math.round(item.score / maxScore * (45 + 54 * completeness))));
        if (relative < MIN_RELATIVE_MATCH_DIAGNOSE) continue;

        const confidence = relative >= 75 ? "alta" : relative >= PDF_CONFIDENCE_THRESHOLD ? "media" : "baja";
        const pdfRelevant = relative >= MIN_RELATIVE_MATCH_DIAGNOSE && confidence !== "baja";
        const associatedComp = extractAssociatedComponents(item.document.text);

        results.push({
            type: "manual",
            title: item.title,
            manual: item.document.manual,
            page: item.document.page,
            context: makeContext(item.document.text, [...item.matchedTokens].sort(compareText).join(" ") || [...allSignalTokens].sort(compareText)[0] || "", 260, 480),
            associated_component: associatedComp,
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
        message: "Las coincidencias encontradas no tienen suficiente relevancia. Intenta con códigos de señal más específicos."
    };

    const bestMatchedCount = results.reduce((b, r) => Math.max(b, r.matched_count), 0);
    return {
        results,
        signals: prepared.map(p => p.value),
        message: bestMatchedCount === totalSignals ? ""
            : results.length > 1 ? "No todas las páginas reúnen todos los síntomas; se muestran las conexiones más relevantes."
            : ""
    };
}

async function _diagnoseLegacyOffline(rawSignals, requestedLimit = 3) {
    const symptoms = LEGACY_SIGNAL_FIELDS.map(field => rawSignals[field]).filter(Boolean);
    return _diagnoseSymptomsOffline(symptoms, requestedLimit);
}

const _cancelledRequests = new Set();

self.onmessage = async event => {
    const { id, type, payload } = event.data || {};

    if (type === "cancel") {
        const targetId = (payload && payload.id) || id;
        if (targetId) {
            _cancelledRequests.add(targetId);
            if (_cancelledRequests.size > 100) {
                const first = _cancelledRequests.values().next().value;
                _cancelledRequests.delete(first);
            }
        }
        return;
    }

    if (_cancelledRequests.has(id)) {
        _cancelledRequests.delete(id);
        return;
    }

    try {
        let data;
        if (type === "search") data = await searchOffline(payload || {});
        else if (type === "diagnose") data = await diagnoseOffline(payload || {});
        else if (type === "catalog") data = await ensureCatalog();
        else throw new Error("Operación offline desconocida");

        if (_cancelledRequests.has(id)) {
            _cancelledRequests.delete(id);
            return;
        }

        self.postMessage({ id, ok: true, data });
    } catch (error) {
        if (_cancelledRequests.has(id)) {
            _cancelledRequests.delete(id);
            return;
        }
        self.postMessage({ id, ok: false, error: error.message || "Error en el índice offline" });
    }
};
