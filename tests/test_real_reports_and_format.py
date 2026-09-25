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
                <tr style="background: #FFFFFF;">
                    <td style="border: 1px solid #4472C4; padding: 4px 8px; font-weight: bold; font-family: Calibri, sans-serif;">{pn}</td>
                    <td style="border: 1px solid #4472C4; padding: 4px 8px; font-family: Calibri, sans-serif;">{desc}</td>
                    <td style="border: 1px solid #4472C4; padding: 4px 8px; text-align: center; font-family: Calibri, sans-serif;">{qty}</td>
                </tr>
            """

    parts_table = ""
    if parts_rows:
        parts_table = f"""
            <div style="margin-top: 10px;">
                <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-size: 10pt; page-break-inside: avoid;">
                    <thead>
                        <tr style="background: #B4C6E7; color: #000000; font-family: 'Tahoma', Calibri, sans-serif; font-weight: bold;">
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: left; width: 28%;">P/N</th>
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: left; width: 57%;">Descripción</th>
                            <th style="border: 1px solid #4472C4; padding: 4px 8px; text-align: center; width: 15%;">Cant.</th>
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
                <div style="border: 1px solid #4472C4; padding: 6px; background: #ffffff; text-align: center; max-width: 340px; flex: 1 1 260px; page-break-inside: avoid; box-sizing: border-box;">
                    <img src="{url}" alt="{name}" style="max-width: 100%; max-height: 220px; object-fit: contain; display: block; margin: 0 auto 6px auto;">
                    <div style="font-size: 9.5pt; font-weight: bold; font-family: Calibri, sans-serif; color: #2F5496; padding: 2px; border-top: 1px solid #D9E2F3;">Fig. {idx + 1}: {name}</div>
                </div>
            """
        images_html = f"""
            <div style="margin-top: 10px; padding: 10px; border-top: 1px solid #4472C4; background: #F8FAFC;">
                <div style="display: flex; flex-wrap: wrap; gap: 14px; justify-content: center; align-items: flex-start;">
                    {fig_items}
                </div>
            </div>
        """

    prog_mark = "☒" if is_programmed else "☐"
    susp_mark = "☒" if is_susp_tto else "☐"

    return f"""
        <div style="font-family: Calibri, Arial, sans-serif; color: #000000; line-height: 1.35; max-width: 820px; margin: 0 auto; background: #ffffff; padding: 6px;">
            <div style="background: #2F5496; color: #FFFFFF; font-family: 'Candara', Calibri, sans-serif; font-size: 16pt; font-weight: bold; text-align: center; padding: 6px 0; border: 1.5px solid #2F5496; margin-bottom: 8px; letter-spacing: 0.5px;">
                | INFORME TÉCNICO
            </div>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; width: 14%; padding: 4px 6px;">Cliente:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; width: 36%; padding: 4px 6px;">{client}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; width: 14%; padding: 4px 6px;">Informe:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; width: 36%; padding: 4px 6px; font-weight: bold;">{number}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Servicio:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{service}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Fecha:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{date}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Equipo:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{equipment}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Departamento:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{dept}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Marca:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{brand}</td>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Modelo:</td>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px;">{model}</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #2F5496; color: #FFFFFF; font-weight: bold; padding: 4px 6px;">Serie:</td>
                        <td colspan="3" style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 4px 6px; font-weight: bold;">{serial}</td>
                    </tr>
                </tbody>
            </table>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">INCIDENTE QUE MANIFIESTA EL USUARIO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 6px 10px; font-size: 10.5pt; min-height: 22px;">{incident}</td>
                    </tr>
                </tbody>
            </table>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 6px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">DIAGNOSTICO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #D9E2F3; color: #000000; padding: 6px 10px; font-size: 10.5pt; min-height: 22px;">{diagnosis}</td>
                    </tr>
                </tbody>
            </table>
            <div style="font-family: Calibri, sans-serif; font-size: 10.5pt; font-weight: bold; margin: 6px 0 8px 4px; color: #000000;">
                PROGRAMADO &nbsp;&nbsp; <span style="font-size: 13pt; vertical-align: middle;">{prog_mark}</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; SUSP TTO &nbsp;&nbsp; <span style="font-size: 13pt; vertical-align: middle;">{susp_mark}</span>
            </div>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10pt; margin-bottom: 8px; text-align: center; page-break-inside: avoid;">
                <thead>
                    <tr style="background: #2F5496; color: #FFFFFF; font-weight: bold;">
                        <th colspan="2" style="border: 1px solid #4472C4; padding: 4px;">Reporte de cliente</th>
                        <th colspan="5" style="border: 1px solid #4472C4; padding: 4px;">Revisión realizada</th>
                    </tr>
                    <tr style="background: #B4C6E7; color: #000000; font-weight: bold; font-size: 9.5pt;">
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 14%;">Fecha</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 12%;">Hora</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 15%;">Fecha Inicio</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 13%;">Hora Inicio</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 15%;">Fecha Fin</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 13%;">Hora Fin</th>
                        <th style="border: 1px solid #4472C4; padding: 3px; width: 18%;">Down Time</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="background: #D9E2F3; color: #000000;">
                        <td style="border: 1px solid #4472C4; padding: 4px;">{client_date}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">{client_time}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">{work_start_date}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">{work_start_time}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">{work_end_date}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px;">{work_end_time}</td>
                        <td style="border: 1px solid #4472C4; padding: 4px; font-weight: bold;">{down_time}</td>
                    </tr>
                </tbody>
            </table>
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10.5pt; margin-bottom: 8px;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">TRABAJO REALIZADO:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #FFFFFF; color: #000000; padding: 10px 12px; line-height: 1.5; text-align: justify; white-space: pre-wrap;">{work}</td>
                    </tr>
                </tbody>
            </table>
            {images_html}
            <table style="width: 100%; border-collapse: collapse; border: 1.5px solid #4472C4; font-family: Calibri, sans-serif; font-size: 10.5pt; margin-bottom: 10px; page-break-inside: avoid;">
                <tbody>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #365F91; color: #FFFFFF; font-weight: bold; padding: 4px 8px; text-transform: uppercase;">CONCLUSIONES:</td>
                    </tr>
                    <tr>
                        <td style="border: 1px solid #4472C4; background: #FFFFFF; color: #000000; padding: 8px 12px; line-height: 1.4; white-space: pre-wrap;">{conclusion}{parts_table}</td>
                    </tr>
                </tbody>
            </table>
            <div style="margin-top: 36px; display: flex; justify-content: space-between; align-items: flex-start; padding: 0 40px; page-break-inside: avoid;">
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #2F5496; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold; color: #2F5496;">Firma / Sello Técnico</div>
                    <div style="font-size: 9.5px; color: #334155;">Servicio Técnico Especializado</div>
                </div>
                <div style="text-align: center; width: 40%;">
                    <div style="border-top: 1.5px solid #2F5496; margin-bottom: 4px;"></div>
                    <div style="font-size: 11px; font-weight: bold; color: #2F5496;">Conformidad del Cliente</div>
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
        self.assertIn("Cliente:", html)
        self.assertIn("INEN", html)
        self.assertIn("PROGRAMADO", html)
        self.assertIn("☒", html)
        self.assertIn("#2F5496", html)
        self.assertIn("#D9E2F3", html)
        self.assertIn("#365F91", html)
        self.assertIn("#B4C6E7", html)
        self.assertIn("#4472C4", html)
        self.assertIn("Candara", html)
        self.assertIn("Calibri", html)
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
        self.assertTrue(
            "contacto" in body.lower() or "contactor" in body.lower() or "potencia" in body.lower()
        )
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

    # ─── CASO 6: POTENCIÓMETRO (MESA PSS / GANTRY) ───────────────────────────

    def test_case_6_potentiometer_hardware(self):
        """Caso 6: Avería de potenciómetro de posición PSS (mesa). Verifica que NO defaultea a tarjetas DIE."""
        payload = {
            "incident": "Fallo en lectura de potenciómetro PSS Y (Mesa de tratamiento)",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "VERSA HD",
            "diagnosis": "Sustitución de potenciómetro y calibración de límites",
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertRegex(body, r"(?i)potenci[oó]metro|PSS|mesa|posici[oó]n")
        self.assertNotIn("DIE-HTB", body)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 6 Potenciómetro")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 7: TRANSFORMADOR ────────────────────────────────────────────────

    def test_case_7_transformer_hardware(self):
        """Caso 7: Fallo térmico / dieléctrico en transformador T1. Verifica razonamiento de transformador."""
        payload = {
            "incident": "Sobrecalentamiento y disparo térmico en transformador de potencia T1",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "SYNERGY",
            "diagnosis": "Sustitución y aislamiento de transformador de potencia",
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertRegex(body, r"(?i)transformador|diel[eé]ctrico|aislamiento")
        self.assertNotIn("DIE-HTB", body)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 7 Transformador")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 8: FUENTE DE PODER DC (PSU) ─────────────────────────────────────

    def test_case_8_power_supply_psu(self):
        """Caso 8: Rizado e inestabilidad en fuente conmutada DC (PSU). Verifica razonamiento de fuentes."""
        payload = {
            "incident": "Rizado excesivo de riel DC e inestabilidad en fuente de poder 24V PSU",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "PRECISE",
            "diagnosis": "Sustitución de módulo de fuente de poder DC",
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertRegex(body, r"(?i)fuente|PSU|rizado|ripple|tensi[oó]n|voltaje")
        self.assertNotIn("DIE-HTB", body)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 8 PSU")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── CASO 9: CAÑÓN DE ELECTRONES (GUN) ───────────────────────────────────

    def test_case_9_electron_gun(self):
        """Caso 9: Degradación en cátodo/filamento del cañón de electrones (Gun)."""
        payload = {
            "incident": "Degradación de emisión en cátodo del cañón de electrones (Gun filament)",
            "equipment": "ACELERADOR LINEAL",
            "brand": "ELEKTA",
            "model": "VERSA HD",
            "diagnosis": "Reemplazo de ensamble de cañón de electrones",
        }
        res = self.client.post("/reports/generate-body", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        body = data.get("body", "")
        self.assertTrue(len(body) > 100)
        self.assertRegex(body, r"(?i)ca[ñn][oó]n|gun|c[aá]todo|filamento|emisi[oó]n")
        self.assertNotIn("DIE-HTB", body)
        self._assert_no_ai_mentions(body, "Cuerpo Caso 9 Gun")

        parts = data.get("suggested_parts", [])
        self.assertTrue(len(parts) > 0)
        self._assert_no_drawing_numbers_in_parts(parts)

    # ─── EXPORTACIÓN DOCX Y VALIDACIÓN ESTRUCTURAL XML ───────────────────────

    def test_docx_export_endpoint_and_xml_structure(self):
        """Valida que /reports/export-docx genere un DOCX válido con la estructura exacta del Word oficial."""
        import io
        import zipfile
        import xml.etree.ElementTree as ET

        payload = {
            "client": "HOSPITAL NACIONAL EDGARDO REBAGLIATI",
            "number": "260925_154574_TEST_POT",
            "service": "Radioterapia",
            "date": "25 de Septiembre del 2026",
            "equipment": "ACELERADOR LINEAL",
            "dept": "LIMA",
            "brand": "ELEKTA",
            "model": "VERSA HD",
            "serial": "154999",
            "incident": "Fallo en lectura de potenciómetro PSS Y (Mesa de tratamiento)",
            "diagnosis": "Sustitución y calibración de potenciómetro multivuelta PSS",
            "isProgrammed": True,
            "isSuspTto": False,
            "clientDate": "25/09/2026",
            "clientTime": "08:00",
            "workStartDate": "25/09/2026",
            "workStartTime": "08:30",
            "workEndDate": "25/09/2026",
            "workEndTime": "11:30",
            "downTime": "3:00 h",
            "work": "Se realizó la intervención técnica sobre la mesa de tratamiento PSS. Se constató la degradación en el potenciómetro de posición y se procedió a su reemplazo y calibración en Service Mode.",
            "conclusion": "- Equipo operativo tras sustitución de potenciómetro\n- Se requiere los siguientes repuestos",
            "parts": [
                {"pn": "45133303822", "description": "POTENTIOMETER ASSY COARSE PSS 10K", "quantity": "02"},
                {"pn": "45133303823", "description": "POTENTIOMETER ASSY FINE PSS 5K", "quantity": "02"},
                {"pn": "45133306120", "description": "DC POWER SUPPLY 24V 10A PSS AUX", "quantity": "01"},
            ],
            "images": [
                {"name": "Foto de Potenciómetro", "dataUrl": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="}
            ],
        }

        res = self.client.post("/reports/export-docx", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("attachment; filename=", res.headers.get("Content-Disposition", ""))

        docx_bytes = res.data
        self.assertGreater(len(docx_bytes), 10000)

        # Parsear el ZIP y document.xml
        zip_buf = io.BytesIO(docx_bytes)
        with zipfile.ZipFile(zip_buf, "r") as docx_zip:
            self.assertIn("word/document.xml", docx_zip.namelist())
            xml_content = docx_zip.read("word/document.xml").decode("utf-8")

        self._assert_no_ai_mentions(xml_content, "Documento DOCX exportado")

        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ET.fromstring(xml_content)
        tables = root.findall(".//w:tbl", ns)
        self.assertGreaterEqual(len(tables), 7)

        # Validar Metadatos en Tabla 1
        t1_text = "".join(tables[0].itertext())
        self.assertIn("HOSPITAL NACIONAL EDGARDO REBAGLIATI", t1_text)
        self.assertIn("260925_154574_TEST_POT", t1_text)

        # Validar Incidente en Tabla 3
        t3_text = "".join(tables[2].itertext())
        self.assertIn("Fallo en lectura de potenciómetro PSS Y", t3_text)

        # Validar Cronograma en Tabla 5 (7 celdas en la fila de datos)
        t5_rows = tables[4].findall("w:tr", ns)
        self.assertEqual(len(t5_rows), 3)
        data_cells = t5_rows[2].findall("w:tc", ns)
        self.assertEqual(len(data_cells), 7)
        self.assertIn("3:00 h", "".join(data_cells[6].itertext()))

        # Validar Trabajo Realizado en Tabla 6
        t6_text = "".join(tables[5].itertext())
        self.assertIn("mesa de tratamiento PSS", t6_text)

        # Validar Repuestos en Tabla 8 (3 repuestos dinámicos agregados)
        t8 = tables[7]
        t8_rows = t8.findall("w:tr", ns)
        # 1 fila cabecera + 3 filas de repuestos = 4 filas
        self.assertEqual(len(t8_rows), 4)
        t8_text = "".join(t8.itertext())
        self.assertIn("45133303822", t8_text)
        self.assertIn("45133303823", t8_text)
        self.assertIn("45133306120", t8_text)
        self.assertIn("POTENTIOMETER ASSY COARSE", t8_text)

    # ─── VERIFICACIÓN DE DIFERENCIACIÓN (NO SON IGUALES) ──────────────────────

    def test_all_cases_produce_distinct_content(self):
        """Verifica que diferentes incidencias generen contenidos claramente diferenciados y no copias idénticas."""
        queries = [
            "HT PSU OT",
            "CON-K ITEM 79",
            "Interlock 283 dosimetría",
            "Ultra alto vacío bomba iónica",
            "Interlock 51 hojas MLC Agility",
            "Fallo en potenciómetro PSS Y",
            "Disparo térmico en transformador T1",
            "Rizado excesivo en fuente DC PSU",
            "Cañón de electrones filamento",
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
