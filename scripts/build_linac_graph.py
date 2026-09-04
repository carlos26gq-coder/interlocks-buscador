"""SOLVI - Compilador del Grafo de Conocimiento Linac (Knowledge Graph).

Procesa las 6,322 páginas de los 19 manuales técnicos de Elekta Linac y compila
una estructura de grafo ultraliviana (JSON compacto) que mapea:
1. Interlocks y Códigos de Error
2. Señales y Códigos ITEM
3. Tarjetas Electrónicas PCB y Módulos
4. Cables (Wxx) y Arneses
5. Conectores (PL, SK, TB, J) y Pines
6. Puntos de Prueba (TP), Relés (RLA/RLB) y Fusibles (FS)
7. Áreas Físicas y Racks (HTCA, Área 16, etc.)
8. Referencias exactas a manuales y páginas de esquemas

Salida: data/linac_graph.json y scripts/static/linac_graph.json (~1.5 MB)
"""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = ROOT_DIR / "scripts" / "static"

MANUALS_FILE = DATA_DIR / "all_manuals.json"
GRAPH_OUTPUT_DATA = DATA_DIR / "linac_graph.json"
GRAPH_OUTPUT_STATIC = STATIC_DIR / "linac_graph.json"

STOP_WORDS = {
    "THE", "AND", "FOR", "WITH", "FROM", "INTO", "DURING", "WAS", "WHEN", "WHERE",
    "WILL", "THIS", "THAT", "HAVE", "BEEN", "IDENTIFICATION", "INFORMATION",
    "DESCRIPTION", "GENERAL", "NOTE", "TABLE", "FIGURE", "SHEET", "SYSTEM",
    "MANUAL", "PAGE", "AREA", "UNIT", "TYPE", "DATA", "TEST", "CHECK", "CODE",
}

# Expresiones regulares para extracción de entidades de hardware
RE_INTERLOCK = re.compile(
    r"\b(?:INTERLOCK\s*([A-Z0-9_\-]+)|INT\s+([0-9]{1,4}|[A-Z0-9_\-]{2,}))\b",
    re.IGNORECASE,
)
RE_ERROR_CODE = re.compile(r"\b(?:ERROR|FAULT)\s*(\d{1,4})\b", re.IGNORECASE)
RE_ITEM_SIGNAL = re.compile(r"\bITEM\s*(\d{2,4})\b", re.IGNORECASE)
RE_SPECIAL_SIGNAL = re.compile(
    r"\b(D_RATE\s*\d+|DOS_\w+|HV_ON|HT_TRIP|VAC_PUMP|COL_ROT|GANTRY_ROT)\b",
    re.IGNORECASE,
)

RE_PCB = re.compile(
    r"\b(?:PCB\s*([A-Z0-9\-]+)|(AO\d+|AI\d+|DIE-[A-Z0-9]+|SCC-[A-Z0-9]+|MCB\d*|MCDC\d*|RT_DRV))\b",
    re.IGNORECASE,
)
RE_CABLE = re.compile(
    r"\b(?:CABLE\s*([A-Z0-9\-]{2,12})|\b(W\d{1,3})\b|HARNESS\s*([A-Z0-9\-]{2,12}))\b",
    re.IGNORECASE,
)
RE_CONNECTOR = re.compile(r"\b(PL\d{1,3}|SK\d{1,3}|TB\d{1,3}|J\d{1,3})\b", re.IGNORECASE)
RE_TEST_POINT = re.compile(
    r"\b(TP\d{1,3}|RL[A-Z]\d?|FS\d{1,2}|[+\-]?(?:15|24|5|12|50)\s*VDC)\b",
    re.IGNORECASE,
)
RE_AREA = re.compile(
    r"\b(AREA\s*\d{1,2}|RACK\s*[A-Z0-9]+|HTCA|GANTRY\s*(?:DRUM|HEAD)|PEDESTAL|CAROUSEL)\b",
    re.IGNORECASE,
)


def normalize_id(text: str) -> str:
    """Normaliza identificadores para búsquedas directas sin distinción de mayúsculas o espacios."""
    return re.sub(r"[\s\-_]+", " ", text.strip().upper())


def normalize_lookup_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower().strip())


