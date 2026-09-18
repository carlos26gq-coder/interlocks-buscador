"""SOLVI - Pruebas de Integración y Compatibilidad del Multímetro Digital.

Valida:
1. Integridad del catálogo de puntos de prueba de los 5 subsistemas Linac.
2. Cálculo de tolerancias, deltas y evaluación de estados (OK, Marginal, Fuera de rango).
3. Robustez ante valores adversariales, NaN, infinitos y tipos inválidos.
4. Motor de simulación e inyección de fallas eléctricas de banco.
5. Ciclo de vida de endpoints HTTP /multimeter/*.
6. Integración de frontend, salvaguardas de memoria RAM y caché offline en sw.js.
7. Cumplimiento estricto de la regla de usuario de CERO menciones de IA visibles.
"""

from pathlib import Path
import json
import math
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATIC_DIR = SCRIPTS_DIR / "static"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app
from multimeter_service import (
    TEST_POINTS_CATALOG,
    get_all_test_points,
    get_test_point,
    evaluate_measurement,
    simulate_reading,
)


class MultimeterIntegrationSuite(unittest.TestCase):
    """Pruebas exhaustivas del multímetro digital, motor de tolerancias y pasarela web."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with (TEMPLATES_DIR / "index.html").open("r", encoding="utf-8") as f:
            cls.html = f.read()
        with (STATIC_DIR / "multimeter.js").open("r", encoding="utf-8") as f:
            cls.multimeter_js = f.read()
        with (STATIC_DIR / "circuit-visualizer.js").open("r", encoding="utf-8") as f:
            cls.cv_js = f.read()
        with (STATIC_DIR / "app.js").open("r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with (ROOT / "sw.js").open("r", encoding="utf-8") as f:
            cls.sw_js = f.read()

    # ─── 1. INTEGRIDAD DEL CATÁLOGO DE PUNTOS DE PRUEBA ──────────────────────

    def test_catalog_contains_key_linac_test_points(self):
        """Verifica que los puntos de prueba clave de los 5 subsistemas Linac estén definidos."""
        required_tps = [
            "TP1", "TP2", "TP5",       # safety_loop
            "TP3", "TP_HT", "TP_RF",    # radiation_beam
            "TP100", "TP_DOSE1", "TP_DOSE2",  # dosimetry
            "TP_SPEED", "TP_POS",       # gantry_collimator
            "TP_VAC", "TP_GUN", "TP7",  # vacuum_gun
            "GEN_VOLT_24", "GEN_VOLT_15", "GEN_CONT_LOOP" # general
        ]
        all_tps = get_all_test_points()
        self.assertGreaterEqual(len(all_tps), len(required_tps))

        for tp_id in required_tps:
            tp = get_test_point(tp_id)
            self.assertIsNotNone(tp, f"Punto de prueba '{tp_id}' no encontrado en el catálogo.")
            self.assertIn("nominal", tp)
            self.assertIn("tolerance_min", tp)
            self.assertIn("tolerance_max", tp)
            self.assertIn("unit", tp)
            self.assertIn("role", tp)
            self.assertIn("notes", tp)
            self.assertLessEqual(tp["tolerance_min"], tp["nominal"])
            self.assertGreaterEqual(tp["tolerance_max"], tp["nominal"])

    def test_case_insensitive_test_point_lookup(self):
        """Verifica que la búsqueda de puntos de prueba admita mayúsculas y minúsculas."""
        self.assertEqual(get_test_point("tp1")["id"], "TP1")
        self.assertEqual(get_test_point("Tp_Ht")["id"], "TP_HT")
        self.assertEqual(get_test_point("gen +24v")["id"], "GEN_VOLT_24")
        self.assertIsNone(get_test_point("PUNTO_INEXISTENTE_XYZ"))

    # ─── 2. CÁLCULO DE TOLERANCIAS Y EVALUACIÓN DETERMINISTA ─────────────────

    def test_evaluate_measurement_nominal_ok(self):
        """Verifica que una lectura en el centro de tolerancia sea evaluada como DENTRO_DE_TOLERANCIA."""
        res = evaluate_measurement("TP1", 24.0, "V")
        self.assertEqual(res["status"], "DENTRO_DE_TOLERANCIA")
        self.assertEqual(res["status_badge"], "OK")
        self.assertAlmostEqual(res["delta"], 0.0, places=3)
        self.assertAlmostEqual(res["percent_error"], 0.0, places=2)
        self.assertEqual(res["color"], "#4ade80")

    def test_evaluate_measurement_marginal_warning(self):
        """Verifica que una lectura próxima al límite dispare estado ADVERTENCIA_MARGINAL."""
        # TP1: nominal 24.0, tol [23.2, 24.8], warning_low=23.5
        res = evaluate_measurement("TP1", 23.3, "V")
        self.assertEqual(res["status"], "ADVERTENCIA_MARGINAL")
        self.assertEqual(res["status_badge"], "MARGINAL")
        self.assertEqual(res["color"], "#f59e0b")
        self.assertLess(res["delta"], 0.0)

    def test_evaluate_measurement_out_of_tolerance_low(self):
        """Verifica que una caída de tensión por debajo del mínimo sea FUERA_DE_TOLERANCIA."""
        res = evaluate_measurement("TP1", 21.5, "V")
        self.assertEqual(res["status"], "FUERA_DE_TOLERANCIA")
        self.assertEqual(res["status_badge"], "FALLA")
        self.assertEqual(res["color"], "#ef4444")
        self.assertIn("inferior al mínimo", res["recommendation"])
        self.assertIn("fusible FS1", res["recommendation"])

    def test_evaluate_measurement_out_of_tolerance_high(self):
        """Verifica que una sobretensión por encima del límite sea FUERA_DE_TOLERANCIA."""
        res = evaluate_measurement("TP1", 27.2, "V")
        self.assertEqual(res["status"], "FUERA_DE_TOLERANCIA")
        self.assertIn("superior al máximo", res["recommendation"])

    def test_evaluate_measurement_zero_nominal_safe_division(self):
        """Puntos de prueba con valor nominal 0 (ej: TP_SPEED estático) no causan ZeroDivisionError y retornan None (P0-5)."""
        res = evaluate_measurement("TP_SPEED", 0.0, "V")
        self.assertEqual(res["status"], "DENTRO_DE_TOLERANCIA")
        self.assertIsNone(res["percent_error"])

        res_moved = evaluate_measurement("TP_SPEED", 4.5, "V")
        self.assertEqual(res_moved["status"], "DENTRO_DE_TOLERANCIA")
        self.assertIsNone(res_moved["percent_error"])

    def test_evaluate_measurement_custom_nominal_and_tolerance(self):
        """Soporta evaluación de puntos personalizados con nominal y tolerancia arbitrarios."""
        res = evaluate_measurement(
            tp_id="CUSTOM_LINE",
            measured_value=12.2,
            unit="V",
            custom_nominal=12.0,
            custom_tolerance_pct=5.0  # 12 ± 0.6 = [11.4, 12.6]
        )
        self.assertEqual(res["status"], "DENTRO_DE_TOLERANCIA")
        self.assertAlmostEqual(res["delta"], 0.2, places=2)

    # ─── 3. RESILIENCIA ANTE ENTRADAS ADVERSARIALES Y FUZZING ────────────────

    def test_evaluate_measurement_rejects_invalid_values(self):
        """Rechaza valores no numéricos, NaN o infinitos con ValueError controlado."""
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", "texto_no_valido")
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", float("nan"))
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", float("inf"))
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", None)

    # ─── 4. MOTOR DE SIMULACIÓN E INYECCIÓN DE FALLAS DE BANCO ───────────────

    def test_simulation_engine_all_fault_types(self):
        """Verifica que todos los tipos de falla generen valores realistas correspondientes."""
        # 1. Normal
        sim_norm = simulate_reading("TP1", fault_type="normal", add_noise=False)
        self.assertEqual(sim_norm["status"], "DENTRO_DE_TOLERANCIA")
        self.assertAlmostEqual(sim_norm["measured_value"], 24.0, places=1)

        # 2. Circuito Abierto
        sim_open = simulate_reading("TP1", fault_type="open_circuit", add_noise=False)
        self.assertEqual(sim_open["status"], "FUERA_DE_TOLERANCIA")
        self.assertLess(sim_open["measured_value"], 1.0)

        # 3. Caída Resistiva
        sim_drop = simulate_reading("TP1", fault_type="resistive_drop", add_noise=False)
        self.assertEqual(sim_drop["status"], "FUERA_DE_TOLERANCIA")
        self.assertGreater(sim_drop["measured_value"], 15.0)
        self.assertLess(sim_drop["measured_value"], 20.0)

        # 4. Cortocircuito
        sim_short = simulate_reading("TP1", fault_type="short_circuit", add_noise=False)
        self.assertEqual(sim_short["status"], "FUERA_DE_TOLERANCIA")
        self.assertAlmostEqual(sim_short["measured_value"], 0.0, places=2)

        # 5. Sobretensión
        sim_over = simulate_reading("TP1", fault_type="overvoltage", add_noise=False)
        self.assertEqual(sim_over["status"], "FUERA_DE_TOLERANCIA")
        self.assertGreater(sim_over["measured_value"], 28.0)

    # ─── 5. ENDPOINTS HTTP REST (/multimeter/*) ──────────────────────────────

    def test_endpoint_get_test_points_success(self):
        """GET /multimeter/test-points retorna catálogo completo con código 200."""
        res = self.client.get("/multimeter/test-points")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(len(data.get("test_points", [])), 15)

    def test_endpoint_post_evaluate_success_and_validation(self):
        """POST /multimeter/evaluate procesa mediciones y valida parámetros obligatorios."""
        # Petición exitosa
        res = self.client.post("/multimeter/evaluate", json={
            "test_point_id": "TP1",
            "measured_value": 23.95,
            "unit": "V"
        })
        self.assertEqual(res.status_code, 200)
        ev = res.get_json().get("evaluation")
        self.assertEqual(ev["status"], "DENTRO_DE_TOLERANCIA")

        # Falta measured_value
        res_missing = self.client.post("/multimeter/evaluate", json={
            "test_point_id": "TP1"
        })
        self.assertEqual(res_missing.status_code, 400)
        self.assertIn("error", res_missing.get_json())

        # measured_value no numérico
        res_invalid = self.client.post("/multimeter/evaluate", json={
            "test_point_id": "TP1",
            "measured_value": "abc"
        })
        self.assertEqual(res_invalid.status_code, 400)

    def test_endpoint_post_simulate_success(self):
        """POST /multimeter/simulate genera telemetría simulada con código 200."""
        res = self.client.post("/multimeter/simulate", json={
            "test_point_id": "TP1",
            "fault_type": "resistive_drop",
            "add_noise": False
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        sim = data.get("simulation")
        self.assertEqual(sim["fault_injected"], "resistive_drop")
        self.assertEqual(sim["status"], "FUERA_DE_TOLERANCIA")

    # ─── 6. INTEGRACIÓN EN FRONTEND, SALVAGUARDAS DE MEMORIA Y PWA ───────────

    def test_multimeter_js_asset_served_and_in_sw_core(self):
        """Verifica que multimeter.js esté en el CORE del Service Worker y se sirva con HTTP 200."""
        self.assertIn("/static/multimeter.js", self.sw_js)
        with self.client.get("/static/multimeter.js") as res:
            self.assertEqual(res.status_code, 200)

    def test_frontend_memory_leak_safeguards_in_multimeter_js(self):
        """Verifica que multimeter.js implemente salvaguardas estrictas contra desbordamiento de RAM."""
        # 1. Búfer histórico acotado
        self.assertIn("MAX_HISTORY_RECORDS", self.multimeter_js)
        self.assertIn("_history.length = MAX_HISTORY_RECORDS", self.multimeter_js)

        # 2. Desactivación de timers y hardware en onDeactivate
        self.assertIn("function onDeactivate()", self.multimeter_js)
        self.assertIn("pausarTelemetriaVirtual()", self.multimeter_js)
        self.assertIn("desconectarHardware()", self.multimeter_js)

        # 3. Frecuencia controlada de telemetría para evitar saturación de CPU
        self.assertIn("THROTTLE_SIMULATION_MS", self.multimeter_js)

    def test_index_html_includes_multimeter_screen_and_handlers(self):
        """Verifica que index.html integre la pantalla de multímetro y navegación táctil."""
        self.assertIn('id="screenMultimeter"', self.html)
        self.assertIn('id="navM"', self.html)
        self.assertIn('onclick="irA(\'Multimeter\')"', self.html)
        self.assertIn('/static/multimeter.js', self.html)

        # Manejadores de entrada táctil
        self.assertIn('function dmmKeypad', self.html)
        self.assertIn('function dmmPreset', self.html)
        self.assertIn('function dmmProcesar', self.html)

    def test_circuit_visualizer_and_app_js_multimeter_bridges(self):
        """Verifica que el visualizador de esquemas y la traza de grafo expongan botón para multímetro."""
        self.assertIn("medirEnMultimetro", self.cv_js)
        self.assertIn("abrirMultimetroConTp", self.app_js)

    def test_get_test_point_schematic_node_mapping(self):
        """Verifica que nodos de planos esquemáticos se resuelvan al punto de prueba adecuado."""
        # Fuentes y lazos
        self.assertEqual(get_test_point("PSU_24V")["id"], "GEN_VOLT_24")
        self.assertEqual(get_test_point("PSU1 +24V")["id"], "GEN_VOLT_24")
        # Pulsadores y switches de seguridad
        self.assertEqual(get_test_point("ESTOP_CONSOLE")["id"], "GEN_CONT_LOOP")
        self.assertEqual(get_test_point("DOOR_SW_283")["id"], "GEN_CONT_LOOP")
        self.assertEqual(get_test_point("COLLISION_HEAD")["id"], "GEN_CONT_LOOP")
        # Drivers y sensores
        self.assertEqual(get_test_point("K1_K2_DRV")["id"], "TP5")
        self.assertEqual(get_test_point("ION_CHAMBER")["id"], "TP100")
        self.assertEqual(get_test_point("GUN_FILAMENT")["id"], "TP_GUN")
        # Prefijos difusos
        self.assertEqual(get_test_point("TP1 - 24V DC")["id"], "TP1")
        self.assertEqual(get_test_point("TP_HT (14kV)")["id"], "TP_HT")

    def test_simulation_engine_never_generates_negative_resistance(self):
        """Verifica que la simulación de continuidad/resistencia jamás produzca valores negativos."""
        for fault in ["normal", "open_circuit", "resistive_drop", "short_circuit", "overvoltage"]:
            for _ in range(25):
                sim = simulate_reading("GEN_CONT_LOOP", fault_type=fault, add_noise=True)
                self.assertGreater(sim["measured_value"], 0.0, f"Resistencia no física detectada en falla {fault}: {sim['measured_value']}")
                self.assertEqual(sim["unit"], "Ω")

    def test_multimeter_js_modal_has_unique_display_and_result_elements(self):
        """Verifica que el modal inspector tenga elementos display y resultado dedicados sin colisión de ID."""
        self.assertIn("dmmModalDisplayValue", self.multimeter_js)
        self.assertIn("dmmModalDisplayUnit", self.multimeter_js)
        self.assertIn("dmmModalResultWrap", self.multimeter_js)
        self.assertIn("dmmModalInfoNominal", self.multimeter_js)
        self.assertIn("dmmModalInfoTol", self.multimeter_js)

        # Verificar que mostrarResultado actualice tanto la pantalla principal como el modal
        self.assertIn('document.getElementById("dmmResultBox")', self.multimeter_js)
        self.assertIn('document.getElementById("dmmModalResultWrap")', self.multimeter_js)

    def test_multimeter_js_exports_last_evaluation_and_dismisses_modal(self):
        """Verifica que exportarAApuntes use _lastEvaluation y cierre el modal flotante."""
        self.assertIn("cerrarInspectorModal()", self.multimeter_js)
        self.assertIn("_lastEvaluation", self.multimeter_js)
        self.assertIn("evaluacionPersonalizada || _lastEvaluation || _history[0]", self.multimeter_js)

    def test_multimeter_js_maps_general_subsystem_in_svg_navigation(self):
        """Verifica que verEnPlanoSvg mapee el subsistema 'general' a 'safety_loop'."""
        self.assertIn('subId === "general"', self.multimeter_js)
        self.assertIn('subId = "safety_loop"', self.multimeter_js)

    def test_multimeter_js_visibility_and_audio_lifecycle(self):
        """Verifica que multimeter.js controle la visibilidad de pestaña y ciclo de vida de audio."""
        self.assertIn('document.addEventListener("visibilitychange"', self.multimeter_js)
        self.assertIn("_pausedByVisibility", self.multimeter_js)
        self.assertIn("_audioContext.suspend()", self.multimeter_js)

    def test_multimeter_js_keyboard_and_keypad_resilience(self):
        """Verifica resiliencia del teclado táctil: signo negativo en vacío, reemplazo de cero inicial y escucha física."""
        self.assertIn('_currentInputStr = "-"', self.multimeter_js)
        self.assertIn('_currentInputStr === "0"', self.multimeter_js)
        self.assertIn('document.addEventListener("keydown"', self.multimeter_js)

    # ─── 7. REGLA ESTRICTA DE USUARIO: CERO MENCIONES VISIBLES DE IA ─────────

    def test_strict_zero_visible_ai_in_multimeter_components(self):
        """Verifica que ningún componente ni texto del multímetro contenga menciones de IA visibles."""
        with (SCRIPTS_DIR / "multimeter_service.py").open("r", encoding="utf-8") as f:
            service_code = f.read()

        for code, label in [
            (service_code, "multimeter_service.py"),
            (self.multimeter_js, "multimeter.js"),
        ]:
            self.assertNotRegex(
                code,
                r"\b(?:IA|AI|Inteligencia\s+Artificial)\b",
                f"Violación de regla de usuario: Mención de IA en {label}"
            )

    def test_multimeter_modal_delegates_action_buttons(self):
        """Verifica que el modal inspector delegue 'exportar-apuntes', 'ver-plano' y 'trazar'."""
        self.assertIn('btn.dataset.dmmAction === "exportar-apuntes"', self.multimeter_js)
        self.assertIn('btn.dataset.dmmAction === "ver-plano"', self.multimeter_js)
        self.assertIn('btn.dataset.dmmAction === "trazar"', self.multimeter_js)

    def test_multimeter_guide_in_html_and_modal(self):
        """Verifica que index.html y el modal contengan la descripción técnica y modos de operación."""
        self.assertIn("dmm-quick-guide", self.html)
        self.assertIn("Entrada Manual Rápida", self.html)
        self.assertIn("Simulador de Banco", self.html)
        self.assertIn("Enlace Digital (BLE / USB-Serie)", self.html)
        self.assertIn("Guardar en Mis Apuntes", self.html)
        self.assertIn("Guía rápida:", self.multimeter_js)


if __name__ == "__main__":
    unittest.main()

