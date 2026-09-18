"""SOLVI - Pruebas Unitarias del Servicio de Diagnóstico Avanzado y Deducción Causal."""

from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ai_service import (
    extract_json_safely,
    get_cached_diagnosis,
    set_cached_diagnosis,
    clear_diagnostic_cache,
    _make_cache_key,
    _DIAG_CACHE,
    _CACHE_TTL_SECONDS,
    gather_grounding_context,
    analyze_with_gemini,
    generate_local_failover_diagnosis,
    _sanitize_error_message,
    GeminiDiagnosis,
    Confidence,
    DEFAULT_GEMINI_TIMEOUT_MS,
    DEFAULT_GEMINI_TIMEOUT_SECONDS,
)
from search_engine import SearchEngine


class AiServiceSuite(unittest.TestCase):
    """Pruebas para extracción robusta de JSON, caché LRU con TTL, thread safety y contexto técnico."""

    def setUp(self):
        clear_diagnostic_cache()

    # ─── 1. EXTRACCIÓN ROBUSTA DE JSON ───────────────────────────────────────

    def test_extract_json_from_clean_string(self):
        """Extrae JSON estándar válido."""
        raw = '{"root_cause": "Falla de disparo en Tiratrón", "confidence": "alta"}'
        parsed = extract_json_safely(raw)
        self.assertEqual(parsed.get("root_cause"), "Falla de disparo en Tiratrón")
        self.assertEqual(parsed.get("confidence"), "alta")

    def test_extract_json_from_markdown_code_block(self):
        """Extrae JSON envuelto en bloques markdown con o sin tag de lenguaje."""
        raw = """Aquí está el análisis causal:
```json
{
    "root_cause": "Descalibración del sensor de posición MLC",
    "confidence": "media",
    "associated_boards": ["PCB 25"]
}
```
Fin del reporte."""
        parsed = extract_json_safely(raw)
        self.assertEqual(parsed.get("root_cause"), "Descalibración del sensor de posición MLC")
        self.assertIn("PCB 25", parsed.get("associated_boards", []))

    def test_extract_json_fixes_trailing_commas_before_closing_brace(self):
        """Repara errores sintácticos comunes como comas finales antes de llaves o corchetes."""
        raw = '{"root_cause": "Sobrecorriente en filamento", "confidence": "alta", }'
        parsed = extract_json_safely(raw)
        self.assertEqual(parsed.get("root_cause"), "Sobrecorriente en filamento")

    def test_extract_json_regex_reconstruction_fallback(self):
        """Texto con JSON corrupto pero con campos clave reconocibles se reconstruye mediante regex."""
        raw = 'Error parcial: "root_cause": "Fuga en guía de ondas RF", texto truncado...'
        parsed = extract_json_safely(raw)
        self.assertEqual(parsed.get("root_cause"), "Fuga en guía de ondas RF")
        self.assertEqual(parsed.get("subsystem"), "General LINAC")

    def test_extract_json_empty_or_invalid_raises_value_error(self):
        """Entradas vacías o sin causa raíz lanzan ValueError controlado."""
        with self.assertRaises(ValueError):
            extract_json_safely("")
        with self.assertRaises(ValueError):
            extract_json_safely("Texto completamente arbitrario sin formato alguno.")

    # ─── 2. CACHÉ EN MEMORIA CON TTL Y THREAD-LOCK ────────────────────────────

    def test_cache_key_normalization_order_and_casing(self):
        """Síntomas en distinto orden y mayúsculas/minúsculas producen la misma clave de caché."""
        k1 = _make_cache_key(["ITEM 409", "modulador rf"])
        k2 = _make_cache_key(["MODULADOR RF", "item 409"])
        self.assertEqual(k1, k2)

    def test_cache_set_and_hit(self):
        """Un resultado guardado se recupera de la caché sin invocar el backend."""
        symptoms = ["ITEM 409", "modulador rf"]
        payload = {"root_cause": "Prueba de caché", "confidence": "alta"}
        set_cached_diagnosis(symptoms, payload, model_used="gemini-3.5-flash")

        cached = get_cached_diagnosis(symptoms)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.get("cached"))
        self.assertEqual(cached["data"].get("root_cause"), "Prueba de caché")

    def test_cache_ttl_expiration(self):
        """Las entradas de caché expiran tras su tiempo de vida (TTL)."""
        symptoms = ["expired_symptom"]
        key = _make_cache_key(symptoms)
        payload = {"root_cause": "Dato antiguo"}
        # Insertar con timestamp de 2 horas atrás
        _DIAG_CACHE[key] = (time.time() - (_CACHE_TTL_SECONDS + 300), payload, "gemini-3.5-flash")

        self.assertIsNone(get_cached_diagnosis(symptoms))

    def test_cache_thread_safety_concurrent_access(self):
        """Acceso concurrente de múltiples hilos a la caché no genera condiciones de carrera ni excepciones."""
        errors = []

        def worker(idx: int):
            try:
                for i in range(25):
                    s = [f"symptom_{idx}_{i % 5}"]
                    set_cached_diagnosis(s, {"root_cause": f"test_{idx}_{i}"}, "gemini-3.5-flash")
                    res = get_cached_diagnosis(s)
                    if res is not None:
                        _ = res["data"]["root_cause"]
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errores en concurrencia: {errors}")

    # ─── 3. CONSTRUCTOR DE CONTEXTO TÉCNICO Y CITAS ──────────────────────────

    def test_gather_grounding_context(self):
        """Extrae fragmentos técnicos de manuales relevantes para alimentar el análisis causal."""
        docs = [
            {"manual": "movement", "page": 10, "text": "Error 66: MLC leaf driver feedback timeout on PCB 25."},
            {"manual": "vacuum", "page": 4, "text": "Vacuum pressure switch SW1 opens if below 10^-7 Torr."},
        ]
        engine = SearchEngine(docs)
        ctx, citation_map = gather_grounding_context(engine, ["Error 66"], max_pages=3)
        self.assertIn("movement", ctx)
        self.assertIn("PCB 25", ctx)
        self.assertIsInstance(citation_map, dict)

    def test_gather_grounding_context_labels_and_citation_map(self):
        """Verifica que gather_grounding_context etiqueta [C1], [C2] y que citation_map coincide con datos reales."""
        docs = [
            {"manual": "movement", "page": 10, "text": "Error 66: MLC leaf driver feedback timeout on PCB 25."},
            {"manual": "diagrams", "page": 45, "text": "Error 66: Safety interlock loop open contactor K1."},
        ]
        engine = SearchEngine(docs)
        ctx, citation_map = gather_grounding_context(engine, ["Error 66"], max_pages=3)
        self.assertIn("[C1]", ctx)
        self.assertIn("C1", citation_map)
        self.assertEqual(citation_map["C1"]["manual"], "movement")
        self.assertEqual(citation_map["C1"]["page"], 10)

    # ─── 4. MOCK TESTS DE INFERENCIA, CITAS DETERMINISTAS Y TRUNCAMIENTO ─────

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_nonexistent_citation_id_discarded(self, mock_client_cls):
        """Citas con IDs inexistentes (ej: C99 inventado por el modelo) se descartan y no generan citas falsas."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = GeminiDiagnosis(
            root_cause="Falla de disparo en Tiratrón",
            subsystem="Radiation & RF",
            confidence=Confidence.ALTA,
            explanation="Explicación técnica detallada.",
            citation_ids=["C99"],  # ID inventado que NO existe en citation_map
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]
        mock_client.models.generate_content.return_value = mock_resp

        res = analyze_with_gemini(["ITEM 409"], engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        manual_refs = res["data"]["manual_references"]
        # Una cita inventada no puede degradarse a una atribución topológica
        # no verificable: el contrato actual bloquea el diagnóstico.
        self.assertEqual(manual_refs, [])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("evidence_blocked"))
        self.assertFalse(any("C99" in ref or "Página 99" in ref for ref in manual_refs))

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_empty_citation_ids_fallback(self, mock_client_cls):
        """AI-03: Cuando citation_ids viene vacío, no atribuye falsamente todas las fuentes; usa fallback de topología."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = GeminiDiagnosis(
            root_cause="Falla de disparo en Tiratrón",
            subsystem="Radiation & RF",
            confidence=Confidence.ALTA,
            explanation="Explicación técnica detallada.",
            citation_ids=[],  # Lista vacía
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]
        mock_client.models.generate_content.return_value = mock_resp

        res = analyze_with_gemini(["ITEM 409"], engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        manual_refs = res["data"]["manual_references"]
        self.assertEqual(manual_refs, [])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("evidence_blocked"))

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_finish_reason_max_tokens_flagged(self, mock_client_cls):
        """Simula truncamiento por MAX_TOKENS y verifica que se marque en _diagnostic_meta."""
        docs = [{"manual": "vacuum", "page": 12, "text": "ITEM 112 vacuum pressure fault switch SW1."}]
        engine = SearchEngine(docs)

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = GeminiDiagnosis(
            root_cause="Falla en bomba iónica",
            subsystem="Vacuum System",
            confidence=Confidence.MEDIA,
            explanation="Análisis incompleto...",
            citation_ids=["C1"],
        )
        mock_resp.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
        mock_client.models.generate_content.return_value = mock_resp

        res = analyze_with_gemini(["ITEM 112"], engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("truncated"))

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_degraded_parse_fallback(self, mock_client_cls):
        """Simula ausencia de response.parsed (SDK antiguo) y confirma que cae a extract_json_safely con degraded_parse."""
        docs = [{"manual": "vacuum", "page": 12, "text": "ITEM 112 vacuum pressure fault switch SW1."}]
        engine = SearchEngine(docs)

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.parsed = None  # Sin parsed tipado
        mock_resp.text = '{"root_cause": "Falla en contactor K1", "subsystem": "Power", "confidence": "alta", "explanation": "Prueba de compatibilidad"}'
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]
        mock_client.models.generate_content.return_value = mock_resp

        res = analyze_with_gemini(["ITEM 112"], engine, api_key="fake_key")
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["root_cause"], "Sin correlación documentada")
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("evidence_blocked"))
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("degraded_parse"))

    # ─── 6. RESILENCIA ANTE TIMEOUTS Y FAILOVER LOCAL DETERMINISTA ───────────

    def test_sanitize_error_message_masks_read_timeout(self):
        """Verifica que mensajes de socket o read timeout se conviertan en texto técnico legible."""
        raw = "Error al procesar el diagnóstico causal: The read operation timed out"
        sanitized = _sanitize_error_message(raw)
        self.assertNotIn("read operation timed out", sanitized)
        self.assertIn("Tiempo de respuesta agotado", sanitized)

    def test_generate_local_failover_diagnosis_structure(self):
        """Verifica que generate_local_failover_diagnosis produzca un esquema completo de diagnóstico."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 409"], engine, reason="timeout")
        self.assertIn("root_cause", failover)
        self.assertIn("subsystem", failover)
        self.assertIn("confidence", failover)
        self.assertIn("action_steps", failover)
        self.assertTrue(len(failover["action_steps"]) >= 2)
        self.assertTrue(failover.get("_diagnostic_meta", {}).get("failover"))
        self.assertEqual(failover.get("_diagnostic_meta", {}).get("reason"), "timeout")

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_timeout_failover(self, mock_client_cls):
        """Verifica que al ocurrir un timeout de lectura, se active el failover determinista local."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = TimeoutError("The read operation timed out")

        res = analyze_with_gemini(["ITEM 409"], engine, api_key="test_key")
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("failover"))
        self.assertIn("data", res)
        self.assertIn("root_cause", res["data"])
        self.assertTrue(res["data"].get("_diagnostic_meta", {}).get("failover"))

    def test_zero_visible_ai_in_failover_diagnosis(self):
        """Garantiza la ausencia total de las palabras 'IA', 'AI' o 'Inteligencia Artificial' en failover."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 409"], engine, reason="timeout")
        serialized = str(failover).lower()
        self.assertNotIn("inteligencia artificial", serialized)
        import re
        self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    def test_default_gemini_timeout_is_milliseconds_and_matches_seconds(self):
        """Verifica que el timeout para types.HttpOptions esté en milisegundos (evitando que 45s se interprete como 45ms)."""
        from google.genai import types
        from google.genai._api_client import get_timeout_in_seconds

        self.assertGreaterEqual(DEFAULT_GEMINI_TIMEOUT_MS, 10000)
        self.assertEqual(DEFAULT_GEMINI_TIMEOUT_MS / 1000.0, DEFAULT_GEMINI_TIMEOUT_SECONDS)

        opts = types.HttpOptions(timeout=DEFAULT_GEMINI_TIMEOUT_MS)
        timeout_seconds = get_timeout_in_seconds(opts.timeout)
        self.assertIsNotNone(timeout_seconds)
        self.assertAlmostEqual(timeout_seconds, DEFAULT_GEMINI_TIMEOUT_SECONDS, places=1)

    def test_failover_metadata_contains_notice(self):
        """Verifica que el diagnóstico determinista de contingencia incluya el aviso explícito para el técnico."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 409"], engine, reason="timeout")
        meta = failover.get("_diagnostic_meta", {})
        self.assertTrue(meta.get("failover"))
        self.assertIn("failover_notice", meta)
        self.assertGreater(len(meta["failover_notice"]), 20)

    def test_sanitize_error_message_broad_timeout_coverage(self):
        """Verifica que cualquier variante de socket, deadline o read timeout se sanee limpiamente."""
        variantes = [
            "The read operation timed out",
            "Read operation timed out after 30 seconds",
            "socket.timeout: timed out",
            "Deadline Exceeded during generate_content",
            "HTTPSConnectionPool: Read timed out.",
        ]
        for v in variantes:
            sanitized = _sanitize_error_message(v)
            self.assertNotIn("timed out", sanitized.lower())
            self.assertIn("Tiempo de respuesta agotado", sanitized)


if __name__ == "__main__":
    unittest.main()
