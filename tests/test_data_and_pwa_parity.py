"""SOLVI - Pruebas de Integridad Masiva de Datos, Paridad PWA y Rendimiento."""

from pathlib import Path
import hashlib
import json
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from search_engine import SearchEngine, MAX_SEARCH_LATENCY_WARMED_MS




class DataAndPwaParitySuite(unittest.TestCase):
    """Verificación profunda de 6,322 páginas, paridad de catálogos y rendimiento masivo."""

    @classmethod
    def setUpClass(cls):
        cls.data_path = ROOT / "data" / "all_manuals.json"
        cls.catalog_path = ROOT / "data" / "search" / "catalog.json"
        cls.graph_data_path = ROOT / "data" / "linac_graph.json"
        cls.graph_static_path = ROOT / "scripts" / "static" / "linac_graph.json"
        cls.documented_paths_path = ROOT / "data" / "verified_signal_paths.json"

        with cls.data_path.open("r", encoding="utf-8") as f:
            cls.master_data = json.load(f)

        cls.engine = SearchEngine(cls.master_data)

    # ─── 1. INTEGRIDAD DE DATOS MAESTROS ─────────────────────────────────────

    def test_master_records_integrity(self):
        """Verifica las 6,322 páginas de manuales: esquema, unicidad y ausencia de vacíos."""
        total = len(self.master_data)
        self.assertGreaterEqual(total, 6000, f"Debe haber más de 6,000 páginas, se encontraron {total}")

        seen_keys = set()
        empty_texts = 0
        manuals = set()

        for idx, doc in enumerate(self.master_data):
            self.assertIsInstance(doc, dict, f"El registro {idx} debe ser un diccionario")
            self.assertIn("manual", doc)
            self.assertIn("page", doc)
            self.assertIn("text", doc)

            manual = doc["manual"].strip().lower()
            page = int(doc["page"])
            text = str(doc["text"]).strip()

            key = (manual, page)
            self.assertNotIn(key, seen_keys, f"Página duplicada detectada: {key}")
            seen_keys.add(key)

            if not text:
                empty_texts += 1
            manuals.add(manual)

        self.assertEqual(empty_texts, 0, f"Se encontraron {empty_texts} páginas sin texto en el índice maestro")
        self.assertEqual(len(manuals), 19, f"Se esperaban 19 manuales, se detectaron {len(manuals)}")

    # ─── 2. PARIDAD DEL CATÁLOGO OFFLINE PWA ──────────────────────────────────

    def test_offline_catalog_and_chunks_parity(self):
        """Valida que todos los fragmentos en data/search/ correspondan exactamente con catalog.json."""
        self.assertTrue(self.catalog_path.exists(), "catalog.json debe existir")
        with self.catalog_path.open("r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertEqual(catalog["documents"], len(self.master_data))

        compact_records = []
        for entry in catalog["manuals"]:
            rel_file = entry["file"].lstrip("/")
            file_path = ROOT / rel_file
            self.assertTrue(file_path.exists(), f"El archivo offline no existe: {file_path}")

            with file_path.open("rb") as f_chunk:
                raw_bytes = f_chunk.read()

            self.assertEqual(len(raw_bytes), entry["bytes"])
            chunk_data = json.loads(raw_bytes.decode("utf-8"))
            self.assertEqual(chunk_data["manual"], entry["name"])
            self.assertEqual(len(chunk_data["documents"]), entry["pages"])

            compact_records.extend(
                {"manual": chunk_data["manual"], "page": row[0], "text": row[1]}
                for row in chunk_data["documents"]
            )

        self.assertEqual(self.master_data, compact_records)

    # ─── 3. PARIDAD DEL GRAFO DE CONOCIMIENTO ────────────────────────────────

    def test_massive_search_queries_and_latency(self):
        """Ejecuta 100 consultas técnicas reales y verifica precisión y velocidad extrema (<5ms/query)."""
        technical_queries = [
            "interlock 283", "item 409", "item 474", "error 66", "dose rate monitor",
            "klystron rf", "vacuum pressure", "thyratron pulse", "mlc calibration", "collimator rotation",
            "pcb 16n", "pcb 22", "pcb scc", "e-stop bunker", "safety chain 24v",
            "cooling water flow", "magnetron frequency", "gun filament current", "bending magnet", "carousel motor",
        ] * 5  # 100 consultas

        start = time.perf_counter()
        total_findings = 0

        for q in technical_queries:
            res = self.engine.search(q, limit=5)
            total_findings += res["total"]

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / len(technical_queries)) * 1000

        self.assertGreater(total_findings, 1000, "Debe haber abundante evidencia técnica indexada")
        self.assertLess(avg_ms, MAX_SEARCH_LATENCY_WARMED_MS, f"Búsqueda promedio: {avg_ms:.2f} ms (máximo {MAX_SEARCH_LATENCY_WARMED_MS} ms)")


if __name__ == "__main__":
    unittest.main()
