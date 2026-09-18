"""SOLVI - Pruebas de Servicio Offline de PDFs de Manuales Técnicos en sw.js y app.js.

Verifica los hallazgos de la auditoría v7:
- P0: sw.js no excluye .pdf ni r2.dev de la interceptación de caché.
- P0: sw.js sirve manuales cacheados mediante estrategia cacheFirstPdf con soporte de cabeceras Range (HTTP 206).
- Optimización de RAM y rendimiento móvil: limpieza de canvas y page.cleanup() en app.js.
- Pre-cacheo del visor PDF.js en CORE de sw.js.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "scripts" / "static"


class PdfOfflineServiceWorkerSuite(unittest.TestCase):
    """Pruebas de verificación de PDFs offline y consumo eficiente de memoria."""

    @classmethod
    def setUpClass(cls):
        with open(ROOT / "sw.js", "r", encoding="utf-8") as f:
            cls.sw_js = f.read()
        with open(STATIC_DIR / "app.js", "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_sw_fetch_exclusion_does_not_exclude_pdf_or_r2(self):
        """P0: Verifica que sw.js haya eliminado la exclusión de .pdf y r2.dev en el manejador fetch."""
        # Extraer el bloque de exclusión rápida
        match_fetch = re.search(r"self\.addEventListener\(['\"]fetch['\"],\s*event\s*=>\s*\{([\s\S]*?)\}\);", self.sw_js)
        self.assertIsNotNone(match_fetch, "Manejador fetch debe existir en sw.js")
        fetch_body = match_fetch.group(1)

        # La condición de exclusión no debe contener .pdf ni r2.dev
        match_if = re.search(r"if\s*\(([\s\S]*?)\)\s*\{\s*return;\s*\}", fetch_body)
        self.assertIsNotNone(match_if, "Debe existir bloque if de exclusión en fetch")
        exclusion_cond = match_if.group(1)

        self.assertNotIn(".pdf", exclusion_cond, "La exclusión no debe ignorar URLs .pdf")
        self.assertNotIn("r2.dev", exclusion_cond, "La exclusión no debe ignorar r2.dev")

    def test_sw_routes_pdf_and_r2_to_cache_first_pdf_strategy(self):
        """P0: Verifica que las peticiones a PDFs o Cloudflare R2 se manejen con cacheFirstPdf."""
        self.assertIn("async function cacheFirstPdf", self.sw_js)
        self.assertIn('url.pathname.endsWith(".pdf")', self.sw_js)
        self.assertIn('url.hostname.includes("r2.dev")', self.sw_js)
        self.assertIn("event.respondWith(cacheFirstPdf(event.request));", self.sw_js)

    def test_sw_handles_range_requests_safely_for_cached_pdfs(self):
        """P0: Verifica soporte de HTTP 206 Partial Content y prevención de TypeError en CacheStorage."""
        self.assertIn("function returnPartialContent", self.sw_js)
        self.assertIn("Content-Range", self.sw_js)
        self.assertIn("status: 206", self.sw_js)
        # Asegurar que no se intente cache.put con respuestas 206
        self.assertIn("response.status === 200", self.sw_js)

    def test_pdf_js_core_assets_are_cached_on_install(self):
        """Verifica que pdf.min.js y pdf.worker.min.js estén incluidos en la lista CORE para soporte 100% offline."""
        self.assertIn("pdf.min.js", self.sw_js)
        self.assertIn("pdf.worker.min.js", self.sw_js)

    def test_app_js_ram_optimization_and_page_cleanup(self):
        """Verifica salvaguardas de memoria RAM en el visor PDF para dispositivos móviles y tablets."""
        # page.cleanup() para liberar glifos de fuentes y búferes internos de PDF.js
        self.assertIn("page.cleanup()", self.app_js)
        # Liberación de documento anterior
        self.assertIn("window._pdfDoc.destroy()", self.app_js)
        # Cancelación de render task en curso
        self.assertIn("window._pdfRenderTask.cancel()", self.app_js)
        # Control de escalado inteligente en móviles
        self.assertIn("isMobileOrTablet", self.app_js)
        self.assertIn("maxImageSize", self.app_js)

    def test_app_js_offline_caching_trigger_on_manual_download(self):
        """Verifica que el botón 'Offline' del visor active el guardado proactivo en CacheStorage."""
        self.assertIn("function cacheManualOffline", self.app_js)
        self.assertIn('data-action="descargar-pdf-offline"', self.app_js)
        self.assertIn("caches.open", self.app_js)

    def test_sw_full_caching_on_first_range_request(self):
        """P0: Verifica que en peticiones con Range no cacheadas, sw.js descargue y almacene el PDF completo (status 200)."""
        self.assertIn("filterHeadersWithoutRange", self.sw_js)
        self.assertIn("cleanRequest", self.sw_js)
        self.assertIn("fullResponse.status === 200", self.sw_js)
        self.assertIn("cache.put(cleanRequest, fullResponse.clone())", self.sw_js)

    def test_sw_buffer_reuse_optimizes_mobile_ram(self):
        """Verifica que returnPartialContent reutilice el ArrayBuffer (_lastPdfBuffer) en peticiones consecutivas."""
        self.assertIn("_lastPdfBuffer", self.sw_js)
        self.assertIn("_lastPdfUrl", self.sw_js)

    def test_app_js_pdf_button_always_rendered_for_manuals(self):
        """Verifica que la tarjeta de búsqueda siempre muestre el botón 'Ver pág.' para manuales técnicos."""
        self.assertIn("Ver pág.", self.app_js)
        self.assertIn("verPDF(result.manual, result.page, keyword)", self.app_js)

    def test_app_js_ver_pdf_handles_unconfigured_r2_url(self):
        """Verifica que verPDF permita configurar la URL de Cloudflare R2 interactivamente si no está presente."""
        self.assertIn("prompt(", self.app_js)
        self.assertIn("Cloudflare R2", self.app_js)


if __name__ == "__main__":
    unittest.main()

