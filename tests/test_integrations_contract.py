"""Contratos locales para Supabase, R2, Service Worker y Render.

No se simula una credencial de producción: la prueba garantiza que el
despliegue tiene los puntos de integración declarados y que secretos no se
versionan accidentalmente.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IntegrationsContractSuite(unittest.TestCase):
    def test_supabase_migration_enforces_service_role_boundary(self):
        sql = (ROOT / "supabase" / "migrations" / "001_notes_rls.sql").read_text(encoding="utf-8")
        for phrase in ("enable row level security", "force row level security", "service_role", "create policy"):
            self.assertIn(phrase, sql.lower())
        self.assertIn("revoke all on table public.notes from anon", sql.lower())

    def test_r2_is_public_base_url_not_a_client_secret(self):
        html = (ROOT / "scripts" / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("_INITIAL_R2_URL", html)
        self.assertNotRegex(html, r"(?i)(secret|access[_-]?key|api[_-]?key)\\s*[:=]")
        self.assertIn("R2_PUBLIC_URL", (ROOT / "render.yaml").read_text(encoding="utf-8"))

    def test_service_worker_uses_versioned_cache_and_explicit_pdf_download(self):
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertRegex(sw, r"const\s+CACHE\s*=\s*['\"]solvi-v\d+['\"]")
        self.assertIn("X-SOLVI-Offline-Download", sw)
        self.assertNotIn("_lastPdfBuffer", sw)

    def test_render_contract_and_pinned_runtime(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        for phrase in ("buildCommand: pip install -r requirements.txt", "healthCheckPath: /health", "gunicorn", "supabase/**"):
            self.assertIn(phrase, render)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(requirements, r"^Flask==", re.MULTILINE)
        self.assertTrue((ROOT / "requirements.lock").exists())
        self.assertEqual((ROOT / ".python-version").read_text(encoding="utf-8").strip(), "3.12")

    def test_catalog_and_traceability_are_valid_json(self):
        for rel in ("data/search/catalog.json", "data/documentary_traceability.json"):
            parsed = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            self.assertTrue(parsed)


if __name__ == "__main__":
    unittest.main()
