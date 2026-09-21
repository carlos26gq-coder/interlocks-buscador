import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class TestDocumentaryParity(unittest.TestCase):
    def test_catalog_declares_indexed_and_physical_pages(self):
        catalog = json.loads((ROOT / "data" / "search" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["documents"], 6322)
        self.assertTrue(all(m["physical_pages"] >= m["pages"] for m in catalog["manuals"]))

    def test_traceability_entries_have_extracts(self):
        matrix = json.loads((ROOT / "data" / "documentary_traceability.json").read_text(encoding="utf-8"))
        self.assertTrue(matrix["entries"])
        published = [entry for entry in matrix["entries"] if entry.get("status", "").startswith("verified")]
        self.assertTrue(published)
        self.assertTrue(all(entry.get("extract") for entry in published))
