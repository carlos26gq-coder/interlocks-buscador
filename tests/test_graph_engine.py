"""SOLVI - Pruebas del Motor de Grafo de Conocimiento y Traza Topológica de Circuitos."""

from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from graph_engine import GraphEngine, get_graph_engine
from search_engine import SearchEngine


class GraphEngineSuite(unittest.TestCase):
    """Pruebas exhaustivas para la resolución y traza física de circuitos en el acelerador."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_graph_engine()

    # ─── 1. INTEGRIDAD ESTRUCTURAL DEL GRAFO ─────────────────────────────────

    def test_graph_file_integrity_and_memory_footprint(self):
        """Verifica existencia, tamaño < 2 MB y densidad mínima de entidades y adyacencias."""
        graph_path = ROOT / "data" / "linac_graph.json"
        self.assertTrue(graph_path.exists(), "linac_graph.json debe existir en data/")
        
        size_mb = graph_path.stat().st_size / (1024 * 1024)
        self.assertLess(size_mb, 2.0, f"El grafo pesa {size_mb:.2f} MB; debe mantenerse < 2.0 MB para móviles")

        self.assertGreater(len(self.engine.entities), 500, "Debe tener al menos 500 entidades técnicas")
        self.assertGreater(len(self.engine.adjacency), 500, "Debe tener al menos 500 listas de adyacencia")

    # ─── 2. RESOLUCIÓN DE ENTIDADES DE HARDWARE ──────────────────────────────

    def test_entity_resolution_item_and_numbers(self):
        """Verifica que códigos ITEM numéricos y normalizados se resuelvan exactamente."""
        self.assertEqual(self.engine.resolve_entity("ITEM 474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("item 474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("ITEM 409"), "ITEM 409")

    def test_entity_resolution_whitespace_and_punctuation(self):
        """Tolerancia a mayúsculas/minúsculas y guiones en identificadores de hardware."""
        self.assertEqual(self.engine.resolve_entity("item-409"), "ITEM 409")
        self.assertEqual(self.engine.resolve_entity("  ITEM 409  "), "ITEM 409")

    # ─── 3. TRAZA TOPOLÓGICA (BFS) ───────────────────────────────────────────

    def test_single_entity_periphery_trace(self):
        """Una sola entidad descubre su periferia (PCBs asociadas, cables, manuales)."""
        res = self.engine.trace_circuit(["ITEM 474"])
        self.assertTrue(res["found"])
        self.assertEqual(res["hub_node"], "ITEM 474")
        self.assertGreaterEqual(len(res["pcbs"]), 1)
        self.assertTrue(any("diagrams" in ref for ref in res["manual_references"]))

    def test_multi_entity_shortest_path_and_hub(self):
        """Múltiples entidades encuentran el camino más corto y el nodo PCB central."""
        res = self.engine.trace_circuit(["ITEM 409", "ITEM 332"])
        self.assertTrue(res["found"])
        self.assertIn("PCB SCC HTB", res["pcbs"])
        self.assertIn("->", res["trace_diagram"])
        self.assertEqual(res["confidence"], "alta")

    def test_unresolved_entities_graceful_fallback(self):
        """Síntomas no presentes en el grafo retornan estado seguro sin excepciones."""
        res = self.engine.trace_circuit(["falla_inexistente_xyz_999"])
        self.assertFalse(res["found"])
        self.assertEqual(res["reason"], "no_entities_resolved")

    # ─── 4. RESOLUCIÓN CONTEXTUAL EN LENGUAJE NATURAL ────────────────────────

    def test_natural_language_symptom_resolution(self):
        """Prueba de síntomas clínicos/técnicos reportados en servicio asistidos por SearchEngine."""
        import json
        manuals_path = ROOT / "data" / "all_manuals.json"
        self.assertTrue(manuals_path.exists())

        with manuals_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        se = SearchEngine(data)

        # 1. Monitoreo de tasa de dosis
        t_dose = self.engine.trace_circuit(["dose rate mon"], search_engine=se)
        self.assertTrue(t_dose["found"], "Debe resolver 'dose rate mon' mediante contexto en manuales")
        self.assertGreaterEqual(len(t_dose["pcbs"]), 1)

        # 2. Falla de alta tensión / disparo HT2
        t_ht2 = self.engine.trace_circuit(["check fail ht2"], search_engine=se)
        self.assertTrue(t_ht2["found"], "Debe resolver 'check fail ht2' hacia su tarjeta de control")
        self.assertIn("PCB DIE ICB", t_ht2["pcbs"])

        # 3. Ambas fallas concurrentes
        t_both = self.engine.trace_circuit(["dose rate mon", "check fail ht2"], search_engine=se)
        self.assertTrue(t_both["found"])
        self.assertIn("PCB DIE ICB", t_both["pcbs"])
        self.assertIn("->", t_both["trace_diagram"])

    # ─── 5. BENCHMARK DE LATENCIA EN TIEMPO REAL ─────────────────────────────

    def test_graph_traversal_speed_benchmark(self):
        """100 consultas de traza consecutivas deben ejecutarse con promedio < 10ms por consulta."""
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            self.engine.trace_circuit(["ITEM 409", "ITEM 332"])
        elapsed_ms = ((time.perf_counter() - start) / iterations) * 1000
        self.assertLess(elapsed_ms, 10.0, f"Latencia promedio: {elapsed_ms:.2f} ms (máximo permitido: 10.0 ms)")

    # ─── 6. DETECCIÓN DE CICLOS Y DETERMINISMO TOPOLÓGICO ─────────────────────

    def test_find_shortest_path_cycle_detection_and_determinism(self):
        """Verifica que grafos con bucles físicos redundantes no generen ciclos infinitos y retornen camino óptimo."""
        cyclic_data = {
            "version": "test",
            "entities": {
                "NODE_A": {"type": "pcb", "pages": [["manual1", 1]]},
                "NODE_B": {"type": "cable", "pages": [["manual1", 2]]},
                "NODE_C": {"type": "pcb", "pages": [["manual1", 3]]},
            },
            "adjacency": {
                # Ciclo cerrado A -> B -> C -> A con camino directo y lazo redundante
                "NODE_A": [["NODE_B", "wire", 1, "manual1", 1]],
                "NODE_B": [["NODE_C", "wire", 1, "manual1", 2], ["NODE_A", "wire", 1, "manual1", 2]],
                "NODE_C": [["NODE_A", "wire", 1, "manual1", 3]],
            },
            "lookup": {"nodea": "NODE_A", "nodeb": "NODE_B", "nodec": "NODE_C"},
        }
        engine = GraphEngine(cyclic_data)
        path = engine.find_shortest_path("NODE_A", "NODE_C")
        self.assertIsNotNone(path)
        # El camino debe ser A -> B -> C (3 pasos) y terminar sin ciclo infinito
        self.assertEqual([step["node"] for step in path], ["NODE_A", "NODE_B", "NODE_C"])


if __name__ == "__main__":
    unittest.main()
