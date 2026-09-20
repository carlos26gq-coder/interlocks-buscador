"""Flujos verificables del explorador documental y del multímetro simulado."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "scripts" / "static"


class TechnicalWorkflowSuite(unittest.TestCase):
    def setUp(self):
        self.visualizer = (STATIC_DIR / "circuit-visualizer.js").read_text(encoding="utf-8")
        self.catalog = json.loads((ROOT / "data" / "verified_signal_paths.json").read_text(encoding="utf-8"))

    def test_documented_catalog_is_loaded_for_offline_first_viewing(self):
        self.assertIn('const CATALOG_URL = "/data/verified_signal_paths.json"', self.visualizer)
        self.assertIn('const TRACEABILITY_URL = "/data/documentary_traceability.json"', self.visualizer)
        self.assertTrue(self.catalog["catalog"])

    def test_path_explains_direction_failure_and_documented_effect(self):
        path = next(item for item in self.catalog["catalog"] if item["id"] == "dosimetry_bias_320v")
        self.assertEqual([step["id"] for step in path["steps"]], ["rhca_area_12", "coaxial_cable", "ion_chamber"])
        self.assertTrue(path["failure_effects"])
        self.assertIn("No se mostrará un código inferido", path["error_code_policy"])

    def test_reference_sheet_is_not_a_fake_simulator(self):
        self.assertNotIn("toggleNodeState", self.visualizer)
        self.assertNotIn("simular abrir/cerrar", self.visualizer)
        self.assertIn("No se infieren señales", self.catalog["catalog"][2]["error_code_policy"])

    def test_trace_bridge_preserves_no_evidence_behavior(self):
        self.assertIn("openFromTrace", self.visualizer)
        self.assertIn("no se asumió una ruta física", self.visualizer)


if __name__ == "__main__":
    unittest.main()
