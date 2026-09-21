"""Contrato de retirada de Esquemas y Multímetro."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from api import app


class RemovedModulesContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        cls.client = app.test_client()

    def test_retired_routes_are_not_published(self):
        for path in ("/diagnose/graph", "/circuits/subsystems", "/circuits/x", "/multimeter/test-points", "/multimeter/evaluate"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_openapi_and_shell_do_not_publish_retired_modules(self):
        paths = self.client.get("/openapi.json").get_json()["paths"]
        self.assertFalse(any(key.startswith(("/circuits", "/multimeter", "/diagnose/graph")) for key in paths))
        html = (ROOT / "scripts" / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('/static/circuit-visualizer.js', html)
        self.assertNotIn('/static/multimeter.js', html)

if __name__ == "__main__":
    unittest.main()
