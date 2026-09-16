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
        .replace(/[^\w\s\.\,\-\:\;\(\)\/]/g, " ")
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
        if (position < 0) position = 0;
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
    const manualFilter = String(payload.manual || "").trim().toLowerCase();
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
        return _diagnoseSymptomsOffline(rawSignals.symptoms);
    }
    return _diagnoseLegacyOffline(rawSignals);
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

        // Filter out overly common tokens (appear in >65% of docs)
        const specificTokens = new Set([...allToks].filter(t => tokenFrequency(t) <= 0.65));
        const activeTokens = specificTokens.size ? specificTokens : allToks;

        prepared.push({
            name: `symptom_${i + 1}`,
            value,
            normalizedValue: normalize(value),
            valueTokens: allToks,
            specificTokens: activeTokens,
            weight: weightsByPosition[i] || 1.0
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

    ranked.sort((a, b) => b.score - a.score || b.matchedSignals.length - a.matchedSignals.length || a.document.page - b.document.page);

    const selected = [];
    const seen = new Set();
    for (const item of ranked) {
        const title = bestLine(item.document.text, allSignalTokens);
        const key = item.document.manual + "|" + item.document.page;
        if (seen.has(key)) continue;
        seen.add(key);
        selected.push({ ...item, title });
        if (selected.length >= 3) break;
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
            context: makeContext(item.document.text, [...item.matchedTokens].join(" "), 260, 480),
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
    const maxScore = (selected.length && selected[0].score > 0) ? selected[0].score : 1;
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
        message: selected.length && bestMatchedCount === totalSignals ? "" :
            (selected.length > 1 ? "No todas las páginas reúnen todos los síntomas; se muestran las conexiones más relevantes." : "")
    };
}

// ─── KNOWLEDGE GRAPH OFFLINE CIRCUIT TRACER (LAZY LOADED) ───────────────────
let _graphData = null;
let _graphLoadingPromise = null;

async function ensureGraphData() {
    if (_graphData) return _graphData;
    if (_graphLoadingPromise) return _graphLoadingPromise;
    _graphLoadingPromise = (async () => {
        try {
            const res = await fetch("/static/linac_graph.json");
            if (!res.ok) throw new Error("No se pudo cargar el grafo de conocimiento: " + res.status);
            _graphData = await res.json();
            if (_graphData && _graphData.entities) {
                const pageMap = new Map();
                for (const entId in _graphData.entities) {
                    const pages = _graphData.entities[entId].pages || [];
                    for (let p = 0; p < pages.length; p++) {
                        const key = pages[p][0] + "|" + pages[p][1];
                        if (!pageMap.has(key)) pageMap.set(key, []);
                        pageMap.get(key).push(entId);
                    }
                }
                _graphData.pageMap = pageMap;
            }
            return _graphData;
        } catch (e) {
            _graphLoadingPromise = null;
            throw e;
        }
    })();
    return _graphLoadingPromise;
}

// ─── CIRCUIT SCHEMATICS OFFLINE MATCHER (LAZY LOADED) ──────────────────────
let _schematicsData = null;
let _schematicsLoadingPromise = null;

async function ensureSchematicsData() {
    if (_schematicsData) return _schematicsData;
    if (_schematicsLoadingPromise) return _schematicsLoadingPromise;
    _schematicsLoadingPromise = (async () => {
        try {
            const res = await fetch("/static/circuit_schematics.json");
            if (!res.ok) return null;
            _schematicsData = await res.json();
            return _schematicsData;
        } catch (e) {
            _schematicsLoadingPromise = null;
            return null;
        }
    })();
    return _schematicsLoadingPromise;
}

const _SUB_KEYWORDS_OFFLINE = {
    radiation_beam: [/\b(radiaci[oó]n|radiation|modulador|modulator|tiratron|thyratron|magnetron|pfn|rf|klistron|klystron)\b/i],
    safety_loop: [/\b(seguridad|safety|bucle|loop|e-stop|estop|parada|puerta|door|colisi[oó]n|collision)\b/i],
    dosimetry: [/\b(dosimetr[ií]a|dosimetry|dosis|dose|c[aá]mara|chamber|d_rate|d-rate|unidades|mu)\b/i],
    gantry_collimator: [/\b(gantry|colimador|collimator|rotaci[oó]n|rotation|servo|encoder|dinamo|taquim[eé]trica|tacho|brake|freno)\b/i],
    vacuum_gun: [/\b(vac[ií]o|vacuum|cañ[oó]n|canon|gun|vacion|vac-ion|filamento|filament|c[aá]todo|cathode|emisi[oó]n)\b/i]
};

const _GENERIC_MATCH_WORDS_OFFLINE = new Set([
    "interlock", "intlk", "item", "cable", "pcb", "rele", "relay", "punto", "prueba",
    "test", "point", "linea", "line", "para", "falla", "error", "alarma", "desde",
    "hacia", "circuito", "bucle", "switch", "sensor", "fuente", "supply", "board"
]);

function _matchesNameWordsOffline(term, node) {
    const termWords = String(term).toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_GENERIC_MATCH_WORDS_OFFLINE.has(w));
    const nameWords = String(node.name || "").toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_GENERIC_MATCH_WORDS_OFFLINE.has(w));
    const codeWords = String(node.code || "").toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_GENERIC_MATCH_WORDS_OFFLINE.has(w));
    const allWords = nameWords.concat(codeWords);
    for (const tw of termWords) {
        for (const nw of allWords) {
            if (tw === nw || (tw.length >= 5 && (tw.includes(nw) || nw.includes(tw)))) {
                return true;
            }
        }
    }
    return false;
}

