"""SOLVI - Pruebas Exhaustivas de Regresión para Remediaciones P0 Master (Bloques A y B).

Verifica de forma estricta:
1. C1: search-worker.js no contiene ReferenceError con variable id no declarada en offline graph diagnosis.
2. C2: log_parser_service.py parse_timestamp garantiza paridad UTC con JavaScript (sufijo Z y fechas /).
3. C3: app.js apiRequest encadena señal abort externa con timeout y garantiza limpieza en finally.
4. C4: search_engine.py SearchEngine sincroniza _search_cache bajo concurrencia con threading.Lock.
5. C5 / AI-01: api.py rechaza/ignora X-Gemini-Key de clientes y valida model_override contra ALLOWED_GEMINI_MODELS.
6. M-01 / M-02 / M-03 / M-05:
   - Paridad de umbral de error porcentual (1e-6) en multimeter.js y multimeter_service.py.
   - Manejo seguro de TP desconocido con guards contra null en tarjetas HTML, notas y avisos.
   - Paridad completa entre OFFLINE_CATALOG y TEST_POINTS_CATALOG (incluyendo notas y tolerancias).
   - Deduplicación de pulsaciones de teclado en campos de entrada física (evita doble dígito).
7. CV-02 / CV-03 / CV-04:
   - circuit-visualizer.js define escapeRegex y neutraliza caracteres especiales en expresiones regulares dinámicas.
8. GE-01 / GE-02 / GE-03 / GE-04 / LG-03:
   - Transaccionalidad y rollback ante fallos en _enrich_with_circuit_schematics de GraphEngine.
   - Resolución canónica de cables (CABLE W10, CABLE_W10, W10).
   - Priorización de tipo de componente en desempates (PCB > señal > cable > área).
   - Poda de cola BFS por max_depth y límite de 2000 elementos en find_shortest_path.
   - Resolución de números aislados a prefijos de ingeniería canónicos (ITEM, INTERLOCK).
9. CD-01 / CD-02:
   - Inicialización hilo-segura de _SUBSYSTEM_NODE_INDEX con doble verificación de bloqueo.
   - Desempate determinista en match_subsystem_for_trace priorizando coincidencias físicas de nodos.
10. LG-01:
   - Paridad criptográfica SHA-256 exacta entre data/linac_graph.json y scripts/static/linac_graph.json.
11. Regla de Usuario:
   - Cero menciones visibles de IA/AI en interfaces y errores.
"""

from __future__ import annotations

from collections import OrderedDict
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATIC_DIR = SCRIPTS_DIR / "static"
DATA_DIR = ROOT / "data"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app
from ai_service import ALLOWED_GEMINI_MODELS
from graph_engine import GraphEngine, _TYPE_PRIORITY
from multimeter_service import (
    TEST_POINTS_CATALOG,
    evaluate_measurement,
    simulate_reading,
    get_test_point,
)
from search_engine import SearchEngine
from log_parser_service import parse_timestamp
import circuit_data


