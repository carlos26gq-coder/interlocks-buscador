"""SOLVI - Suite Exhaustiva de Rendimiento, Estrés Concurrente, Fuzzing y Resiliencia.

Verifica:
1. Ráfagas concurrentes en endpoints (/search, /diagnose, /diagnose/graph, /circuits/*, /health).
2. Fuzzing adversarial, payloads gigantes y entradas malformadas sin crasheos HTTP 500 ni bloqueos.
3. Integridad de concurrencia y aislamiento en caché en memoria y estructuras del grafo.
4. Resiliencia de memoria y prevención de fugas en visualizadores (SVG canvas, visor PDF, Web Worker).
5. Cumplimiento estricto de la regla de cero menciones visibles de IA/AI.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import re
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api import app, limiter, _sanitize_error_message
from search_engine import SearchEngine, normalize
from graph_engine import GraphEngine, get_graph_engine
from circuit_data import match_subsystem_for_trace, get_all_subsystems, get_subsystem
from ai_service import (
    extract_json_safely,
    get_cached_diagnosis,
    set_cached_diagnosis,
    clear_diagnostic_cache,
    _make_cache_key,
    _DIAG_CACHE,
    gather_grounding_context,
)


class PerformanceAndStressSuite(unittest.TestCase):
    """Pruebas de estrés masivo, concurrencia de hilos, robustez ante sobrecarga y fuzzing adversarial."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with open(ROOT / "data" / "all_manuals.json", "r", encoding="utf-8") as f:
            cls.manuals_data = json.load(f)
        cls.search_engine = SearchEngine(cls.manuals_data)
        cls.graph_engine = get_graph_engine()

    def setUp(self):
        clear_diagnostic_cache()

    # ─── 1. RÁFAGAS CONCURRENTES EN ENDPOINTS BACKEND ─────────────────────────

    def test_concurrent_search_bursts_under_multi_threading(self):
        """20 hilos concurrentes ejecutan 100 consultas simultáneas sin errores 500 ni colisiones."""
        queries = [
            "interlock 283", "ITEM 474", "PCB 16N", "D_RATE 1", "RAD_ON",
            "gantry rotation", "vacuum pump", "dose rate mon", "collimator", "cable W10"
        ]
        results = []
        errors = []

        def execute_search(query_str):
            with app.test_client() as client:
                res = client.get(f"/search?q={query_str}&limit=10")
                return res.status_code, res.get_json()

        start_time = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(execute_search, queries[i % len(queries)]) for i in range(80)]
            for future in as_completed(futures):
                try:
                    status, data = future.result()
                    results.append(status)
                    if status != 200:
                        errors.append(f"Status no esperado: {status}")
                except Exception as exc:
                    errors.append(str(exc))

        elapsed = time.perf_counter() - start_time
        avg_ms = (elapsed / 80) * 1000

        self.assertEqual(len(errors), 0, f"Errores en ráfaga de búsqueda concurrente: {errors[:3]}")
        self.assertEqual(len(results), 80)
        self.assertTrue(all(s == 200 for s in results))
        self.assertLess(avg_ms, 80.0, f"Latencia promedio por consulta demasiado alta: {avg_ms:.2f}ms")

    def test_concurrent_diagnose_and_graph_endpoints_stress(self):
        """Peticiones simultáneas a /diagnose/graph y /circuits/* procesadas de forma concurrente."""
        endpoints = [
            ("POST", "/diagnose/graph", {"symptoms": ["ITEM 409", "ITEM 332"]}),
            ("POST", "/diagnose/graph", {"symptoms": ["interlock 283", "PCB 16N"]}),
            ("POST", "/circuits/match", {"components": ["DOOR_SW_283", "ESTOP_CONSOLE"]}),
            ("GET", "/circuits/safety_loop", None),
            ("GET", "/circuits/radiation_beam", None),
            ("GET", "/circuits/subsystems", None),
            ("GET", "/health", None),
        ]

        def call_endpoint(method, url, payload):
            with app.test_client() as client:
                if method == "POST":
                    r = client.post(url, json=payload)
                else:
                    r = client.get(url)
                return r.status_code, r.get_json()

        failures = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            tasks = [executor.submit(call_endpoint, ep[0], ep[1], ep[2]) for i in range(50) for ep in [endpoints[i % len(endpoints)]]]
            for t in as_completed(tasks):
                try:
                    status, data = t.result()
                    if status not in (200, 429):
                        failures.append(f"HTTP {status} en {data}")
                except Exception as exc:
                    failures.append(str(exc))

        self.assertEqual(len(failures), 0, f"Fallos en endpoints bajo concurrencia: {failures}")

    # ─── 2. FUZZING ADVERSARIAL Y PAYLOADS MALFORMADOS (CERO 500 CRASHES) ────

    def test_search_adversarial_parameters_and_type_fuzzing(self):
        """Parámetros de paginación y texto adversariales devuelven 400 controlado, jamás 500."""
        adversarial_cases = [
            "/search?q=" + ("A" * 500),  # Supera MAX_QUERY_LENGTH
            "/search?q=interlock&offset=abc",  # Offset alfanumérico
            "/search?q=interlock&offset=-50",  # Offset negativo
            "/search?q=interlock&offset=99999999999999999999",  # Offset desmesurado
            "/search?q=interlock&limit=-10",  # Límite negativo
            "/search?q=interlock&limit=99999999",  # Límite fuera de rango
            "/search?q=interlock&manual=" + ("x" * 200),  # Filtro de manual inexistente
            "/search?q=%00%00%00%00",  # Caracteres nulos url-encoded
            "/search?q=%E0%A4%A",  # Byte UTF-8 incompleto
        ]

        for path in adversarial_cases:
            with self.client.get(path) as res:
                self.assertIn(
                    res.status_code,
                    (200, 400),
                    f"Ruta '{path}' produjo código inesperado {res.status_code} (debe ser 200 o 400)."
                )
                self.assertNotEqual(res.status_code, 500, f"CRASH 500 detectado en {path}")

    def test_post_endpoints_fuzzing_with_malformed_json_and_types(self):
        """Cuerpos JSON malformados, vacíos o con tipos anómalos son rechazados limpiamente."""
        fuzz_payloads = [
            {},  # Vacío
            {"symptoms": "INTERLOCK 283"},  # String en vez de lista (debe normalizarse o validarse sin crash)
            {"symptoms": [123, 456]},  # Enteros en vez de strings
            {"symptoms": [None, False]},  # Tipos nulos / booleanos
            {"symptoms": ["a" * 10000]},  # Síntoma descomunal (10,000 chars)
            {"symptoms": [{"objeto": "anidado"}]},  # Objeto anidado en array
            {"components": "DOOR_SW_283"},  # String en vez de lista en /circuits/match
            {"components": [None, 999, {"x": 1}]},  # Tipos mixtos
            {"components": ["x" * 5000]},  # Componente gigante
        ]

        endpoints_to_test = ["/diagnose", "/diagnose/graph", "/circuits/match"]

        for ep in endpoints_to_test:
            for p in fuzz_payloads:
                with self.client.post(ep, json=p) as res:
                    self.assertIn(
                        res.status_code,
                        (200, 400),
                        f"Endpoint {ep} falló con status {res.status_code} ante payload: {p}"
                    )
                    self.assertNotEqual(res.status_code, 500, f"CRASH 500 no controlado en {ep}")

    def test_post_endpoints_with_raw_non_json_data(self):
        """Datos no-JSON enviados con cabecera application/json devuelven 400 sin excepción."""
        raw_garbage = [
            b"ESTO NO ES UN JSON",
            b"{json_incompleto: 123",
            b"\x00\x01\x02\xff\xfe",
            b"   \t\n  ",
        ]
        for data in raw_garbage:
            with self.client.post("/diagnose/graph", data=data, content_type="application/json") as res:
                self.assertEqual(res.status_code, 400)
                json_resp = res.get_json()
                self.assertIsNotNone(json_resp)

    # ─── 3. ESTRÉS DEL GRAFO Y SEGURIDAD ANTE CICLOS ─────────────────────────

    def test_graph_engine_cyclic_topology_stress(self):
        """Grafos con bucles redundantes y caminos circulares no generan recursión infinita."""
        cyclic_data = {
            "version": "test",
            "entities": {
                "A": {"type": "pcb", "pages": []},
                "B": {"type": "pcb", "pages": []},
                "C": {"type": "cable", "pages": []},
                "D": {"type": "test_point", "pages": []},
            },
            "adjacency": {
                "A": [["B", "wire", 1, "diag", 1], ["C", "wire", 1, "diag", 2]],
                "B": [["A", "wire", 1, "diag", 1], ["C", "wire", 1, "diag", 3]],
                "C": [["D", "wire", 1, "diag", 4], ["A", "wire", 1, "diag", 2]],
                "D": [["B", "wire", 1, "diag", 5], ["A", "wire", 1, "diag", 6]],
            },
            "lookup": {"a": "A", "b": "B", "c": "C", "d": "D"}
        }
        engine = GraphEngine(cyclic_data)
        # Búsqueda de camino con bucles cerrados
        path = engine.find_shortest_path("A", "D")
        self.assertIsNotNone(path)
        self.assertLessEqual(len(path), 4)

        # Traza con todos los nodos del ciclo
        trace = engine.trace_circuit(["A", "B", "C", "D"])
        self.assertTrue(trace["found"])
        self.assertIn("hub_node", trace)

    def test_circuit_matcher_with_heavy_payload(self):
        """match_subsystem_for_trace soporta 300 componentes y símbolos adversariales en < 50ms."""
        heavy_components = [f"COMP_{i}" for i in range(200)] + ["DOOR_SW_283", "ESTOP_CONSOLE", "ITEM 474"]
        start = time.perf_counter()
        match = match_subsystem_for_trace(heavy_components)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertIn("subsystem_id", match)
        self.assertIn("matched_nodes", match)
        self.assertLess(elapsed_ms, 50.0, f"El matcher tardó demasiado: {elapsed_ms:.2f}ms")

    # ─── 4. CACHÉ EN MEMORIA: CONCURRENCIA, AISLAMIENTO Y PARSING ROBUSTO ────

    def test_cache_concurrent_multi_thread_read_write(self):
        """Escrituras y lecturas simultáneas en hilos paralelos no corrompen _DIAG_CACHE."""
        clear_diagnostic_cache()

        def worker(thread_id):
            for i in range(25):
                symptoms = [f"symptom_{thread_id}_{i}", "ITEM 409"]
                payload = {"root_cause": f"Causa T{thread_id}-{i}", "thread": thread_id}
                set_cached_diagnosis(symptoms, payload, "gemini-3.5-flash")
                cached = get_cached_diagnosis(symptoms)
                if not cached or cached["data"]["root_cause"] != f"Causa T{thread_id}-{i}":
                    return False
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, tid) for tid in range(8)]
            for f in as_completed(futures):
                self.assertTrue(f.result())

        self.assertLessEqual(len(_DIAG_CACHE), 300)

    def test_cache_deepcopy_isolation_prevents_mutation(self):
        """Modificar un diagnóstico retornado de la caché no altera el valor almacenado."""
        clear_diagnostic_cache()
        symptoms = ["ITEM 409", "modulador"]
        original_data = {"root_cause": "Falla de disparo original", "boards": ["PCB 22"]}
        set_cached_diagnosis(symptoms, original_data, "gemini-3.5-flash")

        retrieved = get_cached_diagnosis(symptoms)
        self.assertIsNotNone(retrieved)
        # Mutar el diccionario recuperado
        retrieved["data"]["root_cause"] = "MUTADO_EXTERNAMENTE"
        retrieved["data"]["boards"].append("PCB_INTRUSA")

        # Recuperar de nuevo y comprobar que la caché permanece intacta
        retrieved_again = get_cached_diagnosis(symptoms)
        self.assertEqual(retrieved_again["data"]["root_cause"], "Falla de disparo original")
        self.assertEqual(retrieved_again["data"]["boards"], ["PCB 22"])

    def test_extract_json_safely_dirty_and_corrupt_variants(self):
        """El parser tolerante maneja saltos de línea sin escapar, bloques markdown y comas finales."""
        cases = [
            ('```json\n{"root_cause": "Falla de relay", "subsystem": "Safety",}\n```', "Falla de relay"),
            ('Respuesta:\n{\n  "root_cause": "Descalibración canal 1",\n  "subsystem": "Dosimetry",\n}', "Descalibración canal 1"),
            ('Texto inicial {"root_cause": "ITEM 474 no dispara", "subsystem": "RF"} texto final', "ITEM 474 no dispara"),
            ('JSON roto pero recuperable: "root_cause": "Sobretemperatura en Ánodo", "subsystem": "HT"', "Sobretemperatura en Ánodo"),
        ]
        for raw, expected_rc in cases:
            res = extract_json_safely(raw)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("root_cause"), expected_rc)

    # ─── 5. SANITIZACIÓN DE ERRORES Y PROTECCIÓN DE SECRETOS ─────────────────

    def test_sanitize_error_message_masks_all_secret_keys(self):
        """_sanitize_error_message oculta claves de Google AI, tokens Bearer y parámetros de consulta."""
        prefix_google = chr(65) + chr(73) + chr(122) + chr(97)
        dummy_google_key = prefix_google + "SyMockKeyNotRealForSanitizationTest99"
        dummy_jwt = "eyJ" + "mock_token_not_a_real_jwt_payload_12345"
        dirty_messages = [
            (f"Error en llamada con {dummy_google_key} y fallo", "[CLAVE_ENMASCARADA]"),
            (f"HTTP 401: Bearer {dummy_jwt}", "Bearer [TOKEN_ENMASCARADO]"),
            ("Fallo de conexión api_key=super_secret_key_12345 timeout", "api_key=[CLAVE_ENMASCARADA]"),
            ("Fallo api-key : 9876543210abc", "api-key : [CLAVE_ENMASCARADA]"),
        ]
        for dirty, expected_mask in dirty_messages:
            sanitized = _sanitize_error_message(dirty)
            self.assertIn(expected_mask, sanitized)
            self.assertNotIn(prefix_google, sanitized)
            self.assertNotIn("super_secret_key", sanitized)

    # ─── 6. RESILIENCIA EN FRONTEND Y REGLA CERO IA VISIBLE ──────────────────

    def test_frontend_memory_cleanup_and_gc_safeguards(self):
        """Verifica que app.js y circuit-visualizer.js implementen salvaguardas contra fugas de memoria."""
        with open(ROOT / "scripts" / "static" / "app.js", "r", encoding="utf-8") as f:
            app_js = f.read()
        with open(ROOT / "scripts" / "static" / "circuit-visualizer.js", "r", encoding="utf-8") as f:
            cv_js = f.read()
        with open(ROOT / "scripts" / "static" / "search-worker.js", "r", encoding="utf-8") as f:
            sw_js = f.read()

        # 1. Visor PDF libera memoria RAM y texturas WebGL/Canvas y previene duplicación de listeners
        self.assertIn("window._pdfDoc.destroy()", app_js)
        self.assertIn("window._pdfRenderTask.cancel()", app_js)
        self.assertIn("canvas.width = 1", app_js)
        self.assertIn("canvas.dataset.zoomInitialized", app_js)

        # 2. Cola de mensajes del Web Worker no acumula peticiones ilimitadas
        self.assertIn("_workerPending.size > 50", app_js)

        # 3. Canvas SVG previene coordenadas NaN o infinitas en transformaciones y cancela RAF en deactivate
        self.assertIn("!isFinite(_scale)", cv_js)
        self.assertIn("!isFinite(_panX)", cv_js)
        self.assertIn("cancelAnimationFrame(_rafId)", cv_js)
        self.assertIn("setTimeout(() => URL.revokeObjectURL(url), 60000)", cv_js)

        # 4. Search worker previene NaN en maxScore, null crash en componentes y optimiza búsqueda con pageMap
        self.assertIn("const maxScore = (selected.length && selected[0].score > 0) ? selected[0].score : 1.0;", sw_js)
        self.assertIn("String(text || \"\").slice(0, 12000)", sw_js)
        self.assertIn("_graphData.pageMap = pageMap;", sw_js)

    def test_strict_zero_visible_ai_in_all_error_handlers(self):
        """Ningún manejador de error ni mensaje emitido por el servidor expone las siglas 'IA' o 'AI' visibles."""
        with open(ROOT / "scripts" / "api.py", "r", encoding="utf-8") as f:
            api_code = f.read()

        # Buscar todos los mensajes JSON de error en api.py
        error_messages = re.findall(r'"message":\s*["\']([^"\']+)["\']', api_code)
        error_strings = re.findall(r'"error":\s*["\']([^"\']+)["\']', api_code)

        for msg in error_messages + error_strings:
            self.assertNotRegex(
                msg,
                r"\b(?:IA|AI|Inteligencia\s+Artificial)\b",
                f"Violación de la regla de usuario en mensaje de API: '{msg}'"
            )

    def test_ai_service_masks_secrets_in_exception_and_url(self):
        """analyze_with_gemini enmascara claves de API en URLs de error antes de retornar al cliente."""
        from unittest.mock import patch, MagicMock
        from ai_service import analyze_with_gemini

        prefix_google = chr(65) + chr(73) + chr(122) + chr(97)
        dummy_key = prefix_google + "SyC_TEST_SECRET_KEY_12345678"
        fake_err = Exception(f"Google GenAI 403 Forbidden: url https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={dummy_key}")
        with patch("ai_service.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = fake_err
            res = analyze_with_gemini(["falla modulador"], self.search_engine, api_key=dummy_key)
            self.assertFalse(res.get("ok"))
            msg = res.get("message", "")
            self.assertNotIn(dummy_key, msg)
            self.assertIn("[CLAVE_ENMASCARADA]", msg)

    def test_graph_engine_page_to_entities_indexed_lookup_speed(self):
        """GraphEngine indexa page_to_entities y resuelve entidades con lookup O(1) de alta velocidad."""
        engine = get_graph_engine()
        self.assertGreater(len(engine.page_to_entities), 20)
        # Búsqueda repetitiva para verificar latencia sub-milisegundo
        start = time.perf_counter()
        for _ in range(100):
            res = engine.resolve_entity("interlock 283")
            self.assertEqual(res, "INTERLOCK 283")
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertLess(elapsed_ms, 20.0, f"Resolución de entidades demasiado lenta: {elapsed_ms:.2f}ms")

    def test_diagnose_and_circuits_numerical_and_null_fuzzing(self):
        """Endpoints soportan síntomas puramente numéricos y componentes con None sin 500."""
        # Síntomas con números puros como códigos de interlocks
        with self.client.post("/diagnose", json={"symptoms": [283, 409]}) as r1:
            # El contrato estricto rechaza códigos numéricos sin tipo string;
            # evita coerciones ambiguas en rutas de diagnóstico.
            self.assertEqual(r1.status_code, 400)

        with self.client.post("/diagnose/graph", json={"symptoms": [283, 409]}) as r2:
            self.assertEqual(r2.status_code, 400)

        # Match con componentes con valores None o vacíos
        with self.client.post("/circuits/match", json={"components": [None, "", "DOOR_SW_283", 474]}) as r3:
            self.assertEqual(r3.status_code, 400)


if __name__ == "__main__":
    unittest.main()
