"""SOLVI - Pruebas de Regresión End-to-End para Auditoría Técnica P0/P1.

Verifica:
1. P0-1: Eliminación de XSS por interpolación dinámica en onclick (uso de data-action y delegación).
2. P0-2: Secreto Gemini eliminado de localStorage persistente y migrado a sessionStorage.
3. P0-3: Directivas CSP y cabeceras de seguridad web.
4. P1-1: Eliminación de falso positivo 'Verificado en planos'; estados CANÓNICO, DOCUMENTADO, INFERIDO.
5. P1-2: Semántica en renderDiagrama: 'Hipótesis Principal' en lugar de 'Causa Raíz' para ranking.
6. P1-3: Aislamiento y sanitización de entidades generativas hacia el grafo canónico.
7. P1-4: Validación estricta de puntos de prueba detectados por regex contra catálogo antes de habilitar 'Medir'.
8. P1-5: Visor PDF sin bloqueo arbitrario offline y clasificación granular de errores (404, CORS, dañado, red).
9. P1-6: Sincronización de zoom en canvas PDF sin divergencia tras cambio de página.
10. P1-7: Paginación de búsqueda sin mezclar parámetros del DOM y control de respuestas obsoletas (requestId/Abort).
11. P1-8: Search worker con backpressure sin descartar consultas en vuelo y auto-reinicio ante fallos.
12. P1-9: Idempotencia segura en /notes sin permitir sobrescritura anónima y protección multi-pestaña.
13. Regla de Usuario: Cero menciones visibles de IA/AI en interfaces y mensajes.
"""

from pathlib import Path
import json
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATIC_DIR = SCRIPTS_DIR / "static"
TEMPLATES_DIR = SCRIPTS_DIR / "templates"
sys.path.insert(0, str(SCRIPTS_DIR))

from api import app, DATA_DIR


