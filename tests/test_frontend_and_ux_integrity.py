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
sys.path.insert(0, str(ROOT / "tests"))
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
            "analizarDiagnostico", "analizarDiagnosticoAi",
            "guardarYReintentarAi", "cargarNotas", "abrirFormNota",
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

    def test_zero_visible_ai_mentions_in_ui_templates(self):
        """Verifica que NO haya menciones visibles de 'IA', 'AI' o 'Inteligencia Artificial' en index.html."""
        from _helpers import extract_visible_html_text, assert_no_visible_ai
        visible_text = extract_visible_html_text(self.html)
        assert_no_visible_ai(self, visible_text, "el texto visible de index.html")

    def test_zero_visible_ai_mentions_in_client_strings(self):
        """Verifica que los mensajes, toasts y textos generados en app.js no contengan 'IA' o 'AI' visibles."""
        from _helpers import extract_visible_js_strings, assert_no_visible_ai
        for s in extract_visible_js_strings(self.app_js):
            assert_no_visible_ai(self, s, f"string de cliente '{s}'")

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
        self.assertIn("/data/documentary_traceability.json", core_assets)

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

    def test_global_irA_navigation_function_exported(self):
        """Verifica que window.irA esté asignada a nivel de script en index.html."""
        self.assertIn("window.irA = irA;", self.html)

    def test_normal_search_requires_explicit_action(self):
        """Escribir o cambiar el filtro no debe consultar; solo Buscar o Enter lo hacen."""
        init_match = re.search(
            r'document\.addEventListener\("DOMContentLoaded", async function\(\) \{([\s\S]*?)// Symptom inputs',
            self.app_js,
        )
        self.assertIsNotNone(init_match, "No se encontró la inicialización del buscador.")
        init_code = init_match.group(1)
        self.assertNotIn('q.addEventListener("input"', init_code)
        self.assertNotIn('m.addEventListener("change", dispararBusqueda)', init_code)
        self.assertIn('event.key !== "Enter"', init_code)

    def test_transient_provider_error_has_safe_ui_message(self):
        """La UI debe reconocer 503/saturación sin mostrar detalles del proveedor."""
        self.assertIn('errType === "service_unavailable"', self.app_js)
        self.assertIn('errLower.includes("high demand")', self.app_js)


if __name__ == "__main__":
    unittest.main()
