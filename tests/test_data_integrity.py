import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class DataIntegrityTests(unittest.TestCase):
    def test_master_data_and_offline_catalog_match(self):
        master = json.loads((ROOT / "data" / "all_manuals.json").read_text(encoding="utf-8"))
        catalog = json.loads((ROOT / "data" / "search" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(master), catalog["documents"])

        compact_records = []
        for entry in catalog["manuals"]:
            path = ROOT / entry["file"].lstrip("/")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(entry["name"], payload["manual"])
            self.assertEqual(entry["pages"], len(payload["documents"]))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            self.assertIn(digest, path.name)
            compact_records.extend(
                {"manual": payload["manual"], "page": row[0], "text": row[1]}
                for row in payload["documents"]
            )
        self.assertEqual(master, compact_records)

    def test_records_are_complete_and_unique(self):
        master = json.loads((ROOT / "data" / "all_manuals.json").read_text(encoding="utf-8"))
        keys = set()
        for record in master:
            self.assertTrue({"manual", "page", "text"}.issubset(record))
            self.assertTrue(record["manual"])
            self.assertTrue(record["text"])
            key = (record["manual"], record["page"])
            self.assertNotIn(key, keys)
            keys.add(key)


if __name__ == "__main__":
    unittest.main()
