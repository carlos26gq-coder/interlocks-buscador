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
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
GRAPH_FILE = DATA_DIR / "linac_graph.json"


def _clean_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower().strip())


class GraphEngine:
    """Motor de recorrido de grafo para diagnóstico de aceleradores lineales."""

    def __init__(self, graph_data: dict[str, Any] | None = None):
        if graph_data is None:
            if not GRAPH_FILE.exists():
                raise FileNotFoundError(f"Archivo de grafo no encontrado en {GRAPH_FILE}")
            with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                graph_data = json.load(f)

        self.version: str = graph_data.get("version", "2.0")
        self.entities: dict[str, dict] = graph_data.get("entities", {})
        self.adjacency: dict[str, list] = graph_data.get("adjacency", {})
        self.lookup: dict[str, str] = graph_data.get("lookup", {})

    def resolve_entity(self, text: str) -> str | None:
        """Resuelve un texto de síntoma o consulta a un ID canónico del grafo."""
        clean = _clean_key(text)
        if not clean:
            return None

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

        cable_m = re.search(r"\b(?:cable\s*([a-z0-9]+)|\b(w\d{1,3})\b)", text, re.I)
        if cable_m:
            cab = (cable_m.group(1) or cable_m.group(2)).upper()
            cand = f"CABLE {cab}" if not cab.startswith("W") else cab
            if cand in self.entities:
                return cand

        # 3. Búsqueda por número aislado (ej. "474" o "283")
        num_m = re.search(r"\b(\d{2,4})\b", text)
        if num_m:
            code = num_m.group(1)
            for prefix in ["ITEM", "INTERLOCK", "ERROR"]:
                cand = f"{prefix} {code}"
                if cand in self.entities:
                    return cand

        return None

    def find_shortest_path(self, start_id: str, target_id: str, max_depth: int = 4) -> list[dict] | None:
        """Encuentra el camino topológico más corto entre dos nodos mediante BFS."""
        if start_id not in self.adjacency or target_id not in self.adjacency:
            return None
        if start_id == target_id:
            return [{"node": start_id, "relation": "self", "manual": "diagrams", "page": 1}]

        queue = deque([(start_id, [{"node": start_id, "relation": "start", "manual": "", "page": 0}])])
        visited = {start_id}

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue

            for neighbor, relation, weight, manual, page in self.adjacency.get(current, []):
                if neighbor == target_id:
                    return path + [{"node": neighbor, "relation": relation, "manual": manual, "page": page}]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(
                        (
                            neighbor,
                            path + [{"node": neighbor, "relation": relation, "manual": manual, "page": page}],
                        )
                    )

        return None

    def trace_circuit(self, symptoms: list[str]) -> dict[str, Any]:
        """Calcula la traza física de circuito que conecta los síntomas ingresados."""
        resolved_nodes: list[str] = []
        for s in symptoms:
            node_id = self.resolve_entity(s)
            if node_id and node_id not in resolved_nodes:
                resolved_nodes.append(node_id)

        if not resolved_nodes:
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

            # Ordenar candidatos comunes priorizando PCBs y módulos
            def candidate_rank(node_name: str) -> tuple[int, int]:
                ent_type = self.entities.get(node_name, {}).get("type", "")
                type_weight = 3 if ent_type == "pcb" else (2 if ent_type == "cable" else 1)
                return (common_candidates[node_name], type_weight)

            sorted_candidates = sorted(common_candidates.keys(), key=candidate_rank, reverse=True)
            hub_node = sorted_candidates[0] if sorted_candidates else resolved_nodes[0]

            # Colectar componentes físicos en la traza
            all_involved_nodes = set(resolved_nodes)
            for p in paths:
                for step in p:
                    all_involved_nodes.add(step["node"])

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

        return {
            "found": True,
            "hub_node": single,
            "resolved_nodes": [single],
            "trace_diagram": f"{single} -> " + (pcbs[0] if pcbs else (neighbors[0][0] if neighbors else single)),
            "pcbs": pcbs[:5],
            "cables": cables[:5],
            "connectors": connectors[:6],
            "test_points": test_points[:6],
            "areas": areas[:4],
            "manual_references": manual_refs[:6],
            "confidence": "alta",
        }


# Instancia única reutilizable en el servidor
_GLOBAL_ENGINE: GraphEngine | None = None


def get_graph_engine() -> GraphEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = GraphEngine()
    return _GLOBAL_ENGINE
