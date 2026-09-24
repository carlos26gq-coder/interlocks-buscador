"""SOLVI - Pruebas de Diagnóstico Relacional de Síntomas (Máximo 5 y Razonamiento de Relación vs Independencia).

Valida:
1. Límite estricto de máximo 5 síntomas (1..5 permitidos, 6 o más rechazados con HTTP 400 Bad Request).
2. Razonamiento riguroso de si los síntomas están técnicamente relacionados o desacoplados.
3. Síntomas relacionados: convergencia causal física/eléctrica demostrada en los 19 manuales.
4. Síntomas desacoplados: reconocimiento explícito de fallas independientes sin forzar correlaciones rebuscadas,
   investigando cada síntoma rigurosamente y generando 5 hallazgos continuos estructurados.
5. Regla estricta de CERO menciones visibles de IA/AI.
"""

from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ai_service import (
    generate_local_failover_diagnosis,
    _classify_symptom_domain,
    _get_domain_summary,
    _get_domain_findings,
    SUBSYSTEM_DOMAIN_NAMES,
)
from search_engine import SearchEngine
import api


class RelationalSymptomsSuite(unittest.TestCase):
    """Pruebas unitarias y de integración para diagnóstico relacional de hasta 5 síntomas."""

    @classmethod
    def setUpClass(cls):
        api.app.config["TESTING"] = True
        api.app.config["RATELIMIT_ENABLED"] = False
        cls.client = api.app.test_client()

    # ─── 1. LÍMITE ESTRICTO DE MÁXIMO 5 SÍNTOMAS (HTTP 400 SI > 5) ───────────

    def test_diagnose_endpoint_accepts_1_to_5_symptoms(self):
        """El endpoint /diagnose acepta peticiones válidas con 1, 2, 3, 4 y 5 síntomas."""
        symptom_lists = [
            ["ITEM 79"],
            ["ITEM 79", "CON-K"],
            ["ITEM 79", "CON-K", "ITEM 74"],
            ["ITEM 79", "CON-K", "ITEM 74", "FS73A"],
            ["ITEM 79", "CON-K", "ITEM 74", "FS73A", "CB9"],
        ]
        for sym_list in symptom_lists:
            with self.subTest(count=len(sym_list)):
                res = self.client.post("/diagnose", json={"symptoms": sym_list})
                self.assertEqual(res.status_code, 200, f"Error para {len(sym_list)} síntomas: {res.get_json()}")
                data = res.get_json()
                self.assertIn("results", data)

    def test_diagnose_endpoint_rejects_more_than_5_symptoms_with_400(self):
        """El endpoint /diagnose rechaza 6 o más síntomas con HTTP 400 Bad Request y mensaje claro."""
        six_symptoms = ["S1", "S2", "S3", "S4", "S5", "S6"]
        res = self.client.post("/diagnose", json={"symptoms": six_symptoms})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok", True))
        self.assertIn("máximo 5", data.get("message", "").lower())

        eight_symptoms = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
        res8 = self.client.post("/diagnose", json={"symptoms": eight_symptoms})
        self.assertEqual(res8.status_code, 400)

    def test_diagnose_ai_endpoint_rejects_more_than_5_symptoms_with_400(self):
        """El endpoint /diagnose/ai rechaza más de 5 síntomas con HTTP 400 Bad Request."""
        six_symptoms = ["ITEM 79", "CON-K", "ITEM 74", "FS73A", "CB9", "T1"]
        res = self.client.post("/diagnose/ai", json={"symptoms": six_symptoms, "api_key": "dummy"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok", True))
        self.assertIn("máximo 5", data.get("message", "").lower())

    # ─── 2. RAZONAMIENTO: SÍNTOMAS RELACIONADOS CONVERGENTES ─────────────────

    def test_related_symptoms_con_k_and_item_79_converge_in_power_subsystem(self):
        """Síntomas relacionados (ITEM 79 y CON-K) convergen en la secuencia de potencia y contactores."""
        docs = [
            {"manual": "diagrams", "page": 63, "text": "ITEM 79 HT CON K DIE-ICA PCB 72H IRC-A PCB 74A IRC-B PCB 74B ROC-ICA."},
            {"manual": "power_supplies", "page": 73, "text": "i79 CON-K contactor sequence and soft start interlocks."},
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 79", "CON-K"], engine)

        # 1. Metadatos de relación: is_related es True
        meta = failover.get("_diagnostic_meta", {})
        self.assertTrue(meta.get("is_related", False))

        # 2. Causa raíz unificada
        self.assertIn("CON-K", failover["root_cause"])
        self.assertIn("ITEM 79", failover["root_cause"])

        # 3. Subsistema unificado
        self.assertIn("Alta Tensión", failover["subsystem"])

        # 4. Explicación causal conectando la bobina, los contactos 13/14 y DIE-ICA
        exp = failover["explanation"]
        self.assertIn("CON-K", exp)
        self.assertIn("DIE-ICA", exp)
        self.assertIn("arranque suave", exp.lower())

        # 5. Genera 5 diagnósticos estructurados continuos
        findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
        self.assertEqual(len(findings), 5)

    def test_related_symptoms_dosimetry_channel_and_reset(self):
        """Múltiples síntomas de dosimetría (d1 force, item 475, die-rha) demuestran correlación causal."""
        docs = [
            {"manual": "dosimetry", "page": 69, "text": "ITEM 475 D1 FORCE TERM DIE-RHA watchdog interlock."},
            {"manual": "diagrams", "page": 211, "text": "DIE-RHA PCB 12D ITEM 475 D1 FORCE ITEM 471 D1 RESET."},
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["d1 force", "item 475", "DIE-RHA"], engine)

        meta = failover.get("_diagnostic_meta", {})
        self.assertTrue(meta.get("is_related", False))
        self.assertIn("Dosimetría", failover["subsystem"])
        findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
        self.assertEqual(len(findings), 5)

    # ─── 3. RAZONAMIENTO: SÍNTOMAS NO RELACIONADOS (DESACOPLADOS) ───────────

    def test_unrelated_symptoms_table_pss_and_gun_filament_not_forced(self):
        """Síntomas de subsistemas desacoplados (mesa PSS vs filamento del cañón) NO deben forzar correlación ficticia."""
        docs = [
            {"manual": "movement", "page": 40, "text": "Table PSS potentiometer alignment and calibration in Service Mode."},
            {"manual": "vacuum", "page": 25, "text": "Electron gun filament current and emission under high vacuum."},
        ]
        engine = SearchEngine(docs)
        symptoms = ["potenciómetro de mesa PSS", "filamento del cañón de electrones"]
        failover = generate_local_failover_diagnosis(symptoms, engine)

        # 1. Metadatos de relación: is_related es False
        meta = failover.get("_diagnostic_meta", {})
        self.assertFalse(meta.get("is_related", True))

        # 2. Causa raíz declara abiertamente anomalías independientes
        root = failover["root_cause"].lower()
        self.assertTrue(any(w in root for w in ["independientes", "desacoplados", "sin correlación"]))
        self.assertIn("potenciómetro de mesa pss", root)
        self.assertIn("filamento del cañón de electrones", root)

        # 3. Explicación investiga ambos subsistemas sin inventar conexiones artificiales
        exp = failover["explanation"]
        self.assertTrue(any(w in exp.lower() for w in ["desacoplados", "independientes"]))
        self.assertIn("mesa", exp.lower())
        self.assertIn("cañón", exp.lower())

        # 4. Subsistemas reflejan ambos dominios
        sub = failover["subsystem"]
        self.assertIn("Movimiento", sub)
        self.assertIn("Vacío", sub)

        # 5. Genera exactamente 5 diagnósticos continuos (distribuidos entre mesa y filamento)
        findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
        self.assertEqual(len(findings), 5)
        for idx, f in enumerate(findings):
            self.assertTrue(len(f["title"]) > 10, f"Título muy corto en #{idx+1}")
            self.assertTrue(len(f["cause_mechanism"]) > 40, f"Causa muy corta en #{idx+1}")
            self.assertTrue(len(f["solution_procedure"]) > 40, f"Solución muy corta en #{idx+1}")
            self.assertNotIn(".pdf", f["cause_mechanism"])
            self.assertFalse(any(p in f["title"].lower() for p in ["probabilidad", "prioridad"]))

    def test_unrelated_symptoms_3_and_4_and_5_domains(self):
        """Verifica desacoplamiento correcto con 3, 4 y 5 síntomas independientes."""
        docs = [
            {"manual": "movement", "page": 10, "text": "Table PSS potentiometer and motor driver on PCB 16N."},
            {"manual": "vacuum", "page": 12, "text": "Electron gun filament current and ion pump trip at 10^-5 Torr."},
            {"manual": "dosimetry", "page": 14, "text": "Dose rate chamber bias voltage check and ionisation chamber."},
            {"manual": "communications", "page": 16, "text": "CAN bus timeout and termination resistance 60 ohm."},
            {"manual": "power_supplies", "page": 18, "text": "Contactor CON-A coil supply from T1."},
        ]
        engine = SearchEngine(docs)

        # Caso 3 síntomas desacoplados
        syms_3 = ["potenciómetro de mesa PSS", "filamento del cañón", "tasa de dosis cámara de ionización"]
        diag_3 = generate_local_failover_diagnosis(syms_3, engine)
        self.assertFalse(diag_3["_diagnostic_meta"]["is_related"])
        findings_3 = diag_3.get("diagnostic_findings", [])
        self.assertEqual(len(findings_3), 5)

        # Caso 4 síntomas desacoplados
        syms_4 = ["potenciómetro de mesa PSS", "filamento del cañón", "tasa de dosis cámara de ionización", "can bus timeout"]
        diag_4 = generate_local_failover_diagnosis(syms_4, engine)
        self.assertFalse(diag_4["_diagnostic_meta"]["is_related"])
        findings_4 = diag_4.get("diagnostic_findings", [])
        self.assertEqual(len(findings_4), 5)

        # Caso 5 síntomas desacoplados
        syms_5 = ["potenciómetro de mesa PSS", "filamento del cañón", "tasa de dosis cámara de ionización", "can bus timeout", "contactor CON-A"]
        diag_5 = generate_local_failover_diagnosis(syms_5, engine)
        self.assertFalse(diag_5["_diagnostic_meta"]["is_related"])
        findings_5 = diag_5.get("diagnostic_findings", [])
        self.assertEqual(len(findings_5), 5)

    # ─── 4. REGLA ESTRICTA DE CERO IA / AI ───────────────────────────────────

    def test_strict_zero_visible_ai_in_generated_diagnoses(self):
        """Garantiza que ningún diagnóstico contenga palabras visibles de IA/AI."""
        docs = [
            {"manual": "diagrams", "page": 63, "text": "CON-K ITEM 79 contactor soft start sequence."},
            {"manual": "movement", "page": 10, "text": "Table PSS motor encoder and potentiometer."},
        ]
        engine = SearchEngine(docs)

        for case in [
            ["ITEM 79", "CON-K"],
            ["potenciómetro de mesa PSS", "filamento del cañón de electrones"],
            ["d1 force"],
        ]:
            diag = generate_local_failover_diagnosis(case, engine)
            serialized = str(diag).lower()
            self.assertNotIn("inteligencia artificial", serialized)
            self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    # ─── 5. VERIFICACIÓN DE INTERFAZ FRONTEND (HTML / JS) ───────────────────

    def test_frontend_files_max_5_symptoms_and_zero_ai(self):
        """Verifica que index.html y app.js reflejen el límite de 5 síntomas y no expongan IA."""
        index_html = (ROOT / "scripts" / "templates" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "scripts" / "static" / "app.js").read_text(encoding="utf-8")

        # 1. index.html debe mostrar Máx. 5 síntomas y no Máx. 8 síntomas
        self.assertIn("Máx. 5 síntomas", index_html)
        self.assertNotIn("Máx. 8 síntomas", index_html)

        # 2. app.js debe tener SYMPTOM_NUMS con 5 elementos
        self.assertIn('const SYMPTOM_NUMS = ["①","②","③","④","⑤"];', app_js)

        # 3. app.js debe restringir agregarSintoma a 5
        self.assertIn("rows.length >= 5", app_js)
        self.assertIn('toast("Máximo 5 síntomas", "err")', app_js)

        # 4. Zero visible AI en HTML
        self.assertNotIn("inteligencia artificial", index_html.lower())
        self.assertFalse(bool(re.search(r">\s*(?:ia|ai|inteligencia artificial)\s*<", index_html, re.I)))


if __name__ == "__main__":
    unittest.main()
