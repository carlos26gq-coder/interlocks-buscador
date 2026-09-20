"""Contrato del explorador de rutas documentadas de SOLVI."""

from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api import app
from circuit_data import get_all_subsystems, get_subsystem, match_subsystem_for_trace


class CircuitVisualizerSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.catalog = json.loads((ROOT / "data" / "verified_signal_paths.json").read_text(encoding="utf-8"))
        matrix = json.loads((ROOT / "data" / "documentary_traceability.json").read_text(encoding="utf-8"))
        cls.evidence = {entry["id"]: entry for entry in matrix["entries"]}

    def test_every_published_claim_has_verified_evidence(self):
        """Una ruta visible no puede tener paso, efecto o comprobación sin cita verificable."""
        for record in self.catalog["catalog"]:
            self.assertEqual(record["status"], "verified_text")
            citation_ids = [step["citation_id"] for step in record.get("steps", [])]
            citation_ids += [effect["citation_id"] for effect in record.get("failure_effects", [])]
            citation_ids += [check["citation_id"] for check in record.get("checks", [])]
            citation_ids += [fact["citation_id"] for fact in record.get("facts", [])]
            self.assertTrue(citation_ids)
            for citation_id in citation_ids:
                evidence = self.evidence.get(citation_id)
                self.assertIsNotNone(evidence, f"Falta evidencia {citation_id}")
                self.assertEqual(evidence["status"], "verified_text")
                self.assertTrue(evidence.get("extract"))
                self.assertGreater(evidence.get("physical_page", 0), 0)

    def test_only_explicitly_documented_path_has_directional_steps(self):
        """Las referencias de hojas no se convierten artificialmente en cableado dirigido."""
        paths = [item for item in self.catalog["catalog"] if item["kind"] == "verified_functional_path"]
        references = [item for item in self.catalog["catalog"] if item["kind"] == "verified_document_reference"]
        self.assertEqual([item["id"] for item in paths], ["dosimetry_bias_320v"])
        self.assertGreaterEqual(len(paths[0]["steps"]), 3)
        self.assertTrue(references)
        self.assertTrue(all(not item.get("steps") for item in references))

    def test_unknown_terms_do_not_choose_an_arbitrary_diagram(self):
        match = match_subsystem_for_trace(["interlock 283", "cable", "falla"])
        self.assertIsNone(match["subsystem_id"])
        self.assertEqual(match["matched_nodes"], [])

    def test_matching_returns_only_documented_catalog_entries(self):
        match = match_subsystem_for_trace(["ion chamber", "i189", "-320 V"])
        self.assertEqual(match["subsystem_id"], "dosimetry_bias_320v")
        self.assertTrue(match["matches"])
        self.assertEqual(get_subsystem("dosimetry_bias_320v")["status"], "verified_text")
        self.assertEqual(len(get_all_subsystems()), len(self.catalog["catalog"]))

    def test_api_and_offline_catalog_are_available(self):
        with self.client.get("/data/verified_signal_paths.json") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["schema_version"], 1)
        with self.client.get("/circuits/subsystems") as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])
        with self.client.get("/circuits/dosimetry_bias_320v") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["subsystem"]["kind"], "verified_functional_path")

    def test_legacy_synthetic_asset_is_not_published(self):
        self.assertFalse((ROOT / "scripts" / "static" / "circuit_schematics.json").exists())
        visualizer = (ROOT / "scripts" / "static" / "circuit-visualizer.js").read_text(encoding="utf-8")
        self.assertIn('const CATALOG_URL = "/data/verified_signal_paths.json"', visualizer)
        self.assertNotIn("toggleNodeState", visualizer)


if __name__ == "__main__":
    unittest.main()
