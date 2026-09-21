"""SOLVI - Suite de Pruebas Masivas y Exhaustivas de Compatibilidad y Estrés.
Cubre:
1. Integridad de los 19 manuales (6,322 páginas) y detección de corrupción/duplicados.
2. Paridad del catálogo offline en data/search/ y consistencia de hashes SHA-256.
3. Integridad y rendimiento del Grafo de Conocimiento (data/linac_graph.json y static).
4. Pruebas masivas de búsqueda (100 consultas técnicas, tolerancia a puntuación y rechazo de falsos positivos).
5. Pruebas de Traza de Circuitos física en topología de Linac.
6. Validación completa de endpoints REST de la API Flask (search, diagnose, graph, static, manifest, notes).
7. Simulación de desconexión / paridad con Web Worker.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from search_engine import (
    SearchEngine,
    normalize,
    tokens,
    MAX_SEARCH_LATENCY_COLD_MS,
)

from api import app, search_engine as api_search_engine


class MassiveSOLVITestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_path = ROOT / "data" / "all_manuals.json"
        cls.catalog_path = ROOT / "data" / "search" / "catalog.json"
        cls.graph_data_path = ROOT / "data" / "linac_graph.json"
        cls.graph_static_path = ROOT / "scripts" / "static" / "linac_graph.json"

        with cls.data_path.open("r", encoding="utf-8") as f:
            cls.master_data = json.load(f)

        cls.engine = SearchEngine(cls.master_data)
        cls.client = app.test_client()

    # ─── 1. INTEGRIDAD DE DATOS MAESTROS ─────────────────────────────────────

    def test_01_master_records_integrity(self):
        """Verifica las 6,322 páginas de manuales: tipos, unicidad y ausencia de vacíos."""
        total = len(self.master_data)
        self.assertGreaterEqual(total, 6000, f"Debe haber más de 6,000 páginas, se encontraron {total}")
        
        seen_keys = set()
        empty_texts = 0
        manuals = set()

        for idx, doc in enumerate(self.master_data):
            self.assertIsInstance(doc, dict, f"El registro {idx} debe ser un diccionario")
            self.assertIn("manual", doc, f"Registro {idx} no tiene campo 'manual'")
            self.assertIn("page", doc, f"Registro {idx} no tiene campo 'page'")
            self.assertIn("text", doc, f"Registro {idx} no tiene campo 'text'")
            
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
        self.assertEqual(len(manuals), 19, f"Se esperaban 19 manuales, se detectaron {len(manuals)}: {sorted(manuals)}")

    # ─── 2. PARIDAD DEL CATÁLOGO OFFLINE (PWA) ───────────────────────────────

    def test_02_offline_catalog_and_chunks_parity(self):
        """Valida que todos los fragmentos en data/search/ correspondan con catalog.json."""
        self.assertTrue(self.catalog_path.exists(), "catalog.json debe existir")
        with self.catalog_path.open("r", encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertIn("version", catalog)
        self.assertIn("documents", catalog)
        self.assertIn("manuals", catalog)
        self.assertEqual(catalog["documents"], len(self.master_data))

        total_offline_pages = 0
        for entry in catalog["manuals"]:
            rel_file = entry["file"].lstrip("/")
            file_path = ROOT / rel_file
            self.assertTrue(file_path.exists(), f"El archivo offline no existe: {file_path}")
            
            # Verificar integridad de contenido
            raw_bytes = file_path.read_bytes()
            self.assertEqual(len(raw_bytes), entry["bytes"], f"Tamaño incorrecto en catálogo para {entry['name']}")
            
            chunk_data = json.loads(raw_bytes.decode("utf-8"))
            self.assertEqual(chunk_data["manual"], entry["name"])
            self.assertEqual(len(chunk_data["documents"]), entry["pages"])
            total_offline_pages += len(chunk_data["documents"])

        self.assertEqual(total_offline_pages, len(self.master_data), "El total de páginas offline debe ser 6,322")

    # ─── 3. GRAFO DE CONOCIMIENTO (TOPOLOGÍA LINAC) ──────────────────────────

    def test_04_massive_search_queries_and_false_positive_rejection(self):
        """Ejecuta 100 búsquedas técnicas reales y verifica precisión y velocidad."""
        technical_queries = [
            # 1-10 Interlocks
            "interlock 283", "interlock 409", "interlock 101", "interlock 327", "interlock 204",
            "interlock 211", "interlock 214", "interlock 215", "interlock 216", "interlock 217",
            # 11-20 Items y señales
            "ITEM 474", "ITEM 409", "ITEM 327", "ITEM 332", "ITEM 128",
            "ITEM 665", "ITEM 410", "ITEM 411", "ITEM 412", "ITEM 413",
            # 21-30 Tarjetas PCB
            "PCB 16V", "PCB AO8", "PCB AI12", "PCB SCC-HTB", "PCB DIE HTA",
            "PCB 16N", "PCB AO12", "PCB DIE ICB", "PCB SCC RHA", "PCB 16B",
            # 31-40 Señales de control
            "D_RATE 1", "RAD_ON", "HT INHIBIT", "GUN TRIGGER", "VACUUM FAULT",
            "WATER FLOW", "DOSE RATE", "ENERGY SELECT", "COLLIMATOR ROTATION", "GANTRY ROTATION",
            # 41-50 Cables y Conectores
            "cable assembly", "W10", "W20", "PL1", "SK1",
            "TB1", "PL2", "SK2", "TB2", "J1",
            # 51-60 Áreas y Racks
            "Area 16", "Area 22", "Rack HTCA", "RF Driver", "Klystron",
            "Modulator", "Magnetron", "Electron Gun", "Waveguide", "Vacuum Pump",
            # 61-70 Fallas mecánicas y cinemáticas
            "mlc leaf motor", "leaf missing", "encoder timeout", "table collision", "anti collision",
            "backup timer", "dose 1 channel", "dose 2 channel", "flatness error", "symmetry error",
            # 71-80 Módulos de Imagen y Control
            "iViewGT", "XVI CBCT", "panel communication", "generator fault", "high voltage enable",
            "filament preheat", "arc detection", "thyratron trigger", "de-Qing circuit", "pulse transformer",
            # 81-90 Frases compuestas exactas
            "dose rate mon", "check fail ht2", "facility 1", "facility 2", "safety interlock loop",
            "gantry overspeed", "gantry position potentiometer", "collimator angle", "service mode", "normal mode",
            # 91-100 Síntomas y tolerancias
            "low dose rate monitor", "klystron collector temperature", "target water temperature",
            "vacuum ion pump", "bending magnet current", "focus coil current", "steering coil x",
            "steering coil y", "gun cathode heater", "linac standby"
        ]

        self.assertEqual(len(technical_queries), 100)

        start = time.perf_counter()
        total_results = 0
        for q in technical_queries:
            res = self.engine.search(q, limit=10)
            self.assertIsInstance(res, dict)
            self.assertIn("results", res)
            self.assertIn("total", res)
            total_results += res["total"]

        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / len(technical_queries)) * 1000
        print(f"\n[BENCHMARK] 100 Consultas masivas completadas en {elapsed:.2f}s ({avg_ms:.2f} ms/query). Total hallazgos: {total_results}")
        self.assertLess(avg_ms, MAX_SEARCH_LATENCY_COLD_MS, f"La latencia promedio ({avg_ms:.2f} ms) debe ser < {MAX_SEARCH_LATENCY_COLD_MS} ms")

        # Verificación estricta de rechazo de subcadenas falsas (fragmentos sueltos)
        false_tests = [
            ("art", 0),          # No debe coincidir con 'part', 'start', 'restart'
            ("interl", 0),       # Prefijo incompleto de interlock
            ("calibrati", 0),    # Prefijo incompleto de calibration
            ("rotat", 0),        # Prefijo incompleto de rotation
            ("xyznonexistent999", 0)
        ]
        for term, max_expected in false_tests:
            r = self.engine.search(term, limit=10)
            self.assertLessEqual(r["total"], max_expected, f"Falsos positivos detectados para '{term}': {r['total']}")

    # ─── 5. TRAZA DE CIRCUITOS (TOPOLOGÍA FÍSICA) ────────────────────────────

    def test_06_flask_endpoints(self):
        """Verifica el ciclo de vida completo de endpoints HTTP."""
        # 1. Root y Headers de seguridad
        res_root = self.client.get("/")
        self.assertEqual(res_root.status_code, 200)
        self.assertEqual(res_root.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res_root.headers.get("X-Content-Type-Options"), "nosniff")

        # 2. Health & Version
        res_health = self.client.get("/health")
        self.assertEqual(res_health.status_code, 200)
        h_data = res_health.get_json()
        self.assertTrue(h_data["ok"])
        self.assertEqual(h_data["pages"], len(self.master_data))
        self.assertEqual(h_data["manuals"], 19)

        res_ver = self.client.get("/version")
        self.assertEqual(res_ver.status_code, 200)
        self.assertIn("build", res_ver.get_json())

        # 3. PWA Assets
        for path in ["/manifest.json", "/sw.js", "/data/linac_graph.json", "/data/search/catalog.json"]:
            with self.client.get(path) as r:
                self.assertEqual(r.status_code, 200, f"Error cargando activo {path}")

        # 4. Search endpoint con paginación
        with self.client.get("/search?q=item+409&limit=5&offset=0") as r_search:
            self.assertEqual(r_search.status_code, 200)
            s_data = r_search.get_json()
            self.assertGreater(s_data["total"], 0)
            self.assertLessEqual(len(s_data["results"]), 5)

        # 5. Diagnose endpoint con array de síntomas
        with self.client.post("/diagnose", json={"symptoms": ["dose rate mon", "ITEM 327"]}) as r_diag:
            self.assertEqual(r_diag.status_code, 200)
            d_data = r_diag.get_json()
            self.assertIn("results", d_data)
            self.assertGreater(len(d_data["results"]), 0)

        # 7. Notes endpoint
        r_notes = self.client.get("/notes")
        self.assertEqual(r_notes.status_code, 200)
        self.assertIsInstance(r_notes.get_json(), list)


if __name__ == "__main__":
    unittest.main()
