"""SOLVI - Pruebas de Integridad de Frontend, Exportaciones Globales, DOM y UX Fluida."""

from pathlib import Path
import json
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATIC_DIR = SCRIPTS_DIR / "static"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app


class FrontendAndUxIntegritySuite(unittest.TestCase):
    """Verificación de llamadas a funciones, manejadores de eventos, DOM y rendimiento táctil."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with (TEMPLATES_DIR / "index.html").open("r", encoding="utf-8") as f:
            cls.html = f.read()
        with (STATIC_DIR / "app.js").open("r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with (STATIC_DIR / "circuit-visualizer.js").open("r", encoding="utf-8") as f:
            cls.cv_js = f.read()
        with (STATIC_DIR / "search-worker.js").open("r", encoding="utf-8") as f:
            cls.sw_js = f.read()
        with (ROOT / "sw.js").open("r", encoding="utf-8") as f:
            cls.service_worker_js = f.read()

    # ─── 1. EXPORTACIONES GLOBALES Y PREVENCIÓN DE REFERENCEERROR ────────────

    def test_window_exports_in_app_js_match_existing_functions(self):
        """Verifica que cada 'window.fn = fn' en el bloque de exportaciones apunte a una función declarada."""
        match_block = re.search(r"// ─── EXPORTACIONES GLOBALES[\s\S]*", self.app_js)
        self.assertIsNotNone(match_block, "No se encontró el bloque de exportaciones globales en app.js")
        export_matches = re.findall(r"window\.([A-Za-z0-9_$]+)\s*=\s*([A-Za-z0-9_$]+);", match_block.group(0))
        self.assertGreater(len(export_matches), 15, "Deben existir exportaciones a window para manejadores de UI.")

        for prop_name, fn_name in export_matches:
            fn_pattern = rf"(?:function\s+{fn_name}\b|async\s+function\s+{fn_name}\b|const\s+{fn_name}\s*=|let\s+{fn_name}\s*=)"
            self.assertTrue(
                re.search(fn_pattern, self.app_js),
                f"window.{prop_name} asigna '{fn_name}', pero esa función/variable no está declarada en app.js (provocaría ReferenceError)."
            )

    def test_essential_interactive_handlers_are_globally_exported(self):
        """Verifica que funciones críticas llamadas desde onclicks inline estén exportadas a window."""
        essential_handlers = [
            "verPDF", "buscar", "cargarMasResultados", "quitarSintoma", "agregarSintoma",
            "ejecutarTrazaGrafo", "analizarDiagnostico", "analizarDiagnosticoAi",
            "guardarYReintentarAi", "abrirEnEsquemaSvg", "cargarNotas", "abrirFormNota",
            "guardarNota", "cerrarFormNota", "editarNota", "eliminarNota",
            "verNota", "verNotaEnGrande", "cerrarVisorNota",
            "pdfPagAnterior", "pdfPagSiguiente", "cerrarVisorPDF",
            "adminEntrar", "adminSalir", "cargarListaManuales", "toast"
        ]
        for handler in essential_handlers:
            self.assertIn(
                f"window.{handler} =",
                self.app_js,
                f"El manejador '{handler}' es necesario globalmente para la UI y debe estar exportado en window."
            )

    def test_circuit_visualizer_public_api_methods(self):
        """Verifica que el objeto window.CircuitVisualizer declare todos los métodos de su API pública."""
        required_cv_methods = [
            "init", "cambiarSubsistema", "inspeccionarNodo", "inspeccionarCable",
            "cerrarInspector", "trazarEnDiagnostico", "zoomIn", "zoomOut",
            "resetZoom", "fitToScreen", "exportSvg", "buscarEnEsquema",
            "limpiarResaltados", "resaltarUnicoNodo", "resaltarRuta",
            "loadAndHighlightFromTrace", "onActivate", "onDeactivate"
        ]
        match_cv = re.search(r"window\.CircuitVisualizer\s*=\s*\{([\s\S]*?)\n\s*\};\s*\n\s*\}\)\(window\);", self.cv_js)
        self.assertIsNotNone(match_cv, "window.CircuitVisualizer no está asignado en circuit-visualizer.js")
        cv_body = match_cv.group(1)

        for method in required_cv_methods:
            self.assertTrue(
                re.search(rf"\b{method}\b", cv_body),
                f"El método '{method}' falta en el objeto público window.CircuitVisualizer."
            )

    # ─── 2. COHERENCIA ENTRE HTML Y MANEJADORES JAVASCRIPT ───────────────────

    def test_html_inline_event_handlers_are_defined(self):
        """Verifica que todos los onclick, onchange y oninput de index.html tengan su implementación."""
        handlers = re.findall(r'(?:onclick|onchange|oninput)\s*=\s*["\']([^"\']+)["\']', self.html)
        for h in handlers:
            call_match = re.match(r"([A-Za-z0-9_$.]+)\s*\(", h.strip())
            if not call_match:
                continue
            fn_name = call_match.group(1)
            if fn_name.startswith("CircuitVisualizer."):
                method = fn_name.split(".")[1]
                self.assertIn(
                    method,
                    self.cv_js,
                    f"El manejador HTML '{fn_name}' no existe en circuit-visualizer.js."
                )
            else:
                defined = (
                    f"window.{fn_name} =" in self.app_js or
                    f"function {fn_name}" in self.app_js or
                    f"function {fn_name}" in self.html
                )
                self.assertTrue(defined, f"El manejador HTML '{fn_name}' no está definido ni en app.js ni en index.html.")

    # ─── 3. REGLA ESTRICTA DE USUARIO: CERO MENCIONES VISIBLES DE IA / AI ────

    def test_zero_visible_ai_mentions_in_ui_templates(self):
        """Verifica que NO haya menciones visibles de 'IA', 'AI' o 'Inteligencia Artificial' en index.html."""
        # Limpiar tags y comentarios HTML para inspeccionar solo texto visible
        cleaned_html = re.sub(r"<!--[\s\S]*?-->", "", self.html)
        # Excluir nombres de atributos técnicos como id="btnDiagnoseAi", class="btn-ai"
        visible_text = re.sub(r'<[^>]+>', ' ', cleaned_html)

        self.assertNotRegex(
            visible_text,
            r"\bInteligencia\s+Artificial\b",
            "Violación de regla de usuario: Aparece 'Inteligencia Artificial' en el texto visible del HTML."
        )
        self.assertNotRegex(
            visible_text,
            r"\b(?:IA|AI)\b",
            "Violación de regla de usuario: Aparece 'IA' o 'AI' como palabra visible en el HTML."
        )

    def test_zero_visible_ai_mentions_in_client_strings(self):
        """Verifica que los mensajes, toasts y textos generados en app.js no contengan 'IA' o 'AI' visibles."""
        ui_strings = re.findall(r'toast\s*\(\s*["\']([^"\']+)["\']', self.app_js)
        ui_strings += re.findall(r'placeholder\s*=\s*["\']([^"\']+)["\']', self.app_js)
        ui_strings += re.findall(r'title\s*=\s*["\']([^"\']+)["\']', self.app_js)

        for s in ui_strings:
            self.assertNotRegex(
                s,
                r"\b(?:IA|AI|Inteligencia\s+Artificial)\b",
                f"Violación de regla de usuario en string de cliente: '{s}'"
            )

    # ─── 4. FLUIDEZ, CSS Y RENDIMIENTO TÁCTIL MÓVIL ──────────────────────────

    def test_mobile_touch_fluidity_and_gpu_acceleration(self):
        """Verifica directivas CSS para aceleración por GPU, prevención de jank y scroll overscroll."""
        self.assertIn("will-change:transform", self.html.replace(" ", ""))
        self.assertIn("overscroll-behavior:contain", self.html.replace(" ", ""))
        self.assertIn("touch-action:none", self.html.replace(" ", ""))
        self.assertIn("safe-area-inset-bottom", self.html)

    def test_pwa_cache_manifest_and_core_assets_served(self):
        """Verifica que todos los archivos listados en el CORE de sw.js existan y se sirvan con HTTP 200."""
        match_core = re.search(r"const\s+CORE\s*=\s*\[([\s\S]*?)\];", self.service_worker_js)
        self.assertIsNotNone(match_core, "No se encontró la lista CORE en sw.js")
        core_assets = re.findall(r'["\'](/[^"\']+)["\']', match_core.group(1))

        self.assertGreaterEqual(len(core_assets), 8)
        self.assertIn("/static/circuit_schematics.json", core_assets)
        self.assertIn("/static/circuit-visualizer.js", core_assets)

        for asset in core_assets:
            with self.client.get(asset) as res:
                self.assertEqual(res.status_code, 200, f"El recurso crítico del Service Worker '{asset}' falló con {res.status_code}.")

    # ─── 5. CASOS BORDE, RED LOCAL (HTTP/LAN) Y ROBUSTEZ ─────────────────────

    def test_r2_url_server_injection_and_pdf_extension_sanitization(self):
        """Verifica que index.html inyecte _INITIAL_R2_URL y que verPDF no duplique extensiones .pdf."""
        self.assertIn("window._INITIAL_R2_URL", self.html)
        self.assertIn("cleanManual.toLowerCase().endsWith(\".pdf\")", self.app_js)

    def test_http_lan_uuid_fallback_prevents_crashes(self):
        """Verifica que exista generarUUID() con fallback para contextos HTTP no seguros en red local."""
        self.assertIn("function generarUUID()", self.app_js)
        self.assertIn("xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx", self.app_js)
        self.assertIn("id || generarUUID()", self.app_js)

    def test_circuit_schematic_bridge_present_in_causal_diagnostics(self):
        """Verifica que el diagnóstico causal avanzado tenga el botón de esquema SVG y actualice la traza."""
        match_fn = re.search(r"function\s+renderDiagnosticoAi\s*\([\s\S]*?\n\}", self.app_js)
        self.assertIsNotNone(match_fn, "renderDiagnosticoAi no encontrada")
        fn_code = match_fn.group(0)
        self.assertIn("abrirEnEsquemaSvg()", fn_code)
        self.assertIn("_ultimoResultadoGrafo", fn_code)

    def test_svg_export_and_canvas_namespace_validity(self):
        """Verifica que el elemento SVG y la exportación declaren el espacio de nombres XML."""
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', self.cv_js)
        self.assertIn('setAttribute("version", "1.1")', self.cv_js)

    def test_global_irA_navigation_function_exported(self):
        """Verifica que window.irA esté asignada a nivel de script en index.html."""
        self.assertIn("window.irA = irA;", self.html)


if __name__ == "__main__":
    unittest.main()