function _getNodePatternsOffline(node) {
    const pats = new Set();
    const nid = String(node.id || "").toUpperCase().replace(/[\W_]+/g, "");
    const code = String(node.code || "").toUpperCase().replace(/[\W_]+/g, "");
    if (nid) pats.add(nid);
    if (code) pats.add(code);

    const fullStr = `${node.code || ""} ${node.id || ""} ${node.spec || ""}`;
    const mItem = fullStr.match(/\bITEM_?(\d+)\b/i);
    if (mItem) {
        const num = mItem[1];
        pats.add("ITEM" + num);
        pats.add("INTERLOCK" + num);
        pats.add("INTLK" + num);
        pats.add(num);
    }
    const mIntlk = fullStr.match(/\b(?:INTERLOCK|INTLK)_?(\d+)\b/i);
    if (mIntlk) {
        const num = mIntlk[1];
        pats.add("INTERLOCK" + num);
        pats.add("INTLK" + num);
        pats.add("ITEM" + num);
        pats.add(num);
    }
    const mPcb = fullStr.match(/\bPCB_?(\w+)\b/i);
    if (mPcb) {
        pats.add("PCB" + mPcb[1].toUpperCase());
        pats.add(mPcb[1].toUpperCase());
    }
    const mRelay = fullStr.match(/\bK\d+\b/i);
    if (mRelay) {
        pats.add(mRelay[0].toUpperCase());
        pats.add("RELAY" + mRelay[0].toUpperCase());
    }
    return pats;
}

async function matchSubsystemForTraceOffline(components) {
    if (!components || !components.length) {
        return { subsystem_id: "safety_loop", matched_nodes: [] };
    }
    const schems = await ensureSchematicsData();
    if (!schems) {
        const compStr = components.join(" ").toLowerCase();
        let sub = "safety_loop";
        if (/\b(409|474|modulador|radiaci[oó]n|radiation|tiratron|magnetron|rf|pfn|pcb\s*22)\b/i.test(compStr)) sub = "radiation_beam";
        else if (/\b(dosis|dose|camara|chamber|d_rate|327|332|66|pcb\s*17|pcb\s*18)\b/i.test(compStr)) sub = "dosimetry";
        else if (/\b(gantry|colimador|collimator|motor|encoder|215|servo|pcb\s*25)\b/i.test(compStr)) sub = "gantry_collimator";
        else if (/\b(vac[ií]o|vacuum|cañ[oó]n|canon|gun|112|118|vacion|pcb\s*14|pcb\s*12)\b/i.test(compStr)) sub = "vacuum_gun";
        return { subsystem_id: sub, matched_nodes: [] };
    }

    const matchedBySub = {
        safety_loop: [],
        radiation_beam: [],
        dosimetry: [],
        gantry_collimator: [],
        vacuum_gun: []
    };

    for (const sId in schems) {
        const sub = schems[sId];
        const nodes = sub.nodes || [];
        for (const node of nodes) {
            const pats = _getNodePatternsOffline(node);
            for (const c of components) {
                const cStr = String(c || "").trim();
                if (!cStr) continue;
                const normC = String(cStr).toUpperCase().replace(/[\W_]+/g, "");
                let matched = false;
                if (pats.has(normC)) {
                    matched = true;
                } else {
                    for (const p of pats) {
                        const escapedP = String(p).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
                        if (p.length >= 3 && (p === normC || new RegExp("\\b" + escapedP + "\\b", "i").test(cStr))) {
                            matched = true;
                            break;
                        }
                    }
                }
                if (!matched && _matchesNameWordsOffline(cStr, node)) {
                    matched = true;
                }
                if (matched && !matchedBySub[sId].includes(node.id)) {
                    matchedBySub[sId].push(node.id);
                }
            }
        }
    }

    const scores = {};
    for (const sId in schems) {
        scores[sId] = (matchedBySub[sId] || []).length * 10;
    }
    const fullText = components.map(c => String(c).toLowerCase()).join(" ");
    for (const sId in _SUB_KEYWORDS_OFFLINE) {
        for (const kw of _SUB_KEYWORDS_OFFLINE[sId]) {
            if (kw.test(fullText)) {
                scores[sId] = (scores[sId] || 0) + 5;
            }
        }
    }

    let bestSubsystem = "safety_loop";
    let maxScore = -1;
    for (const sId in scores) {
        if (scores[sId] > maxScore) {
            maxScore = scores[sId];
            bestSubsystem = sId;
        }
    }

    return {
        subsystem_id: bestSubsystem,
        matched_nodes: matchedBySub[bestSubsystem] || []
    };
}

