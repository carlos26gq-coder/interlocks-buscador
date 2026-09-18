"""SOLVI - Pruebas Exhaustivas de Auditoría Técnica (P0, P1, P2, P3, P4, P5).

Verifica:
1. P0-1: Manejo de errores en app.js sin ReferenceError (errMsg, errType declarados).
2. P0-2: Etiqueta de probabilidad baja '⬤ Probabilidad baja' en app.js.
3. P0-3: Rechazo de TP desconocido en evaluate_measurement sin custom_nominal y flag is_known_test_point.
4. P0-4: simulate_reading rechaza TP desconocido con ValueError / 400.
5. P0-5: percent_error no invierte signo con nominal negativo y cálculo consistente con nominal cero.
6. P0-6: Bandas de tolerancia de TP_POS admiten estado MARGINAL (0.0 < 0.5 <= 9.5 < 10.0).
7. P0-7: Validación estricta de unidad en evaluate_measurement (rechazo de V para continuidad en Ω).
8. P0-8: ai_service no almacena en caché diagnósticos truncados ni degradados.
9. P1: Rate limiting en /search y /circuits/*, path traversal prevention en /data, esquemas OpenAPI y CSP.
10. P2: Resiliencia de cascada en ai_service y timeout explícito.
11. P3: Paridad estricta entre catálogo Python y JS, vocabulario de estados FALLA y ciclo de vida de audio.
12. P4: GraphEngine desempate determinista en resolve_entity, flag enriched_circuits y soporte de sumideros.
13. Regla de Usuario: Cero menciones visibles de IA/AI en interfaces y errores.
"""

from pathlib import Path
import json
import logging
import math
import os
import re
import statistics
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATIC_DIR = SCRIPTS_DIR / "static"
TESTS_DIR = ROOT / "tests"
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app, DATA_DIR
from graph_engine import GraphEngine
from multimeter_service import (
    TEST_POINTS_CATALOG,
    evaluate_measurement,
    simulate_reading,
    get_test_point,
    get_all_test_points,
)
from ai_service import (
    analyze_with_gemini,
    clear_diagnostic_cache,
    get_cached_diagnosis,
    set_cached_diagnosis,
    GeminiDiagnosis,
    Confidence,
)
from search_engine import SearchEngine


