"""Motor de búsqueda y diagnóstico para SOLVI.

El índice se construye una vez al iniciar. Las coincidencias son textuales con
índice invertido, normalización de acentos y diferenciación clara entre
búsqueda general (Search) y diagnóstico técnico (Relacionar).

En el diagnóstico:
- Se evalúan múltiples síntomas/señales independientes (hasta 4).
- Se priorizan las páginas y diagramas donde coinciden las señales ingresadas.
- Se extrae e identifica la tarjeta, PCB, área, o componente asociado más próximo.
- Se asigna un nivel de confianza (alta, media, baja) para decidir relevancia del PDF.
- Se descartan páginas de ruido (índices vacíos, tablas de contenido genéricas).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata


TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "al", "and", "are", "as", "at", "be", "by", "con", "de", "del",
    "el", "en", "es", "for", "from", "in", "is", "la", "las", "los", "of",
    "on", "or", "para", "por", "que", "se", "the", "to", "un", "una", "y",
}

# Palabras técnicas de diagnóstico
DIAGNOSTIC_WORDS = {
    "interlock", "inhibit", "error", "fault", "alarm", "failure", "failed",
    "calibration", "encoder", "motor", "beam", "dose", "mlc", "leaf", "gantry",
    "collimator", "monitor", "sensor", "cable", "board", "driver", "power",
    "supply", "voltage", "current", "temperature", "pressure", "vacuum",
    "rf", "klystron", "modulator", "gun", "dose1", "dose2", "pcb", "card",
    "tarjeta", "area", "module", "circuit", "switch", "relay", "valve",
}

MIN_RELATIVE_MATCH_DIAGNOSE = 25
PDF_CONFIDENCE_THRESHOLD = 50


def normalize(value: object) -> str:
    text = str(value or "").lower()
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def tokens(value: object) -> list[str]:
    return TOKEN_RE.findall(normalize(value))


def _query_tokens(value: object) -> list[str]:
    result = []
    for token in tokens(value):
        if token not in STOP_WORDS and (len(token) >= 2 or token.isdigit()):
            if token not in result:
                result.append(token)
    return result


def _phrase_pattern(value: object) -> re.Pattern | None:
    parts = tokens(value)
    if not parts:
        return None
    sep = r"(?:[\W_]+|[\W_]+(?:the|a|an|of|in|to|and|or|de|la|el|del|y|en)[\W_]+)"
    return re.compile(r"\b" + sep.join(re.escape(part) for part in parts) + r"\b")


def _context(text: str, query: str, before: int = 160, after: int = 320) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text)
    cleaned = re.sub(r"[^\w\s\.\,\-\:\;\(\)\/]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    norm_text = normalize(cleaned)
    pat = _phrase_pattern(query)
    match = pat.search(norm_text) if pat else None

    if match:
        position = match.start()
        match_len = match.end() - match.start()
    else:
        norm_query = normalize(query).strip()
        position = norm_text.find(norm_query)
        match_len = len(norm_query)
        if position < 0:
            positions = [norm_text.find(token) for token in _query_tokens(query)]
            positions = [pos for pos in positions if pos >= 0]
            position = min(positions, default=0)

    start = max(0, position - before)
    end = min(len(cleaned), position + max(match_len, 1) + after)
    snippet = cleaned[start:end].strip()
    if start > 0:
        snippet = "... " + snippet
    if end < len(cleaned):
        snippet += " ..."
    return snippet


def _best_line(text: str, signal_tokens: set[str]) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.splitlines()]
    lines = [line for line in lines if 5 <= len(line) <= 180]
    if not lines:
        return "Evidencia relacionada"

    def line_score(line: str) -> tuple[int, int]:
        line_tokens = set(tokens(line))
        return len(signal_tokens & line_tokens), -len(line)

    best = max(lines, key=line_score)
    if line_score(best)[0] == 0:
        best = lines[0]
    return best[:140]


def _extract_associated_components(text: str, signal_tokens: set[str]) -> str:
    """Extrae tarjetas (PCBs), módulos, áreas, cables, conectores, puntos de prueba e ITEMs técnicos."""
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)

    # 1. Items y Números de Parte (Elekta 12NC y códigos ITEM)
    items: list[str] = []
    item_matches = re.findall(
        r"\b(?:ITEM\s*\d+|P\/N\s*[A-Z0-9\-]+|PART\s*NO\.?\s*[A-Z0-9\-]+|45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5})\b",
        cleaned,
        re.IGNORECASE,
    )
    for it in item_matches:
        it_clean = re.sub(r"\s+", " ", it).strip().upper()
        if it_clean not in items:
            items.append(it_clean)

    # 2. Tarjetas / PCBs / Cards / Unidades
    boards: list[str] = []
    board_matches = re.findall(
        r"\b(?:PCB\s+[A-Z0-9]+|AO\d+|AI\s*\d+[A-Z]?|DO\s*\d+|DI\s*\d+|PWA\s+[A-Z0-9]+|PWB\s+[A-Z0-9]+|DIE-[A-Z0-9]+|SCC-[A-Z0-9]+|CPU-[A-Z0-9]+|MOT-[A-Z0-9]+|DRV-[A-Z0-9]+|TMC\b|RTD\b|MLC\b|XVI\b)\b",
        cleaned,
        re.IGNORECASE,
    )
    for b in board_matches:
        b_clean = re.sub(r"\s+", " ", b).strip().upper()
        if b_clean not in boards and len(b_clean) >= 3 and b_clean not in {"PCB", "PWA", "PWB"}:
            boards.append(b_clean)

    # 3. Cables, Arneses y Conectores
    cables: list[str] = []
    cable_matches = re.findall(
        r"\b(?:CABLE\s*[A-Z0-9\-]+|HARNESS\s*[A-Z0-9\-]+|PL\d{1,3}|SK\d{1,3}|TB\d{1,3}|J\d{1,3}|W\d{1,3})\b",
        cleaned,
        re.IGNORECASE,
    )
    for c in cable_matches:
        c_clean = re.sub(r"\s+", " ", c).strip().upper()
        if c_clean not in cables and len(c_clean) >= 2:
            cables.append(c_clean)

    # 4. Puntos de Prueba (TP), Relés, Fusibles y Voltajes
    tps: list[str] = []
    tp_matches = re.findall(
        r"\b(?:TP\d{1,3}|TP_[A-Z0-9]+|RL[AB]?\d{1,3}|FS\d{1,3}|FUSE\s*[A-Z0-9]+|[+\-]?\d+(?:\.\d+)?\s*(?:VDC|VAC|kV))\b",
        cleaned,
        re.IGNORECASE,
    )
    for tp in tp_matches:
        tp_clean = re.sub(r"\s+", " ", tp).strip().upper()
        if tp_clean not in tps:
            tps.append(tp_clean)

    # 5. Áreas / Ubicaciones físicas
    areas: list[str] = []
    area_matches = re.findall(
        r"\b(?:(?:HTCA\s+)?AREA\s+\d+[A-Z]?|RACK\s+[A-Z0-9]+|CABINET\s+[A-Z0-9]+|GANTRY\s+DRUM|PEDESTAL)\b",
        cleaned,
        re.IGNORECASE,
    )
    for a in area_matches:
        a_clean = re.sub(r"\s+", " ", a).strip().upper()
        if a_clean not in areas:
            areas.append(a_clean)

    # 6. Título del subsistema / plano
    subsystem = ""
    title_match = re.search(
        r"(?:^|\n)\s*(?:(?:\d+\.\d+\s+)?([A-Za-z0-9\s\-]+(?:system|interlock[s]?|control|circuit|power|supply|assembly|module|sheet\s+\d+)))",
        cleaned,
        re.IGNORECASE,
    )
    if title_match:
        sub = re.sub(r"\s+", " ", title_match.group(1)).strip()
        if 5 <= len(sub) <= 70:
            subsystem = sub

    parts: list[str] = []
    if boards:
        parts.append("Tarjeta: " + ", ".join(boards[:3]))
    if items:
        parts.append("Señal/Item: " + ", ".join(items[:3]))
    if cables:
        parts.append("Conector/Cable: " + ", ".join(cables[:3]))
    if tps:
        parts.append("TP/Medición: " + ", ".join(tps[:2]))
    if areas:
        parts.append("Ubicación: " + ", ".join(areas[:2]))
    if subsystem:
        parts.append("Subsistema: " + subsystem)

    return " · ".join(parts) if parts else "Componente documentado en manual"


def _is_noise_page(document_normalized: str) -> bool:
    """Detecta páginas que son solo índice o tablas de contenido vacías de contenido técnico."""
    if "table of contents" in document_normalized[:400] and len(document_normalized) < 400:
        return True
    if document_normalized[:300].count(". . .") >= 5:
        return True
    return False


def _token_specificity(token: str, postings: dict, total_docs: int) -> float:
    """Calcula qué tan específico es un token: 1.0 = muy específico, 0.0 = muy común."""
    doc_freq = len(postings.get(token, set()))
    if doc_freq == 0:
        return 1.0
    ratio = doc_freq / max(total_docs, 1)
    if ratio > 0.65:
        return 0.0
    if ratio > 0.35:
        return 0.3
    if ratio > 0.15:
        return 0.6
    return 1.0


def _code_near_any_label(text: str, value_tokens: set[str]) -> bool:
    """Verifica si un código numérico aparece cerca de alguna etiqueta técnica."""
    numeric_codes = [token for token in value_tokens if token.isdigit()]
    if not numeric_codes:
        return False
    labels = r"interlock|inhibit|error|fault|alarm|code|item|i\d{1,4}|e\d{1,4}"
    for code in numeric_codes:
        code_pattern = rf"(?:i|e|item)?\s*{re.escape(code)}"
        if re.search(rf"\b(?:{labels})\b[\W_]{{0,30}}\b{code_pattern}\b", text):
            return True
        if re.search(rf"\b{code_pattern}\b[\W_]{{0,30}}\b(?:{labels})\b", text):
            return True
    return False


@dataclass(frozen=True)
class IndexedDocument:
    manual: str
    page: int
    text: str
    normalized: str
    token_set: frozenset[str]


class SearchEngine:
    def __init__(self, records: list[dict]):
        self.documents: list[IndexedDocument] = []
        self.postings: dict[str, set[int]] = defaultdict(set)
        self.manuals: dict[str, list[int]] = defaultdict(list)

        for record in records:
            text = str(record.get("text", ""))
            manual = str(record.get("manual", "")).strip().lower()
            try:
                page = int(record.get("page", 0))
            except (TypeError, ValueError):
                continue
            token_set = frozenset(tokens(text))
            document_id = len(self.documents)
            self.documents.append(
                IndexedDocument(manual, page, text, normalize(text), token_set)
            )
            self.manuals[manual].append(document_id)
            for token in token_set:
                if len(token) >= 2 or token.isdigit():
                    self.postings[token].add(document_id)

    def _candidate_ids(self, query: str, manual: str = "") -> set[int]:
        query_terms = _query_tokens(query)
        if not query_terms:
            query_terms = tokens(query)
        if not query_terms:
            candidates = set(range(len(self.documents)))
        else:
            term_postings = []
            for t in query_terms:
                if t in self.postings:
                    term_postings.append(self.postings[t])
                else:
                    # Cada palabra exacta debe existir en el vocabulario de manuales
                    return set()

            term_postings.sort(key=len)
            # Intersección estricta: todos los términos de la consulta deben coincidir
            candidates = set.intersection(*term_postings)

        manual = normalize(manual).strip()
        if manual:
            candidates.intersection_update(self.manuals.get(manual, []))
        return candidates

    # ─── BÚSQUEDA GENERAL (SEARCH TAB) ───────────────────────────────────────

    def search(self, query: str, manual: str = "", offset: int = 0, limit: int = 25) -> dict:
        q_tokens = tokens(query)
        if not q_tokens:
            return {"results": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

        phrase_pattern = _phrase_pattern(query)
        if not phrase_pattern:
            return {"results": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

        ranked = []
        for document_id in self._candidate_ids(query, manual):
            document = self.documents[document_id]

            # Buscar todas las coincidencias exactas con límites de palabra (\b)
            matches = list(phrase_pattern.finditer(document.normalized))
            if not matches:
                continue

            occurrences = len(matches)
            score = occurrences * 50.0

            # Priorizar documentos donde la coincidencia exacta aparece más arriba
            first_position = matches[0].start()
            score += max(0.0, 10.0 - (first_position / 500.0))

            ranked.append((score, document))

        ranked.sort(key=lambda item: (-item[0], item[1].manual, item[1].page))
        total = len(ranked)
        page_items = ranked[offset:offset + limit]
        return {
            "results": [
                {
                    "type": "manual",
                    "manual": document.manual,
                    "page": document.page,
                    "context": _context(document.text, query),
                }
                for _, document in page_items
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }


    # ─── DIAGNÓSTICO LEGACY (CAMPOS NOMBRADOS) ───────────────────────────────

    def diagnose(self, signals: dict[str, str], limit: int = 3) -> dict:
        symptom_list = [v for k, v in signals.items() if v]
        return self.diagnose_symptoms(symptom_list, limit=limit)

    # ─── DIAGNÓSTICO POR SÍNTOMAS / SEÑALES (RELACIONAR TAB) ─────────────────

    def diagnose_symptoms(self, symptoms: list[str], limit: int = 3) -> dict:
        """Diagnóstico relacional: busca dónde se conectan y convergen los síntomas ingresados."""
        weights_by_position = [1.4, 1.3, 1.2, 1.1]
        prepared = []
        all_signal_tokens: set[str] = set()
        candidate_ids: set[int] = set()
        total_docs = len(self.documents)

        for i, raw_value in enumerate(symptoms[:4]):
            value = str(raw_value or "").strip()
            if not value:
                continue
            value_tokens = set(_query_tokens(value))
            if not value_tokens:
                continue

            # Priorizar tokens específicos (no stopwords ni palabras ultracomunes)
            specific_tokens = {
                t for t in value_tokens
                if _token_specificity(t, self.postings, total_docs) > 0.0
            }
            if not specific_tokens:
                specific_tokens = value_tokens

            weight = weights_by_position[i] if i < len(weights_by_position) else 1.0
            label = f"symptom_{i + 1}"
            
            # Precompilar expresiones regulares para códigos numéricos
            numeric_codes = [t for t in specific_tokens if t.isdigit()]
            code_regexes = []
            if numeric_codes:
                labels = r"interlock|inhibit|error|fault|alarm|code|item|i\d{1,4}|e\d{1,4}"
                for code in numeric_codes:
                    code_pattern = rf"(?:i|e|item)?\s*{re.escape(code)}"
                    code_regexes.append(re.compile(rf"\b(?:{labels})\b[\W_]{{0,30}}\b{code_pattern}\b"))
                    code_regexes.append(re.compile(rf"\b{code_pattern}\b[\W_]{{0,30}}\b(?:{labels})\b"))

            prepared.append((label, value, normalize(value), value_tokens, specific_tokens, weight, code_regexes))
            all_signal_tokens.update(specific_tokens)

            for token in specific_tokens:
                candidate_ids.update(self.postings.get(token, set()))

        if not prepared:
            return {
                "results": [],
                "signals": [],
                "message": "Ingresa al menos un código, señal o síntoma específico.",
            }

        ranked = []
        for document_id in candidate_ids:
            document = self.documents[document_id]
            if _is_noise_page(document.normalized):
                continue

            score = 0.0
            matched_signals = []
            matched_tokens: set[str] = set()

            for name, value, normalized_value, value_tokens, specific_tokens, weight, code_regexes in prepared:
                hits_specific = specific_tokens & document.token_set
                hits_all = value_tokens & document.token_set
                if not hits_specific and not hits_all:
                    continue

                hits = hits_specific or hits_all
                coverage = len(hits) / max(len(specific_tokens), 1)
                exact_phrase = normalized_value in document.normalized
                code_match = any(rgx.search(document.normalized) for rgx in code_regexes) if code_regexes else False

                signal_score = len(hits) * 6 + coverage * 16
                if exact_phrase:
                    signal_score += 45
                elif code_match:
                    signal_score += 35

                score += signal_score * weight
                matched_signals.append({
                    "field": name,
                    "value": value,
                    "coverage": round(coverage, 2),
                })
                matched_tokens.update(hits)

            if not matched_signals:
                continue

            # Bonificación masiva por convergencia: páginas donde coinciden 2, 3 o 4 señales
            coincidence_count = len(matched_signals)
            if coincidence_count > 1:
                score += (coincidence_count - 1) * 60  # Premia fuertemente páginas con múltiples señales

            # Bonificación por densidad de componentes/términos técnicos
            diag_hits = len(DIAGNOSTIC_WORDS & document.token_set)
            score += min(diag_hits, 8) * 2.0

            ranked.append((score, document, matched_signals, matched_tokens))

        ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1].manual, item[1].page))

        # Seleccionar los mejores sin duplicar páginas idénticas
        selected = []
        seen: set[tuple] = set()
        for score, document, matched_signals, matched_tokens in ranked:
            title = _best_line(document.text, all_signal_tokens)
            dedupe_key = (document.manual, document.page)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            selected.append((score, document, matched_signals, matched_tokens, title))
            if len(selected) >= limit:
                break

        if not selected:
            return {
                "results": [],
                "signals": [item[1] for item in prepared],
                "message": "No se encontraron relaciones directas en los manuales para las señales ingresadas.",
            }

        max_score = selected[0][0]
        total_signals = len(prepared)
        results = []

        for score, document, matched_signals, matched_tokens, title in selected:
            query_for_context = " ".join(matched_tokens) or next(iter(all_signal_tokens), "")
            completeness = len(matched_signals) / total_signals
            relative = max(1, min(99, round((score / max_score) * (45 + 54 * completeness))))

            # Extraer tarjeta / PCB / área / componente asociado
            associated_comp = _extract_associated_components(document.text, all_signal_tokens)

            confidence = "alta" if relative >= 75 else "media" if relative >= PDF_CONFIDENCE_THRESHOLD else "baja"
            pdf_relevant = relative >= MIN_RELATIVE_MATCH_DIAGNOSE and confidence != "baja"

            if relative < MIN_RELATIVE_MATCH_DIAGNOSE:
                continue

            results.append({
                "type": "manual",
                "title": title,
                "manual": document.manual,
                "page": document.page,
                "context": _context(document.text, query_for_context, before=260, after=480),
                "associated_component": associated_comp,  # Tarjeta / Componente asociado
                "matched_signals": matched_signals,
                "relative_match": relative,
                "confidence": confidence,
                "pdf_relevant": pdf_relevant,
                "matched_count": len(matched_signals),
                "signal_count": total_signals,
            })

        if not results:
            return {
                "results": [],
                "signals": [item[1] for item in prepared],
                "message": "Las coincidencias encontradas no tienen suficiente relevancia. Intenta con códigos de señal más específicos.",
            }

        best_matched_count = max(r["matched_count"] for r in results)
        return {
            "results": results,
            "signals": [item[1] for item in prepared],
            "message": (
                "" if best_matched_count == total_signals
                else "No todas las páginas reúnen todos los síntomas; se muestran las conexiones más relevantes."
                if len(results) > 1
                else ""
            ),
        }
