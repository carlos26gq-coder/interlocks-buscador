import unittest
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent

class TestDocumentaryParity(unittest.TestCase):
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
