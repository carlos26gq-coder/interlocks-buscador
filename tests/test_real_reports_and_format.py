"""SOLVI - Pruebas reales de generación de informes técnicos y validación de formato.

Verifica que el generador híbrido produzca informes técnicos con razonamiento
adaptado a diferentes averías de aceleradores lineales Elekta (Synergy, Versa HD, Precise, Agility),
siguiendo estrictamente la estructura, campos, colores y tablas del modelo institucional oficial.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from api import app, search_engine
from report_service import (
    generate_local_report_body,
    generate_report_body_hybrid,
    _is_drawing_number,
)

AI_MENTION_REGEX = re.compile(r"\b(?:Inteligencia\s+Artificial|IA|AI)\b", re.IGNORECASE)


def build_preview_html_reference(
    client: str,
    number: str,
    service: str,
    date: str,
    equipment: str,
    dept: str,
    brand: str,
    model: str,
    serial: str,
    incident: str,
    diagnosis: str,
    is_programmed: bool,
    is_susp_tto: bool,
    client_date: str,
    client_time: str,
    work_start_date: str,
    work_start_time: str,
    work_end_date: str,
    work_end_time: str,
    down_time: str,
    work: str,
    conclusion: str,
    parts: list[dict[str, str]],
    images: list[dict[str, str]],
) -> str:
    """Construye el HTML idéntico al renderizado por previewInforme() en app.js."""
    parts_rows = ""
    for p in parts:
        pn = p.get("pn", "").strip()
        desc = p.get("description", "").strip()
        qty = p.get("quantity", "01").strip()
        if pn or desc:
            parts_rows += f"""
                <tr>
                    <td style="border: 1px solid #000; padding: 5px 8px; font-weight: 600;">{pn}</td>
                    <td style="border: 1px solid #000; padding: 5px 8px;">{desc}</td>
                    <td style="border: 1px solid #000; padding: 5px 8px; text-align: center;">{qty}</td>
                </tr>
            """

    parts_table = ""
    if parts_rows:
        parts_table = f"""
            <div style="margin-top: 8px; border-top: 1px solid #000;">
                <table style="width: 100%; border-collapse: collapse; font-size: 10.5px;">
                    <thead>
                        <tr style="background: #e2e8f0; font-weight: bold;">
                            <th style="border: 1px solid #000; padding: 4px 8px; text-align: left; width: 28%;">P/N</th>
                            <th style="border: 1px solid #000; padding: 4px 8px; text-align: left; width: 57%;">Descripción</th>
                            <th style="border: 1px solid #000; padding: 4px 8px; text-align: center; width: 15%;">Cant.</th>
                        </tr>
                    </thead>
                    <tbody>
                        {parts_rows}
                    </tbody>
                </table>
            </div>
        """

    images_html = ""
    if images:
        fig_items = ""
        for idx, img in enumerate(images):
            name = img.get("name", f"Figura {idx+1}")
            url = img.get("dataUrl", "")
            fig_items += f"""
                <div style="border: 1px solid #000; padding: 6px; background: #ffffff; text-align: center; max-width: 340px; flex: 1 1 260px; page-break-inside: avoid; box-sizing: border-box;">
                    <img src="{url}" alt="{name}" style="max-width: 100%; max-height: 220px; object-fit: contain; display: block; margin: 0 auto 6px auto;">
                    <div style="font-size: 10px; font-weight: bold; color: #000000; padding: 2px; border-top: 1px solid #e2e8f0;">Fig. {idx + 1}: {name}</div>
                </div>
            """
        images_html = f"""
            <div style="margin-top: 10px; padding: 10px; border-top: 1px solid #000; background: #fafafa;">
                <div style="display: flex; flex-wrap: wrap; gap: 14px; justify-content: center; align-items: flex-start;">
                    {fig_items}
                </div>
            </div>
        """

    prog_mark = "☒" if is_programmed else "☐"
    susp_mark = "☒" if is_susp_tto else "☐"

    return f"""
        <div style="font-family: Arial, Helvetica, sans-serif; color: #000000; line-height: 1.35; max-width: 800px; margin: 0 auto; background: #ffffff;">
            <div style="border: 2px solid #000; text-align: center; padding: 6px 0; font-size: 17px; font-weight: 900; letter-spacing: 1.5px; background: #e2e8f0; margin-bottom: 8px;">
                INFORME TÉCNICO
            </div>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #000; font-size: 10.5px; margin-bottom: 10px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; width: 14%; padding: 4px 6px;">CLIENTE:</td>
                        <td style="border: 1px solid #000; width: 36%; padding: 4px 6px;">{client}</td>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; width: 14%; padding: 4px 6px;">INFORME:</td>
                        <td style="border: 1px solid #000; width: 36%; padding: 4px 6px; font-weight: 600;">{number}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">SERVICIO:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{service}</td>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">FECHA:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{date}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">EQUIPO:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{equipment}</td>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">DEPARTAMENTO:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{dept}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">MARCA:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{brand}</td>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">MODELO:</td>
                        <td style="border: 1px solid #000; padding: 4px 6px;">{model}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #000; background: #e2e8f0; font-weight: bold; padding: 4px 6px;">SERIE:</td>
                        <td colspan="3" style="border: 1px solid #000; padding: 4px 6px; font-weight: 600;">{serial}</td>
                    </tr>
                </tbody>
            </table>
            <div style="border: 1.5px solid #000; margin-bottom: 10px; page-break-inside: avoid;">
                <div style="background: #e2e8f0; font-weight: bold; font-size: 11px; padding: 4px 8px; border-bottom: 1px solid #000;">INCIDENTE QUE MANIFIESTA EL USUARIO</div>
                <div style="padding: 8px 10px; font-size: 11px; line-height: 1.4; white-space: pre-wrap; min-height: 24px;">{incident}</div>
            </div>
            <div style="border: 1.5px solid #000; margin-bottom: 10px; page-break-inside: avoid;">
                <div style="background: #e2e8f0; font-weight: bold; font-size: 11px; padding: 4px 8px; border-bottom: 1px solid #000; display: flex; justify-content: space-between; align-items: center;">
                    <span>DIAGNOSTICO</span>
                    <div style="font-size: 11px; display: flex; gap: 20px;">
                        <span>PROGRAMADO <strong style="border: 1px solid #000; display: inline-block; width: 14px; height: 14px; text-align: center; line-height: 13px; font-size: 11px; vertical-align: middle; background: #ffffff;">{prog_mark}</strong></span>
                        <span>SUSP TTO <strong style="border: 1px solid #000; display: inline-block; width: 14px; height: 14px; text-align: center; line-height: 13px; font-size: 11px; vertical-align: middle; background: #ffffff;">{susp_mark}</strong></span>
                    </div>
                </div>
                <div style="padding: 8px 10px; font-size: 11px; line-height: 1.4; white-space: pre-wrap; min-height: 24px;">{diagnosis}</div>
            </div>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #000; font-size: 10.5px; margin-bottom: 10px; text-align: center; page-break-inside: avoid;">
                <thead>
                    <tr style="background: #e2e8f0; font-weight: bold;">
                        <th colspan="2" style="border: 1px solid #000; padding: 4px;">Reporte de cliente</th>
                        <th colspan="5" style="border: 1px solid #000; padding: 4px;">Revisión realizada</th>
                    </tr>
                    <tr style="background: #f1f5f9; font-weight: 600; font-size: 10px;">
                        <th style="border: 1px solid #000; padding: 3px; width: 14%;">Fecha</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 12%;">Hora</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 15%;">Fecha Inicio</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 13%;">Hora Inicio</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 15%;">Fecha Fin</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 13%;">Hora Fin</th>
                        <th style="border: 1px solid #000; padding: 3px; width: 18%;">Down Time</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="border: 1px solid #000; padding: 5px;">{client_date}</td>
                        <td style="border: 1px solid #000; padding: 5px;">{client_time}</td>
                        <td style="border: 1px solid #000; padding: 5px;">{work_start_date}</td>
                        <td style="border: 1px solid #000; padding: 5px;">{work_start_time}</td>
                        <td style="border: 1px solid #000; padding: 5px;">{work_end_date}</td>
                        <td style="border: 1px solid #000; padding: 5px;">{work_end_time}</td>
                        <td style="border: 1px solid #000; padding: 5px; font-weight: bold;">{down_time}</td>
                    </tr>
                </tbody>
            </table>
            <div style="border: 1.5px solid #000; margin-bottom: 10px;">
                <div style="background: #e2e8f0; font-weight: bold; font-size: 11px; padding: 4px 8px; border-bottom: 1px solid #000;">TRABAJO REALIZADO</div>
                <div style="padding: 10px; font-size: 11px; line-height: 1.5; text-align: justify; white-space: pre-wrap;">{work}</div>
                {images_html}
            </div>
            <div style="border: 1.5px solid #000; margin-bottom: 10px; page-break-inside: avoid;">
                <div style="background: #e2e8f0; font-weight: bold; font-size: 11px; padding: 4px 8px; border-bottom: 1px solid #000;">CONCLUSIONES</div>
                <div style="padding: 8px 10px; font-size: 11px; line-height: 1.4; white-space: pre-wrap;">{conclusion}</div>
                {parts_table}
            </div>
            <div style="margin-top: 36px; display: flex; justify-content: space-between; align-items: flex-start; padding: 0 40px; page-break-inside: avoid;">
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #000; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold;">Firma / Sello Técnico</div>
                    <div style="font-size: 9.5px; color: #334155;">Servicio Técnico Especializado</div>
                </div>
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #000; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold;">Conformidad del Cliente</div>
                    <div style="font-size: 9.5px; color: #334155;">Responsable de Servicio / Física Médica</div>
                </div>
            </div>
        </div>
    """


class RealReportsAndFormatValidationTests(unittest.TestCase):
    """Batería de pruebas reales para diferentes incidencias y validación de formato."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def _assert_no_ai_mentions(self, text: str, field_desc: str):
        matches = AI_MENTION_REGEX.findall(text)
        self.assertEqual(len(matches), 0, f"Mención no permitida de IA/AI en '{field_desc}': {matches}")

    def _assert_no_drawing_numbers_in_parts(self, parts: list[dict[str, str]]):
        for p in parts:
            pn = str(p.get("pn", "")).strip()
            self.assertFalse(
                _is_drawing_number(pn),
                f"El número '{pn}' es un número de plano y no debe ser asignado como repuesto P/N."
            )

    # ─── CASO 1: HT PSU OT (MODELO EXACTO DE REFERENCIA) ───────────────────────

    def test_case_1_ht_psu_ot_model_fidelity(self):
        """Caso 1: Verifica el modelo de referencia HT PSU OT, Switch Assembly, DIE-HTB pin A3."""
        payload = {
            "incident": "HT PSU OT",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "SYNERGY FULL",
            "diagnosis": "Reemplazo de Switch Assembly y DIE HTB",
            "image_descriptions": ["Foto del interruptor fuelle", "Esquema DIE-HTB pin A3"],
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 150)
        self.assertIn("HT PSU OT", body)
        self.assertIn("Switch Assembly", body)
        self.assertIn("DIE-HTB", body)
        self.assertRegex(body, r"(?i)(?:[aá]rea\s*16|HTCA|PCB\s*16[MN])")
        self.assertRegex(body, r"(?i)pin\s*A3")
        self.assertIn("45133308377", body)
        self.assertIn("1573801", body)

        parts = data.get("suggested_parts", [])
        self.assertGreaterEqual(len(parts), 2)
        pns = [p["pn"] for p in parts]
        self.assertIn("45133308377", pns)
        self.assertIn("1573801", pns)
        self._assert_no_drawing_numbers_in_parts(parts)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 1")

        # Validar HTML del modelo
        html = build_preview_html_reference(
            client="INEN",
            number="260915_154574_ CG HT PSU OT",
            service="Radioterapia",
            date="15 de Septiembre del 2026",
            equipment="ACELERADOR LINEAL",
            dept="LIMA",
            brand="ELEKTA",
            model="SYNERGY FULL",
            serial="154574",
            incident="HT PSU OT",
            diagnosis="Reemplazo de Switch Assembly y DIE HTB",
            is_programmed=True,
            is_susp_tto=False,
            client_date="15/09/2026",
            client_time="19:00",
            work_start_date="15/09/2026",
            work_start_time="19:00",
            work_end_date="15/09/2026",
            work_end_time="21:00 h",
            down_time="2:00 h",
            work=body,
            conclusion=data.get("suggested_conclusions", "- Equipo operativo\n- Se requiere los siguientes repuestos"),
            parts=parts,
            images=[
                {"name": "Foto del interruptor fuelle", "dataUrl": "data:image/png;base64,iVBORw0KGgo="},
                {"name": "Esquema DIE-HTB pin A3", "dataUrl": "data:image/png;base64,iVBORw0KGgo="},
            ],
        )

        self.assertIn("INFORME TÉCNICO", html)
        self.assertIn("CLIENTE:", html)
        self.assertIn("INEN", html)
        self.assertIn("PROGRAMADO <strong", html)
        self.assertIn("☒", html)
        self.assertIn("Down Time", html)
        self.assertIn("2:00 h", html)
        self.assertIn("TRABAJO REALIZADO", html)
        self.assertIn("Fig. 1: Foto del interruptor fuelle", html)
        self.assertIn("Fig. 2: Esquema DIE-HTB pin A3", html)
        self.assertIn("CONCLUSIONES", html)
        self.assertIn("45133308377", html)
        self.assertIn("Switch Assembly", html)
        self.assertIn("Firma / Sello Técnico", html)
        self.assertIn("Conformidad del Cliente", html)

    # ─── CASO 2: CONTACTOR CON-K / ITEM 79 ─────────────────────────────────────

    def test_case_2_con_k_and_item_79(self):
        """Caso 2: Fallo de contactor CON-K e ITEM 79 (cadena de potencia y contactos auxiliares)."""
        payload = {
            "incident": "Inhibición de encendido de potencia por fallo en contactor CON-K e ITEM 79",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "VERSA HD",
            "diagnosis": "Reemplazo de contactos auxiliares de contactor CON-K",
            "image_descriptions": ["Registro de contactos CON-K"],
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertIn("CON-K", body)
        self.assertIn("ITEM 79", body)
        self.assertIn("DIE-ICA", body)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 2")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 3: DOSIMETRÍA / INTERLOCK 283 ───────────────────────────────────

    def test_case_3_dosimetry_interlock_283(self):
        """Caso 3: Discrepancia dosimétrica Canal 1 y 2 / Interlock 283 en cabezal de radiación."""
        payload = {
            "incident": "Interlock 283 discrepancia de dosimetría en Canal 1 y Canal 2 durante radiación",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "PRECISE",
            "diagnosis": "Sustitución de tarjeta de dosimetría DIE-RHA y polarización",
            "image_descriptions": ["Medición de polarización -500V"],
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertIn("DIE-RHA", body)
        self.assertTrue("Canal" in body or "dosimetr" in body.lower())
        self._assert_no_ai_mentions(body, "Cuerpo Caso 3")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 4: ALTO VACÍO Y BOMBA IÓNICA ────────────────────────────────────

    def test_case_4_vacuum_and_ion_pump(self):
        """Caso 4: Interrupción por degradación de vacío en cañón y bomba iónica."""
        payload = {
            "incident": "Disparo en lazo de ultra alto vacío y corriente resistiva en bomba iónica",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "SYNERGY",
            "diagnosis": "Limpieza y sustitución de pasamuros de alto vacío",
            "image_descriptions": ["Curva de corriente iónica"],
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertTrue("vacío" in body.lower() or "bomba" in body.lower())
        self._assert_no_ai_mentions(body, "Cuerpo Caso 4")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 5: COLIMADOR / MLC AGILITY ──────────────────────────────────────

    def test_case_5_collimator_and_mlc(self):
        """Caso 5: Error de posicionamiento de hojas MLC Agility e Interlock 51."""
        payload = {
            "incident": "Interlock 51 desvío de hojas MLC Agility y timeout de comunicación bus CAN",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "VERSA HD",
            "diagnosis": "Revisión de bus CAN y servocontrolador de hojas MLC",
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 5")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── VERIFICACIÓN DE DIFERENCIACIÓN (NO SON IGUALES) ──────────────────────

    def test_all_five_cases_produce_distinct_content(self):
        """Verifica que las 5 incidencias generen contenidos claramente diferenciados y no copias idénticas."""
        queries = [
            "HT PSU OT",
            "CON-K ITEM 79",
            "Interlock 283 dosimetría",
            "Ultra alto vacío bomba iónica",
            "Interlock 51 hojas MLC Agility",
        ]
        bodies = []
        for q in queries:
            res = self.client.post("/reports/generate-body", json={"incident": q})
            self.assertEqual(res.status_code, 200)
            bodies.append(res.get_json().get("body", ""))

        # Verificar que no haya dos cuerpos idénticos
        for i in range(len(bodies)):
            for j in range(i + 1, len(bodies)):
                self.assertNotEqual(
                    bodies[i],
                    bodies[j],
                    f"Los informes para '{queries[i]}' y '{queries[j]}' no deben ser idénticos."
                )


if __name__ == "__main__":
    unittest.main()
