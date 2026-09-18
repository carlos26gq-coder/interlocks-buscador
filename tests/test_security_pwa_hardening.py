import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestSecurityPwaHardening(unittest.TestCase):
    def test_notes_migration_enables_rls_and_denies_direct_clients(self):
        sql = (ROOT / "supabase/migrations/001_notes_rls.sql").read_text(encoding="utf-8")
        self.assertIn("enable row level security", sql.lower())
        self.assertIn("force row level security", sql.lower())
        self.assertIn("using (false)", sql.lower())
        self.assertIn("grant all on table public.notes to service_role", sql.lower())

    def test_api_has_shared_limits_cache_and_pagination(self):
        api = (ROOT / "scripts/api.py").read_text(encoding="utf-8")
        self.assertIn("RATELIMIT_STORAGE_URI", api)
        self.assertIn("NOTES_CACHE_REDIS_URL", api)
        self.assertIn('request.args.get("page")', api)
        self.assertIn('@limiter.limit("30 per minute")', api)
        self.assertIn("Cada elemento de 'notes' debe ser un objeto JSON", api)

    def test_service_worker_loads_search_chunks_on_demand(self):
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertNotIn("cacheOfflineManuals", sw)
        self.assertIn("fetchWithTimeout", sw)
        self.assertIn("explicitDownload", sw)
        self.assertIn("arrayBuffer()", sw)

    def test_pdf_loading_task_is_cancelled_before_new_document(self):
        app = (ROOT / "scripts/static/app.js").read_text(encoding="utf-8")
        self.assertIn("window._pdfLoadingTask.destroy()", app)
        self.assertIn("window._pdfLoadSequence", app)
        self.assertIn("15000", app)

    def test_manifest_allows_landscape_and_ui_has_live_sync_status(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["orientation"], "any")
        html = (ROOT / "scripts/templates/index.html").read_text(encoding="utf-8")
        self.assertIn('id="notesSyncStatus"', html)
        self.assertIn('data-action="cargar-mas-notas"', html)
        self.assertIn('aria-label="Buscar en manuales"', html)


if __name__ == "__main__":
    unittest.main()
