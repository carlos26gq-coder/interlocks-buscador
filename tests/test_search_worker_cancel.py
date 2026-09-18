"""SOLVI - Pruebas de Manejo de Cancelación y Memoria en Search Worker.

Verifica el hallazgo P2 de la auditoría v7:
- Soporte para mensajes de tipo 'cancel' en search-worker.js.
- Aborto inmediato si la petición fue cancelada antes de iniciar el cálculo.
- Límite acotado de IDs cancelados en memoria para evitar fugas.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "scripts" / "static"


class SearchWorkerCancelSuite(unittest.TestCase):
    """Pruebas de verificación del manejo de cancelación en Web Worker offline."""

    @classmethod
    def setUpClass(cls):
        with open(STATIC_DIR / "search-worker.js", "r", encoding="utf-8") as f:
            cls.worker_js = f.read()

    def test_search_worker_handles_cancel_type(self):
        """Verifica que onmessage reconozca y gestione type === 'cancel'."""
        self.assertIn('type === "cancel"', self.worker_js)
        self.assertIn("_cancelledRequests", self.worker_js)

    def test_search_worker_checks_cancellation_before_execution(self):
        """Verifica que el worker verifique si la petición ya fue cancelada antes de procesar."""
        match_onmessage = re.search(r"self\.onmessage\s*=\s*async\s+event\s*=>\s*\{([\s\S]*?)\n\};", self.worker_js)
        self.assertIsNotNone(match_onmessage, "onmessage debe existir en search-worker.js")
        body = match_onmessage.group(1)

        idx_cancel_block = body.find('type === "cancel"')
        idx_early_check = body.find("_cancelledRequests.has(id)")
        idx_try = body.find("try {")

        self.assertNotEqual(idx_cancel_block, -1)
        self.assertNotEqual(idx_early_check, -1)
        self.assertNotEqual(idx_try, -1)
        self.assertLess(idx_early_check, idx_try, "Debe comprobar cancelación antes del bloque try {} de cálculo")

    def test_search_worker_bounds_cancelled_requests_set_size(self):
        """Verifica que el Set de peticiones canceladas esté acotado para prevenir fuga de memoria."""
        self.assertIn("_cancelledRequests.size > 100", self.worker_js)


if __name__ == "__main__":
    unittest.main()
