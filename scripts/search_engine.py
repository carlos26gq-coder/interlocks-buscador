"""Motor de búsqueda y diagnóstico para SOLVI.

El índice se construye una vez al iniciar. Las coincidencias son textuales con
índice invertido, normalización de acentos y diferenciación clara entre
búsqueda general (Search) y diagnóstico técnico (Relacionar).

En el diagnóstico:
- Se exige que los tokens de cada síntoma sean específicos (no comunes).
- Se extraen frases de acción/solución para mostrar qué hacer.
- Se asigna un nivel de confianza que determina si el PDF es relevante.
- Se filtran resultados de baja calidad (tablas de contenido, índices, etc.).
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
# Palabras de acción/solución — indican páginas diagnósticas reales
ACTION_WORDS = {
    "adjust", "calibrate", "check", "connect", "correct", "disconnect", "ensure",
    "examine", "inspect", "install", "measure", "remove", "replace", "reset",
    "restart", "restore", "set", "verify", "ajustar", "calibrar", "comprobar",
    "corregir", "desconectar", "examinar", "inspeccionar", "reemplazar", "reiniciar",
    "restablecer", "verificar",
}
# Patrón para detectar frases con instrucciones/diagnóstico
_ACTION_PATTERN = re.compile(
    r"\b(?:check|verify|replace|reset|calibrate|inspect|ensure|adjust|connect|"
    r"disconnect|remove|install|measure|restore|comprobar|verificar|reemplazar|"
    r"reiniciar|calibrar|inspeccionar|ajustar|revisar|cambiar|limpiar|corregir|"
    r"ensure|should|must|cause[ds]?|due to|result[s]? from|indicates?|suggest[s]?)\b",
    re.IGNORECASE,
)
# Palabras técnicas de diagnóstico — tokens con alto valor diagnóstico
DIAGNOSTIC_WORDS = {
    "interlock", "inhibit", "error", "fault", "alarm", "failure", "failed",
    "calibration", "encoder", "motor", "beam", "dose", "mlc", "leaf", "gantry",
    "collimator", "monitor", "sensor", "cable", "board", "driver", "power",
    "supply", "voltage", "current", "temperature", "pressure", "vacuum",
    "rf", "klystron", "modulator", "gun", "dose1", "dose2",
}
# Umbral mínimo de confianza para considerar un resultado útil
MIN_RELATIVE_MATCH_DIAGNOSE = 28
# Si relative_match >= este valor, el PDF es definitivamente relevante
PDF_CONFIDENCE_THRESHOLD = 52


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
        if token not in STOP_WORDS and (len(token) >= 3 or token.isdigit()):
            if token not in result:
                result.append(token)
    return result


def _phrase_pattern(value: object) -> re.Pattern | None:
    parts = tokens(value)
    if not parts:
        return None
    return re.compile(r"\b" + r"[\W_]+".join(re.escape(part) for part in parts) + r"\b")


def _context(text: str, query: str, before: int = 180, after: int = 380) -> str:
    normalized_text = normalize(text)
    normalized_query = normalize(query)
    position = normalized_text.find(normalized_query)
    if position < 0:
        positions = [normalized_text.find(token) for token in _query_tokens(query)]
        positions = [pos for pos in positions if pos >= 0]
        position = min(positions, default=0)
    start = max(0, position - before)
    end = min(len(text), position + max(len(query), 1) + after)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if start:
        snippet = "... " + snippet
    if end < len(text):
        snippet += " ..."
    return snippet


def _best_line(text: str, signal_tokens: set[str]) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
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


def _extract_action_sentences(text: str, signal_tokens: set[str], max_sentences: int = 2) -> str:
    """Extrae las frases más relevantes con instrucciones/diagnóstico del texto.

    Prioriza frases que contengan palabras de acción Y tokens del síntoma.
    Retorna un resumen de hasta `max_sentences` frases separadas por espacio.
    """
    # Dividir en oraciones usando puntuación
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    sentences = [re.sub(r"\s+", " ", s).strip() for s in raw_sentences]
    sentences = [s for s in sentences if 18 <= len(s) <= 320]

    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        sentence_tokens = set(tokens(sentence))
        token_hits = len(signal_tokens & sentence_tokens)
        action_hits = len(_ACTION_PATTERN.findall(sentence))
        diagnostic_hits = len(DIAGNOSTIC_WORDS & sentence_tokens)
        total = token_hits * 4 + action_hits * 3 + diagnostic_hits * 2
        if total >= 4:  # Solo frases con suficiente densidad diagnóstica
            scored.append((total, sentence))

    scored.sort(key=lambda x: -x[0])
    if scored:
        # Evitar duplicados muy similares (primeros 40 chars)
        seen_starts: set[str] = set()
        unique: list[str] = []
        for _, s in scored:
            key = normalize(s[:40])
            if key not in seen_starts:
                seen_starts.add(key)
                unique.append(s)
            if len(unique) >= max_sentences:
                break
        return " ".join(unique)
    return ""


def _is_noise_page(document_normalized: str) -> bool:
    """Detecta páginas que son índice, tabla de contenidos, listas de partes, etc."""
    if "table of contents" in document_normalized[:500]:
        return True
    if document_normalized[:300].count(". . .") >= 3:
        return True
    # Páginas con muchos números aislados (listas de partes)
    digit_only_lines = len(re.findall(r"(?:^|\n)\s*[\d\s\-\.]+\s*(?:\n|$)", document_normalized[:400]))
    if digit_only_lines >= 5:
        return True
    return False


def _token_specificity(token: str, postings: dict, total_docs: int) -> float:
    """Qué tan específico es un token: 1.0 = muy raro, 0.0 = muy común."""
    doc_freq = len(postings.get(token, set()))
    if doc_freq == 0:
        return 1.0
    # IDF simplificado
    ratio = doc_freq / max(total_docs, 1)
    if ratio > 0.60:
        return 0.0   # Aparece en >60% de docs → token sin valor diagnóstico
    if ratio > 0.35:
        return 0.3
    if ratio > 0.15:
        return 0.6
    return 1.0


def _code_near_label(text: str, field: str, value_tokens: set[str]) -> bool:
    """Verifica si un código numérico aparece cerca de su etiqueta (interlock/error)."""
    numeric_codes = [token for token in value_tokens if token.isdigit()]
    if not numeric_codes or field not in {"interlock", "error"}:
        return False
    labels = r"interlock|inhibit" if field == "interlock" else r"error|fault"
    for code in numeric_codes:
        code_pattern = rf"(?:i|e)?\s*{re.escape(code)}"
        if re.search(rf"\b(?:{labels})\b[\W_]{{0,20}}\b{code_pattern}\b", text):
            return True
        if re.search(rf"\b{code_pattern}\b[\W_]{{0,20}}\b(?:{labels})\b", text):
            return True
    return False


def _code_near_any_label(text: str, value_tokens: set[str]) -> bool:
    """Verifica si un código numérico aparece cerca de cualquier etiqueta técnica."""
    numeric_codes = [token for token in value_tokens if token.isdigit()]
    if not numeric_codes:
        return False
    labels = r"interlock|inhibit|error|fault|alarm|code|i\d{1,4}|e\d{1,4}"
    for code in numeric_codes:
        code_pattern = rf"(?:i|e)?\s*{re.escape(code)}"
        if re.search(rf"\b(?:{labels})\b[\W_]{{0,25}}\b{code_pattern}\b", text):
            return True
        if re.search(rf"\b{code_pattern}\b[\W_]{{0,25}}\b(?:interlock|inhibit|error|fault|alarm)\b", text):
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
                if len(token) >= 2:
                    self.postings[token].add(document_id)

    def _candidate_ids(self, query: str, manual: str = "") -> set[int]:
        query_terms = _query_tokens(query)
        first_pool = self.postings.get(query_terms[0]) if query_terms else None
        candidate_ids = set(first_pool) if first_pool is not None else set(range(len(self.documents)))
        manual = normalize(manual).strip()
        if manual:
            candidate_ids.intersection_update(self.manuals.get(manual, []))
        return candidate_ids

    # ─── BÚSQUEDA GENERAL ────────────────────────────────────────────────────

    def search(self, query: str, manual: str = "", offset: int = 0, limit: int = 25) -> dict:
        normalized_query = normalize(query).strip()
        phrase_pattern = _phrase_pattern(query)
        ranked = []
        for document_id in self._candidate_ids(query, manual):
            document = self.documents[document_id]
            raw_occurrences = document.normalized.count(normalized_query)
            flexible_matches = list(phrase_pattern.finditer(document.normalized)) if phrase_pattern else []
            if not raw_occurrences and not flexible_matches:
                continue
            occurrences = raw_occurrences or len(flexible_matches)
            first_position = document.normalized.find(normalized_query)
            if first_position < 0 and flexible_matches:
                first_position = flexible_matches[0].start()
            score = occurrences * 10 + max(0, 5 - first_position / 1000)
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

    # ─── DIAGNÓSTICO LEGACY (campos nombrados) ───────────────────────────────

    def diagnose(self, signals: dict[str, str], limit: int = 6) -> dict:
        """Legacy diagnose: acepta campos nombrados (interlock, error, message, observations)."""
        weights = {"interlock": 1.5, "error": 1.5, "message": 1.15, "observations": 0.8}
        prepared = []
        all_signal_tokens: set[str] = set()
        candidate_ids: set[int] = set()

        for name, raw_value in signals.items():
            value = str(raw_value or "").strip()
            if not value:
                continue
            semantic_value = value
            if name == "interlock" and "interlock" not in normalize(value):
                semantic_value = f"interlock {value}"
            elif name == "error" and not ({"error", "fault"} & set(tokens(value))):
                semantic_value = f"error {value}"
            value_tokens = set(_query_tokens(semantic_value))
            if not value_tokens:
                continue
            prepared.append((name, value, normalize(semantic_value), value_tokens, weights.get(name, 1.0)))
            all_signal_tokens.update(value_tokens)
            for token in value_tokens:
                candidate_ids.update(self.postings.get(token, set()))

        if not prepared:
            return {"results": [], "signals": [], "message": "Ingresa al menos un código o síntoma."}

        ranked = []
        for document_id in candidate_ids:
            document = self.documents[document_id]
            if _is_noise_page(document.normalized):
                continue
            score = 0.0
            matched_signals = []
            matched_tokens: set[str] = set()

            for name, value, normalized_value, value_tokens, weight in prepared:
                hits = value_tokens & document.token_set
                if not hits:
                    continue
                specific_tokens = value_tokens - {"interlock", "error", "fault"}
                if specific_tokens and not (hits & specific_tokens):
                    continue
                coverage = len(hits) / len(value_tokens)
                exact_phrase = normalized_value in document.normalized
                code_match = _code_near_label(document.normalized, name, value_tokens)
                if name in {"interlock", "error"} and any(token.isdigit() for token in value_tokens):
                    if not (exact_phrase or code_match):
                        continue
                elif name == "message" and len(value_tokens) > 1 and coverage < 0.5:
                    continue
                elif name == "observations" and len(value_tokens) > 2 and coverage < 0.34:
                    continue
                signal_score = len(hits) * 4 + coverage * 12
                if exact_phrase:
                    signal_score += 35
                elif code_match:
                    signal_score += 28
                score += signal_score * weight
                matched_signals.append({"field": name, "value": value, "coverage": round(coverage, 2)})
                matched_tokens.update(hits)

            if not matched_signals:
                continue
            score += max(0, len(matched_signals) - 1) * 28
            action_hits = ACTION_WORDS & document.token_set
            score += min(len(action_hits), 5) * 1.5
            ranked.append((score, document, matched_signals, matched_tokens))

        ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1].manual, item[1].page))
        selected = []
        seen = set()
        for score, document, matched_signals, matched_tokens in ranked:
            title = _best_line(document.text, all_signal_tokens)
            dedupe_key = (document.manual, normalize(title)[:90])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            selected.append((score, document, matched_signals, matched_tokens, title))
            if len(selected) >= limit:
                break

        max_score = selected[0][0] if selected else 1
        total_signals = len(prepared)
        results = []
        for score, document, matched_signals, matched_tokens, title in selected:
            query_for_context = " ".join(matched_tokens) or next(iter(all_signal_tokens), "")
            completeness = len(matched_signals) / total_signals
            relative = max(1, min(99, round((score / max_score) * (45 + 54 * completeness))))
            results.append({
                "type": "manual",
                "title": title,
                "manual": document.manual,
                "page": document.page,
                "context": _context(document.text, query_for_context, before=260, after=480),
                "matched_signals": matched_signals,
                "relative_match": relative,
                "matched_count": len(matched_signals),
                "signal_count": total_signals,
                "pdf_relevant": relative >= PDF_CONFIDENCE_THRESHOLD,
            })

        best_matched_count = max((len(item[2]) for item in selected), default=0)
        return {
            "results": results,
            "signals": [item[1] for item in prepared],
            "message": (
                "" if results and best_matched_count == total_signals
                else "No se encontró una página que reúna todos los datos; se muestran coincidencias parciales."
                if results
                else "No se encontró una relación suficiente en los manuales."
            ),
        }

    # ─── DIAGNÓSTICO POR SÍNTOMAS LIBRES ─────────────────────────────────────

    def diagnose_symptoms(self, symptoms: list[str], limit: int = 6) -> dict:
        """Diagnóstico por lista libre de síntomas/errores (hasta 4).

        A diferencia de la búsqueda general:
        - Exige que los tokens sean específicos (no muy comunes en el índice).
        - Para códigos numéricos: requiere proximidad con etiqueta técnica.
        - Para texto: requiere cobertura mínima del 55%.
        - Extrae frases de acción/solución para cada resultado.
        - Asigna nivel de confianza y decide si el PDF es relevante.
        - Filtra páginas de índice, tabla de contenidos, listas de partes.
        """
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

            # Filtrar tokens demasiado comunes (aparecen en >60% de páginas)
            specific_tokens = {
                t for t in value_tokens
                if _token_specificity(t, self.postings, total_docs) > 0.0
            }
            if not specific_tokens:
                continue  # Todos los tokens son ruido — síntoma demasiado genérico

            weight = weights_by_position[i] if i < len(weights_by_position) else 1.0
            label = f"symptom_{i + 1}"
            prepared.append((label, value, normalize(value), value_tokens, specific_tokens, weight))
            all_signal_tokens.update(specific_tokens)

            # Usar solo tokens específicos para buscar candidatos
            for token in specific_tokens:
                candidate_ids.update(self.postings.get(token, set()))

        if not prepared:
            return {
                "results": [],
                "signals": [],
                "message": "Los síntomas ingresados son demasiado genéricos. Ingresa códigos de error, interlocks o términos técnicos específicos.",
            }

        ranked = []
        for document_id in candidate_ids:
            document = self.documents[document_id]

            # Descartar páginas de baja calidad diagnóstica
            if _is_noise_page(document.normalized):
                continue

            score = 0.0
            matched_signals = []
            matched_tokens: set[str] = set()

            for name, value, normalized_value, value_tokens, specific_tokens, weight in prepared:
                hits_all = value_tokens & document.token_set
                hits_specific = specific_tokens & document.token_set
                if not hits_specific:
                    continue  # Ningún token específico del síntoma aparece aquí

                coverage_specific = len(hits_specific) / len(specific_tokens)
                coverage_all = len(hits_all) / max(len(value_tokens), 1)
                exact_phrase = normalized_value in document.normalized
                has_numeric = any(t.isdigit() for t in specific_tokens)
                code_match = _code_near_any_label(document.normalized, specific_tokens) if has_numeric else False

                # Reglas de aceptación estrictas:
                if has_numeric and len(specific_tokens) <= 3:
                    # Código corto (ej. "Interlock 283") — REQUIERE proximidad exacta
                    if not (exact_phrase or code_match):
                        continue
                elif has_numeric and len(specific_tokens) > 3:
                    # Código + descripción — requiere el código próximo O alta cobertura
                    if not (exact_phrase or code_match) and coverage_specific < 0.55:
                        continue
                else:
                    # Solo texto — requiere cobertura significativa de tokens específicos
                    if coverage_specific < 0.55:
                        continue

                # Penalizar si los tokens específicos son comunes en este corpus
                specificity_bonus = sum(
                    _token_specificity(t, self.postings, total_docs)
                    for t in hits_specific
                ) / max(len(hits_specific), 1)

                signal_score = len(hits_specific) * 5 + coverage_specific * 15 + specificity_bonus * 8
                if exact_phrase:
                    signal_score += 40
                elif code_match:
                    signal_score += 32

                score += signal_score * weight
                matched_signals.append({
                    "field": name,
                    "value": value,
                    "coverage": round(coverage_specific, 2),
                })
                matched_tokens.update(hits_specific)

            if not matched_signals:
                continue

            score += max(0, len(matched_signals) - 1) * 30
            # Bonificación fuerte por densidad de palabras de acción (páginas de diagnóstico/reparación)
            action_hits = ACTION_WORDS & document.token_set
            action_bonus = min(len(action_hits), 8) * 2.5
            score += action_bonus
            # Bonificación por palabras técnicas de diagnóstico
            diagnostic_hit_count = len(DIAGNOSTIC_WORDS & document.token_set)
            score += min(diagnostic_hit_count, 6) * 1.8

            ranked.append((score, document, matched_signals, matched_tokens))

        ranked.sort(key=lambda item: (-item[0], -len(item[2]), item[1].manual, item[1].page))

        # Seleccionar los mejores sin duplicados
        selected = []
        seen: set[tuple] = set()
        for score, document, matched_signals, matched_tokens in ranked:
            title = _best_line(document.text, all_signal_tokens)
            dedupe_key = (document.manual, normalize(title)[:90])
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
                "message": "No se encontró evidencia suficientemente específica en los manuales para estos síntomas.",
            }

        max_score = selected[0][0]
        total_signals = len(prepared)
        results = []

        for score, document, matched_signals, matched_tokens, title in selected:
            query_for_context = " ".join(matched_tokens) or next(iter(all_signal_tokens), "")
            completeness = len(matched_signals) / total_signals
            relative = max(1, min(99, round((score / max_score) * (45 + 54 * completeness))))

            # Extraer frases con acción/solución (el valor añadido clave)
            action_summary = _extract_action_sentences(document.text, all_signal_tokens, max_sentences=2)

            # Nivel de confianza claro
            if relative >= 75:
                confidence = "alta"
            elif relative >= PDF_CONFIDENCE_THRESHOLD:
                confidence = "media"
            else:
                confidence = "baja"

            # El PDF solo se muestra si la confianza es media o alta
            pdf_relevant = relative >= MIN_RELATIVE_MATCH_DIAGNOSE and confidence in {"alta", "media"}

            # Filtro final: descartar resultados de confianza muy baja
            if relative < MIN_RELATIVE_MATCH_DIAGNOSE:
                continue

            results.append({
                "type": "manual",
                "title": title,
                "manual": document.manual,
                "page": document.page,
                "context": _context(document.text, query_for_context, before=260, after=480),
                "action_summary": action_summary,  # Frases de acción/solución
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
                "message": "Las coincidencias encontradas no tienen suficiente relevancia diagnóstica. Intenta con códigos de error más específicos.",
            }

        best_matched_count = max(r["matched_count"] for r in results)
        return {
            "results": results,
            "signals": [item[1] for item in prepared],
            "message": (
                "" if best_matched_count == total_signals
                else "No todas las páginas reúnen todos los síntomas; se muestran las más relevantes."
                if len(results) > 1
                else ""
            ),
        }
