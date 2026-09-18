"""SOLVI - Pruebas Unitarias y de Integración de Endpoints REST de la API Flask."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import api as api_module
from api import MAX_QUERY_LENGTH, app
from postgrest.exceptions import APIError


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeNotesQuery:
    def __init__(self, backend):
        self.backend = backend
        self.operation = None
        self.payload = None
        self.note_id = None

    def insert(self, payload):
        self.operation = "insert"
        self.payload = deepcopy(payload)
        return self

    def select(self, _columns):
        self.operation = "select"
        return self

    def eq(self, column, value):
        if column == "id":
            self.note_id = value
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self.operation == "insert":
            if self.backend.unexpected_insert_error:
                raise RuntimeError("fallo inesperado simulado")
            note_id = self.payload["id"]
            if note_id in self.backend.rows:
                raise APIError({"code": "23505", "message": "duplicate key"})
            self.backend.rows[note_id] = deepcopy(self.payload)
            return _FakeResponse([deepcopy(self.payload)])

        if self.operation == "select":
            if self.backend.lookup_error:
                raise APIError({"code": "08006", "message": "lookup unavailable"})
            row = self.backend.rows.get(self.note_id)
            return _FakeResponse([deepcopy(row)] if row else [])

        raise AssertionError(f"Operación no soportada en fake: {self.operation}")


class _FakeSupabase:
    def __init__(self, *, lookup_error=False, unexpected_insert_error=False):
        self.rows = {}
        self.lookup_error = lookup_error
        self.unexpected_insert_error = unexpected_insert_error

    def table(self, name):
        if name != "notes":
            raise AssertionError(f"Tabla inesperada: {name}")
        return _FakeNotesQuery(self)


class ApiEndpointsSuite(unittest.TestCase):
    """Pruebas completas de rutas HTTP, esquemas de entrada/salida, seguridad y validaciones."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    # ─── 1. RUTAS BASE Y CABECERAS DE SEGURIDAD ──────────────────────────────

    def test_home_page_and_security_headers(self):
        """La raíz entrega index.html con todas las cabeceras de seguridad requeridas."""
        with self.client.get("/") as res:
            self.assertEqual(res.status_code, 200)
            self.assertIn(b"<!DOCTYPE html>", res.data)
            self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
            self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
            self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy", ""))
            self.assertIn("no-store", res.headers.get("Cache-Control", ""))

    def test_openapi_specification(self):
        """El endpoint /openapi.json retorna la especificación válida en OpenAPI 3.0."""
        with self.client.get("/openapi.json") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("openapi"), "3.0.3")
            self.assertIn("/search", data.get("paths", {}))
            self.assertIn("/diagnose/ai", data.get("paths", {}))

    def test_health_and_version(self):
        """Los endpoints de salud y versión responden con datos de páginas y manuales."""
        with self.client.get("/health") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertGreater(data.get("pages", 0), 6000)
            self.assertEqual(data.get("manuals"), 19)

        with self.client.get("/version") as res:
            self.assertEqual(res.status_code, 200)
            self.assertIn("build", res.get_json())

    def test_pwa_assets(self):
        """Los archivos del manifiesto y Service Worker se sirven con sus mimetypes respectivos."""
        with self.client.get("/manifest.json") as res_man:
            self.assertEqual(res_man.status_code, 200)
            self.assertIn("application/manifest+json", res_man.content_type)

        with self.client.get("/sw.js") as res_sw:
            self.assertEqual(res_sw.status_code, 200)
            self.assertIn("application/javascript", res_sw.content_type)

    # ─── 2. ENDPOINT DE BÚSQUEDA TÉCNICA ─────────────────────────────────────

    def test_search_valid_query_and_pagination(self):
        """Búsqueda con paginación correcta."""
        with self.client.get("/search?q=interlock+283&limit=5&offset=0") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("results", data)
            self.assertIn("total", data)
            self.assertLessEqual(len(data["results"]), 5)

    def test_search_empty_query_returns_empty_results(self):
        """Búsqueda sin parámetro 'q' devuelve lista vacía con status 200."""
        with self.client.get("/search") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["results"], [])
            self.assertEqual(data["total"], 0)

    def test_search_oversized_query_rejects_with_400(self):
        """Consultas que superan el límite de caracteres son rechazadas con error 400."""
        oversized = "a" * (MAX_QUERY_LENGTH + 10)
        with self.client.get(f"/search?q={oversized}") as res:
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertIn("error", data)

    # ─── 3. ENDPOINTS DE DIAGNÓSTICO Y TRAZA DE CIRCUITOS ────────────────────

    def test_diagnose_endpoint_with_symptoms_array(self):
        """Diagnóstico multi-síntoma devuelve relaciones técnicas documentadas."""
        payload = {"symptoms": ["dose rate mon", "ITEM 327"]}
        with self.client.post("/diagnose", json=payload) as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("results", data)
            self.assertGreater(len(data["results"]), 0)

    def test_diagnose_endpoint_with_legacy_fields(self):
        """Diagnóstico con campos clásicos mantiene compatibilidad."""
        payload = {"interlock": "283", "error": "66"}
        with self.client.post("/diagnose", json=payload) as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("results", data)

    def test_diagnose_graph_endpoint_includes_schematic_correlation(self):
        """El endpoint de traza topológica incluye la correlación con esquemas SVG interactivos."""
        payload = {"symptoms": ["ITEM 409", "ITEM 332"]}
        with self.client.post("/diagnose/graph", json=payload) as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("found"))
            self.assertIn("circuit_schematic", data)
            self.assertIn("subsystem_id", data["circuit_schematic"])
            self.assertIn("matched_nodes", data["circuit_schematic"])

    def test_diagnose_graph_empty_symptoms_rejects_with_400(self):
        """Llamar a traza de grafo sin síntomas genera error 400 de validación."""
        with self.client.post("/diagnose/graph", json={"symptoms": []}) as res:
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertEqual(data.get("error"), "validation_error")

    # ─── 4. ENDPOINTS DEL VISUALIZADOR DE ESQUEMAS SVG ───────────────────────

    def test_circuits_subsystems_list(self):
        """El endpoint /circuits/subsystems devuelve los 5 subsistemas de ingeniería."""
        with self.client.get("/circuits/subsystems") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(len(data.get("subsystems", [])), 5)

    def test_circuit_subsystem_detail_and_404(self):
        """Detalle de subsistema válido devuelve datos; ID inexistente devuelve 404."""
        with self.client.get("/circuits/safety_loop") as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data["subsystem"]["id"], "safety_loop")

        with self.client.get("/circuits/subsistema_falso_xyz") as res_404:
            self.assertEqual(res_404.status_code, 404)
            data_404 = res_404.get_json()
            self.assertFalse(data_404.get("ok"))

    def test_circuits_match_endpoint(self):
        """El endpoint /circuits/match procesa componentes y determina el subsistema óptimo."""
        payload = {"components": ["DOOR_SW_283", "ESTOP_CONSOLE"]}
        with self.client.post("/circuits/match", json=payload) as res:
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("subsystem_id"), "safety_loop")

    # ─── 5. SEGURIDAD Y CONTROL DE ACCESO ADMINISTRATIVO ─────────────────────

    def test_admin_endpoints_require_authentication(self):
        """Rutas administrativas rechazan peticiones sin la cabecera X-Admin-Password."""
        with self.client.get("/admin/manuals") as res:
            self.assertIn(res.status_code, [403, 503])

        with self.client.get("/admin/config") as res:
            self.assertIn(res.status_code, [403, 503])

    # ─── 6. IDEMPOTENCIA Y NO SOBRESCRITURA DE APUNTES ──────────────────────

    def test_notes_post_create_and_identical_retry_are_idempotent(self):
        """Una creación retorna 201 y el mismo reintento retorna 200 sin duplicar."""
        backend = _FakeSupabase()
        payload = {
            "id": "11111111-1111-4111-8111-111111111111",
            "title": "Falla de dosis",
            "text": "Verificar PCB 12D",
            "tags": ["dose", "pcb"],
        }

        with patch.object(api_module, "supabase", backend):
            created = self.client.post("/notes", json=payload)
            retried = self.client.post("/notes", json=payload)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.get_json(), payload)
        self.assertEqual(len(backend.rows), 1)

    def test_notes_post_rejects_uuid_conflict_without_overwrite(self):
        """Un UUID existente con contenido distinto retorna 409 y conserva el original."""
        backend = _FakeSupabase()
        note_id = "22222222-2222-4222-8222-222222222222"
        original = {
            "id": note_id,
            "title": "Original",
            "text": "Contenido original",
            "tags": ["seguro"],
        }
        conflicting = {
            "id": note_id,
            "title": "Intento de reemplazo",
            "text": "Contenido alterado",
            "tags": ["cambio"],
        }

        with patch.object(api_module, "supabase", backend):
            created = self.client.post("/notes", json=original)
            conflict = self.client.post("/notes", json=conflicting)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()["error"], "note_id_conflict")
        self.assertEqual(backend.rows[note_id], original)

    def test_notes_post_double_backend_failure_returns_controlled_json(self):
        """Si inserción y consulta fallan, el endpoint conserva su contrato JSON 502."""
        backend = _FakeSupabase(lookup_error=True)
        payload = {
            "id": "33333333-3333-4333-8333-333333333333",
            "title": "Reintento",
            "text": "Sin persistir",
            "tags": [],
        }
        backend.rows[payload["id"]] = deepcopy(payload)

        with patch.object(api_module, "supabase", backend):
            response = self.client.post("/notes", json=payload)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.content_type, "application/json")
        self.assertIn("error", response.get_json())

    def test_notes_post_unexpected_backend_failure_returns_controlled_json(self):
        """Una excepción inesperada no escapa como HTML ni expone detalles internos."""
        backend = _FakeSupabase(unexpected_insert_error=True)
        payload = {
            "id": "44444444-4444-4444-8444-444444444444",
            "title": "Error inesperado",
            "text": "",
            "tags": [],
        }

        with patch.object(api_module, "supabase", backend):
            response = self.client.post("/notes", json=payload)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.content_type, "application/json")
        self.assertNotIn("fallo inesperado simulado", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
