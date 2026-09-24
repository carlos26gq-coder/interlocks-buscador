"""Motor de búsqueda y diagnóstico para SOLVI.

El índice se construye una vez al iniciar. Las coincidencias son textuales con
índice invertido, normalización de acentos y diferenciación clara entre
búsqueda general (Search) y diagnóstico técnico (Relacionar).

En el diagnóstico:
- Se evalúan múltiples síntomas/señales independientes (hasta 5).
- Se priorizan las páginas y diagramas donde coinciden las señales ingresadas.
- Se extrae e identifica la tarjeta, PCB, área, o componente asociado más próximo.
- Se asigna un nivel de confianza (alta, media, baja) para decidir relevancia del PDF.
- Se descartan páginas de ruido (índices vacíos, tablas de contenido genéricas).
"""

from __future__ import annotations

import functools
import re
import threading
import unicodedata
from collections import OrderedDict, defaultdict
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[a-z0-9]+")
_RE_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_RE_PUNCT_CLEAN = re.compile(r"[^\w\s\.\,\-\:\;\(\)\/]")
_RE_WHITESPACE = re.compile(r"\s+")
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
LEGACY_SIGNAL_FIELDS = ("interlock", "error", "message", "observations")

MIN_RELATIVE_MATCH_DIAGNOSE = 25
PDF_CONFIDENCE_THRESHOLD = 50
MAX_SEARCH_LATENCY_WARMED_MS: float = 5.0
MAX_SEARCH_LATENCY_COLD_MS: float = 50.0



def normalize(value: object) -> str:
    text = str(value or "").lower()
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


@functools.lru_cache(maxsize=2048)
def _tokens_cached(text: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(normalize(text)))


def tokens(value: object) -> list[str]:
    if isinstance(value, str) and len(value) < 128:
        return list(_tokens_cached(value))
    return TOKEN_RE.findall(normalize(value))


@functools.lru_cache(maxsize=1024)
def _query_tokens_cached(text: str) -> tuple[str, ...]:
    result = []
    for token in tokens(text):
        if token not in STOP_WORDS and (len(token) >= 2 or token.isdigit()):
            if token not in result:
                result.append(token)
    return tuple(result)


def _query_tokens(value: object) -> list[str]:
    if isinstance(value, str) and len(value) < 128:
        return list(_query_tokens_cached(value))
    result = []
    for token in tokens(value):
        if token not in STOP_WORDS and (len(token) >= 2 or token.isdigit()):
            if token not in result:
                result.append(token)
    return result


@functools.lru_cache(maxsize=1024)
def _phrase_pattern_cached(val: str) -> re.Pattern | None:
    parts = tokens(val)
    if not parts:
        return None
    # Deduplicar tokens consecutivos idénticos para eliminar ReDoS por backtracking exponencial
    deduped: list[str] = []
    for p in parts:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    parts = deduped[:16]
    sep = r"[\W_]+(?:(?:the|a|an|of|in|to|and|or|de|la|el|del|y|en)[\W_]+)?"
    return re.compile(r"\b" + sep.join(re.escape(part) for part in parts) + r"\b")


def _phrase_pattern(value: object) -> re.Pattern | None:
    if isinstance(value, str):
        return _phrase_pattern_cached(value)
    parts = tokens(value)
    if not parts:
        return None
    deduped: list[str] = []
    for p in parts:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    parts = deduped[:16]
    sep = r"[\W_]+(?:(?:the|a|an|of|in|to|and|or|de|la|el|del|y|en)[\W_]+)?"
    return re.compile(r"\b" + sep.join(re.escape(part) for part in parts) + r"\b")


def _context(text: str, query: str, before: int = 160, after: int = 320) -> str:
    cleaned = _RE_CONTROL_CHARS.sub(" ", text)
    cleaned = _RE_PUNCT_CLEAN.sub(" ", cleaned)
    cleaned = _RE_WHITESPACE.sub(" ", cleaned).strip()

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
    snippet = _clean_text_no_ai(snippet)
    if start > 0:
        snippet = "... " + snippet
    if end < len(cleaned):
        snippet += " ..."
    return snippet