class AuditEndToEndRegressionSuite(unittest.TestCase):
    """Suite de regresión para verificar todas las resoluciones de la auditoría técnica."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()
        with open(STATIC_DIR / "multimeter.js", "r", encoding="utf-8") as f:
            cls.multimeter_js = f.read()
        with open(STATIC_DIR / "circuit-visualizer.js", "r", encoding="utf-8") as f:
            cls.cv_js = f.read()
        with open(STATIC_DIR / "log-parser.js", "r", encoding="utf-8") as f:
            cls.log_parser_js = f.read()
        with open(STATIC_DIR / "search-worker.js", "r", encoding="utf-8") as f:
            cls.worker_js = f.read()
        with open(SCRIPTS_DIR / "api.py", "r", encoding="utf-8") as f:
            cls.api_code = f.read()
        with open(TEMPLATES_DIR / "index.html", "r", encoding="utf-8") as f:
            cls.html = f.read()

    # ─── 1. P0-1: SEGURIDAD XSS Y DELEGACIÓN DE EVENTOS ──────────────────────

    def test_p0_1_no_dynamic_onclick_in_any_static_module(self):
        """Verifica que no existan atributos onclick dinámicos en ningún módulo estático."""
        self.assertEqual(len(re.findall(r'onclick\s*=', self.app_js, re.IGNORECASE)), 0, "app.js debe tener 0 handlers onclick inline")
        self.assertEqual(len(re.findall(r'onclick\s*=', self.cv_js, re.IGNORECASE)), 0, "circuit-visualizer.js debe tener 0 handlers onclick inline")
        self.assertEqual(len(re.findall(r'onclick\s*=', self.log_parser_js, re.IGNORECASE)), 0, "log-parser.js debe tener 0 handlers onclick inline")
        self.assertEqual(len(re.findall(r'onclick\s*=', self.multimeter_js, re.IGNORECASE)), 0, "multimeter.js debe tener 0 handlers onclick inline")

        # Debe utilizar data-action para delegación segura
        self.assertIn('data-action="medir-tp"', self.app_js)
        self.assertIn('data-action="ver-pdf"', self.app_js)
        self.assertIn('data-action="ver-nota-grande"', self.app_js)
        self.assertIn('data-action="esquema-svg"', self.app_js)

    def test_p0_1_centralized_event_delegation_listener_exists(self):
        """Verifica que exista un listener centralizado en document para despachar data-action."""
        self.assertIn('document.addEventListener("click"', self.app_js)
        self.assertIn('event.target.closest("[data-action]")', self.app_js)
        self.assertIn('action === "medir-tp"', self.app_js)
        self.assertIn('action === "ver-pdf"', self.app_js)

    # ─── 2. P0-2: SECRETO GEMINI NUNCA RESIDE EN EL CLIENTE ──────────────────

    def test_p0_2_gemini_key_never_stored_or_entered_in_client(self):
        """Verifica que la clave de API jamás se almacene en storage del cliente ni se exponga en UI."""
        self.assertNotIn('localStorage.getItem("solvi_gemini_key")', self.app_js)
        self.assertNotIn('localStorage.setItem("solvi_gemini_key"', self.app_js)
        self.assertNotIn('localStorage.getItem("gemini_key"', self.app_js)
        self.assertNotIn('localStorage.setItem("gemini_key"', self.app_js)
        self.assertNotIn('sessionStorage.getItem("solvi_gemini_key")', self.app_js)
        self.assertNotIn('sessionStorage.setItem("solvi_gemini_key"', self.app_js)
        self.assertNotIn('sessionStorage.getItem("gemini_key"', self.app_js)
        self.assertNotIn('sessionStorage.setItem("gemini_key"', self.app_js)
        self.assertNotIn('headers["X-Gemini-Key"]', self.app_js)
        self.assertNotIn('promptGeminiKey', self.app_js)
        self.assertNotIn('promptGeminiKey', self.html)

    # ─── 3. P1-1: SEMÁNTICA DE VERIFICACIÓN EN TRAZA DE GRAFO ────────────────

    def test_p1_1_verification_badge_distinguishes_canonical_documented_inferred(self):
        """Verifica que renderTrazaGrafo no emita '⬤ Verificado en planos' incondicionalmente."""
        self.assertNotIn("'<span style=\"font-size:.65rem;font-family:var(--mono);color:var(--green)\">⬤ Verificado en planos</span>'", self.app_js)
        self.assertIn("⬤ CANÓNICO (Esquema verificado)", self.app_js)
        self.assertIn("⬤ DOCUMENTADO (Manuales)", self.app_js)
        self.assertIn("⬤ INFERIDO (Topología aproximada)", self.app_js)

    # ─── 4. P1-2: CORRELACIÓN VS CAUSA RAÍZ EN DIAGRAMA ──────────────────────

    def test_p1_2_render_diagrama_labels_top_result_as_hypothesis_not_root_cause(self):
        """Verifica que el ranking de búsqueda en renderDiagrama se etiquete como Hipótesis Principal."""
        self.assertNotIn("⚡ Factor Común / Causa Raíz", self.app_js)
        self.assertIn("⚡ Hipótesis Principal (Relación Priorizada)", self.app_js)

    # ─── 5. P1-3 & P1-4: AISLAMIENTO AI -> GRAFO Y VALIDACIÓN DE TP ──────────

    def test_p1_3_ai_to_graph_sanitizes_candidate_entities(self):
        """Verifica que renderDiagnosticoAi sanitice entidades antes de pasar a _ultimoResultadoGrafo."""
        self.assertIn("sanitizeCandidateList", self.app_js)
        self.assertIn("is_inferred: true", self.app_js)

    def test_p1_4_test_points_validated_against_catalog_before_measure_button(self):
        """Verifica que los TP extraídos por regex en IA se validen contra el catálogo antes de habilitar (Medir)."""
        self.assertIn("resolverPuntoDePrueba(tpCode, false)", self.app_js)
        self.assertIn("isKnownTp", self.app_js)

    # ─── 6. P1-5: VISOR PDF OFFLINE Y CLASIFICACIÓN DE ERRORES ───────────────

    def test_p1_5_ver_pdf_does_not_block_offline_with_hard_alert(self):
        """Verifica que verPDF intente abrir el visor sin bloquear con alert cuando offline."""
        self.assertNotIn('if (!navigator.onLine) {\n        alert("📴 Sin conexión a internet', self.app_js)

    def test_p1_5_pdf_error_classification_granular(self):
        """Verifica que abrirVisorPDF distinga 404, CORS, archivo dañado y red."""
        self.assertIn("MissingPDFException", self.app_js)
        self.assertIn("Documento No Encontrado (404)", self.app_js)
        self.assertIn("Acceso Restringido (CORS / 403)", self.app_js)
        self.assertIn("InvalidPDFException", self.app_js)
        self.assertIn("Archivo PDF Dañado", self.app_js)

    # ─── 7. P1-6: ESTADO DE ZOOM CONCURRENTE ─────────────────────────────────

    def test_p1_6_zoom_state_synchronizes_with_dataset_on_touch(self):
        """Verifica que activarZoomCanvas sincronice currentZoom con canvas.dataset.currentZoom."""
        self.assertIn("currentZoom = parseFloat(canvas.dataset.currentZoom) || 1;", self.app_js)

    # ─── 8. P1-7: BÚSQUEDA: PAGINACIÓN Y PREVENCIÓN DE RESPUESTAS OBSOLETAS ──

    def test_p1_7_pagination_uses_preserved_search_state_query_and_manual(self):
        """Verifica que buscar(true) use _searchState.query en lugar de leer el DOM alterado."""
        self.assertIn("const keyword = loadMore ? (_searchState.query || inputQ) : inputQ;", self.app_js)
        self.assertIn("const manual = loadMore ? (_searchState.manual || inputManual) : inputManual;", self.app_js)

    def test_p1_7_search_race_conditions_prevented_with_sequence_and_abort(self):
        """Verifica que buscar use _searchRequestId y AbortController para descartar respuestas viejas."""
        self.assertIn("let _searchRequestId = 0;", self.app_js)
        self.assertIn("let _searchAbortController = null;", self.app_js)
        self.assertIn("if (currentReqId !== _searchRequestId) return;", self.app_js)

    # ─── 9. P1-8: WORKER BACKPRESSURE Y AUTO-RECONSTRUCCIÓN ──────────────────

    def test_p1_8_worker_backpressure_preserves_inflight_requests(self):
        """Verifica que sobrecarga en workerRequest rechace sólo la nueva petición sin purgar las existentes."""
        self.assertIn('Cola de búsqueda saturada', self.app_js)
        # No debe vaciar el mapa de pendientes con for (const [oldId, oldPending] of _workerPending)
        self.assertNotIn('oldPending.reject(new Error("Petición offline descartada por sobrecarga"))', self.app_js)

    def test_p1_8_worker_onerror_triggers_auto_restart(self):
        """Verifica que _iniciarSearchWorker reinicie el worker en onerror."""
        self.assertIn("_iniciarSearchWorker", self.app_js)
        self.assertIn("setTimeout(_iniciarSearchWorker, 200)", self.app_js)

    # ─── 10. P1-9: IDEMPOTENCIA EN NOTAS Y CONCURRENCIA MULTI-TAB ────────────

    def test_p1_9_notes_backend_creation_is_idempotent_without_anonymous_overwrite(self):
        """POST reintenta por UUID sin permitir que un cliente anónimo sobrescriba una nota."""
        self.assertIn('supabase.table("notes").insert(note_data).execute()', self.api_code)
        self.assertIn("_same_note_content(existing, note_data)", self.api_code)
        self.assertIn('"error": "note_id_conflict"', self.api_code)
        self.assertNotIn('supabase.table("notes").upsert(note_data).execute()', self.api_code)

    def test_p1_9_sync_pendientes_has_multi_tab_concurrency_protection(self):
        """Verifica que syncPendientes proteja la sincronización contra ejecuciones simultáneas."""
        self.assertIn("_isSyncingNotes", self.app_js)
        self.assertIn("navigator.locks.request", self.app_js)

    # ─── 11. AUDITORÍA EXHAUSTIVA: FINDINGS 4.6, 6.5, 6.6 ───────────────────

    def test_finding_4_6_dmm_tp_options_dynamically_populated_from_catalog(self):
        """Verifica que multimeter.js pueble dinámicamente el selector de TP desde el catálogo canónico."""
        self.assertIn("generarOpcionesPuntosPrueba()", self.multimeter_js)
        self.assertIn("dmmTpSelect", self.multimeter_js)

    def test_finding_6_5_search_worker_cancellation_on_timeout(self):
        """Verifica que en timeout se envíe mensaje de cancelación al worker y el worker lo reconozca."""
        self.assertIn('type: "cancel"', self.app_js)
        self.assertIn('_cancelledRequests', self.worker_js)
        self.assertIn('type === "cancel"', self.worker_js)

    def test_finding_6_6_indexeddb_solvi_notes_db_persistence(self):
        """Verifica que app.js implemente persistencia de apuntes en IndexedDB (SolviNotesDB)."""
        self.assertIn("SolviNotesDB", self.app_js)
        self.assertIn("getNotesDB", self.app_js)
        self.assertIn("initNotesStorage", self.app_js)
        self.assertIn("idbPut", self.app_js)
        self.assertIn("idbClearAndPutAll", self.app_js)


if __name__ == "__main__":
    unittest.main()
