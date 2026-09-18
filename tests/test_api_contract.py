"""Contrato HTTP verificable sin dependencias externas ni credenciales.

Estas pruebas ejercitan Flask con su cliente real: validan formas JSON,
errores de tipos, paginación y que las rutas administrativas no queden
abiertas por una configuración ausente.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from api import app  # noqa: E402


class ApiContractSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        cls.client = app.test_client()

    def test_openapi_and_health_contract(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json().get("ok"))

        spec = self.client.get("/openapi.json")
        self.assertEqual(spec.status_code, 200)
        body = spec.get_json()
        self.assertEqual(body.get("openapi"), "3.0.3")
        for path in ("/search", "/diagnose", "/diagnose/graph", "/notes", "/notes/batch"):
            self.assertIn(path, body["paths"])

    def test_search_and_notes_pagination_shapes(self):
        search = self.client.get("/search?q=interlock&page=1&limit=3")
        self.assertEqual(search.status_code, 200)
        self.assertIsInstance(search.get_json().get("results"), list)
        self.assertIn("has_more", search.get_json())

        notes = self.client.get("/notes?page=1&limit=3")
        self.assertEqual(notes.status_code, 200)
        data = notes.get_json()
        self.assertIsInstance(data, dict)
        self.assertIsInstance(data.get("notes"), list)
        self.assertIn("has_more", data)

    def test_strict_types_return_controlled_400(self):
        for path, payload in (
            ("/diagnose", {"symptoms": [283]}),
            ("/diagnose/graph", {"symptoms": [None]}),
            ("/circuits/match", {"components": [474]}),
            ("/multimeter/evaluate", {"test_point_id": 1, "measured_value": "24"}),
        ):
            response = self.client.post(path, json=payload)
            self.assertEqual(response.status_code, 400, path)
            self.assertIsInstance(response.get_json(), dict)

    def test_admin_routes_are_not_public(self):
        for path in ("/admin/config", "/admin/manuals"):
            self.assertIn(self.client.get(path).status_code, (401, 403, 503))


if __name__ == "__main__":
    unittest.main()