def _clean_text_no_ai(text: str) -> str:
    """Elimina menciones de IA/AI preservando tarjetas legítimas de Entrada Analógica (AI12, AI8)."""
    if not text:
        return ""
    # Si es una tarjeta de Entrada Analógica tipo 'AI 12' o 'AI 8', normalizar a 'AI12' (sin espacio)
    s = re.sub(r"\bAI\s*(\d+[A-Za-z\-]*)\b", r"AI\1", text)
    # Reemplazar menciones sueltas de IA / AI / Inteligencia Artificial
    s = re.sub(r"\b(?:Inteligencia\s+Artificial|IA|AI)\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _best_line(text: str, signal_tokens: set[str]) -> str:
    # Preservar CR/LF para que Python y el worker evalúen las mismas líneas.
    cleaned = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.splitlines()]
    lines = [line for line in lines if 5 <= len(line) <= 180]
    if not lines:
        return "Evidencia relacionada"

    expanded_tokens: set[str] = set()
    for tok in signal_tokens:
        expanded_tokens.add(tok.lower())
        for sub in tokens(tok):
            expanded_tokens.add(sub.lower())

    generic_stops = {"the", "a", "an", "of", "in", "to", "and", "or", "for", "with", "from", "at", "on", "by", "is", "it", "as", "de", "la", "el", "en"}
    expanded_tokens -= generic_stops

    tech_words = {
        "interlock", "inhibit", "contactor", "relay", "rele", "fault", "error", "switch",
        "sensor", "transformer", "circuit", "board", "pcb", "fuse", "power", "supply",
        "monitor", "safety", "voltage", "current", "trips", "limits", "dose", "rate", "vacuum", "rf"
    }

    def line_score(line: str) -> tuple[int, float, int]:
        norm_l = line.lower()
        line_toks = set(tokens(norm_l))
        hits = len((expanded_tokens & line_toks) - generic_stops)
        phrase_hits = sum(1 for tok in signal_tokens if len(tok) >= 3 and tok.lower() in norm_l)
        total_hits = hits + phrase_hits * 2

        if total_hits == 0:
            return (0, -100.0, -len(line))

        # Penalizar fuertemente números puros, códigos de dibujo, encabezados de tabla o líneas con puntos suspensivos (TOC)
        is_heading_noise = bool(re.match(r"^(?:table|tabla|figure|figura|section|secci[oó]n|\d+[\.\d]*)\b", norm_l, re.I)) and len(line) < 32
        is_pure_id = bool(re.fullmatch(r"[\d\s\-_/.]+", line))
        has_dot_leader = bool(re.search(r"(?:\.\s*){4,}", line))
        penalty = -45.0 if has_dot_leader else (-25.0 if (is_heading_noise or is_pure_id) else 0.0)

        # Bonificación por contexto técnico y longitud de oración informativa
        tech_bonus = min(len(line_toks & tech_words) * 2.5, 8.0)
        len_score = 5.0 if 30 <= len(line) <= 110 else (3.0 if 15 <= len(line) < 30 else 1.0)

        total_qual = penalty + tech_bonus + len_score
        return (total_hits, total_qual, len(line))

    best = max(lines, key=line_score)
    if line_score(best)[0] == 0:
        candidates = [
            l for l in lines
            if not re.match(r"^(?:[0-9\.\-_/]+|copyright.*|©.*)$", l.lower()) and len(l) >= 15
        ]
        best = candidates[0] if candidates else lines[0]
    clean_best = re.sub(r"(?:\s*\.){3,}.*$", "", best).strip()
    if len(clean_best) >= 10:
        best = clean_best
    return _clean_text_no_ai(best)[:140]


INVALID_BOARDS = {
    "PCB", "PWA", "PWB", "PCB IDENTIFICATION", "PCB ASSY", "PCB ASSEMBLY",
    "PCB LAYOUT", "PCB DRAWING", "PCB SCHEMATIC", "PCB CONNECTIONS", "PCB MOUNTING",
    "PCB AREA", "PCB POSITION", "PCB DESCRIPTION", "PCB TITLE", "PCB DETAILS",
    "PCB NUMBER", "PCB REF", "PCB REFERENCE", "PCB NAME", "PCB REV", "PCB REVISION",
    "PCB CODE", "PCB STATUS", "PCB SYSTEM", "PCB CIRCUIT", "PCB SUB", "PCB PART",
    "PCB PCB", "PCB P4", "PCB FS17B", "PCB 72H", "PCB 74", "PCB RACK", "PCB CABINET",
    "PCB FRAME", "PCB CHASSIS", "PCB ITEM",
}

