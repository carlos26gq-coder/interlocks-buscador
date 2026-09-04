import sys
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from graph_engine import GraphEngine, get_graph_engine  # noqa: E402


class GraphEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = get_graph_engine()

    def test_graph_file_integrity_and_size(self):
        graph_path = ROOT / "data" / "linac_graph.json"
        self.assertTrue(graph_path.exists(), "El archivo linac_graph.json debe existir en data/")
        size_mb = graph_path.stat().st_size / (1024 * 1024)
        # Requisito de protección estricta de memoria en móviles: menor a 2.0 MB
        self.assertLess(size_mb, 2.0, f"El grafo pesa {size_mb:.2f} MB, debe ser menor a 2 MB para móviles")
        self.assertGreater(len(self.engine.entities), 500, "Debe tener al menos 500 entidades")
        self.assertGreater(len(self.engine.adjacency), 500, "Debe tener al menos 500 adyacencias")

    def test_entity_resolution_numeric_and_text(self):
        # Resolución directa y normalizada
        self.assertEqual(self.engine.resolve_entity("ITEM 474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("item 474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("474"), "ITEM 474")
        self.assertEqual(self.engine.resolve_entity("ITEM 409"), "ITEM 409")

    def test_single_entity_periphery_trace(self):
        res = self.engine.trace_circuit(["ITEM 474"])
        self.assertTrue(res["found"])
        self.assertEqual(res["hub_node"], "ITEM 474")
        self.assertGreaterEqual(len(res["pcbs"]), 1)
        self.assertTrue(any("diagrams" in ref for ref in res["manual_references"]))

    def test_multi_entity_topological_path(self):
        res = self.engine.trace_circuit(["ITEM 409", "ITEM 332"])
        self.assertTrue(res["found"])
        self.assertIn("PCB SCC HTB", res["pcbs"])
        self.assertIn("->", res["trace_diagram"])
        self.assertEqual(res["confidence"], "alta")

    def test_unresolved_entities_graceful_fallback(self):
        res = self.engine.trace_circuit(["palabra inexistente xyz 999"])
        self.assertFalse(res["found"])
        self.assertEqual(res["reason"], "no_entities_resolved")

    def test_graph_traversal_speed_benchmark(self):
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            self.engine.trace_circuit(["ITEM 409", "ITEM 332"])
        elapsed_ms = ((time.perf_counter() - start) / iterations) * 1000
        # Debe responder en menos de 10ms por consulta
        self.assertLess(elapsed_ms, 10.0, f"Latencia promedio: {elapsed_ms:.2f} ms")


if __name__ == "__main__":
    unittest.main()
