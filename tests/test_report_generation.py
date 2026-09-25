"""SOLVI - Pruebas de Integración y Calidad para el Módulo de Informes Técnicos."""

from pathlib import Path
import json
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
STATIC_DIR = SCRIPTS_DIR / "static"

sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app, search_engine
from report_service import (
    generate_local_report_body,
    generate_report_body_hybrid,
    _extract_spare_parts_from_context,
    _is_drawing_number,
)
from _helpers import assert_no_visible_ai, extract_visible_html_text, extract_visible_js_strings


class ReportGenerationTestSuite(unittest.TestCase):
    """Pruebas exhaustivas para el servicio de redacción de informes técnicos y endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with (TEMPLATES_DIR / "index.html").open("r", encoding="utf-8") as f:
            cls.html = f.read()
        with (STATIC_DIR / "app.js").open("r", encoding="utf-8") as f:
            cls.app_js = f.read()

    # ─── 1. MOTOR LOCAL DE REDACCIÓN TÉCNICA FUNDAMENTADA ─────────────────────

    def test_local_report_generation_for_ht_psu_ot(self):
        """Verifica que el informe para HT PSU OT identifique vástago, switch, tarjeta DIE-HTB y repuestos exactos."""
        result = generate_local_report_body(
            incident="HT PSU OT",
            equipment="ACELERADOR LINEAL",
            brand="ELEKTA",
            model="SYNERGY FULL",
            diagnosis="Reemplazo de Switch Assembly y DIE HTB",
            image_descriptions=["Foto del interruptor fuelle", "Esquema DIE-HTB pin A3"],
            search_engine=search_engine,
        )

        body = result.get("body", "")
        self.assertIn("HT PSU OT", body)
        self.assertIn("Switch Assembly", body)
        self.assertIn("45133308377", body)
        self.assertIn("DIE-HTB", body)
        self.assertIn("1573801", body)
        self.assertIn("Área 16", body)
        self.assertIn("pin A3", body)
        self.assertIn("fuelle", body)
        self.assertIn("[IMÁGENES ADJUNTAS:", body)

        parts = result.get("suggested_parts", [])
        self.assertGreaterEqual(len(parts), 2)
        pns = [p["pn"] for p in parts]
        self.assertIn("45133308377", pns)
        self.assertIn("1573801", pns)

        conclusions = result.get("suggested_conclusions", "")
        self.assertTrue(len(conclusions) > 10)

    def test_local_report_generation_generic_incident(self):
        """Verifica que incidentes generales generen redacción continua y sobria."""
        result = generate_local_report_body(
            incident="INTERLOCK 283 VACUUM",
            equipment="ACELERADOR LINEAL",
            brand="ELEKTA",
            model="PRECISE",
            diagnosis="",
            image_descriptions=[],
            search_engine=search_engine,
        )

        body = result.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertIn("INTERLOCK 283", body)
        self.assertNotIn("undefined", body)

    def test_hybrid_fallback_without_api_key(self):
        """Verifica que generate_report_body_hybrid recurra de forma transparente al motor local sin API key."""
        result = generate_report_body_hybrid(
            incident="HT PSU OT",
            equipment="ACELERADOR LINEAL",
            brand="ELEKTA",
            model="SYNERGY FULL",
            diagnosis="",
            search_engine=search_engine,
            api_key="",
        )
        self.assertIn("body", result)
        self.assertIn("suggested_parts", result)
        self.assertGreaterEqual(len(result["body"]), 80)

    def test_drawing_numbers_filtered_from_spare_parts(self):
        """Verifica que números de esquema (1024xxx, 45133307xxx) se identifiquen y filtren como no-repuestos."""
        self.assertTrue(_is_drawing_number("1024690"))
        self.assertTrue(_is_drawing_number("1024686"))
        self.assertTrue(_is_drawing_number("45133307021"))
        # Un repuesto genuino NO es un plano
        self.assertFalse(_is_drawing_number("45133308377"))
        self.assertFalse(_is_drawing_number("1573801"))
        self.assertFalse(_is_drawing_number("1512130"))

    def test_local_report_generation_for_con_k(self):
        """Verifica que incidentes de CON-K / ITEM 79 generen reporte con contactor y DIE-ICA."""
        result = generate_local_report_body(
            incident="CON-K ITEM 79",
            equipment="ACELERADOR LINEAL",
            brand="ELEKTA",
            model="SYNERGY FULL",
            search_engine=search_engine,
        )
        body = result.get("body", "")
        self.assertIn("CON-K", body)
        self.assertIn("ITEM 79", body)
        self.assertIn("DIE-ICA", body)
        parts = result.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        pns = [p["pn"] for p in parts]
        # Ningún número de plano 1024xxx en repuestos
        for pn in pns:
            self.assertFalse(_is_drawing_number(pn), f"P/N no debe ser número de plano: {pn}")

    # ─── 2. ENDPOINTS HTTP Y VALIDACIÓN DE ENTRADAS ──────────────────────────

    def test_api_report_generate_body_success(self):
        """Verifica el endpoint POST /reports/generate-body con carga útil válida."""
        payload = {
            "incident": "HT PSU OT",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "SYNERGY FULL",
            "diagnosis": "Reemplazo de Switch Assembly",
            "image_descriptions": ["Foto fuelle"],
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("body", data)
        self.assertIn("suggested_parts", data)
        self.assertIn("suggested_diagnosis", data)
        self.assertIn("suggested_conclusions", data)

    def test_api_report_generate_body_validation_error(self):
        """Verifica que el endpoint rechace peticiones sin incidente con código 400."""
        res = self.client.post("/reports/generate-body", json={})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("ok"), False)
        self.assertEqual(data.get("error"), "validation_error")

    def test_api_reports_generate_body_alias(self):
        """Verifica el endpoint alias /api/reports/generate-body."""
        payload = {"incident": "INTERLOCK 112"}
        res = self.client.post("/api/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(len(data.get("body", "")) > 50)

    # ─── 3. INTEGRIDAD DE LA PLANTILLA Y ELEMENTOS DOM ───────────────────────

    def test_all_report_form_fields_present_in_template(self):
        """Verifica que todos los campos requeridos existan con IDs correctos en index.html."""
        required_ids = [
            "reportClient", "reportNumber", "reportService", "reportDate", "reportEquipment",
            "reportDept", "reportBrand", "reportModel", "reportSerial", "reportIncident",
            "reportDiagnosis", "reportProgrammed", "reportSuspTto", "reportClientDate",
            "reportClientTime", "reportWorkStartDate", "reportWorkStartTime", "reportWorkEndDate",
            "reportWorkEndTime", "reportDownTime", "reportWork", "reportImages", "reportImagesList",
            "reportConclusion", "reportParts", "btnDraftReportBody", "reportWorkSpinner",
            "informePreviewModal", "informePreviewContent"
        ]
        for el_id in required_ids:
            self.assertIn(f'id="{el_id}"', self.html, f"Falta el elemento #{el_id} en index.html")

    def test_spare_parts_row_add_button_has_accessible_name(self):
        """Verifica que el botón para agregar repuestos tenga el texto accesible '+ Repuesto' requerido por smoke tests."""
        self.assertIn("+ Repuesto", self.html)
        self.assertIn('data-action="report-add-part"', self.html)

    def test_app_js_exports_report_handlers(self):
        """Verifica que las funciones de informes estén exportadas a window en app.js."""
        expected_exports = [
            "addReportPart", "previewInforme", "exportInforme", "closeReportPreview",
            "redactarTrabajoRealizado", "handleReportImagesChange", "actualizarNombreImagenReporte",
            "eliminarImagenReporte", "resetReportForm", "calcularDownTimeInforme"
        ]
        for exp in expected_exports:
            self.assertIn(f"window.{exp} =", self.app_js, f"Falta exportar {exp} en window de app.js")

    def test_zero_ai_mentions_in_report_ui(self):
        """Verifica que NO existan menciones de IA/AI en los elementos visuales del informe."""
        visible_text = extract_visible_html_text(self.html)
        assert_no_visible_ai(self, visible_text, "index.html con formulario de informe")


if __name__ == "__main__":
    unittest.main()