_INVALID_PCB_SUBTITLES = {
    "AREA", "POSITION", "DESCRIPTION", "TITLE", "DETAILS", "NUMBER", "REF",
    "REFERENCE", "NAME", "REV", "REVISION", "CODE", "STATUS", "SYSTEM",
    "CIRCUIT", "SUB", "ASSY", "ASSEMBLY", "MOUNTING", "IDENTIFICATION", "PART",
    "PROGRAMMING", "PRINTED", "RETRACTILE", "FPGA", "LAYOUT", "DRAWING",
    "SCHEMATIC", "CONNECTIONS", "FUSE", "RELAY", "SWITCH", "TERMINAL",
    "CONNECTOR", "ISOLATION", "DETECTOR", "CROWBAR", "PCB", "RACK", "CABINET",
    "FRAME", "CHASSIS", "ITEM", "BOX", "PANEL", "GRID",
    "THROUGH", "IF", "SETS", "SENSES", "IS", "AND", "SUPPLIES", "MONITORS", "AS",
    "TO", "IN", "FOR", "WITH", "THAT", "WHEN", "WHERE", "BY", "FROM", "ON", "AT",
    "OR", "AN", "THE", "NOT", "CAN", "MAY", "WILL", "DOES", "HAS", "HAVE", "GIVES",
    "USES", "SHOWS", "OPERATES", "PREVENTS", "STOP", "STOPS", "CARRIES", "ENABLES",
    "PROVIDES", "GENERATES", "RECEIVES", "SENDS", "TRANSMITS", "DETECTS", "OUTPUT",
    "INPUT", "SIGNAL", "SIGNALS", "DIE", "PPG", "PRF",
}


