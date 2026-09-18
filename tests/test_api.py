"""Pruebas unitarias y de integración para los endpoints REST de SOLVI (api.py)."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api import app, search_engine


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_root_and_security_headers(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertGreater(data.get("pages", 0), 0)
        self.assertGreater(data.get("manuals", 0), 0)

    def test_version_endpoint(self):
        res = self.client.get("/version")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("build", data)

    def test_search_endpoint_empty_query(self):
        res = self.client.get("/search?q=")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["results"], [])

    def test_search_endpoint_with_query(self):
        res = self.client.get("/search?q=item+409&limit=5")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreater(data["total"], 0)
        self.assertLessEqual(len(data["results"]), 5)

    def test_search_endpoint_rejects_long_query(self):
        res = self.client.get(f"/search?q={'a' * 205}")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("error", data)

    def test_diagnose_endpoint_with_symptoms_list(self):
        res = self.client.post("/diagnose", json={"symptoms": ["dose rate mon", "ITEM 327"]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("results", data)
        self.assertGreater(len(data["results"]), 0)

    def test_diagnose_endpoint_legacy_format(self):
        res = self.client.post("/diagnose", json={
            "interlock": "283",
            "error": "66",
            "message": "motor timeout",
            "observations": ""
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("results", data)

    def test_diagnose_graph_endpoint_success(self):
        res = self.client.post("/diagnose/graph", json={"symptoms": ["ITEM 409", "ITEM 332"]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("found"))
        self.assertIn("pcbs", data)

    def test_diagnose_graph_endpoint_empty_symptoms_returns_400(self):
        res = self.client.post("/diagnose/graph", json={"symptoms": []})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("found"))

    def test_diagnose_ai_endpoint_without_key_returns_400(self):
        res = self.client.post("/diagnose/ai", json={"symptoms": ["falla de gantry"]})
        # Sin key debe devolver 400 con error invalid_api_key o no_api_key
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("ok"))

    @patch("api.analyze_with_gemini")
    def test_diagnose_ai_endpoint_success(self, mock_analyze):
        mock_analyze.return_value = {
            "ok": True,
            "data": {
                "root_cause": "Falla en PCB 16V",
                "confidence": "alta",
                "explanation": "Detalle técnico",
                "associated_boards": ["PCB 16V"],
                "cables_and_connectors": [],
                "test_points_and_signals": [],
                "manual_references": ["diagrams"],
                "action_steps": ["Verificar fusibles"],
                "safety_warning": ""
            }
        }
        res = self.client.post("/diagnose/ai", json={"symptoms": ["ITEM 409"], "api_key": "fake-key"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["root_cause"], "Falla en PCB 16V")

    def test_notes_endpoint(self):
        res = self.client.get("/notes")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.get_json(), list)

    def test_same_note_content_none_text(self):
        from api import _same_note_content
        existing = {"title": "A", "text": None, "tags": ["b"]}
        submitted = {"title": "A", "text": "", "tags": ["b"]}
        self.assertTrue(_same_note_content(existing, submitted))

    def test_same_note_content_tags_order(self):
        from api import _same_note_content
        existing = {"title": "A", "text": "B", "tags": ["a", "b"]}
        submitted = {"title": "A", "text": "B", "tags": ["b", "a"]}
        self.assertTrue(_same_note_content(existing, submitted))

    def test_procfile_has_bind_flag(self):
        procfile_path = ROOT / "Procfile"
        with procfile_path.open("r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("--bind 0.0.0.0:$PORT", content)


if __name__ == "__main__":
    unittest.main()
