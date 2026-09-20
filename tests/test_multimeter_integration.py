"""Pruebas de contrato del registro de mediciones verificadas.

Estas pruebas protegen el límite de seguridad: una lectura es una referencia
documental, no una simulación eléctrica ni un dictamen de conformidad.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from api import app
from multimeter_service import evaluate_measurement, get_all_test_points, get_test_point


class VerifiedMeasurementSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        cls.client = app.test_client()
        cls.catalog = json.loads((ROOT / "data" / "verified_measurement_catalog.json").read_text(encoding="utf-8"))
        cls.traceability = json.loads((ROOT / "data" / "documentary_traceability.json").read_text(encoding="utf-8"))
        cls.sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        cls.js = (ROOT / "scripts" / "static" / "multimeter.js").read_text(encoding="utf-8")

    def test_each_published_measurement_has_verified_traceability(self):
        evidence = {entry["id"]: entry for entry in self.traceability["entries"]}
        self.assertGreater(len(self.catalog["catalog"]), 0)
        for record in self.catalog["catalog"]:
            self.assertEqual(record["evaluation_policy"], "reference_only")
            self.assertIsInstance(record["documented_reference_value"], (int, float))
            self.assertTrue(record["citations"])
            for citation in record["citations"]:
                self.assertIn(citation, evidence)
                self.assertEqual(evidence[citation]["status"], "verified_text")

    def test_only_explicit_aliases_resolve(self):
        record = get_test_point("TP100")
        self.assertEqual(record["id"], "DOSIMETRY_BIAS_AT_ION_CHAMBER")
        self.assertEqual(get_test_point("cámara de ionización")["id"], record["id"])
        self.assertIsNone(get_test_point("TP1"))
        self.assertIsNone(get_test_point("TP100 lectura inventada"))
        self.assertEqual(len(get_all_test_points()), 1)

    def test_evaluation_never_claims_pass_or_fail(self):
        result = evaluate_measurement("DOSIMETRY_BIAS_AT_ION_CHAMBER", -320.0, "V DC")
        self.assertEqual(result["status"], "REFERENCE_ONLY")
        self.assertFalse(result["is_pass_fail"])
        self.assertEqual(result["status_badge"], "SIN UMBRAL")
        self.assertNotIn("tolerance", result)
        self.assertAlmostEqual(result["delta_from_reference"], 0.0)

    def test_service_rejects_unknown_points_bad_units_and_nonfinite_values(self):
        for value in ("abc", float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                evaluate_measurement("DOSIMETRY_BIAS_AT_ION_CHAMBER", value)
        with self.assertRaises(ValueError):
            evaluate_measurement("TP1", 24.0)
        with self.assertRaises(ValueError):
            evaluate_measurement("DOSIMETRY_BIAS_AT_ION_CHAMBER", -320.0, "A")

    def test_http_contract_and_simulation_removal(self):
        records = self.client.get("/multimeter/test-points")
        self.assertEqual(records.status_code, 200)
        self.assertEqual(records.get_json()["test_points"][0]["id"], "DOSIMETRY_BIAS_AT_ION_CHAMBER")
        response = self.client.post("/multimeter/evaluate", json={"test_point_id": "TP100", "measured_value": -319.6, "unit": "V DC"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["evaluation"]["status"], "REFERENCE_ONLY")
        self.assertEqual(self.client.post("/multimeter/simulate", json={}).status_code, 404)

    def test_frontend_and_worker_use_the_single_catalog_without_simulation(self):
        self.assertIn("/data/verified_measurement_catalog.json", self.sw)
        self.assertNotIn("/static/multimeter_catalog.json", self.sw)
        self.assertIn("CATALOG_URL", self.js)
        self.assertIn("CircuitVisualizer.openFromTrace", self.js)
        self.assertNotIn("simulate", self.js.lower())
        self.assertIn("SIN UMBRAL PUBLICADO", self.js)


if __name__ == "__main__":
    unittest.main()
