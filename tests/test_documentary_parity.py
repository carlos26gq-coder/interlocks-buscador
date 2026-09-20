import unittest
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent

class TestDocumentaryParity(unittest.TestCase):
    def _catalog(self):
        with open(ROOT / "data" / "search" / "catalog.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def test_catalog_declares_indexed_and_physical_pages(self):
        catalog = self._catalog()
        self.assertEqual(catalog["documents"], 6322)
        for manual in catalog["manuals"]:
            self.assertIn("physical_pages", manual)
            self.assertGreaterEqual(manual["physical_pages"], manual["pages"])

    def test_traceability_matrix_contains_required_claims(self):
        with open(ROOT / "data" / "documentary_traceability.json", "r", encoding="utf-8") as f:
            matrix = json.load(f)
        entries = {entry["id"]: entry for entry in matrix["entries"]}
        for claim_id in ("TP100", "PCB_PPG", "ITEM_456", "ITEM_506"):
            self.assertIn(claim_id, entries)
            self.assertTrue(entries[claim_id].get("extract"))
            self.assertIn(entries[claim_id]["status"], {"verified_text", "verified_voltage_not_label"})

    def test_documented_signal_paths_reference_valid_manuals_and_claims(self):
        """El visor publica solo citas que existen en la matriz verificable."""
        catalog_path = ROOT / "data" / "search" / "catalog.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        manual_pages = {m["name"]: m["pages"] for m in catalog["manuals"]}
        with open(ROOT / "data" / "documentary_traceability.json", "r", encoding="utf-8") as f:
            evidence = {entry["id"]: entry for entry in json.load(f)["entries"]}
        with open(ROOT / "data" / "verified_signal_paths.json", "r", encoding="utf-8") as f:
            paths = json.load(f)["catalog"]

        for record in paths:
            refs = [step["citation_id"] for step in record.get("steps", [])]
            refs += [effect["citation_id"] for effect in record.get("failure_effects", [])]
            refs += [check["citation_id"] for check in record.get("checks", [])]
            refs += [fact["citation_id"] for fact in record.get("facts", [])]
            for ref in refs:
                entry = evidence[ref]
                self.assertIn(entry["manual"], manual_pages)
                self.assertLessEqual(entry["physical_page"], manual_pages[entry["manual"]])
                self.assertEqual(entry["status"], "verified_text")
                
    def test_published_measurements_reference_verified_evidence(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        with open(ROOT / "data" / "verified_measurement_catalog.json", "r", encoding="utf-8") as f:
            measurements = json.load(f)["catalog"]
        with open(ROOT / "data" / "documentary_traceability.json", "r", encoding="utf-8") as f:
            evidence = {entry["id"]: entry for entry in json.load(f)["entries"]}
        for measurement in measurements:
            self.assertEqual(measurement["evaluation_policy"], "reference_only")
            for citation in measurement["citations"]:
                self.assertEqual(evidence[citation]["status"], "verified_text")

if __name__ == "__main__":
    unittest.main()