def extract_structured_components(text: str) -> dict[str, list[str] | str]:
    """Extrae componentes estructurados y limpios (tarjetas, cables, señales, puntos de prueba y subsistema)."""
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text or "")[:12000])

    # 1. Items de señal y supervisión (solo códigos funcionales ITEM <num> o i<num>; excluye planos 1024xxx y 4513...)
    items: list[str] = []
    item_matches = re.findall(
        r"\b(?:ITEM\s*\d{1,4}|i\d{1,4})\b",
        cleaned,
        re.IGNORECASE,
    )
    for it in item_matches:
        m_i = re.match(r"^i(\d{1,4})$", it, re.I)
        if m_i:
            it_clean = f"ITEM {int(m_i.group(1))}"
        else:
            m_num = re.search(r"\d+", it)
            it_clean = f"ITEM {int(m_num.group(0))}" if m_num else it.upper()
        if it_clean not in items:
            items.append(it_clean)

    # 1b. Planos y esquemas técnicos (1024xxx, 4513..., P/N) - clasificados como planos, NUNCA como señales funcionales
    drawings: list[str] = []
    drawing_matches = re.findall(
        r"\b(?:45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5}|1024\d{3}|P\/N\s*[A-Z0-9\-]+|PART\s*NO\.?\s*[A-Z0-9\-]+)\b",
        cleaned,
        re.IGNORECASE,
    )
    for dr in drawing_matches:
        dr_clean = re.sub(r"\s+", " ", dr).strip().upper()
        if dr_clean not in drawings:
            drawings.append(dr_clean)

    # 2. Tarjetas / PCBs / Cards / Unidades (con soporte para módulos de potencia y RF)
    boards: list[str] = []
    functional_named_boards = [
        "DIE-HTA", "DIE-HTB", "PCB 16M", "PCB 16N", "PCB 22", "HT ISOLATION PCB", "HT PSU CONTROL PCB",
        "HT CROWBAR DETECTOR PCB", "DRIVER PCB", "ROC-HTA", "AO12-HTA",
        "PPG-HTB", "DIE-RHA", "DIE-RHB", "DIE-ICA", "DIE-ICB", "TS22A",
    ]
    for fb in functional_named_boards:
        if re.search(r"\b" + re.escape(fb) + r"\b", cleaned, re.IGNORECASE):
            if fb not in boards:
                boards.append(fb)

    board_matches = re.findall(
        r"\b(?:PCB\s+[0-9]{1,3}[A-Z]{0,2}|PCB\s+[A-Z0-9]+|AO\d+|AI\s*\d+[A-Z]?|DO\s*\d+|DI\s*\d+|PWA\s+[A-Z0-9]+|PWB\s+[A-Z0-9]+|DIE-[A-Z0-9]+|ROC-[A-Z0-9]+|PPG-[A-Z0-9]+|SCC-[A-Z0-9]+|CPU-[A-Z0-9]+|MOT-[A-Z0-9]+|DRV-[A-Z0-9]+|TMC\b|RTD\b|MLC\b|XVI\b)\b",
        cleaned,
        re.IGNORECASE,
    )
    for b in board_matches:
        b_clean = re.sub(r"\s+", " ", b).strip().upper()
        parts_b = b_clean.split()
        if len(parts_b) >= 2 and parts_b[0] == "PCB":
            sub_part = parts_b[1]
            if sub_part in _INVALID_PCB_SUBTITLES:
                continue
            if re.match(r"^(?:P\d+|FS\d+|PL\d+|SK\d+|TB\d+|SW\d+|TS\d+|CB\d+)$", sub_part):
                continue
            # Rechazar coordenadas de rejilla de esquemas (ej: 72H, 14A, 15B)
            if re.match(r"^\d{2,3}[A-Z]$", sub_part) and sub_part not in {"16M", "16N", "16R", "16H", "16L", "16S", "16C", "17A", "17B", "12D", "12F"}:
                continue
        if b_clean not in boards and len(b_clean) >= 3 and b_clean not in INVALID_BOARDS:
            boards.append(b_clean)

    # 3. Cables, Arneses, Conectores y Terminales (soporta terminales con pin e.g. PL2-a3 y jumpers LK*)
    cables: list[str] = []
    cable_matches = re.findall(
        r"\b(?:CABLE\s*[A-Z0-9\-]+|HARNESS\s*[A-Z0-9\-]+|PL\d{1,3}(?:-[a-z0-9]+)?|SK\d{1,3}(?:-[a-z0-9]+)?|TB\d{1,3}|J\d{1,3}|W\d{1,3}|LK\d{1,3}|LINK\s*\d+)\b",
        cleaned,
        re.IGNORECASE,
    )
    for c in cable_matches:
        c_clean = re.sub(r"\s+", " ", c).strip().upper()
        if c_clean not in cables:
            cables.append(c_clean)
    # 4. Puntos de Prueba (TP), Interruptores Térmicos, Relés, Fusibles, Disyuntores y Señales Críticas
    tps: list[str] = []
    tp_matches = re.findall(
        r"\b(?:TP[U]?[0-9]{1,3}(?:-[0-9]{1,3})?|TS[U]?[0-9]{1,3}[A-Z]?(?:-[0-9]{1,3})?|TP_[A-Z0-9]+|SW[1-9]\d?|TS[1-9]\d?[A-Z]?|CB[1-9]\d?|CON-[A-Z]|CON\s+[A-Z]|CON_[A-Z]_(?:ON|MON)|RL[AB]?[0-9]{1,3}|RLD-1|FS[0-9]{1,3}[A-Z]?|FUSE\s*[A-Z0-9]+|PRI\s+I\s+MON|PRI\s+REF|HT\s+OVERTEMP\s+DETECTOR|RAD_ON|GUN_ON|CROWBAR\s+O\/P|CHARGERATE|[+\-]?\d+(?:\.\d+)?\s*(?:VDC|VAC|kV|mA|A))\b",
        cleaned,
        re.IGNORECASE,
    )
    for tp in tp_matches:
        tp_clean = re.sub(r"\s+", " ", tp).strip().upper()
        if re.match(r"^CON\s+([A-Z])$", tp_clean):
            tp_clean = f"CON-{tp_clean.split()[1]}"
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

    return {
        "boards": boards,
        "items": items,
        "drawings": drawings,
        "cables": cables,
        "tps": tps,
        "areas": areas,
        "subsystem": subsystem,
    }