def build_graph() -> dict:
    if not MANUALS_FILE.exists():
        raise FileNotFoundError(f"No se encontró el archivo de manuales en {MANUALS_FILE}")

    print(f"[1/4] Leyendo manuales desde {MANUALS_FILE}...")
    with open(MANUALS_FILE, "r", encoding="utf-8") as f:
        pages = json.load(f)

    print(f"[2/4] Minería de entidades y topología en {len(pages)} páginas...")

    entities: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}
    lookup: dict[str, str] = {}

    def register_entity(ent_id: str, ent_type: str, raw_name: str, manual: str, page_num: int):
        clean_id = normalize_id(ent_id)
        if clean_id not in entities:
            entities[clean_id] = {
                "id": clean_id,
                "type": ent_type,
                "name": raw_name.strip(),
                "pages": [],
            }
            lookup[normalize_lookup_key(clean_id)] = clean_id
            lookup[normalize_lookup_key(raw_name)] = clean_id
            num_match = re.search(r"\b(\d{2,4})\b", clean_id)
            if num_match:
                lookup[normalize_lookup_key(num_match.group(1))] = clean_id

        page_entry = [manual, page_num]
        if page_entry not in entities[clean_id]["pages"]:
            if len(entities[clean_id]["pages"]) < 20:
                entities[clean_id]["pages"].append(page_entry)

    def add_edge(id_a: str, id_b: str, rel_type: str, manual: str, page_num: int):
        clean_a = normalize_id(id_a)
        clean_b = normalize_id(id_b)
        if clean_a == clean_b:
            return

        pair = tuple(sorted([clean_a, clean_b]))
        if pair not in edges:
            edges[pair] = {
                "source": pair[0],
                "target": pair[1],
                "relation": rel_type,
                "weight": 1,
                "pages": [[manual, page_num]],
            }
        else:
            edges[pair]["weight"] += 1
            if len(edges[pair]["pages"]) < 5 and [manual, page_num] not in edges[pair]["pages"]:
                edges[pair]["pages"].append([manual, page_num])

    for p in pages:
        manual = p.get("manual", "general")
        page_num = p.get("page", 1)
        text = p.get("text", "")

        page_interlocks = set()
        for m in RE_INTERLOCK.finditer(text):
            code = (m.group(1) or m.group(2)).strip().upper()
            if not code or code in STOP_WORDS:
                continue
            full_name = f"INTERLOCK {code}"
            register_entity(full_name, "interlock", full_name, manual, page_num)
            page_interlocks.add(full_name)

        for m in RE_ERROR_CODE.finditer(text):
            code = m.group(1).strip()
            full_name = f"ERROR {code}"
            register_entity(full_name, "error", full_name, manual, page_num)
            page_interlocks.add(full_name)

        page_signals = set()
        for m in RE_ITEM_SIGNAL.finditer(text):
            code = m.group(1).strip()
            full_name = f"ITEM {code}"
            register_entity(full_name, "signal", full_name, manual, page_num)
            page_signals.add(full_name)

        for m in RE_SPECIAL_SIGNAL.finditer(text):
            sig = m.group(1).strip().upper()
            register_entity(sig, "signal", sig, manual, page_num)
            page_signals.add(sig)

        page_pcbs = set()
        for m in RE_PCB.finditer(text):
            board = (m.group(1) or m.group(2)).strip().upper()
            if not board or board in STOP_WORDS or len(board) < 2:
                continue
            full_name = f"PCB {board}" if not board.startswith("PCB") else board
            register_entity(full_name, "pcb", full_name, manual, page_num)
            page_pcbs.add(full_name)

        page_cables = set()
        for m in RE_CABLE.finditer(text):
            cab = (m.group(1) or m.group(2) or m.group(3)).strip().upper()
            if not cab or cab in STOP_WORDS or len(cab) < 2:
                continue
            full_name = f"CABLE {cab}" if not cab.startswith(("CABLE", "W")) else cab
            register_entity(full_name, "cable", full_name, manual, page_num)
            page_cables.add(full_name)

        page_conns = set()
        for m in RE_CONNECTOR.finditer(text):
            conn = m.group(1).strip().upper()
            if not conn or conn in STOP_WORDS:
                continue
            register_entity(conn, "connector", f"CONECTOR {conn}", manual, page_num)
            page_conns.add(conn)

        page_tps = set()
        for m in RE_TEST_POINT.finditer(text):
            tp = m.group(1)
            register_entity(tp, "test_point", f"PUNTO {tp}", manual, page_num)
            page_tps.add(tp)

        page_areas = set()
        for m in RE_AREA.finditer(text):
            ar = m.group(1)
            register_entity(ar, "area", ar, manual, page_num)
            page_areas.add(ar)

        for sig in page_signals:
            for pcb in page_pcbs:
                add_edge(sig, pcb, "hosted_on", manual, page_num)
            for cab in page_cables:
                add_edge(sig, cab, "routes_through", manual, page_num)

        for cab in page_cables:
            for conn in page_conns:
                add_edge(cab, conn, "terminates_at", manual, page_num)
            for pcb in page_pcbs:
                add_edge(cab, pcb, "connects_to", manual, page_num)

        for pcb in page_pcbs:
            for ar in page_areas:
                add_edge(pcb, ar, "located_in", manual, page_num)
            for tp in page_tps:
                add_edge(pcb, tp, "has_test_point", manual, page_num)

        for intlk in page_interlocks:
            for sig in page_signals:
                add_edge(intlk, sig, "monitors_signal", manual, page_num)
            for pcb in page_pcbs:
                add_edge(intlk, pcb, "tripped_by", manual, page_num)

    print(f"[3/4] Indexando adyacencias comprimidas ({len(entities)} nodos, {len(edges)} aristas)...")

    adjacency: dict[str, list] = defaultdict(list)
    for (ent_a, ent_b), edge_data in edges.items():
        rel = edge_data["relation"]
        wt = edge_data["weight"]
        p_ref = edge_data["pages"][0] if edge_data["pages"] else ["general", 1]
        adjacency[ent_a].append([ent_b, rel, wt, p_ref[0], p_ref[1]])
        adjacency[ent_b].append([ent_a, rel, wt, p_ref[0], p_ref[1]])

    for ent_id in adjacency:
        adjacency[ent_id].sort(key=lambda x: -x[2])
        adjacency[ent_id] = adjacency[ent_id][:25]

    graph_payload = {
        "version": "2.0",
        "entity_count": len(entities),
        "edge_count": len(edges),
        "entities": entities,
        "adjacency": adjacency,
        "lookup": lookup,
    }

    print(f"[4/4] Guardando grafo en {GRAPH_OUTPUT_DATA} y {GRAPH_OUTPUT_STATIC}...")
    GRAPH_OUTPUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_OUTPUT_DATA, "w", encoding="utf-8") as f:
        json.dump(graph_payload, f, separators=(",", ":"))

    GRAPH_OUTPUT_STATIC.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_OUTPUT_STATIC, "w", encoding="utf-8") as f:
        json.dump(graph_payload, f, separators=(",", ":"))

    size_mb = GRAPH_OUTPUT_DATA.stat().st_size / (1024 * 1024)
    print(f"Grafo de Conocimiento compilado exitosamente: {size_mb:.2f} MB")
    return graph_payload


if __name__ == "__main__":
    build_graph()
