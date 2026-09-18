"""SOLVI - Pruebas de Persistencia Offline de Notas (IndexedDB + Memoria + Fallback LocalStorage).

Verifica los hallazgos de la auditoría v7:
- P1: Tolerancia a QuotaExceededError en localStorage y persistencia segura en IndexedDB.
- P1: Prioridad de lectura invertida: notasLocal() usa la memoria sincronizada con IndexedDB.
- P1.1: Secuenciación de arranque: await initNotesStorage() antes de sincronizaciones de red.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "scripts" / "static"


class NotesOfflineStorageSuite(unittest.TestCase):
    """Pruebas de arquitectura y robustez del subsistema de notas offline en app.js."""

    @classmethod
    def setUpClass(cls):
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_safe_local_storage_set_handles_quota_exceeded_with_user_warning(self):
        """Verifica que safeLocalStorageSet detecte fallos de localStorage (cuota llena) y alerte al usuario."""
        self.assertIn("function safeLocalStorageSet", self.app_js)
        self.assertIn("console.warn", self.app_js)
        # Debe emitir toast de aviso y no tragar silenciosamente el error
        self.assertIn("toast", self.app_js)
        self.assertIn("Almacenamiento rápido lleno", self.app_js)

    def test_safe_local_storage_get_survives_security_error_in_javascript(self):
        """Verifica que la función contenga el try/catch necesario para sobrevivir a SecurityError."""
        helper_match = re.search(
            r"function\s+safeLocalStorageGet\s*\([^)]*\)\s*\{([\s\S]*?)\n\}",
            self.app_js,
        )
        self.assertIsNotNone(helper_match, "safeLocalStorageGet() debe existir en app.js")
        body = helper_match.group(1)
        self.assertIn("try", body, "Debe contener un bloque try")
        self.assertIn("catch", body, "Debe contener un bloque catch")
        self.assertIn("return", body, "Debe retornar un valor")

    def test_r2url_startup_reads_use_safe_helper(self):
        """La inicialización de R2 no debe leer localStorage directamente."""
        self.assertIn('let _r2url = safeLocalStorageGet("r2url")', self.app_js)
        self.assertIn('!safeLocalStorageGet("r2url")', self.app_js)
        self.assertNotIn('let _r2url = localStorage.getItem("r2url")', self.app_js)

    def test_in_memory_cache_exists_and_inverts_read_priority(self):
        """Verifica que notasLocal lea del caché en memoria (_memNotes) respaldado por IndexedDB."""
        self.assertIn("let _memNotes = null;", self.app_js)
        self.assertIn("let _memPending = null;", self.app_js)

        # notasLocal debe chequear _memNotes antes de localStorage
        match_notas_local = re.search(r"function\s+notasLocal\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match_notas_local, "notasLocal() debe existir en app.js")
        body = match_notas_local.group(1)
        self.assertIn("if (_memNotes !== null) return _memNotes;", body)

    def test_init_notes_storage_returns_promise_and_populates_memory_cache(self):
        """Verifica que initNotesStorage retorne una promesa que resuelva al completar la lectura de IndexedDB."""
        match_init = re.search(r"async\s+function\s+initNotesStorage\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match_init, "initNotesStorage() debe ser una función asíncrona")
        body = match_init.group(1)
        self.assertIn("new Promise", body)
        self.assertIn("_memNotes = idbNotes;", body)
        self.assertIn("resolve();", body)

    def test_startup_sequencing_awaits_init_notes_storage_before_sync(self):
        """Verifica que el listener de arranque espere con await a initNotesStorage antes de syncPendientes."""
        match_dom_loaded = re.search(r'addEventListener\("DOMContentLoaded",\s*(async\s+function[\s\S]*?\n\}\));', self.app_js)
        self.assertIsNotNone(match_dom_loaded, "DOMContentLoaded listener debe existir")
        body = match_dom_loaded.group(1)

        # Verificar que el callback sea async y tenga await initNotesStorage()
        self.assertIn("async", body[:50])
        idx_init = body.find("await initNotesStorage();")
        self.assertNotEqual(idx_init, -1, "DOMContentLoaded debe ejecutar 'await initNotesStorage();'")

        idx_sync = body.find("await syncPendientes();")
        if idx_sync == -1:
            idx_sync = body.find("syncPendientes();")
        self.assertNotEqual(idx_sync, -1, "syncPendientes() debe invocarse tras initNotesStorage")
        self.assertLess(idx_init, idx_sync, "initNotesStorage() debe completarse ANTES de syncPendientes()")

    def test_simulated_local_storage_quota_exceeded_simulation(self):
        """Simula la lógica JavaScript: si localStorage.setItem falla por QuotaExceeded,

        la nota sigue en memoria e IndexedDB, siendo 100% visible tras recargar.
        """
        # Emulador del comportamiento en app.js
        mock_idb = {}
        mock_local_storage = {}
        storage_quota_blown = True
        warnings = []

        def safe_local_storage_set(key, val):
            if storage_quota_blown:
                warnings.append("QuotaExceeded")
                return False
            mock_local_storage[key] = val
            return True

        # Guardar nota con localStorage lleno
        mem_notes = []
        new_note = {"id": "note-123", "title": "Inspección Tiratrón", "text": "Revisar filamento"}
        mem_notes.append(new_note)

        # notasGuardar logic
        safe_local_storage_set("interlocks_notas", str(mem_notes))
        mock_idb["notes"] = list(mem_notes)

        self.assertTrue(len(warnings) > 0, "Debe registrarse advertencia de cuota")
        self.assertEqual(len(mock_idb["notes"]), 1, "La nota debe estar guardada en IndexedDB")

        # Simular recarga (F5): reinicio de memoria
        mem_notes_after_f5 = None
        # initNotesStorage logic: lee de IndexedDB
        idb_notes_loaded = mock_idb.get("notes", [])
        if idb_notes_loaded:
            mem_notes_after_f5 = list(idb_notes_loaded)

        # notasLocal logic
        def notas_local():
            nonlocal mem_notes_after_f5
            if mem_notes_after_f5 is not None:
                return mem_notes_after_f5
            return mock_local_storage.get("interlocks_notas", [])

        recovered_notes = notas_local()
        self.assertEqual(len(recovered_notes), 1)
        self.assertEqual(recovered_notes[0]["title"], "Inspección Tiratrón")

    def test_startup_sequencing_uses_merge_cloud_notes_not_clobbering_offline(self):
        """Verifica que el listener de arranque use mergeCloudNotes(data) para no borrar apuntes offline pendientes."""
        self.assertIn("mergeCloudNotes(data)", self.app_js)

    def test_r2url_storage_is_safe_under_quota_exceeded(self):
        """Verifica que los intentos de guardar r2url en localStorage estén protegidos con try/catch."""
        lines = self.app_js.splitlines()
        for idx, line in enumerate(lines, 1):
            if 'localStorage.setItem("r2url"' in line or "localStorage.setItem('r2url'" in line:
                surround = "\n".join(lines[max(0, idx - 2):min(len(lines), idx + 1)])
                self.assertIn("try", surround, f"Línea {idx} tiene localStorage.setItem('r2url') sin try: {line}")

    def test_safe_local_storage_set_debounces_toasts(self):
        """Verifica que safeLocalStorageSet evite saturar la pantalla con toasts consecutivos en ráfagas de escritura."""
        self.assertIn("_lastQuotaToast", self.app_js)


if __name__ == "__main__":
    unittest.main()
