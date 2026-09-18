"""SOLVI - Pruebas de Reestructuración Arquitectónica, Resiliencia Offline-First y Ergonomía UI."""

from pathlib import Path
import json
import os
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
TOOLS_DIR = SCRIPTS_DIR / "tools"
STATIC_DIR = SCRIPTS_DIR / "static"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TOOLS_DIR))

from _helpers import extract_visible_html_text, extract_visible_js_strings, assert_no_visible_ai
from api import app


class ArchitecturalRestructureAndResilienceSuite(unittest.TestCase):
    """Suite de validación para las especializaciones ARCH_STRUCT, NETWORK_SYNC y UI_LAYOUT."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with open(TEMPLATES_DIR / "index.html", "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(STATIC_DIR / "log-parser.js", "r", encoding="utf-8") as f:
            cls.log_parser_js = f.read()
        with open(STATIC_DIR / "multimeter.js", "r", encoding="utf-8") as f:
            cls.multimeter_js = f.read()
        with open(STATIC_DIR / "circuit-visualizer.js", "r", encoding="utf-8") as f:
            cls.cv_js = f.read()
        with open(ROOT / "sw.js", "r", encoding="utf-8") as f:
            cls.sw_js = f.read()

    # ─── 1. [ARCH_STRUCT]: REESTRUCTURACIÓN MODULAR Y RETROCOMPATIBILIDAD ────

    def test_tools_directory_and_package_structure(self):
        """Verifica que scripts/tools/ exista como paquete modular con __init__.py."""
        self.assertTrue(TOOLS_DIR.exists(), "El directorio scripts/tools/ debe existir")
        self.assertTrue(TOOLS_DIR.is_dir(), "scripts/tools/ debe ser un directorio")
        self.assertTrue((TOOLS_DIR / "__init__.py").exists(), "__init__.py debe existir en scripts/tools/")

    def test_modular_cli_tools_exist_in_tools_package(self):
        """Verifica que las herramientas CLI residan de forma modular en scripts/tools/."""
        expected_tools = [
            "add_manual.py",
            "build_index.py",
            "build_linac_graph.py",
            "extract_pages.py",
            "search_manuals.py",
            "validate_data.py",
        ]
        for tool in expected_tools:
            tool_path = TOOLS_DIR / tool
            self.assertTrue(tool_path.exists(), f"La herramienta {tool} debe existir en {TOOLS_DIR}")

    def test_tools_point_to_repository_root(self):
        """Verifica que las herramientas en scripts/tools/ resuelvan BASE_DIR hacia el repositorio raíz."""
        from tools.validate_data import BASE_DIR as val_base
        self.assertEqual(val_base.resolve(), ROOT.resolve(), "validate_data.BASE_DIR debe apuntar al root")

        from tools.build_index import BASE_DIR as idx_base
        self.assertEqual(idx_base.resolve(), ROOT.resolve(), "build_index.BASE_DIR debe apuntar al root")

        from tools.build_linac_graph import ROOT_DIR as graph_root
        self.assertEqual(graph_root.resolve(), ROOT.resolve(), "build_linac_graph.ROOT_DIR debe apuntar al root")

    def test_validate_data_tool_execution(self):
        """Ejecuta tools/validate_data.py y comprueba que los 6,322 registros sean íntegros."""
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "validate_data.py")],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, f"validate_data falló:\n{result.stderr}")
        self.assertIn("Total páginas: 6322", result.stdout)
        self.assertIn("Manuales: 19", result.stdout)
        self.assertIn("Registros inválidos: 0", result.stdout)

    def test_backwards_compatible_forwarders_in_scripts(self):
        """Verifica que los 6 forwarders en scripts/ deleguen correctamente a scripts/tools/."""
        forwarders = [
            "add_manual.py",
            "build_index.py",
            "build_linac_graph.py",
            "extract_pages.py",
            "search_manuals.py",
            "validate_data.py",
        ]
        for f in forwarders:
            file_path = SCRIPTS_DIR / f
            self.assertTrue(file_path.exists(), f"El forwarder scripts/{f} debe existir")
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("scripts.tools." + f.replace(".py", ""), content, f"scripts/{f} debe delegar a scripts.tools")

    def test_validate_data_import_has_no_side_effects(self):
        """Verifica que importar tools.validate_data no ejecute código ni imprima a stdout."""
        cmd = [sys.executable, "-c", "import scripts.tools.validate_data"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "", "Importar validate_data no debe imprimir a stdout")

    def test_deployment_entrypoints_and_render_compatibility(self):
        """Verifica que Procfile y render.yaml conserven sus puntos de entrada requeridos."""
        procfile_path = ROOT / "Procfile"
        self.assertTrue(procfile_path.exists())
        proc_content = procfile_path.read_text(encoding="utf-8")
        self.assertIn("api:app", proc_content)

        render_path = ROOT / "render.yaml"
        self.assertTrue(render_path.exists())
        render_content = render_path.read_text(encoding="utf-8")
        self.assertIn("api:app", render_content)
        self.assertIn("autoDeployTrigger: checksPass", render_content)
        self.assertIn("buildFilter:", render_content)
        self.assertIn("- render.yaml", render_content)
        self.assertIn("pip install -r requirements.txt", render_content)
        self.assertIn("gunicorn --chdir scripts api:app", render_content)
        self.assertNotIn("rootDir: scripts", render_content)

        workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(workflow_path.exists())
        workflow_content = workflow_path.read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests -v", workflow_content)
        self.assertIn("node --check scripts/static/app.js", workflow_content)

    # ─── 2. [NETWORK_SYNC]: RESILIENCIA OFFLINE-FIRST Y CONECTIVIDAD ─────────

    def test_reactive_network_monitoring_and_is_online_export(self):
        """Verifica que app.js defina isOnline y NetworkMonitor con exportación global."""
        self.assertIn("function isOnline()", self.app_js)
        self.assertIn("const NetworkMonitor =", self.app_js)
        self.assertIn("window.isOnline = isOnline;", self.app_js)

    def test_offline_queue_supports_create_and_delete_operations(self):
        """Verifica que syncPendientes procese operaciones de creación y eliminación en la cola."""
        self.assertIn('item.op === "create"', self.app_js)
        self.assertIn('item.op === "delete"', self.app_js)
        self.assertIn("pendLoad()", self.app_js)
        self.assertIn("pendSave(", self.app_js)
        self.assertIn("pendAddDelete(", self.app_js)

    def test_offline_local_note_deletion_without_blocking(self):
        """Verifica que un apunte creado localmente se pueda eliminar offline sin requerir admin."""
        self.assertIn("isLocalPending", self.app_js)
        self.assertIn('toast("🗑 Apunte local eliminado")', self.app_js)

    def test_offline_cloud_note_deletion_queued_when_admin(self):
        """Verifica que eliminar una nota de la nube offline o con red fallida encole la eliminación."""
        self.assertIn("pendAddDelete(id)", self.app_js)
        self.assertIn("se sincronizará al conectar", self.app_js)

    def test_merge_cloud_notes_filters_out_pending_deletions(self):
        """Verifica que mergeCloudNotes no resucite notas que están en cola de eliminación."""
        self.assertIn('p.op === "delete"', self.app_js)
        self.assertIn("deletedIds", self.app_js)

    def test_api_request_wraps_network_and_offline_errors(self):
        """Verifica que apiRequest capture fallos de red y devuelva error informativo limpio."""
        self.assertIn("Sin conexión con el servidor. Verifica tu conexión de red.", self.app_js)
        self.assertIn("netErr.isOffline = true;", self.app_js)

    def test_log_parser_parse_text_backend_offline_resilience(self):
        """Verifica que parseTextBackend en log-parser.js tenga degradación elegante a cliente si offline."""
        self.assertTrue("!online" in self.log_parser_js or "!navigator.onLine" in self.log_parser_js)
        self.assertIn("LogParser.parseChunk", self.log_parser_js)
        self.assertIn("LogParser.aggregate", self.log_parser_js)

    def test_causal_diagnostics_graceful_offline_degradation(self):
        """Verifica que el diagnóstico causal degrade limpiamente a local cuando no hay conexión."""
        self.assertIn("El análisis causal avanzado requiere internet. Mostrando diagnóstico local...", self.app_js)
        self.assertIn("return analizarDiagnostico();", self.app_js)

    def test_admin_functions_informative_offline_rejection(self):
        """Verifica que adminEntrar informe elegantemente al usuario cuando esté offline."""
        self.assertIn("El área de administración requiere conexión al servidor", self.app_js)

    # ─── 3. [UI_LAYOUT]: ERGONOMÍA, ESPACIO DE TRABAJO Y ZERO AI MENTIONS ────

    def test_active_tool_workspace_badge_in_header(self):
        """Verifica que el layout principal integre el indicador dinámico de herramienta activa."""
        self.assertIn('id="activeToolBadge"', self.html)
        self.assertIn('id="activeToolName"', self.html)
        self.assertIn('id="activeToolMode"', self.html)
        self.assertIn("header-status-group", self.html)

    def test_workspace_navigation_updates_active_tool_badge(self):
        """Verifica que irA(name) actualice la etiqueta y modo de la herramienta en el workspace."""
        self.assertIn("_TOOL_META", self.html)
        self.assertIn("activeToolName", self.html)
        self.assertIn("activeToolMode", self.html)
        self.assertIn("BUSCADOR", self.html)
        self.assertIn("MULTÍMETRO", self.html)
        self.assertIn("ESQUEMAS", self.html)

    def test_warning_toast_styling_support(self):
        """Verifica que index.html y app.js soporten toasts de advertencia con estilo .twarn."""
        self.assertIn(".twarn", self.html)
        self.assertIn('"twarn"', self.app_js)

    def test_bottom_nav_ergonomics_and_touch_target_accessibility(self):
        """Verifica que los botones de navegación inferior cumplan estándares táctiles (mínimo 44px)."""
        self.assertIn("min-height:48px", self.html.replace(" ", ""))
        self.assertIn("touch-action:manipulation", self.html.replace(" ", ""))
        self.assertIn("-webkit-tap-highlight-color:transparent", self.html.replace(" ", ""))

    def test_zero_visible_ai_mentions_in_updated_html(self):
        """REGLA ESTRICTA: Verifica CERO menciones visibles de IA/AI en el HTML actualizado."""
        visible_text = extract_visible_html_text(self.html)
        assert_no_visible_ai(self, visible_text, "el texto visible de index.html")

    def test_zero_visible_ai_mentions_in_updated_js_strings(self):
        """REGLA ESTRICTA: Verifica CERO menciones de IA/AI en mensajes al usuario de app.js."""
        for s in extract_visible_js_strings(self.app_js):
            assert_no_visible_ai(self, s, f"string de cliente '{s}'")


if __name__ == "__main__":
    unittest.main()
