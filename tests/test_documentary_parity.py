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

    def test_circuit_nodes_manuals(self):
        # Validate that all nodes in circuit_data use valid manuals and pages
        sys.path.insert(0, str(ROOT / "scripts"))
        from circuit_data import SUBSYSTEMS
        
        catalog_path = ROOT / "data" / "search" / "catalog.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
            
        manual_pages = {m["name"]: m["pages"] for m in catalog["manuals"]}
        
        for sub_id, sub_data in SUBSYSTEMS.items():
            for node in sub_data["nodes"]:
                manual = node["manual"]
                self.assertIn(manual, manual_pages, f"El manual {manual} no existe en el catalogo.")
                self.assertLessEqual(node["page"], manual_pages[manual], f"La pagina {node['page']} excede el total de {manual}.")
                self.assertGreaterEqual(node["page"], 1)
                
    def test_multimeter_tps_manuals(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from multimeter_service import TEST_POINTS_CATALOG
        
        catalog_path = ROOT / "data" / "search" / "catalog.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
            
        manual_pages = {m["name"]: m["pages"] for m in catalog["manuals"]}
                
        for tp_id, tp_data in TEST_POINTS_CATALOG.items():
            manual = tp_data["manual"]
            self.assertIn(manual, manual_pages, f"El manual {manual} no existe en el catalogo.")
            self.assertLessEqual(tp_data["page"], manual_pages[manual])
            self.assertGreaterEqual(tp_data["page"], 1)

if __name__ == "__main__":
    unittest.main()
