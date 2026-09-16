"""SOLVI - Motor de Traza Topológica y Consulta del Grafo de Conocimiento Linac.

Proporciona consultas de alta velocidad (<5ms) para:
1. Resolución de entidades desde texto (interlocks, señales ITEM, PCBs, cables W, conectores).
2. Traza de circuito determinista: camino más corto y ancestro/tarjeta común entre síntomas.
3. Extracción de puntos de prueba TP, cables, conectores y planos exactos para servicio de campo.
"""

from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
import re
import threading
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
GRAPH_FILE = DATA_DIR / "linac_graph.json"


def _clean_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower().strip())


_TYPE_PRIORITY: dict[str, int] = {
    "pcb": 10,
    "interlock": 9,
    "error": 9,
    "signal": 8,
    "test_point": 8,
    "switch": 7,
    "relay": 7,
    "sensor": 7,
    "source": 7,
    "load": 7,
    "cable": 6,
    "connector": 6,
    "area": 1,
}


class GraphEngine:
    """Motor de recorrido de grafo para diagnóstico de aceleradores lineales."""

    def __init__(self, graph_data: dict[str, Any] | None = None):
        enrich_circuits = False
        if graph_data is None:
            if not GRAPH_FILE.exists():
                raise FileNotFoundError(f"Archivo de grafo no encontrado en {GRAPH_FILE}")
            with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                graph_data = json.load(f)
            enrich_circuits = True

        self.version: str = graph_data.get("version", "2.0")
        self.entities: dict[str, dict] = graph_data.get("entities", {})
        self.adjacency: dict[str, list] = graph_data.get("adjacency", {})
        self.lookup: dict[str, str] = graph_data.get("lookup", {})
        self.page_to_entities: dict[tuple[str, int], list[str]] = defaultdict(list)
        self.enriched_circuits: bool = False

        if enrich_circuits:
            self._enrich_with_circuit_schematics()

        # Índice invertido de (manual, página) -> lista de entidades para búsquedas O(1)
        for ent_id, ent in self.entities.items():
            for page in ent.get("pages", []):
                if isinstance(page, (list, tuple)) and len(page) >= 2:
                    self.page_to_entities[(str(page[0]), int(page[1]))].append(ent_id)

    def _enrich_with_circuit_schematics(self) -> None:
        """Enriquece entidades y topología con los 5 esquemas de circuitos de ingeniería."""
        saved_entities = {k: v.copy() if isinstance(v, dict) else v for k, v in self.entities.items()}
        saved_lookup = self.lookup.copy()
        saved_adjacency = {k: [list(edge) for edge in edges] for k, edges in self.adjacency.items()}
        try:
            from circuit_data import SUBSYSTEMS
            for sub_id, sub in SUBSYSTEMS.items():
                man_refs = sub.get("manual_references", [])
                sub_page = 14
                sub_man = "diagrams"
                if man_refs:
                    m = re.search(r"(\w+)\s*\(P[aá]g\s*(\d+)\)", man_refs[0], re.I)
                    if m:
                        sub_man, sub_page = m.group(1), int(m.group(2))
                sub_pcbs = [n.get("code") or n.get("id") for n in sub.get("nodes", []) if n.get("type") == "pcb"]
                for n in sub.get("nodes", []):
                    code = n.get("code") or n.get("id")
                    nid = n.get("id")
                    ntype = n.get("type", "circuit_component")
                    nname = n.get("name", code)
                    man = n.get("manual", sub_man)
                    page = int(n.get("page", sub_page))
                    for key in [code, nid]:
                        if not key:
                            continue
                        k_clean = _clean_key(key)
                        if k_clean and k_clean not in self.lookup:
                            self.lookup[k_clean] = key
                        if key not in self.entities:
                            self.entities[key] = {
                                "id": key,
                                "type": ntype,
                                "name": nname,
                                "pages": [[man, page]],
                            }
                    if ntype != "pcb" and sub_pcbs and code:
                        for pcb in sub_pcbs:
                            edge = [pcb, "controlled_by", 5, man, page]
                            self.adjacency.setdefault(code, [])
                            if edge not in self.adjacency[code]:
                                self.adjacency[code].append(edge)
                for wire in sub.get("wires", []):
                    u = wire.get("from")
                    v = wire.get("to")
                    for n in sub.get("nodes", []):
                        if n.get("id") == u:
                            u = n.get("code") or u
                        if n.get("id") == v:
                            v = n.get("code") or v
                    if u and v:
                        wtype = wire.get("type", "wire")
                        edge_uv = [v, wtype, 5, sub_man, sub_page]
                        edge_vu = [u, wtype, 5, sub_man, sub_page]
                        self.adjacency.setdefault(u, [])
                        self.adjacency.setdefault(v, [])
                        if edge_uv not in self.adjacency[u]:
                            self.adjacency[u].append(edge_uv)
                        if edge_vu not in self.adjacency[v]:
                            self.adjacency[v].append(edge_vu)
            self.enriched_circuits = True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Error al enriquecer grafo con esquemas de circuito: %s", exc)
            self.entities = saved_entities
            self.lookup = saved_lookup
            self.adjacency = saved_adjacency
            self.enriched_circuits = False

    def resolve_entity(self, text: str, search_engine: Any = None) -> str | None:
        """Resuelve un texto de síntoma o consulta a un ID canónico del grafo."""
        text = str(text or "")[:300].strip()
        clean = _clean_key(text)
        if not clean:
            return None

        # LG-03: Si el texto es puramente numérico (ej. "474" o "283"), priorizar prefijos de ingeniería canónicos
        if re.match(r"^\d{2,4}$", clean):
            for prefix in ["ITEM", "INTERLOCK", "ERROR", "PCB"]:
                cand = f"{prefix} {clean}"
                if cand in self.entities:
                    return cand

        # 1. Búsqueda exacta en mapa de lookup
        if clean in self.lookup:
            return self.lookup[clean]

        # 2. Si el texto tiene formato "item 474", "pcb 16n", "interlock 283"
        item_m = re.search(r"\bitem\s*(\d{2,4})\b", text, re.I)
        if item_m:
            cand = f"ITEM {item_m.group(1)}"
            if cand in self.entities:
                return cand

        intlk_m = re.search(r"\b(?:interlock|int)\s*(\d{2,4})\b", text, re.I)
        if intlk_m:
            cand = f"INTERLOCK {intlk_m.group(1)}"
            if cand in self.entities:
                return cand

        cable_m = re.search(r"\b(?:cable\s*([a-z0-9_]+)|\b(w\d{1,3})\b)", text, re.I)
        if cable_m:
            cab = (cable_m.group(1) or cable_m.group(2)).upper().replace("CABLE_", "").replace("CABLE ", "")
            for cand in [f"CABLE {cab}", f"CABLE_{cab}", cab]:
                if cand in self.entities:
                    return cand

        # 3. Búsqueda por número aislado (ej. "474" o "283")
        num_m = re.search(r"\b(\d{2,4})\b", text)
        if num_m:
            code = num_m.group(1)
            for prefix in ["ITEM", "INTERLOCK", "ERROR", "PCB"]:
                cand = f"{prefix} {code}"
                if cand in self.entities:
                    return cand

        # 4. Coincidencia en entidades
        clean_digits = re.findall(r"\d+", clean)

        # 4a. Coincidencia exacta limpia con ent_id
        for ent_id in self.entities:
            ent_clean = _clean_key(ent_id)
            if clean == ent_clean:
                return ent_id

        # 4b. Coincidencias por subcadena ordenadas por tipo de componente (GE-03), especificidad de longitud y desempate alfabético
        candidates: list[str] = []
        for ent_id in self.entities:
            ent_clean = _clean_key(ent_id)
            if (len(clean) >= 4 and clean in ent_clean) or (len(ent_clean) >= 4 and ent_clean in clean):
                ent_digits = re.findall(r"\d+", ent_clean)
                if clean_digits and ent_digits and clean_digits != ent_digits:
                    continue
                candidates.append(ent_id)

        if candidates:
            candidates.sort(
                key=lambda eid: (
                    -_TYPE_PRIORITY.get(self.entities.get(eid, {}).get("type", ""), 5),
                    -len(_clean_key(eid)),
                    eid,
                )
            )
            return candidates[0]

        # 5. Búsqueda contextual en los manuales para mapear síntomas en lenguaje natural a hardware
        if search_engine is not None:
            try:
                s_res = search_engine.search(text, limit=3)
                cands = []
                for r in s_res.get("results", []):
                    m, p = str(r.get("manual", "")), int(r.get("page", 0))
                    for ent_id in self.page_to_entities.get((m, p), []):
                        ent = self.entities.get(ent_id, {})
                        t_weight = 3 if ent.get("type") == "pcb" else (2 if ent.get("type") == "signal" else 1)
                        cands.append((t_weight, ent_id))
                if cands:
                    cands.sort(key=lambda x: -x[0])
                    return cands[0][1]
            except Exception:
                pass

        return None

    def find_shortest_path(self, start_id: str, target_id: str, max_depth: int = 4) -> list[dict] | None:
        """Encuentra el camino topológico más corto entre dos nodos mediante BFS."""
        if start_id not in self.entities or target_id not in self.entities:
            return None

        # Soportar nodos sumidero garantizando claves en self.adjacency
        self.adjacency.setdefault(start_id, [])
        self.adjacency.setdefault(target_id, [])

        if start_id == target_id:
            ent = self.entities.get(start_id, {})
            pages = ent.get("pages", [])
            man = pages[0][0] if pages else "diagrams"
            page = int(pages[0][1]) if pages and len(pages[0]) > 1 else 1
            return [{"node": start_id, "relation": "self", "manual": man, "page": page}]

        queue = deque([(start_id, [{"node": start_id, "relation": "start", "manual": "", "page": 0}])])
        visited = {start_id}

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue

            for edge in self.adjacency.get(current, []):
                if not edge or not isinstance(edge, (list, tuple)):
                    continue
                neighbor = str(edge[0])
                relation = str(edge[1]) if len(edge) > 1 else "connected"
                manual = str(edge[3]) if len(edge) > 3 else ""
                page = int(edge[4]) if len(edge) > 4 and isinstance(edge[4], (int, float)) else 0

                if neighbor == target_id:
                    return path + [{"node": neighbor, "relation": relation, "manual": manual, "page": page}]

                if len(path) < max_depth and neighbor not in visited:
                    if len(queue) >= 2000:
                        break
                    visited.add(neighbor)
                    queue.append(
                        (
                            neighbor,
                            path + [{"node": neighbor, "relation": relation, "manual": manual, "page": page}],
                        )
                    )

        return None

    def trace_circuit(self, symptoms: list[str], search_engine: Any = None) -> dict[str, Any]:
        """Calcula la traza física de circuito que conecta los síntomas ingresados."""
        if isinstance(symptoms, str):
            symptoms = [symptoms]
        elif not isinstance(symptoms, list):
            symptoms = []
        symptoms = [str(s).strip()[:300] for s in symptoms[:6] if str(s).strip()]
        resolved_nodes: list[str] = []
        for s in symptoms:
            node_id = self.resolve_entity(s, search_engine=search_engine)
            if node_id and node_id not in resolved_nodes:
                resolved_nodes.append(node_id)

        # Si no se resolvió ningún nodo directamente, intentar buscar en manuales para obtener páginas de esquemas
        if not resolved_nodes:
            fallback_pages = []
            if search_engine is not None:
                for s in symptoms:
                    try:
                        s_res = search_engine.search(s, limit=2)
                        for r in s_res.get("results", []):
                            ref = f"{r.get('manual', '')} (Pág {r.get('page', 0)})"
                            if ref not in fallback_pages:
                                fallback_pages.append(ref)
                    except Exception:
                        pass

            if fallback_pages:
                return {
                    "found": True,
                    "hub_node": "Conexión Técnica en Manuales",
                    "resolved_nodes": symptoms,
                    "trace_diagram": " -> ".join(symptoms[:3]),
                    "pcbs": [],
                    "cables": [],
                    "connectors": [],
                    "test_points": [],
                    "areas": [],
                    "manual_references": fallback_pages[:6],
                    "confidence": "media",
                }

            return {"found": False, "reason": "no_entities_resolved", "resolved_nodes": []}

        # Caso A: Múltiples nodos resueltos -> Buscar nodo común / intersección de caminos
        if len(resolved_nodes) >= 2:
            paths = []
            common_candidates = defaultdict(int)

            # Buscar vecinos comunes de orden 1 y 2
            for i in range(len(resolved_nodes)):
                for j in range(i + 1, len(resolved_nodes)):
                    n1 = resolved_nodes[i]
                    n2 = resolved_nodes[j]
                    path = self.find_shortest_path(n1, n2)
                    if path:
                        paths.append(path)
                        for step in path:
                            common_candidates[step["node"]] += 1

            # Ordenar candidatos comunes priorizando frecuencia, tipo y nombre alfabético como desempate determinista
            def candidate_rank(node_name: str) -> tuple[int, int, str]:
                ent_type = self.entities.get(node_name, {}).get("type", "")
                type_weight = 3 if ent_type == "pcb" else (2 if ent_type == "cable" else 1)
                return (-common_candidates[node_name], -type_weight, node_name)

            sorted_candidates = sorted(common_candidates.keys(), key=candidate_rank)
            hub_node = sorted_candidates[0] if sorted_candidates else resolved_nodes[0]

            # Colectar componentes físicos en la traza en orden determinista de descubrimiento
            all_involved_nodes: list[str] = []
            for n in resolved_nodes:
                if n not in all_involved_nodes:
                    all_involved_nodes.append(n)
            for p in paths:
                for step in p:
                    if step["node"] not in all_involved_nodes:
                        all_involved_nodes.append(step["node"])

            pcbs = []
            cables = []
            connectors = []
            test_points = []
            areas = []
            manual_refs = []

            for n in all_involved_nodes:
                ent = self.entities.get(n, {})
                etype = ent.get("type", "")
                if etype == "pcb" and n not in pcbs:
                    pcbs.append(n)
                elif etype == "cable" and n not in cables:
                    cables.append(n)
                elif etype == "connector" and n not in connectors:
                    connectors.append(n)
                elif etype == "test_point" and n not in test_points:
                    test_points.append(n)
                elif etype == "area" and n not in areas:
                    areas.append(n)

                for man, pg in ent.get("pages", []):
                    ref_str = f"{man} (Pág {pg})"
                    if ref_str not in manual_refs and len(manual_refs) < 6:
                        manual_refs.append(ref_str)

            # Formular la traza visual de conexión
            trace_steps = []
            if paths:
                for step in paths[0]:
                    trace_steps.append(step["node"])
            else:
                trace_steps = resolved_nodes + ([hub_node] if hub_node not in resolved_nodes else [])

            trace_diagram = " -> ".join(trace_steps)

            return {
                "found": True,
                "hub_node": hub_node,
                "resolved_nodes": resolved_nodes,
                "trace_diagram": trace_diagram,
                "pcbs": pcbs[:5],
                "cables": cables[:5],
                "connectors": connectors[:6],
                "test_points": test_points[:6],
                "areas": areas[:4],
                "manual_references": manual_refs,
                "confidence": "alta" if len(paths) > 0 else "media",
            }

        # Caso B: 1 solo nodo resuelto -> Explorar su periferia inmediata
        single = resolved_nodes[0]
        neighbors = self.adjacency.get(single, [])
        pcbs = []
        cables = []
        connectors = []
        test_points = []
        areas = []
        manual_refs = []

        ent_info = self.entities.get(single, {})
        stype = ent_info.get("type", "")
        if stype == "pcb":
            pcbs.append(single)
        elif stype == "cable":
            cables.append(single)
        elif stype == "connector":
            connectors.append(single)
        elif stype == "test_point":
            test_points.append(single)
        elif stype == "area":
            areas.append(single)

        for man, pg in ent_info.get("pages", []):
            manual_refs.append(f"{man} (Pág {pg})")

        for neigh, rel, wt, man, pg in neighbors[:15]:
            nent = self.entities.get(neigh, {})
            ntype = nent.get("type", "")
            if ntype == "pcb" and neigh not in pcbs:
                pcbs.append(neigh)
            elif ntype == "cable" and neigh not in cables:
                cables.append(neigh)
            elif ntype == "connector" and neigh not in connectors:
                connectors.append(neigh)
            elif ntype == "test_point" and neigh not in test_points:
                test_points.append(neigh)
            elif ntype == "area" and neigh not in areas:
                areas.append(neigh)
            ref_str = f"{man} (Pág {pg})"
            if ref_str not in manual_refs and len(manual_refs) < 6:
                manual_refs.append(ref_str)

        target_neigh = next((p for p in pcbs if p != single), None) or (neighbors[0][0] if neighbors else None)
        trace_diag = f"{single} -> {target_neigh}" if target_neigh else f"{single} (Enfoque Directo)"

        return {
            "found": True,
            "hub_node": single,
            "resolved_nodes": [single],
            "trace_diagram": trace_diag,
            "pcbs": pcbs[:5],
            "cables": cables[:5],
            "connectors": connectors[:6],
            "test_points": test_points[:6],
            "areas": areas[:4],
            "manual_references": manual_refs[:6],
            "confidence": "alta",
        }


# Instancia única reutilizable en el servidor (Thread-safe)
_GLOBAL_ENGINE: GraphEngine | None = None
_GRAPH_LOCK = threading.Lock()


def get_graph_engine() -> GraphEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        with _GRAPH_LOCK:
            if _GLOBAL_ENGINE is None:
                _GLOBAL_ENGINE = GraphEngine()
    return _GLOBAL_ENGINE