def _extract_associated_components(text: str, signal_tokens: set[str] | None = None) -> str:
    """Extrae tarjetas (PCBs), módulos, áreas, cables, conectores, puntos de prueba e ITEMs técnicos."""
    comp = extract_structured_components(text)
    boards = comp["boards"]
    items = comp["items"]
    cables = comp["cables"]
    tps = comp["tps"]
    areas = comp["areas"]
    subsystem = comp["subsystem"]

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
    if "table of contents" in document_normalized[:400] and len(document_normalized) < 500:
        return True
    if document_normalized[:500].count(". . .") >= 3 or document_normalized.count(". . .") >= 8:
        return True
    if ("list of figures" in document_normalized[:500] or "list of tables" in document_normalized[:500]) and document_normalized.count(". . .") >= 3:
        return True
    return False


def _token_specificity(token: str, postings: dict, total_docs: int) -> float:
    """Calcula qué tan específico es un token: 1.0 = muy específico, 0.0 = muy común."""
    if total_docs < 10 or token.isdigit() or re.match(r"^[ie]\d+$", token):
        return 1.0
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
            base_tokens = set(tokens(text))
            expanded_tokens = set(base_tokens)
            for tok in base_tokens:
                m_i = re.match(r"^i(\d{1,4})$", tok)
                if m_i:
                    num_str = m_i.group(1)
                    expanded_tokens.add(num_str)
                    expanded_tokens.add(str(int(num_str)))
                m_e = re.match(r"^e(\d{1,4})$", tok)
                if m_e:
                    num_str = m_e.group(1)
                    expanded_tokens.add(num_str)
                    expanded_tokens.add(str(int(num_str)))

            norm_doc = normalize(text)
            # Expansión de acrónimos técnicos y modos operativos clave
            if "over temp" in norm_doc or "overtemp" in norm_doc or "over-temp" in norm_doc or "ht psu ot" in norm_doc:
                expanded_tokens.update(["ot", "psu", "ht", "overtemp"])
            if "vmat" in norm_doc or "volumetric modulated arc" in norm_doc:
                expanded_tokens.add("vmat")
            if "die-hta" in norm_doc or "die hta" in norm_doc:
                expanded_tokens.update(["die-hta", "diehta", "hta"])
            if "die-htb" in norm_doc or "die htb" in norm_doc:
                expanded_tokens.update(["die-htb", "diehtb", "htb"])
            if "die-rha" in norm_doc or "die rha" in norm_doc:
                expanded_tokens.update(["die-rha", "dierha", "rha"])
            if "die-rhb" in norm_doc or "die rhb" in norm_doc:
                expanded_tokens.update(["die-rhb", "dierhb", "rhb"])
            if "pcb 22" in norm_doc or "pcb22" in norm_doc or "ts22a" in norm_doc or "area 22" in norm_doc:
                expanded_tokens.update(["pcb22", "ts22a", "ts22"])
            if "heat exchanger" in norm_doc or "cooling pump" in norm_doc or "chiller" in norm_doc:
                expanded_tokens.update(["exchanger", "chiller", "cooling"])
            if "sw1" in norm_doc or "sw2" in norm_doc or "ts1" in norm_doc or "ts2" in norm_doc:
                expanded_tokens.update(["sw1", "sw2", "ts1", "ts2"])
            if "con-k" in norm_doc or "con k" in norm_doc or "contactor k" in norm_doc or "con_k" in norm_doc:
                expanded_tokens.update(["con-k", "conk", "con_k"])
            if "con-a" in norm_doc or "con a" in norm_doc or "contactor a" in norm_doc:
                expanded_tokens.update(["con-a", "cona"])
            if "con-d" in norm_doc or "con d" in norm_doc or "contactor d" in norm_doc:
                expanded_tokens.update(["con-d", "cond"])
            if "con-j" in norm_doc or "con j" in norm_doc or "contactor j" in norm_doc:
                expanded_tokens.update(["con-j", "conj"])
            for m_item in re.finditer(r"\b(?:item|i)\s*(\d{1,4})\b", norm_doc):
                c_code = m_item.group(1)
                expanded_tokens.add(f"i{c_code}")
                expanded_tokens.add(f"item{c_code}")
                expanded_tokens.add(c_code)
                expanded_tokens.add(str(int(c_code)))

            token_set = frozenset(expanded_tokens)
            document_id = len(self.documents)
            self.documents.append(
                IndexedDocument(manual, page, text, normalize(text), token_set)
            )
            self.manuals[manual].append(document_id)
            for token in token_set:
                if len(token) >= 2 or token.isdigit():
                    self.postings[token].add(document_id)
        self._search_cache: OrderedDict[tuple, dict] = OrderedDict()
        self._search_cache_max: int = 512
        self._search_cache_lock = threading.Lock()

    def _candidate_ids(self, query: str, manual: str = "") -> set[int]:
        norm_q = normalize(query)
        if re.search(r"\b(?:ht[\s\-_]+)?(?:con[\s\-_]*k|contactor[\s\-_]*k)\b", norm_q) or norm_q in ("con k", "con-k", "ht con k", "ht con-k", "contactor k"):
            candidates = set()
            for c_tok in ["con-k", "conk", "con_k", "contactor", "die-hta", "die-htb"]:
                if c_tok in self.postings:
                    candidates.update(self.postings[c_tok])
            if candidates:
                if manual:
                    manual = normalize(manual).strip()
                    if manual:
                        candidates.intersection_update(self.manuals.get(manual, []))
                return candidates

        m_code = re.match(r"^(?:item|interlock|codigo|code|i)?\s*(\d+)$", str(query or "").strip().lower())
        if m_code:
            code_num = str(int(m_code.group(1)))
            candidates = set()
            for tok in [code_num, f"i{code_num}", f"i{int(code_num):03d}", f"{int(code_num):03d}"]:
                if tok in self.postings:
                    candidates.update(self.postings[tok])
            manual = normalize(manual).strip()
            if manual:
                candidates.intersection_update(self.manuals.get(manual, []))
            return candidates

        query_terms = _query_tokens(query)
        if not query_terms:
            query_terms = tokens(query)
        if not query_terms:
            candidates = set(range(len(self.documents)))
        else:
            term_postings = []
            numeric_codes = [t for t in query_terms if t.isdigit()]
            for t in query_terms:
                matching_docs = set()
                if t in self.postings:
                    matching_docs.update(self.postings[t])
                # Expansión para prefijos i\d+ (ej: 475 busca 475 e i475)
                if t.isdigit() and len(t) <= 4:
                    i_tok = f"i{t}"
                    if i_tok in self.postings:
                        matching_docs.update(self.postings[i_tok])
                    i_tok_pad = f"i{int(t):03d}"
                    if i_tok_pad in self.postings:
                        matching_docs.update(self.postings[i_tok_pad])
                # Expansión inversa (ej: i475 busca i475 y 475)
                m_i = re.match(r"^i(\d{1,4})$", t)
                if m_i:
                    num_tok = m_i.group(1)
                    if num_tok in self.postings:
                        matching_docs.update(self.postings[num_tok])
                    clean_num = str(int(num_tok))
                    if clean_num in self.postings:
                        matching_docs.update(self.postings[clean_num])
                # Expansión para prefijos como 'item', 'interlock', 'codigo', 'code'
                # cuando la consulta acompaña un código numérico (ej: 'item 475')
                if t in {"item", "interlock", "codigo", "code"} and numeric_codes:
                    for num in numeric_codes:
                        for prefix in ["i", "e"]:
                            p_tok = f"{prefix}{num}"
                            if p_tok in self.postings:
                                matching_docs.update(self.postings[p_tok])
                            p_tok_pad = f"{prefix}{int(num):03d}"
                            if p_tok_pad in self.postings:
                                matching_docs.update(self.postings[p_tok_pad])

                if matching_docs:
                    term_postings.append(matching_docs)
                else:
                    return set()

            term_postings.sort(key=len)
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

        cache_key = (query, manual, offset, limit)
        with self._search_cache_lock:
            if cache_key in self._search_cache:
                self._search_cache.move_to_end(cache_key)
                hit = self._search_cache[cache_key]
                return {
                    "results": list(hit["results"]),
                    "total": hit["total"],
                    "offset": hit["offset"],
                    "limit": hit["limit"],
                    "has_more": hit["has_more"],
                }

        phrase_pattern = _phrase_pattern(query)
        m_code = re.match(r"^(?:item|interlock|codigo|code|i)?\s*(\d+)$", query.strip().lower())
        if m_code:
            code_num = str(int(m_code.group(1)))
            code_pattern = re.compile(
                rf"\b(?:(?:item\s*|i0*|interlock\s*|code\s*)?{re.escape(code_num)}|i0*{re.escape(code_num)})\b",
                re.IGNORECASE,
            )
        else:
            code_pattern = None

        if not phrase_pattern and not code_pattern:
            return {"results": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

        ranked = []
        for document_id in self._candidate_ids(query, manual):
            document = self.documents[document_id]

            first_match = None
            if code_pattern:
                first_match = code_pattern.search(document.normalized)
            if not first_match and phrase_pattern:
                first_match = phrase_pattern.search(document.normalized)

            if not first_match:
                continue

            first_position = first_match.start()
            active_pat = code_pattern if (code_pattern and code_pattern.search(document.normalized)) else phrase_pattern
            occurrences = len(active_pat.findall(document.normalized)) if active_pat else 1
            score = occurrences * 50.0 + max(0.0, 10.0 - (first_position / 500.0))

            ranked.append((score, document))

        ranked.sort(key=lambda item: (-item[0], item[1].manual, item[1].page))
        total = len(ranked)
        page_items = ranked[offset:offset + limit]
        res = {
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
        with self._search_cache_lock:
            if len(self._search_cache) >= self._search_cache_max:
                self._search_cache.popitem(last=False)
            self._search_cache[cache_key] = res
        return res


    # ─── DIAGNÓSTICO LEGACY (CAMPOS NOMBRADOS) ───────────────────────────────

    def diagnose(self, signals: dict[str, str], limit: int = 3) -> dict:
        symptom_list = [signals.get(field, "") for field in LEGACY_SIGNAL_FIELDS if signals.get(field)]
        return self.diagnose_symptoms(symptom_list, limit=limit)

    # ─── DIAGNÓSTICO POR SÍNTOMAS / SEÑALES (RELACIONAR TAB) ─────────────────

    def diagnose_symptoms(self, symptoms: list[str], limit: int = 5) -> dict:
        """Diagnóstico relacional: busca dónde se conectan y convergen los síntomas ingresados."""
        prepared = []
        all_signal_tokens: set[str] = set()
        candidate_ids: set[int] = set()
        total_docs = len(self.documents)

        for i, raw_value in enumerate(symptoms[:5]):
            value = str(raw_value or "").strip()
            if not value:
                continue
            norm_val = normalize(value)
            value_tokens = set(_query_tokens(value))
            if not value_tokens:
                value_tokens = set(tokens(value))

            # Priorizar tokens específicos (no stopwords ni palabras ultracomunes)
            specific_tokens = {
                t for t in value_tokens
                if _token_specificity(t, self.postings, total_docs) > 0.0 or t.isdigit()
            }
            if not specific_tokens:
                specific_tokens = set(value_tokens)

            # Si el valor completo o normalizado con guión existe en postings (ej: con-k, con-a, die-hta, fs73a)
            if norm_val in self.postings:
                specific_tokens.add(norm_val)
                value_tokens.add(norm_val)
            norm_val_dash = norm_val.replace(" ", "-").replace("_", "-")
            if norm_val_dash in self.postings:
                specific_tokens.add(norm_val_dash)
                value_tokens.add(norm_val_dash)
            norm_val_compact = norm_val.replace(" ", "").replace("-", "").replace("_", "")
            if norm_val_compact in self.postings:
                specific_tokens.add(norm_val_compact)
                value_tokens.add(norm_val_compact)

            # Todas las informaciones y síntomas ingresados tienen prioridad equitativa y alta
            weight = 1.0
            label = f"symptom_{i + 1}"
            
            # Precompilar expresiones regulares y expandir códigos numéricos
            numeric_codes = [t for t in value_tokens if t.isdigit()]
            code_regexes = []
            if numeric_codes:
                labels = r"interlock|inhibit|error|fault|alarm|code|item|i\d{1,4}|e\d{1,4}"
                for code in numeric_codes:
                    clean_c = str(int(code))
                    specific_tokens.add(f"i{clean_c}")
                    specific_tokens.add(f"i{int(clean_c):03d}")
                    specific_tokens.add(clean_c)
                    code_regexes.append(re.compile(rf"\b(?:i0*|item\s*|interlock\s*|code\s*|e0*){re.escape(clean_c)}\b"))
                    code_pattern = rf"(?:i|e|item)?\s*{re.escape(code)}"
                    code_regexes.append(re.compile(rf"\b(?:{labels})\b[\W_]{{0,30}}\b{code_pattern}\b"))
                    code_regexes.append(re.compile(rf"\b{code_pattern}\b[\W_]{{0,30}}\b(?:{labels})\b"))

            if "ht psu" in norm_val or "psu ot" in norm_val or "over temp" in norm_val or "overtemp" in norm_val:
                specific_tokens.update(["ot", "psu", "ht", "overtemp"])
            if "vmat" in norm_val:
                specific_tokens.add("vmat")
            if "die-hta" in norm_val or "die hta" in norm_val:
                specific_tokens.update(["die-hta", "diehta", "hta"])
            if "die-htb" in norm_val or "die htb" in norm_val:
                specific_tokens.update(["die-htb", "diehtb", "htb"])
            if "pcb 22" in norm_val or "pcb22" in norm_val or "area 22" in norm_val:
                specific_tokens.update(["pcb22", "ts22a", "ts22"])
            if "ts1" in norm_val or "ts2" in norm_val or "sw1" in norm_val or "sw2" in norm_val:
                specific_tokens.update(["ts1", "ts2", "sw1", "sw2"])
            if re.search(r"\b(?:ht[\s\-_]+)?(?:con[\s\-_]*k|contactor[\s\-_]*k)\b", norm_val) or norm_val in ("con k", "con-k", "ht con k", "ht con-k", "contactor k"):
                specific_tokens.update(["con-k", "conk", "con_k", "contactor", "die-ica", "dieica", "irc-a", "irc-b", "roc-ica", "1024690", "t1", "fs73a"])
                value_tokens.add("con-k")
            if "79" in numeric_codes or re.search(r"\b(?:item\s*0*79|i0*79)\b", norm_val):
                specific_tokens.update(["i79", "con-k", "conk", "con_k", "die-ica", "dieica", "irc-a", "irc-b", "roc-ica", "area72", "area74"])
            if "con-a" in norm_val or "con a" in norm_val or "contactor a" in norm_val:
                specific_tokens.update(["con-a", "cona"])
                value_tokens.add("con-a")
            if "con-d" in norm_val or "con d" in norm_val or "contactor d" in norm_val:
                specific_tokens.update(["con-d", "cond"])
                value_tokens.add("con-d")
            if "con-j" in norm_val or "con j" in norm_val or "contactor j" in norm_val:
                specific_tokens.update(["con-j", "conj"])
                value_tokens.add("con-j")

            if not specific_tokens and not value_tokens:
                continue

            prepared.append((label, value, norm_val, value_tokens, specific_tokens, weight, code_regexes))
            all_signal_tokens.update(specific_tokens)
            all_signal_tokens.update(value_tokens)

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
                if code_match and not exact_phrase:
                    exact_phrase = True

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

        # Seleccionar los mejores garantizando diversidad equitativa entre todos los 19 manuales
        selected = []
        deferred = []
        seen: set[tuple] = set()
        manual_counts: dict[str, int] = defaultdict(int)
        max_per_manual = max(1, limit // 4)

        for score, document, matched_signals, matched_tokens in ranked:
            dedupe_key = (document.manual, document.page)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            title = _best_line(document.text, all_signal_tokens)
            item = (score, document, matched_signals, matched_tokens, title)

            if manual_counts[document.manual] < max_per_manual:
                manual_counts[document.manual] += 1
                selected.append(item)
                if len(selected) >= limit:
                    break
            else:
                deferred.append(item)

        # Si aún quedan cupos para alcanzar el límite, incorporar los elementos diferidos
        if len(selected) < limit:
            for item in deferred:
                selected.append(item)
                if len(selected) >= limit:
                    break

        if not selected:
            return {
                "results": [],
                "signals": [item[1] for item in prepared],
                "message": "No se encontraron relaciones directas en los manuales para las señales ingresadas.",
            }

        max_score = max(selected[0][0], 1.0)
        total_signals = len(prepared)
        results = []

        for score, document, matched_signals, matched_tokens, title in selected:
            query_for_context = " ".join(sorted(matched_tokens)) or next(iter(sorted(all_signal_tokens)), "")
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