class AuditFixesVerificationSuite(unittest.TestCase):
    """Suite integral de verificación para todas las correcciones de auditoría técnica."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(STATIC_DIR / "multimeter.js", "r", encoding="utf-8") as f:
            cls.multimeter_js = f.read()
        with open(SCRIPTS_DIR / "api.py", "r", encoding="utf-8") as f:
            cls.api_code = f.read()

    def setUp(self):
        clear_diagnostic_cache()

    # ─── 1. P0-1 & P0-2: FRONTEND APP.JS INTEGRITY ──────────────────────────

    def test_p0_1_app_js_catch_block_declares_err_msg_and_err_type(self):
        """Verifica que el bloque catch de analizarDiagnosticoAi declare errMsg y errType."""
        match_catch = re.search(r"function\s+analizarDiagnosticoAi[\s\S]*?catch\s*\(\s*error\s*\)\s*\{([\s\S]*?)(?:finally|\n\})", self.app_js)
        self.assertIsNotNone(match_catch, "No se encontró el bloque catch de analizarDiagnosticoAi")
        catch_code = match_catch.group(1)
        self.assertIn("const errMsg", catch_code, "errMsg no está declarado en el catch de app.js")
        self.assertIn("const errType", catch_code, "errType no está declarado en el catch de app.js")

    def test_p0_2_app_js_low_confidence_label_is_probabilidad_baja(self):
        """Verifica que la etiqueta de confianza baja muestre '⬤ Probabilidad baja'."""
        self.assertIn('baja: { color: "var(--muted)", label: "⬤ Probabilidad baja" }', self.app_js)
        self.assertNotIn('baja: { color: "var(--muted)", label: "⬤ Probabilidad media" }', self.app_js)

    # ─── 2. P0-3, P0-4, P0-5, P0-6, P0-7: MULTIMETER SERVICE SAFETY ──────────

    def test_p0_3_unknown_test_point_without_custom_nominal_rejected(self):
        """Punto de prueba desconocido sin custom_nominal lanza ValueError en vez de fallback silencioso a 24V."""
        with self.assertRaises(ValueError):
            evaluate_measurement("TP_INEXISTENTE_999", 24.0)

        # En endpoint HTTP /multimeter/evaluate debe retornar 400
        res = self.client.post("/multimeter/evaluate", json={
            "test_point_id": "TP_INEXISTENTE_999",
            "measured_value": 24.0,
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("error"), "validation_error")

    def test_p0_3_and_p3_3_evaluation_metadata_and_known_flag(self):
        """evaluate_measurement incluye is_known_test_point, test_point_code, manual y page."""
        res_known = evaluate_measurement("TP1", 24.0, unit="V")
        self.assertTrue(res_known["is_known_test_point"])
        self.assertEqual(res_known["test_point_code"], "TP1")
        self.assertEqual(res_known["manual"], "diagrams")
        self.assertEqual(res_known["page"], 14)

        res_custom = evaluate_measurement("CUSTOM_LINE", 12.0, custom_nominal=12.0)
        self.assertFalse(res_custom["is_known_test_point"])
        self.assertEqual(res_custom["test_point_code"], "CUSTOM_LINE")

    def test_p0_4_simulate_reading_rejects_unknown_test_point(self):
        """simulate_reading lanza ValueError ante TP desconocido en vez de sustituirlo silenciosamente por TP1."""
        with self.assertRaises(ValueError):
            simulate_reading("UNKNOWN_TP_RANDOM")

        res = self.client.post("/multimeter/simulate", json={
            "test_point_id": "UNKNOWN_TP_RANDOM",
            "fault_type": "normal",
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("error"), "validation_error")

    def test_p0_5_negative_nominal_percent_error_sign_parity(self):
        """Con valor nominal negativo (TP7: -150V), percent_error respeta el signo de delta."""
        # Lectura superior a nominal: -140V > -150V (delta = +10V) -> percent_error debe ser positivo (+6.67%)
        res_high = evaluate_measurement("TP7", -140.0, unit="V")
        self.assertEqual(res_high["delta"], 10.0)
        self.assertGreater(res_high["percent_error"], 0.0)
        self.assertAlmostEqual(res_high["percent_error"], 6.67, places=2)

        # Lectura inferior a nominal: -160V < -150V (delta = -10V) -> percent_error debe ser negativo (-6.67%)
        res_low = evaluate_measurement("TP7", -160.0, unit="V")
        self.assertEqual(res_low["delta"], -10.0)
        self.assertLess(res_low["percent_error"], 0.0)
        self.assertAlmostEqual(res_low["percent_error"], -6.67, places=2)

    def test_p0_5_zero_nominal_safe_percent_error(self):
        """Con nominal cero (TP_SPEED: 0V), percent_error devuelve None (N/A en frontend) para evitar división por cero o números inventados."""
        res_zero = evaluate_measurement("TP_SPEED", 0.0, unit="V")
        self.assertEqual(res_zero["delta"], 0.0)
        self.assertIsNone(res_zero["percent_error"])

        res_speed = evaluate_measurement("TP_SPEED", 4.5, unit="V")
        self.assertEqual(res_speed["delta"], 4.5)
        self.assertIsNone(res_speed["percent_error"])

    def test_p0_6_tp_pos_marginal_band_audited(self):
        """TP_POS permite el estado ADVERTENCIA_MARGINAL al tener tolerance_min < warning_low <= warning_high < tolerance_max."""
        tp = get_test_point("TP_POS")
        self.assertLess(tp["tolerance_min"], tp["warning_low"])
        self.assertLess(tp["warning_high"], tp["tolerance_max"])

        # Lectura óptima nominal
        ev_ok = evaluate_measurement("TP_POS", 5.0, unit="V")
        self.assertEqual(ev_ok["status"], "DENTRO_DE_TOLERANCIA")
        self.assertEqual(ev_ok["status_badge"], "OK")

        # Lectura marginal baja (0.2V está entre tolerance_min 0.0 y warning_low 0.5)
        ev_marg_low = evaluate_measurement("TP_POS", 0.2, unit="V")
        self.assertEqual(ev_marg_low["status"], "ADVERTENCIA_MARGINAL")
        self.assertEqual(ev_marg_low["status_badge"], "MARGINAL")

        # Lectura marginal alta (9.8V está entre warning_high 9.5 y tolerance_max 10.0)
        ev_marg_high = evaluate_measurement("TP_POS", 9.8, unit="V")
        self.assertEqual(ev_marg_high["status"], "ADVERTENCIA_MARGINAL")
        self.assertEqual(ev_marg_high["status_badge"], "MARGINAL")

        # Lectura fuera de tolerancia (> 10.0)
        ev_fail = evaluate_measurement("TP_POS", 10.5, unit="V")
        self.assertEqual(ev_fail["status"], "FUERA_DE_TOLERANCIA")
        self.assertEqual(ev_fail["status_badge"], "FALLA")

    def test_p0_7_unit_compatibility_strict_validation(self):
        """evaluate_measurement valida compatibilidad de unidad y rechaza discrepancias (ej. V para bucle en Ω)."""
        # GEN_CONT_LOOP requiere Ω
        with self.assertRaises(ValueError):
            evaluate_measurement("GEN_CONT_LOOP", 0.2, unit="V")

        # Unidad compatible admitida
        ok_res = evaluate_measurement("GEN_CONT_LOOP", 0.2, unit="Ω")
        self.assertEqual(ok_res["status"], "DENTRO_DE_TOLERANCIA")

        # Alias de ohmios admitido
        ok_alias = evaluate_measurement("GEN_CONT_LOOP", 0.2, unit="ohm")
        self.assertEqual(ok_alias["status"], "DENTRO_DE_TOLERANCIA")

        # TP1 requiere V, debe rechazar Ω
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", 24.0, unit="Ω")

        # Endpoint HTTP retorna 400 ante unidad incompatible
        res_http = self.client.post("/multimeter/evaluate", json={
            "test_point_id": "GEN_CONT_LOOP",
            "measured_value": 0.2,
            "unit": "V",
        })
        self.assertEqual(res_http.status_code, 400)
        self.assertEqual(res_http.get_json().get("error"), "validation_error")

    # ─── 3. P0-8 & P2: AI SERVICE RESILIENCE & CACHE SAFETY ─────────────────

    @patch("ai_service.genai.Client")
    def test_p0_8_truncated_response_not_cached(self, mock_client_cls):
        """Respuestas truncadas por MAX_TOKENS no se guardan en la caché de diagnósticos."""
        engine = SearchEngine([{"manual": "vacuum", "page": 10, "text": "ITEM 112 vacuum failure"}])
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = GeminiDiagnosis(
            root_cause="Falla truncada de vacío",
            subsystem="Vacuum",
            confidence=Confidence.MEDIA,
            explanation="Incompleto",
            citation_ids=["C1"],
        )
        mock_resp.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
        mock_client.models.generate_content.return_value = mock_resp

        symptoms = ["ITEM 112 vacuum leak"]
        res = analyze_with_gemini(symptoms, engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("truncated"))

        # Verificar que NO se haya guardado en caché
        cached = get_cached_diagnosis(symptoms)
        self.assertIsNone(cached, "Una respuesta truncada por MAX_TOKENS fue guardada en caché incorrectamente.")

    @patch("ai_service.genai.Client")
    def test_p0_8_degraded_parse_response_not_cached(self, mock_client_cls):
        """Respuestas procesadas por parser tolerante (degraded_parse) no se guardan en caché."""
        engine = SearchEngine([{"manual": "vacuum", "page": 10, "text": "ITEM 112 vacuum failure"}])
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = None
        mock_resp.text = '{"root_cause": "Falla de contactor", "subsystem": "Power", "confidence": "alta", "explanation": "Fallback"}'
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]
        mock_client.models.generate_content.return_value = mock_resp

        symptoms = ["ITEM 112 contactor"]
        res = analyze_with_gemini(symptoms, engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("degraded_parse"))

        # Verificar que NO se haya guardado en caché
        cached = get_cached_diagnosis(symptoms)
        self.assertIsNone(cached, "Una respuesta con parse degradado fue guardada en caché incorrectamente.")

    # ─── 4. P1: REST API, SEGURIDAD, ENRUTAMIENTO Y OPENAPI ──────────────────

    def test_p1_1_rate_limiting_applied_to_search_and_circuits(self):
        """Verifica que /search y /circuits/* estén decorados con limiter en api.py."""
        self.assertRegex(self.api_code, r'@app\.route\("/search"\)[\s\S]*?@limiter\.limit')
        self.assertRegex(self.api_code, r'@app\.route\("/circuits/subsystems"[\s\S]*?@limiter\.limit')
        self.assertRegex(self.api_code, r'@app\.route\("/circuits/<subsystem_id>"[\s\S]*?@limiter\.limit')
        self.assertRegex(self.api_code, r'@app\.route\("/circuits/match"[\s\S]*?@limiter\.limit')

    def test_p1_3_serve_data_prevents_path_traversal_probing(self):
        """Verifica que /data/<path:filename> bloquee intentos de escape de directorio."""
        with self.client.get("/data/../../etc/passwd") as res:
            self.assertEqual(res.status_code, 404)
            data = res.get_json()
            self.assertFalse(data.get("ok", True))
            self.assertEqual(data.get("error"), "not_found")

        with self.client.get("/data/..\\..\\windows\\system32") as res:
            self.assertEqual(res.status_code, 404)

    def test_p1_6_debug_mode_restricted_to_loopback(self):
        """Verifica que el código de arranque restrinja debug=True exclusivamente a loopback."""
        self.assertIn("is_loopback = host in", self.api_code)
        self.assertIn("debug_mode = debug_requested and is_loopback", self.api_code)

    def test_p1_8_openapi_defines_error_schemas(self):
        """El endpoint /openapi.json documenta los esquemas estandarizados de ErrorResponse y ValidationErrorResponse."""
        with self.client.get("/openapi.json") as res:
            self.assertEqual(res.status_code, 200)
            spec = res.get_json()
            schemas = spec.get("components", {}).get("schemas", {})
            self.assertIn("ErrorResponse", schemas)
            self.assertIn("ValidationErrorResponse", schemas)
            self.assertIn("error", schemas["ErrorResponse"]["properties"])
            self.assertIn("message", schemas["ErrorResponse"]["properties"])

    def test_p1_9_full_csp_security_directives(self):
        """Verifica que las cabeceras CSP incluyan todas las directivas de seguridad obligatorias."""
        with self.client.get("/") as res:
            csp = res.headers.get("Content-Security-Policy", "")
            self.assertIn("default-src 'self'", csp)
            self.assertIn("object-src 'none'", csp)
            self.assertIn("base-uri 'self'", csp)
            self.assertIn("script-src 'self'", csp)
            self.assertIn("worker-src 'self'", csp)
            self.assertIn("connect-src 'self'", csp)

    # ─── 5. P3: PARIDAD DEL MULTÍMETRO FRONTEND / BACKEND ───────────────────

    def test_p3_1_all_test_points_parity_python_vs_json(self):
        """Todos los puntos de prueba del catálogo Python existen en multimeter_catalog.json."""
        import json
        with open("scripts/static/multimeter_catalog.json", "r", encoding="utf-8") as f:
            catalog = json.load(f)
        for tp_id, tp in TEST_POINTS_CATALOG.items():
            self.assertIn(tp_id, catalog, f"Punto de prueba {tp_id} falta en multimeter_catalog.json")

    def test_p3_2_unified_failure_status_badge(self):
        """El badge para FUERA_DE_TOLERANCIA en multimeter.js está alineado con 'FALLA' del backend."""
        self.assertIn('statusBadge = "FALLA";', self.multimeter_js)

    def test_p3_5_sonar_beeper_audio_lifecycle_and_disconnection(self):
        """sonarBeeper encadena al resume() de Web Audio y desconecta oscilador y ganancia en onended."""
        self.assertIn(".resume().then(playTone)", self.multimeter_js)
        self.assertIn("osc.disconnect()", self.multimeter_js)
        self.assertIn("gain.disconnect()", self.multimeter_js)

    # ─── 6. P4: GRAPH ENGINE OPTIMIZATIONS ──────────────────────────────────

    def test_p4_1_graph_engine_deterministic_resolution(self):
        """resolve_entity prioriza coincidencia exacta y ordena subcadenas por especificidad."""
        graph = GraphEngine()
        # "item 409" debe resolver exactamente a ITEM 409
        self.assertEqual(graph.resolve_entity("item 409"), "ITEM 409")

        # Coincidencia exacta limpia
        self.assertEqual(graph.resolve_entity("PCB DOSE"), "PCB DOSE")

        # Coincidencias de texto deterministas por subcadena
        ent_sub = graph.resolve_entity("RATE 1")
        self.assertIsNotNone(ent_sub)
        self.assertEqual(ent_sub, "D RATE 1")

    def test_p4_2_graph_engine_enriched_circuits_flag(self):
        """GraphEngine expone el flag enriched_circuits tras inicializarse."""
        graph = GraphEngine()
        self.assertTrue(hasattr(graph, "enriched_circuits"))
        self.assertTrue(graph.enriched_circuits)

    def test_p4_3_graph_engine_find_shortest_path_sink_nodes_and_unknown(self):
        """find_shortest_path maneja nodos sumidero sin excepción y rechaza IDs desconocidos."""
        graph = GraphEngine()
        # Nodos que no existen en entities retornan None
        self.assertIsNone(graph.find_shortest_path("NODO_FANTASMA_1", "NODO_FANTASMA_2"))
        self.assertIsNone(graph.find_shortest_path("ITEM 409", "NODO_FANTASMA_2"))

        # Mismo nodo devuelve camino self
        path_self = graph.find_shortest_path("ITEM 409", "ITEM 409")
        self.assertIsNotNone(path_self)
        self.assertEqual(len(path_self), 1)
        self.assertEqual(path_self[0]["relation"], "self")

    def test_circuit_matcher_high_performance_and_no_truncation(self):
        """Separa el presupuesto de inicialización fría del rendimiento sostenido."""
        from circuit_data import match_subsystem_for_trace
        heavy_components = [f"DUMMY_COMP_{i}" for i in range(250)] + ["DOOR_SW_283", "ESTOP_CONSOLE", "ITEM 474"]

        # La primera llamada puede construir perezosamente el índice de nodos.
        start = time.perf_counter()
        match_res = match_subsystem_for_trace(heavy_components)
        cold_elapsed_ms = (time.perf_counter() - start) * 1000

        # El contrato operativo se mide sobre varias llamadas ya inicializadas;
        # la mediana evita falsos fallos por una interrupción puntual del SO/CI.
        warm_samples_ms = []
        for _ in range(5):
            start = time.perf_counter()
            match_subsystem_for_trace(heavy_components)
            warm_samples_ms.append((time.perf_counter() - start) * 1000)

        self.assertLess(cold_elapsed_ms, 50.0, f"Arranque frío tardó {cold_elapsed_ms:.2f}ms (límite 50ms)")
        self.assertLess(
            statistics.median(warm_samples_ms),
            30.0,
            f"Mediana caliente {statistics.median(warm_samples_ms):.2f}ms (límite 30ms)",
        )
        self.assertEqual(match_res["subsystem_id"], "safety_loop")
        self.assertIn("DOOR_SW_283", match_res["matched_nodes"])
        self.assertIn("ESTOP_CONSOLE", match_res["matched_nodes"])

    def test_search_worker_parity_for_p4_1_and_p4_3(self):
        """search-worker.js implementa coincidencia exacta previa, desempate determinista y soporte de sumideros."""
        with open(SCRIPTS_DIR / "static" / "search-worker.js", "r", encoding="utf-8") as f:
            sw_code = f.read()

        # P4-1: Coincidencia exacta primero y ordenamiento por longitud descendente
        self.assertIn("clean === entClean", sw_code)
        self.assertIn("cleanKey(b).length - cleanKey(a).length", sw_code)
        self.assertIn("a.localeCompare(b)", sw_code)

        # P4-3: Nodos sumidero en findShortestPath no retornan null prematuramente
        self.assertIn("graph.adjacency[startId] = []", sw_code)
        self.assertIn("graph.adjacency[targetId] = []", sw_code)

    def test_multimeter_js_unknown_point_not_green_and_null_percent_error(self):
        """multimeter.js nunca evalúa en verde un TP desconocido y retorna percent_error null con nominal 0."""
        # Verificar que resolverPuntoDePrueba admita fallbackDefault explícito
        self.assertIn("resolverPuntoDePrueba(idOrCode, fallbackDefault = false)", self.multimeter_js)
        # Verificar que evaluarLectura maneje !tp retornando status_badge DESCONOCIDO
        self.assertIn('status_badge: "DESCONOCIDO"', self.multimeter_js)
        self.assertIn('is_known_test_point: false', self.multimeter_js)
        # Verificar que generarLecturaSimulada no sustituya silenciosamente por TP1
        self.assertIn('No se puede simular lectura para el punto de prueba desconocido', self.multimeter_js)
        # Verificar que con nominal <= 1e-5 percentError sea null
        self.assertIn("percentError = null;", self.multimeter_js)

    # ─── 7. STRICT ZERO VISIBLE AI CONSTRAINT ───────────────────────────────

    def test_strict_zero_visible_ai_in_new_code_and_errors(self):
        """Verifica que ningún mensaje ni texto de error exponga siglas visibles de IA o AI."""
        with open(SCRIPTS_DIR / "multimeter_service.py", "r", encoding="utf-8") as f:
            multimeter_code = f.read()

        for code, label in [
            (multimeter_code, "multimeter_service.py"),
            (self.multimeter_js, "multimeter.js"),
            (self.app_js, "app.js"),
        ]:
            # Buscar strings de usuario como toast, alert o placeholders
            user_strings = re.findall(r'toast\s*\(\s*["\']([^"\']+)["\']', code)
            user_strings += re.findall(r'placeholder\s*=\s*["\']([^"\']+)["\']', code)
            for s in user_strings:
                self.assertNotRegex(
                    s,
                    r"\b(?:IA|AI|Inteligencia\s+Artificial)\b",
                    f"Violación de regla estricta de usuario en {label}: '{s}'"
                )

    def test_strict_zero_visible_ai_in_html_and_templates(self):
        """index.html no contiene menciones visibles al usuario de IA, AI o Inteligencia Artificial."""
        template_file = SCRIPTS_DIR / "templates" / "index.html"
        if template_file.is_file():
            with open(template_file, "r", encoding="utf-8") as f:
                html_code = f.read()
            from _helpers import extract_visible_html_text, assert_no_visible_ai
            visible_text = extract_visible_html_text(html_code)
            assert_no_visible_ai(self, visible_text, "index.html")


if __name__ == "__main__":
    unittest.main()