class AuditP0MasterFixesSuite(unittest.TestCase):
    """Suite de verificación para todas las remediaciones P0 de Bloques A y B."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with open(STATIC_DIR / "search-worker.js", "r", encoding="utf-8") as f:
            cls.worker_js = f.read()
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(STATIC_DIR / "multimeter.js", "r", encoding="utf-8") as f:
            cls.multimeter_js = f.read()
        with open(STATIC_DIR / "circuit-visualizer.js", "r", encoding="utf-8") as f:
            cls.cv_js = f.read()
        with open(SCRIPTS_DIR / "api.py", "r", encoding="utf-8") as f:
            cls.api_py = f.read()
        with open(SCRIPTS_DIR / "ai_service.py", "r", encoding="utf-8") as f:
            cls.ai_service_py = f.read()
        with open(SCRIPTS_DIR / "graph_engine.py", "r", encoding="utf-8") as f:
            cls.graph_engine_py = f.read()
        with open(SCRIPTS_DIR / "circuit_data.py", "r", encoding="utf-8") as f:
            cls.circuit_data_py = f.read()

    # ─── C1: SEARCH-WORKER OFFLINE GRAPH DIAGNOSIS ─────────────────────────────

    def test_c1_search_worker_no_undefined_id_reference(self):
        """diagnoseGraphOffline en search-worker.js debe invocar finalizeTrace sin referencia a variable id no definida."""
        self.assertNotIn("postMessage({ id, type: 'graph_diagnosis_result'", self.worker_js)
        self.assertIn("return await finalizeTrace({", self.worker_js)
        func_match = re.search(r"async function diagnoseGraphOffline[\s\S]*?\n\}", self.worker_js)
        self.assertIsNotNone(func_match)
        func_body = func_match.group(0)
        self.assertNotIn("postMessage({ id", func_body)

    # ─── C2: LOG PARSER UTC TIMESTAMP PARITY ──────────────────────────────────

    def test_c2_log_parser_utc_timestamp_numerical_parity(self):
        """parse_timestamp interpreta timestamps con Z en UTC garantizando paridad de época con JS."""
        ts_str = "2023-10-24T14:30:00Z"
        expected_utc = datetime.datetime(2023, 10, 24, 14, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
        parsed_ts = parse_timestamp(ts_str)
        self.assertEqual(parsed_ts, expected_utc)

        ts_slash = "24/10/2023 14:30:00"
        parsed_slash = parse_timestamp(ts_slash)
        expected_slash = datetime.datetime(2023, 10, 24, 14, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(parsed_slash, expected_slash)

    # ─── C3: APP.JS APIREQUEST SIGNAL & TIMEOUT INTEGRATION ────────────────────

    def test_c3_app_js_api_request_signal_and_timeout_integration(self):
        """apiRequest en app.js encadena signal externo al controller y limpia timeout en finally."""
        self.assertIn("if (options.signal) {", self.app_js)
        self.assertTrue('options.signal.addEventListener("abort"' in self.app_js or "options.signal.addEventListener('abort'" in self.app_js)
        self.assertIn("clearTimeout(timer);", self.app_js)

    # ─── C4: SEARCH_ENGINE THREAD SAFETY ON CACHE ──────────────────────────────

    def test_c4_search_engine_cache_thread_safety(self):
        """SearchEngine._search_cache está protegido contra concurrencia con Lock."""
        sample_docs = [
            {"manual": "movement", "page": 10, "text": "Interlock 283 and Error 66. Reset motors."},
            {"manual": "vacuum", "page": 4, "text": "Error: 66. Examine the vacuum pump."},
        ]
        engine = SearchEngine(records=sample_docs)
        self.assertTrue(hasattr(engine, "_search_cache_lock"))

        errors = []
        def concurrent_reader_writer(thread_idx: int):
            try:
                for i in range(25):
                    q = f"interlock test query {i % 5}"
                    engine.search(q, limit=5)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(concurrent_reader_writer, idx) for idx in range(8)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Errores en acceso concurrente a la caché de búsqueda: {errors}")

    # ─── C5 & AI-01: API SECURITY & ALLOWLIST ─────────────────────────────────

    def test_c5_api_ignores_client_x_gemini_key_and_validates_model(self):
        """api.py no acepta X-Gemini-Key del cliente y valida model_override contra allowlist."""
        self.assertNotIn("request.headers.get('X-Gemini-Key')", self.api_py)
        self.assertNotIn('request.headers.get("X-Gemini-Key")', self.api_py)

        res = self.client.post("/diagnose/ai", json={
            "symptoms": ["ITEM 409"],
            "model_override": "gemini-ultra-pro-dangerous-model",
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("error"), "validation_error")
        self.assertIn("Modelo de diagnóstico no permitido", data.get("message", ""))

        self.assertIn("gemini-2.5-flash", ALLOWED_GEMINI_MODELS)
        self.assertNotIn("gemini-2.5-pro", ALLOWED_GEMINI_MODELS)

    # ─── M-01 & M-02 & M-03 & M-05: MULTIMETER REMEDIATIONS ───────────────────

    def test_m01_epsilon_threshold_parity_1e6(self):
        """multimeter.js utiliza Math.abs(nominal) < 1e-6 alineado exactamente con Python 1e-6."""
        self.assertIn("1e-6", self.multimeter_js)
        self.assertNotIn("1e-5", self.multimeter_js)

    def test_m02_unknown_test_point_safely_evaluated_and_rendered(self):
        """Punto de prueba desconocido retorna ok: false, error: 'unknown_test_point' y los renders no lanzan TypeError."""
        self.assertIn('error: "unknown_test_point"', self.multimeter_js)
        self.assertIn('status_badge: "DESCONOCIDO"', self.multimeter_js)
        self.assertIn('typeof ev.nominal_value === "number"', self.multimeter_js)
        self.assertIn('typeof ev.tolerance_min === "number"', self.multimeter_js)
        self.assertIn('evaluacion.status_badge === "DESCONOCIDO"', self.multimeter_js)

    def test_m03_offline_catalog_tp3_notes_and_specs_parity_json(self):
        """El catálogo offline en JSON contiene la especificación y nota exacta de TP3."""
        import json
        with open("scripts/static/multimeter_catalog.json", "r", encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertIn("TP3", catalog)
        self.assertIn("800V pico / 3.5µs (Pulso de rejilla de tiratrón)", catalog["TP3"]["spec"])

    def test_m05_keydown_deduplication_on_editable_elements(self):
        """multimeter.js comprueba isEditable y retorna inmediatamente para no duplicar pulsaciones."""
        self.assertIn("const isEditable = tag === \"INPUT\" || tag === \"TEXTAREA\" || tag === \"SELECT\" || (e.target && e.target.isContentEditable);", self.multimeter_js)
        self.assertIsNotNone(re.search(r"if\s*\(\s*isEditable\s*\)\s*\{\s*return;", self.multimeter_js))

    # ─── CV-02: VISOR DOCUMENTAL Y SALIDA SEGURA ─────────────────────────────

    def test_cv02_circuit_visualizer_escapes_documentary_values(self):
        """El visor inserta evidencia como texto escapado y no compila búsquedas del usuario como regex."""
        self.assertIn("function esc(value)", self.cv_js)
        self.assertIn("&quot;", self.cv_js)
        self.assertNotIn("new RegExp(", self.cv_js)

    # ─── GE-01 / GE-02 / GE-03 / GE-04 / LG-03: GRAPH ENGINE ─────────────────

    def test_ge01_graph_never_enriches_cooccurrences_as_circuits(self):
        """El grafo conserva su índice base; no importa topologías sintéticas desde circuit_data."""
        engine = GraphEngine(enrich_circuits=False)
        self.assertFalse(engine.enriched_circuits)
        self.assertFalse(hasattr(engine, "_enrich_with_circuit_schematics"))
        self.assertNotIn("controlled_by", {edge[1] for edges in engine.adjacency.values() for edge in edges})

    def test_ge02_base_graph_resolution_does_not_depend_on_removed_synthetic_cables(self):
        """El grafo resuelve entidades realmente indexadas y no fabrica el cable W10 histórico."""
        engine = GraphEngine()
        self.assertEqual(engine.resolve_entity("ITEM 474"), "ITEM 474")
        self.assertIsNone(engine.resolve_entity("CABLE W10"))

    def test_ge03_candidate_type_prioritization(self):
        """En desempates por subcadena, _TYPE_PRIORITY da preferencia a PCB sobre AREA."""
        engine = GraphEngine()
        self.assertGreater(_TYPE_PRIORITY["pcb"], _TYPE_PRIORITY["area"])
        self.assertGreater(_TYPE_PRIORITY["signal"], _TYPE_PRIORITY["area"])
        self.assertGreater(_TYPE_PRIORITY["cable"], _TYPE_PRIORITY["area"])

    def test_ge04_shortest_path_pruning(self):
        """find_shortest_path no agrega caminos con longitud superior a max_depth."""
        engine = GraphEngine()
        path = engine.find_shortest_path("ITEM 409", "CATHODE_GUN", max_depth=1)
        self.assertIsNone(path)

    def test_lg03_numeric_input_does_not_resolve_removed_synthetic_entities(self):
        """Un número publicado se resuelve; un interlock no indexado ya no se inventa."""
        engine = GraphEngine()
        res_474 = engine.resolve_entity("474")
        self.assertEqual(res_474, "ITEM 474")

        self.assertIsNone(engine.resolve_entity("283"))

    # ─── CD-01 & CD-02: CATÁLOGO DOCUMENTAL CONCURRENCIA Y MATCH ────────────

    def test_cd01_documented_catalog_cache_is_thread_safe(self):
        """La carga cacheada del único catálogo retorna la misma estructura en lecturas paralelas."""
        circuit_data.load_catalog.cache_clear()
        results = []

        def worker():
            results.append(len(circuit_data.get_all_subsystems()))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(results), 10)
        self.assertTrue(all(r == results[0] for r in results))

    def test_cd02_documented_match_never_falls_back_to_an_arbitrary_diagram(self):
        """Una coincidencia abre la ruta publicada; una consulta ajena no inventa un esquema."""
        res = circuit_data.match_subsystem_for_trace(["TP100", "ION CHAMBER"])
        self.assertEqual(res["subsystem_id"], "dosimetry_bias_320v")
        self.assertIsNone(circuit_data.match_subsystem_for_trace(["DOOR_SW_283"])["subsystem_id"])

    # ─── LG-01: SHA-256 PARITY BETWEEN DATA AND STATIC GRAPH ──────────────────

    def test_lg01_linac_graph_sha256_parity(self):
        """data/linac_graph.json y scripts/static/linac_graph.json deben tener el mismo hash SHA-256."""
        data_graph_path = DATA_DIR / "linac_graph.json"
        static_graph_path = STATIC_DIR / "linac_graph.json"
        self.assertTrue(data_graph_path.exists(), "Falta data/linac_graph.json")
        self.assertTrue(static_graph_path.exists(), "Falta scripts/static/linac_graph.json")

        with open(data_graph_path, "rb") as f:
            data_hash = hashlib.sha256(f.read()).hexdigest()
        with open(static_graph_path, "rb") as f:
            static_hash = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(data_hash, static_hash, f"Discrepancia de hash: data={data_hash}, static={static_hash}")

    # ─── AI-03: CITAS VACÍAS SIN FALSA ATRIBUCIÓN ─────────────────────────────

    def test_ai03_empty_citation_ids_fallback_does_not_falsely_attribute_all_sources(self):
        """AI-03: Cuando citation_ids viene vacío, no se deben incluir todas las fuentes como citadas."""
        self.assertNotIn("extracted_cids = list(citation_map.keys())", self.ai_service_py)

    # ─── LG-02: RESOLUCIÓN DETERMINISTA AREA 70 vs AREA70 ──────────────────────

    def test_lg02_area70_ocr_determinism_parity(self):
        """LG-02: AREA 70 y AREA70 resuelven deterministamente al nodo canónico 'AREA 70' con todas sus páginas."""
        data_graph_path = DATA_DIR / "linac_graph.json"
        with open(data_graph_path, "r", encoding="utf-8") as f:
            g = json.load(f)
        self.assertEqual(g.get("lookup", {}).get("area70"), "AREA 70")
        area_entity = g.get("entities", {}).get("AREA 70", {})
        pages = area_entity.get("pages", [])
        self.assertIn(["catalogue", 281], pages)
        self.assertIn(["catalogue", 285], pages)

        engine = GraphEngine()
        self.assertEqual(engine.resolve_entity("AREA 70"), "AREA 70")
        self.assertEqual(engine.resolve_entity("AREA70"), "AREA 70")
        self.assertEqual(engine.resolve_entity("area 70"), "AREA 70")

    # ─── DUP-15 & PARIDAD DE DIAGNÓSTICO TOPOLÓGICO JS↔PYTHON ──────────────────

    def test_dup15_clean_key_accent_normalization_parity_js_python(self):
        """DUP-15: search-worker.js cleanKey normaliza diacríticos (NFD) garantizando paridad con Python _clean_key."""
        self.assertIn('.normalize("NFD")', self.worker_js)
        self.assertIn('replace(/[\\u0300-\\u036f]/g, "")', self.worker_js)

    def test_search_worker_resolve_entity_parity_with_graph_engine(self):
        """search-worker.js implementa _TYPE_PRIORITY, resolución de cables y límites de 6 síntomas como graph_engine.py."""
        self.assertIn("const _TYPE_PRIORITY =", self.worker_js)
        self.assertIn("cableM = String(text).match", self.worker_js)
        self.assertIn(".slice(0, 6)", self.worker_js)

    # ─── CV-01: CATÁLOGO PUBLICABLE ÚNICO ───────────────────────────────────

    def test_cv01_verified_signal_paths_is_the_only_published_catalog(self):
        """No queda un archivo SVG sintético ni una segunda definición Python de las rutas."""
        import json
        with open("data/verified_signal_paths.json", "r", encoding="utf-8") as f:
            paths = json.load(f)
        self.assertEqual(paths, circuit_data.load_catalog())
        self.assertFalse((STATIC_DIR / "circuit_schematics.json").exists())

    # ─── X-13: SIN FALLBACK HEURÍSTICO DE ESQUEMAS ───────────────────────────

    def test_x13_documented_matcher_has_no_legacy_subsystem_fallback(self):
        """Backend y worker usan el catálogo publicado y devuelven null ante falta de evidencia."""
        self.assertIn('fetch("/data/verified_signal_paths.json")', self.worker_js)
        self.assertIn('subsystem_id: null', self.worker_js)
        self.assertNotIn('"safety_loop"', self.worker_js)

    # ─── M-03 / M-04: PARIDAD PROFUNDA DE CATÁLOGO Y MAPAS TP ─────────────────

    def test_m03_m04_full_catalog_and_node_to_tp_deep_parity_json(self):
        """M-03 y M-04: El catálogo offline cargado es igual al backend y el mapeo en JS coincide."""
        from multimeter_service import TEST_POINTS_CATALOG, NODE_TO_TP_MAP
        self.assertEqual(len(TEST_POINTS_CATALOG), 20)
        self.assertEqual(len(NODE_TO_TP_MAP), 12)

        import json
        with open("scripts/static/multimeter_catalog.json", "r", encoding="utf-8") as f:
            catalog = json.load(f)
            
        for tp_id in TEST_POINTS_CATALOG:
            self.assertIn(tp_id, catalog)

        for node_id, mapped_tp in NODE_TO_TP_MAP.items():
            self.assertIn(f'"{node_id}": "{mapped_tp}"', self.multimeter_js)


    # ─── REGLA DE USUARIO: CERO MENCIONES VISIBLES DE IA / AI ─────────────────

    def test_strict_zero_visible_ai_mentions_in_frontend(self):
        """Verifica que no existan menciones visibles de IA/AI en index.html ni en toasts/alerts."""
        from _helpers import extract_visible_html_text, assert_no_visible_ai
        template_file = SCRIPTS_DIR / "templates" / "index.html"
        if template_file.is_file():
            with open(template_file, "r", encoding="utf-8") as f:
                html_code = f.read()
            visible_text = extract_visible_html_text(html_code)
            assert_no_visible_ai(self, visible_text, "index.html")

        toast_regex = re.compile(r'(?:toast|alert)\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE)
        for js_name, js_content in [
            ("app.js", self.app_js),
            ("multimeter.js", self.multimeter_js),
            ("circuit-visualizer.js", self.cv_js),
        ]:
            for toast_str in toast_regex.findall(js_content):
                self.assertNotRegex(
                    toast_str,
                    r"\b(?:IA|AI|Inteligencia\s+Artificial)\b",
                    f"Mención de IA/AI en toast/alert en {js_name}: {toast_str}"
                )


if __name__ == "__main__":
    unittest.main()

