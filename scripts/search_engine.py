"""Motor de búsqueda y diagnóstico compartido por la API.

El índice se construye una sola vez al iniciar el proceso. Las coincidencias siguen
siendo textuales, pero se usa un índice invertido para reducir los documentos que
hay que revisar y se normalizan mayúsculas y tildes.
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
ACTION_WORDS = {
    "adjust", "calibrate", "check", "connect", "correct", "disconnect", "ensure",
    "examine", "inspect", "install", "measure", "remove", "replace", "reset",
    "restart", "restore", "set", "verify", "ajustar", "calibrar", "comprobar",
    "corregir", "desconectar", "examinar", "inspeccionar", "reemplazar", "reiniciar",
    "restablecer", "verificar",
}


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


def _context(text: str, query: str, before: int = 140, after: int = 260) -> str:
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


def _code_near_label(text: str, field: str, value_tokens: set[str]) -> bool:
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
        # La búsqueda histórica acepta palabras incompletas ("dose rate mon").
        # El primer término reduce candidatos sin exigir que el último sea un
        # token completo; la comprobación textual posterior decide el resultado.
        first_pool = self.postings.get(query_terms[0]) if query_terms else None
        candidate_ids = set(first_pool) if first_pool is not None else set(range(len(self.documents)))

        manual = normalize(manual).strip()
        if manual:
            candidate_ids.intersection_update(self.manuals.get(manual, []))
        return candidate_ids

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

    def diagnose(self, signals: dict[str, str], limit: int = 6) -> dict:
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
            if document.text.count(". . .") >= 5 or "table of contents" in document.normalized[:500]:
                score *= 0.35
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
                "context": _context(document.text, query_for_context, before=220, after=420),
                "matched_signals": matched_signals,
                "relative_match": relative,
                "matched_count": len(matched_signals),
                "signal_count": total_signals,
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