async function diagnoseGraphOffline(payload) {
    const graph = await ensureGraphData();
    const rawSymptoms = Array.isArray(payload.symptoms) ? payload.symptoms : [];
    const symptoms = rawSymptoms.map(s => String(s || "").trim().substring(0, 300)).filter(Boolean).slice(0, 6);
    if (!symptoms.length) return { found: false, reason: "no_symptoms" };

    async function finalizeTrace(res) {
        if (!res || !res.found) return res;
        const comps = [res.hub_node, ...(res.pcbs || []), ...(res.connectors || []), ...(res.test_points || []), ...symptoms];
        try {
            res.circuit_schematic = await matchSubsystemForTraceOffline(comps);
        } catch (e) {
            res.circuit_schematic = { subsystem_id: "safety_loop", matched_nodes: [] };
        }
        return res;
    }

    const _TYPE_PRIORITY = {
        pcb: 10,
        interlock: 9,
        error: 9,
        signal: 8,
        test_point: 8,
        switch: 7,
        relay: 7,
        sensor: 7,
        source: 7,
        load: 7,
        cable: 6,
        connector: 6,
        area: 1
    };

    function cleanKey(t) {
        if (!t) return "";
        return String(t)
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .trim()
            .replace(/[\W_]+/g, "");
    }

    function resolveEntity(text) {
        const clean = cleanKey(text);
        if (!clean) return null;

        // LG-03: Si el texto es puramente numérico (ej. "474", "283" o "12"), priorizar prefijos canónicos antes de lookup
        if (/^\d{2,4}$/.test(clean)) {
            for (const pref of ["ITEM", "INTERLOCK", "ERROR", "PCB"]) {
                const cand = pref + " " + clean;
                if (graph.entities && graph.entities[cand]) return cand;
            }
        }

        if (graph.lookup && graph.lookup[clean]) return graph.lookup[clean];

        const itemM = String(text).match(/\bitem\s*(\d{2,4})\b/i);
        if (itemM) {
            const cand = "ITEM " + itemM[1];
            if (graph.entities && graph.entities[cand]) return cand;
        }
        const intlkM = String(text).match(/\b(?:interlock|int)\s*(\d{2,4})\b/i);
        if (intlkM) {
            const cand = "INTERLOCK " + intlkM[1];
            if (graph.entities && graph.entities[cand]) return cand;
        }

        // GE-02: Resolución determinista de cables
        const cableM = String(text).match(/\b(?:cable\s*([a-z0-9_]+)|\b(w\d{1,3})\b)/i);
        if (cableM) {
            const rawCab = (cableM[1] || cableM[2]).toUpperCase().replace(/^(?:CABLE[_\s]+)/, "");
            for (const cand of [`CABLE ${rawCab}`, `CABLE_${rawCab}`, rawCab]) {
                if (graph.entities && graph.entities[cand]) return cand;
            }
        }

        const numM = String(text).match(/\b(\d{2,4})\b/);
        if (numM) {
            const code = numM[1];
            for (const pref of ["ITEM", "INTERLOCK", "ERROR", "PCB"]) {
                const cand = pref + " " + code;
                if (graph.entities && graph.entities[cand]) return cand;
            }
        }
        // 3a. Coincidencia exacta limpia con entId
        for (const entId in graph.entities) {
            const entClean = cleanKey(entId);
            if (clean === entClean) return entId;
        }

        // 3b. Coincidencias por subcadena ordenadas por prioridad de tipo (GE-03), longitud descendente y desempate alfabético
        const cleanDigits = clean.match(/\d+/g) || [];
        const candidates = [];
        for (const entId in graph.entities) {
            const entClean = cleanKey(entId);
            if ((clean.length >= 4 && entClean.includes(clean)) || (entClean.length >= 4 && clean.includes(entClean))) {
                const entDigits = entClean.match(/\d+/g) || [];
                if (cleanDigits.length && entDigits.length && cleanDigits.join() !== entDigits.join()) {
                    continue;
                }
                candidates.push(entId);
            }
        }
        if (candidates.length) {
            candidates.sort((a, b) => {
                const typeA = (graph.entities[a] && graph.entities[a].type) || "";
                const typeB = (graph.entities[b] && graph.entities[b].type) || "";
                const prioDiff = (_TYPE_PRIORITY[typeB] || 5) - (_TYPE_PRIORITY[typeA] || 5);
                if (prioDiff !== 0) return prioDiff;
                const diff = cleanKey(b).length - cleanKey(a).length;
                if (diff !== 0) return diff;
                return a.localeCompare(b);
            });
            return candidates[0];
        }

        // 4. Búsqueda contextual en documentos offline
        if (documents && documents.length && graph.pageMap) {
            const cIds = candidateIds(text, "");
            const cands = [];
            for (let i = 0; i < Math.min(cIds.length, 3); i++) {
                const doc = documents[cIds[i]];
                if (!doc) continue;
                const key = doc.manual + "|" + doc.page;
                const matchingEnts = graph.pageMap.get(key) || [];
                for (let k = 0; k < matchingEnts.length; k++) {
                    const entId = matchingEnts[k];
                    const ent = (graph.entities && graph.entities[entId]) || {};
                    const tWeight = ent.type === "pcb" ? 3 : (ent.type === "signal" ? 2 : 1);
                    cands.push({ id: entId, weight: tWeight });
                }
            }
            if (cands.length) {
                cands.sort((a, b) => b.weight - a.weight);
                return cands[0].id;
            }
        }

        return null;
    }

    const resolvedNodes = [];
    for (const s of symptoms) {
        const nid = resolveEntity(s);
        if (nid && !resolvedNodes.includes(nid)) resolvedNodes.push(nid);
    }

    if (!resolvedNodes.length) {
        // Modo fallback: buscar en manuales para sugerir esquemas clave
        const fallbackRefs = [];
        if (documents && documents.length) {
            for (const sym of symptoms) {
                const cIds = candidateIds(sym, "");
                for (let i = 0; i < Math.min(cIds.length, 2); i++) {
                    const d = documents[cIds[i]];
                    if (d) {
                        const ref = d.manual + " (Pág " + d.page + ")";
                        if (!fallbackRefs.includes(ref)) fallbackRefs.push(ref);
                    }
                }
            }
        }
        if (fallbackRefs.length) {
            return await finalizeTrace({
                found: true,
                hub_node: "Conexión Técnica en Manuales",
                resolved_nodes: symptoms,
                trace_diagram: symptoms.slice(0, 3).join(" -> "),
                pcbs: [],
                cables: [],
                connectors: [],
                test_points: [],
                areas: [],
                manual_references: fallbackRefs.slice(0, 6),
                confidence: "media"
            });
        }
        return { found: false, reason: "no_entities_resolved", resolved_nodes: [] };
    }

    function findShortestPath(startId, targetId, maxDepth = 4) {
        if (!graph.entities || !graph.entities[startId] || !graph.entities[targetId]) return null;
        if (!graph.adjacency) graph.adjacency = {};
        if (!graph.adjacency[startId]) graph.adjacency[startId] = [];
        if (!graph.adjacency[targetId]) graph.adjacency[targetId] = [];
        if (startId === targetId) return [{ node: startId, relation: "self" }];
        const queue = [[startId, [{ node: startId, relation: "start" }]]];
        const visited = new Set([startId]);
        while (queue.length) {
            const [current, path] = queue.shift();
            if (path.length > maxDepth) continue;
            const neighbors = graph.adjacency[current] || [];
            for (let i = 0; i < neighbors.length; i++) {
                const [neigh, rel] = neighbors[i];
                if (neigh === targetId) {
                    return [...path, { node: neigh, relation: rel }];
                }
                if (!visited.has(neigh)) {
                    visited.add(neigh);
                    queue.push([neigh, [...path, { node: neigh, relation: rel }]]);
                }
            }
        }
        return null;
    }

    const pcbs = [];
    const cables = [];
    const connectors = [];
    const testPoints = [];
    const areas = [];
    const manualRefs = [];

    function collectNodeHardware(n) {
        const ent = (graph.entities && graph.entities[n]) || {};
        const etype = ent.type || "";
        if (etype === "pcb" && !pcbs.includes(n)) pcbs.push(n);
        else if (etype === "cable" && !cables.includes(n)) cables.push(n);
        else if (etype === "connector" && !connectors.includes(n)) connectors.push(n);
        else if (etype === "test_point" && !testPoints.includes(n)) testPoints.push(n);
        else if (etype === "area" && !areas.includes(n)) areas.push(n);

        const pages = ent.pages || [];
        for (let i = 0; i < pages.length; i++) {
            const refStr = pages[i][0] + " (Pág " + pages[i][1] + ")";
            if (!manualRefs.includes(refStr) && manualRefs.length < 6) manualRefs.push(refStr);
        }
    }

    if (resolvedNodes.length >= 2) {
        const paths = [];
        const commonCounts = {};

        for (let i = 0; i < resolvedNodes.length; i++) {
            for (let j = i + 1; j < resolvedNodes.length; j++) {
                const p = findShortestPath(resolvedNodes[i], resolvedNodes[j]);
                if (p) {
                    paths.push(p);
                    for (let k = 0; k < p.length; k++) {
                        const stepNode = p[k].node;
                        commonCounts[stepNode] = (commonCounts[stepNode] || 0) + 1;
                    }
                }
            }
        }

        const sortedCands = Object.keys(commonCounts).sort((a, b) => {
            const ta = graph.entities[a]?.type === "pcb" ? 3 : 1;
            const tb = graph.entities[b]?.type === "pcb" ? 3 : 1;
            return (commonCounts[b] * 10 + tb) - (commonCounts[a] * 10 + ta);
        });
        const hubNode = sortedCands.length ? sortedCands[0] : resolvedNodes[0];

        const allNodes = new Set(resolvedNodes);
        for (const p of paths) {
            for (const step of p) allNodes.add(step.node);
        }
        for (const n of allNodes) collectNodeHardware(n);

        const traceSteps = paths.length ? paths[0].map(s => s.node) : resolvedNodes;
        return await finalizeTrace({
            found: true,
            hub_node: hubNode,
            resolved_nodes: resolvedNodes,
            trace_diagram: traceSteps.join(" -> "),
            pcbs: pcbs.slice(0, 5),
            cables: cables.slice(0, 5),
            connectors: connectors.slice(0, 6),
            test_points: testPoints.slice(0, 6),
            areas: areas.slice(0, 4),
            manual_references: manualRefs.slice(0, 6),
            confidence: paths.length ? "alta" : "media"
        });
    }

    // 1 solo nodo
    const single = resolvedNodes[0];
    collectNodeHardware(single);
    const neighs = graph.adjacency[single] || [];
    for (let i = 0; i < Math.min(neighs.length, 12); i++) {
        collectNodeHardware(neighs[i][0]);
    }

    const otherPcb = pcbs.find(p => p !== single);
    const targetNeigh = otherPcb || (neighs.length ? neighs[0][0] : null);
    const traceDiag = targetNeigh ? (single + " -> " + targetNeigh) : (single + " (Enfoque Directo)");

    return await finalizeTrace({
        found: true,
        hub_node: single,
        resolved_nodes: [single],
        trace_diagram: traceDiag,
        pcbs: pcbs.slice(0, 5),
        cables: cables.slice(0, 5),
        connectors: connectors.slice(0, 6),
        test_points: testPoints.slice(0, 6),
        areas: areas.slice(0, 4),
        manual_references: manualRefs.slice(0, 6),
        confidence: "alta"
    });
}

const _cancelledRequests = new Set();

self.onmessage = async event => {
    const { id, type, payload } = event.data || {};
    if (type === "cancel") {
        const targetId = (payload && payload.id) || id;
        if (targetId) _cancelledRequests.add(targetId);
        return;
    }
    try {
        let data;
        if (type === "search") data = await searchOffline(payload || {});
        else if (type === "diagnose") data = await diagnoseOffline(payload || {});
        else if (type === "diagnose_graph") data = await diagnoseGraphOffline(payload || {});
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
