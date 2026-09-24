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
    _sanitize_explanation,
    _sanitize_root_cause,
    _is_drawing_or_schematic_number,
    _sanitize_action_steps,
    _sanitize_differential_diagnoses,
    DifferentialDiagnosis,
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

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_503_uses_local_failover(self, mock_client_cls):
        """Una saturación 503 de todos los modelos no debe llegar como error crudo a la UI."""
        docs = [{"manual": "ht_rf", "page": 22, "text": "ITEM 409 RAD_ON command from console to PCB 22."}]
        engine = SearchEngine(docs)
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception(
            "503 UNAVAILABLE: model is currently experiencing high demand"
        )

        res = analyze_with_gemini(["ITEM 409 saturation test"], engine, api_key="test_key")
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("failover"))
        self.assertEqual(res["data"].get("_diagnostic_meta", {}).get("reason"), "service_unavailable")
        self.assertNotIn("503", res.get("notice", ""))

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
        """Verifica que el timeout de 90 s use milisegundos en types.HttpOptions."""
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

    def test_failover_diagnosis_item475_item471_clean_entities_and_4_steps(self):
        """Verifica que el diagnóstico local de ITEM 475 e ITEM 471 genere entidades limpias, pasos dinámicos y sin plantillas rígidas."""
        docs = [
            {
                "manual": "diagrams",
                "page": 211,
                "text": "PCB IDENTIFICATION PCB ASSY DIE-RHA PCB 12D PCB 12F ITEM 475 D1 FORCE TERM ITEM 471 D1 RESET DOSE PL1 PL2 SK12 TP12",
            }
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 475", "ITEM 471"], engine, reason="timeout")

        # 1. Tarjetas limpias (sin títulos de plano ni prefijo "Tarjeta:")
        self.assertIn("associated_boards", failover)
        boards = failover["associated_boards"]
        for b in boards:
            self.assertFalse(b.startswith("Tarjeta:"))
            self.assertNotIn("PCB IDENTIFICATION", b)
            self.assertNotIn("PCB ASSY", b)
        self.assertTrue(any("DIE-RHA" in b or "PCB 12D" in b for b in boards))

        # 2. Conectores limpios (sin prefijo "Conector:")
        self.assertIn("cables_and_connectors", failover)
        connectors = failover["cables_and_connectors"]
        for c in connectors:
            self.assertFalse(c.startswith("Conector:"))
        self.assertTrue(any("PL1" in c or "SK12" in c for c in connectors))

        # 3. Señales priorizan los síntomas consultados
        self.assertIn("test_points_and_signals", failover)
        signals = failover["test_points_and_signals"]
        self.assertIn("ITEM 475", signals[:2])
        self.assertIn("ITEM 471", signals[:2])

        # 4. Pasos de acción generados dinámicamente según componentes (sin plantillas rígidas preenlatadas)
        steps = failover.get("action_steps", [])
        self.assertTrue(len(steps) >= 3)
        self.assertFalse(any("Probabilidad 1" in s for s in steps))
        self.assertFalse(any("Probabilidad 2" in s for s in steps))
        self.assertTrue(any("ITEM 475" in s or "ITEM 471" in s for s in steps))
        self.assertTrue(any("DIE-RHA" in s or "PCB 12D" in s or "tarjetas" in s for s in steps))

        # 5. Explicación fundamentada sin texto genérico repetitivo ni enumeración de manuales
        explanation = failover.get("explanation", "")
        self.assertNotIn("Contexto Operativo: En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos", explanation)
        self.assertNotIn(".pdf", explanation)
        self.assertNotIn("diagrams.pdf", explanation)
        refs = failover.get("manual_references", [])
        self.assertTrue(any("diagrams" in r.lower() for r in refs))
        self.assertTrue(any(sig in explanation for sig in ["ITEM 475", "ITEM 471"]))

        # 6. Ausencia total de cadenas prohibidas o evasivas
        serialized = str(failover).lower()
        self.assertNotIn("contingencia", serialized)
        self.assertNotIn("saturación temporal", serialized)
        self.assertNotIn("no establece una causa raíz", serialized)
        self.assertNotIn("no cuenta con suficiente data", serialized)
        self.assertNotIn("inteligencia artificial", serialized)
        import re
        self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    def test_sanitize_explanation_removes_generic_boilerplate(self):
        """Verifica que _sanitize_explanation elimine texto introductorio genérico."""
        bad_texts = [
            "Contexto Operativo: En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos y Seguridad (Elekta LINAC). La señal ITEM 409 supervisa...",
            "Contexto Operativo: En la arquitectura del acelerador lineal Elekta las señales analizadas forman parte integral del sistema. Se detecta falla...",
            "En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos y Seguridad (Elekta LINAC). Fallo en tarjeta...",
        ]
        for bt in bad_texts:
            cleaned = _sanitize_explanation(bt)
            self.assertNotIn("Contexto Operativo", cleaned)
            self.assertNotIn("forman parte integral del Sistema General de Interbloqueos", cleaned)
            self.assertTrue(len(cleaned) > 0)

    def test_sanitize_action_steps_removes_rigid_probability_templates(self):
        """Verifica que _sanitize_action_steps limpie prefijos rígidos de probabilidades."""
        bad_steps = [
            "Paso 1 (Probabilidad 1 - Alimentación y Protecciones Básicas): Medir voltajes de 24VDC en PCB 12D.",
            "Paso 2 (Probabilidad 2 - Puntos de Prueba y Niveles Lógicos): Verificar TP12 con osciloscopio.",
            "Probabilidad 3: Revisar continuidad del arnés PL1.",
            "Prioridad 4: Calibrar umbrales en Service Mode.",
            "Paso 5: Ajustar potenciómetro R12.",
        ]
        cleaned = _sanitize_action_steps(bad_steps)
        self.assertEqual(len(cleaned), 5)
        for s in cleaned:
            self.assertFalse(s.startswith("Paso 1"))
            self.assertFalse("Probabilidad" in s)
            self.assertFalse("Prioridad" in s)
        self.assertEqual(cleaned[0], "Medir voltajes de 24VDC en PCB 12D.")
        self.assertEqual(cleaned[1], "Verificar TP12 con osciloscopio.")
        self.assertEqual(cleaned[2], "Revisar continuidad del arnés PL1.")

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_sanitizes_explanation_and_action_steps(self, mock_client_cls):
        """Verifica que analyze_with_gemini aplique sanitización al resultado generado por Gemini."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]
        mock_response.parsed = GeminiDiagnosis(
            root_cause="Fallo en lazo de disparo",
            subsystem="Dosimetría",
            confidence=Confidence.ALTA,
            explanation="Contexto Operativo: En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos y Seguridad (Elekta LINAC). La señal ITEM 409 disparó.",
            associated_boards=["PCB 12D"],
            cables_and_connectors=["PL1"],
            test_points_and_signals=["ITEM 409"],
            citation_ids=["C1"],
            action_steps=[
                "Paso 1 (Probabilidad 1 - Alimentación y Protecciones Básicas): Medir tensión de alimentación.",
                "Paso 2 (Probabilidad 2 - Puntos de Prueba y Niveles Lógicos): Medir punto de prueba TP1.",
            ],
            safety_warning="Peligro HT",
        )

        mock_client.models.generate_content.return_value = mock_response

        docs = [{"manual": "diagrams", "page": 100, "text": "ITEM 409 trigger on PCB 12D with PL1."}]
        engine = SearchEngine(docs)

        result = analyze_with_gemini(["ITEM 409"], engine, api_key="dummy_valid_key")
        self.assertTrue(result["ok"])
        data = result["data"]

        # Explanation sanitizada
        self.assertNotIn("Contexto Operativo", data["explanation"])
        self.assertIn("La señal ITEM 409 disparó.", data["explanation"])

        # Action steps sanitizados
        for step in data["action_steps"]:
            self.assertNotIn("Probabilidad 1", step)
            self.assertNotIn("Probabilidad 2", step)
        self.assertEqual(data["action_steps"][0], "Medir tensión de alimentación.")
        self.assertEqual(data["action_steps"][1], "Medir punto de prueba TP1.")

    # ─── 7. DIAGNÓSTICOS DIFERENCIALES Y RAZONAMIENTO MULTIMODAL ────────────

    def test_differential_diagnosis_pydantic_schema_and_serialization(self):
        """Verifica el esquema Pydantic de DifferentialDiagnosis y su serialización en GeminiDiagnosis."""
        diff = DifferentialDiagnosis(
            hypothesis="Deriva térmica en comparadores de ventana analógicos",
            subsystem="Dosimetría",
            likelihood="alta",
            rationale="Discrepancia en canal D1 sin variación en canal D2.",
        )
        self.assertEqual(diff.hypothesis, "Deriva térmica en comparadores de ventana analógicos")
        self.assertEqual(diff.subsystem, "Dosimetría")
        self.assertEqual(diff.likelihood, "alta")
        self.assertEqual(diff.rationale, "Discrepancia en canal D1 sin variación en canal D2.")

        # Por defecto GeminiDiagnosis tiene differential_diagnoses vacío
        diag_default = GeminiDiagnosis(
            root_cause="Causa",
            subsystem="Sub",
            confidence=Confidence.ALTA,
            explanation="Exp",
        )
        self.assertEqual(diag_default.differential_diagnoses, [])

        # GeminiDiagnosis con lista de diagnósticos diferenciales
        diag_with_diffs = GeminiDiagnosis(
            root_cause="Causa",
            subsystem="Sub",
            confidence=Confidence.ALTA,
            explanation="Exp",
            differential_diagnoses=[diff],
        )
        dumped = diag_with_diffs.model_dump(mode="json")
        self.assertEqual(len(dumped["differential_diagnoses"]), 1)
        self.assertEqual(dumped["differential_diagnoses"][0]["likelihood"], "alta")

    def test_sanitize_differential_diagnoses_normalization(self):
        """Verifica que _sanitize_differential_diagnoses normalice campos, probabilidades y tipos anómalos."""
        raw_diffs = [
            {
                "hypothesis": "  Microfuga en fuelle de vacío de cañón de electrones  ",
                "subsystem": "Sistema de Vacío",
                "likelihood": "ALTA",
                "rationale": "Incremento de corriente en bomba iónica.",
            },
            {
                "hypothesis": "Fallo en optoacoplador de bus de seguridad",
                "subsystem": "Comunicaciones",
                "likelihood": "desconocida",  # Debe normalizarse a 'media'
                "rationale": "Latencia intermitente en trama ARCNET.",
            },
            "Hipótesis en formato de cadena simple",
            None,
            12345,
            {"hypothesis": ""},  # Hipótesis vacía debe descartarse
        ]
        sanitized = _sanitize_differential_diagnoses(raw_diffs)
        self.assertEqual(len(sanitized), 3)
        self.assertEqual(sanitized[0]["hypothesis"], "Microfuga en fuelle de vacío de cañón de electrones")
        self.assertEqual(sanitized[0]["likelihood"], "alta")
        self.assertEqual(sanitized[1]["likelihood"], "media")
        self.assertEqual(sanitized[2]["hypothesis"], "Hipótesis en formato de cadena simple")
        self.assertEqual(sanitized[2]["likelihood"], "media")

        # Entrada no iterable o None devuelve lista vacía
        self.assertEqual(_sanitize_differential_diagnoses(None), [])
        self.assertEqual(_sanitize_differential_diagnoses("no una lista"), [])

    def test_failover_diagnosis_generates_differential_diagnoses_and_procedural_steps(self):
        """Verifica que generate_local_failover_diagnosis produzca diagnósticos diferenciales y pasos procedimentales profundos."""
        docs = [
            {
                "manual": "dosimetry",
                "page": 69,
                "text": "Table 4.18: Conditions that cause an HT relay interlock: Watchdogs, 3.3V/5V rail failures, chamber bias voltage out of limits, DIE-RHA watchdog trip.",
            },
            {
                "manual": "diagrams",
                "page": 211,
                "text": "PCB ASSY DIE-RHA PCB 12D ITEM 475 D1 FORCE TERM ITEM 471 D1 RESET DOSE PL1 PL2 SK12 TP12",
            },
            {
                "manual": "communications",
                "page": 95,
                "text": "DIE-RHA board communications bus jumper links LK1, LK2 and termination resistors on ARCNET interface.",
            },
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 475", "ITEM 471", "DIE-RHA"], engine, reason="timeout")

        # 1. Diagnósticos diferenciales estructurados (3-4 hipótesis)
        diffs = failover.get("differential_diagnoses", [])
        self.assertTrue(len(diffs) >= 3, f"Se esperaban >= 3 diagnósticos diferenciales, se obtuvieron: {len(diffs)}")
        for d in diffs:
            self.assertTrue(bool(d.get("hypothesis")))
            self.assertIn(d.get("likelihood"), {"alta", "media", "baja"})
            self.assertTrue(bool(d.get("rationale")))
            self.assertTrue(bool(d.get("subsystem")))

        # 2. Pasos de acción variados y procedimentales (cubren verificación de software, hardware, mediciones, calibración)
        steps = failover.get("action_steps", [])
        self.assertTrue(len(steps) >= 4, f"Se esperaban >= 4 pasos, se obtuvieron: {len(steps)}")
        step_text = " ".join(steps).lower()
        self.assertTrue(any(w in step_text for w in ["ccp", "service mode", "consola", "pantalla"]))
        self.assertTrue(any(w in step_text for w in ["calibración", "tolerancia", "umbral", "tensión", "voltaje"]))
        self.assertTrue(any(w in step_text for w in ["relé", "lazo", "arnés", "conector", "continuidad"]))

        # 3. Explicación fundamentada y sin enumerar manuales en la narrativa
        exp = failover.get("explanation", "")
        self.assertNotIn(".pdf", exp)
        self.assertNotIn("dosimetry.pdf", exp)
        self.assertNotIn("diagrams.pdf", exp)
        refs = failover.get("manual_references", [])
        self.assertTrue(any("dosimetry" in r.lower() for r in refs))
        self.assertTrue(any("diagrams" in r.lower() for r in refs))

        # 4. Strict zero IA/AI
        serialized = str(failover).lower()
        self.assertNotIn("inteligencia artificial", serialized)
        import re
        self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    def test_gather_grounding_context_multi_manual_diversity(self):
        """Verifica que gather_grounding_context extraiga evidencia balanceada de múltiples manuales sin sesgo hacia diagrams.pdf."""
        docs = [
            {"manual": "diagrams", "page": 10, "text": "ITEM 475 DIE-RHA relay loop schematic page 10."},
            {"manual": "diagrams", "page": 11, "text": "ITEM 475 DIE-RHA relay loop schematic page 11."},
            {"manual": "diagrams", "page": 12, "text": "ITEM 475 DIE-RHA relay loop schematic page 12."},
            {"manual": "diagrams", "page": 13, "text": "ITEM 475 DIE-RHA relay loop schematic page 13."},
            {"manual": "dosimetry", "page": 69, "text": "ITEM 475 DIE-RHA chamber calibration and watchdog interlock."},
            {"manual": "communications", "page": 95, "text": "ITEM 475 DIE-RHA bus arbitration and CAN timeout."},
            {"manual": "power_supplies", "page": 73, "text": "ITEM 475 DIE-RHA 24VDC and 5V rail distribution."},
        ]
        engine = SearchEngine(docs)
        ctx, citation_map = gather_grounding_context(engine, ["ITEM 475", "DIE-RHA"], max_pages=8)

        # Verificar que el citation_map incluya múltiples manuales diferentes
        manuals_in_cites = {v["manual"] for v in citation_map.values()}
        self.assertGreaterEqual(len(manuals_in_cites), 3, f"Manuales en citas insuficientes: {manuals_in_cites}")
        self.assertIn("dosimetry", manuals_in_cites)
        self.assertIn("communications", manuals_in_cites)

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_preserves_and_sanitizes_differential_diagnoses(self, mock_client_cls):
        """Verifica que analyze_with_gemini conserve y normalice los diagnósticos diferenciales devueltos por el modelo."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]
        mock_response.parsed = GeminiDiagnosis(
            root_cause="Bloqueo por disparo en tarjeta DIE-RHA",
            subsystem="Dosimetría y Monitoreo de Haz",
            confidence=Confidence.ALTA,
            explanation="La señal ITEM 475 disparó la cadena de interbloqueo conforme a diagrams.pdf (Página 211).",
            citation_ids=["C1"],
            differential_diagnoses=[
                DifferentialDiagnosis(
                    hypothesis="Fallo de comunicación en bus ARCNET",
                    subsystem="Comunicaciones",
                    likelihood="media",
                    rationale="Timeout intermitente reportado en el procesador central.",
                ),
                DifferentialDiagnosis(
                    hypothesis="Deriva en la fuente auxiliar de 5V",
                    subsystem="Fuentes DC",
                    likelihood="baja",
                    rationale="Ondulación residual por envejecimiento de capacitores.",
                ),
            ],
            associated_boards=["DIE-RHA"],
            cables_and_connectors=["PL1", "SK12"],
            test_points_and_signals=["ITEM 475", "ITEM 471"],
            action_steps=["Comprobar continuidad del lazo en PL1."],
            safety_warning="Desenergizar antes de intervenir.",
        )

        mock_client.models.generate_content.return_value = mock_response

        docs = [{"manual": "diagrams", "page": 211, "text": "ITEM 475 DIE-RHA on PL1."}]
        engine = SearchEngine(docs)

        result = analyze_with_gemini(["ITEM 475"], engine, api_key="dummy_key")
        self.assertTrue(result["ok"])
        data = result["data"]

        diffs = data.get("differential_diagnoses", [])
        self.assertEqual(len(diffs), 2)
        self.assertEqual(diffs[0]["hypothesis"], "Fallo de comunicación en bus ARCNET")
        self.assertEqual(diffs[0]["likelihood"], "media")
        self.assertEqual(diffs[1]["subsystem"], "Fuentes DC")

    def test_failover_diagnosis_strictly_prohibits_canned_multimeter_templates_and_prioritizes_user_boards(self):
        """Verifica que el caso exacto reportado por el usuario (ITEM 475, ITEM 471, DIE-RHA)

        produzca un diagnóstico no-enlatado, con DIE-RHA priorizada como tarjeta,
        subsistema de Dosimetría, y pasos procedimentales profundos sin plantillas rígidas.
        """
        docs = [
            {
                "manual": "dosimetry",
                "page": 68,
                "text": "i471 D1 reset dose, i475 D1 Force term. Low dose rate monitor i044 / i045 calibration.",
            },
            {
                "manual": "diagrams",
                "page": 211,
                "text": "1.101 DOSIMETRY CHANNEL ITEM 475 D1 FORCE TERM ITEM 471 D1 RESET DOSE DIE-RHA PL1 PL2 SK12",
            },
            {
                "manual": "communications",
                "page": 33,
                "text": "List of the PCBs in the RHCA: DIE-RHA, MTU-RHA, ROC-RHA, AI12-RHA.",
            },
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ITEM 475", "ITEM 471", "DIE-RHA"], engine, reason="timeout")

        # 1. Subsistema preciso de Dosimetría
        subsystem = failover.get("subsystem", "")
        self.assertIn("Dosimetría", subsystem)

        # 2. DIE-RHA debe estar en associated_boards y como primera tarjeta, JAMÁS en signals
        boards = failover.get("associated_boards", [])
        self.assertTrue(len(boards) > 0)
        self.assertEqual(boards[0], "DIE-RHA")
        signals = failover.get("test_points_and_signals", [])
        self.assertNotIn("DIE-RHA", signals)
        self.assertIn("ITEM 475", signals)
        self.assertIn("ITEM 471", signals)

        # 3. PROHIBICIÓN ABSOLUTA DE LAS 4 PLANTILLAS PREENLATADAS REPORTADAS POR EL USUARIO
        steps = failover.get("action_steps", [])
        self.assertGreaterEqual(len(steps), 5)
        for s in steps:
            self.assertNotIn("Medir con multímetro u osciloscopio los niveles lógicos y señales de prueba", s)
            self.assertNotIn("Inspeccionar visual y térmicamente DIE-RHA, comprobando el estado de sus fusibles", s)
            self.assertNotIn("Comprobar la continuidad eléctrica, apriete de terminales y ausencia de bornes flojos", s)
            self.assertNotIn("Consultar los procedimientos de diagnóstico y tablas de calibración en diagrams.pdf", s)

        # 4. Pasos técnicos procedimentales profundos verificables
        step_text = " ".join(steps).lower()
        self.assertIn("service mode", step_text)
        self.assertTrue(any(w in step_text for w in ["chamber bias", "cámara de ionización", "polarización"]))
        self.assertTrue(any(w in step_text for w in ["calibración", "tolerancia", "simetría"]))
        self.assertTrue(any(w in step_text for w in ["watchdog", "arcnet", "jumpers", "puentes"]))
        self.assertTrue(any(w in step_text for w in ["rizado", "mvpp", "rail", "rieles"]))
        self.assertTrue(any(w in step_text for w in ["rad_on", "reinicio seguro", "normalización"]))

        # 5. Prioridad equilibrada de manuales (no solo diagrams.pdf)
        refs = failover.get("manual_references", [])
        self.assertTrue(any("dosimetry" in r.lower() for r in refs))
        self.assertTrue(any("diagrams" in r.lower() for r in refs))

    def test_generate_local_failover_diagnosis_ht_psu_ot_and_vmat(self):
        """Verifica la generación causal profunda de HT PSU OT y VMAT con tarjetas, señales, items y procedimientos."""
        docs = [
            {"manual": "diagrams", "page": 57, "text": "HT PSU SYSTEM 1024686 Area 17 T4 SW2 SW1 BLA TR1 TR2 FS17A FS17B CB3."},
            {"manual": "diagrams", "page": 159, "text": "PRF Interlocks 45133307021-WD-14 DIE-HTB PL2-a3 ITEM 251 HT PSU OT RAD_ON."},
            {"manual": "ht_rf", "page": 92, "text": "DIE-HTB monitors HT OVERTEMP DETECTOR Item 251. SW1 SW2. Item 330 Chargerate PRI I MON PRI REF."},
            {"manual": "ht_rf", "page": 225, "text": "Charge rate test Item 330 TPU1-8 TPU1-1 0V 2.5V 5.0V. HT PSU OT Inhibit."},
            {"manual": "item part", "page": 145, "text": "i251 HT PSU OT HT over temperature Drawing 4513 330 7021 SW1 SW2."},
            {"manual": "movement", "page": 80, "text": "VMAT dose delivery variable dose rate dynamic MLC Item 2200."},
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(
            ["ht psu ot", "error ocurre cuando realizan tratamientos vmat"],
            engine,
            reason="timeout",
        )

        # 1. Subsistema preciso
        self.assertIn("Alta Tensión y Generación de RF", failover["subsystem"])

        # 2. Causa raíz con lazo térmico, VMAT, DIE-HTB, PL2-a3 e ITEM 251
        root_cause = failover["root_cause"]
        self.assertIn("HT OVERTEMP DETECTOR", root_cause)
        self.assertIn("VMAT", root_cause)
        self.assertIn("ITEM 251", root_cause)
        self.assertIn("DIE-HTB", root_cause)
        self.assertIn("PL2-a3", root_cause)

        # 3. Tarjetas clave
        boards = failover["associated_boards"]
        self.assertIn("DIE-HTB", boards)
        self.assertIn("PCB 22", boards)
        self.assertIn("HT PSU CONTROL PCB", boards)
        self.assertIn("HT ISOLATION PCB", boards)

        # 4. Cables y terminales clave
        cables = failover["cables_and_connectors"]
        self.assertIn("PL2-a3", cables)
        self.assertTrue(any(c in cables for c in ["SK17C", "PL16S", "SK16R", "TS22A"]))

        # 5. Señales e ítems clave
        signals = failover["test_points_and_signals"]
        self.assertIn("ITEM 251", signals)
        self.assertIn("ITEM 330", signals)
        self.assertIn("PRI I MON", signals)
        self.assertIn("SW1", signals)
        self.assertIn("SW2", signals)
        self.assertIn("TS1", signals)
        self.assertIn("TS2", signals)

        # 6. Explicación profunda y razonada
        explanation = failover["explanation"]
        self.assertIn("ITEM 251", explanation)
        self.assertIn("ITEM 330", explanation)
        self.assertIn("SW1", explanation)
        self.assertIn("SW2", explanation)
        self.assertIn("VMAT", explanation)
        self.assertIn("DIE-HTB", explanation)
        self.assertIn("PL2-a3", explanation)
        self.assertIn("HT OVERTEMP DETECTOR", explanation)

        # 7. Diagnósticos diferenciales técnicos multifacéticos
        diffs = failover["differential_diagnoses"]
        self.assertEqual(len(diffs), 4)
        hypotheses = " ".join(d["hypothesis"] for d in diffs)
        self.assertIn("SW1", hypotheses)
        self.assertIn("SW2", hypotheses)
        self.assertIn("HT ISOLATION PCB", hypotheses)
        self.assertIn("PRI I MON", hypotheses)

        # 8. Pasos de acción concretos y no preenlatados
        steps = failover["action_steps"]
        self.assertEqual(len(steps), 6)
        step_blob = " ".join(steps)
        self.assertIn("ITEM 251", step_blob)
        self.assertIn("ITEM 330", step_blob)
        self.assertIn("SW1", step_blob)
        self.assertIn("SW2", step_blob)
        self.assertIn("PL2-a3", step_blob)
        self.assertIn("TPU1-8", step_blob)
        self.assertIn("HT ISOLATION PCB", step_blob)
        self.assertIn("BLA", step_blob)

        # 9. Referencias documentales a manuales pertinentes
        refs = failover["manual_references"]
        self.assertTrue(any("diagrams" in r for r in refs))
        self.assertTrue(any("ht_rf" in r for r in refs))
        self.assertTrue(any("power_supplies" in r for r in refs))
        self.assertTrue(any("corrective" in r for r in refs))
        self.assertTrue(any("planned" in r for r in refs))
        self.assertTrue(any("item part" in r for r in refs))

        # 10. Advertencia de seguridad de alta tensión
        self.assertIn("ALTA TENSIÓN", failover["safety_warning"])

        # 11. Restricción estricta de CERO menciones de IA / AI
        serialized = str(failover).lower()
        self.assertNotIn("inteligencia artificial", serialized)
        import re
        self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    def test_gather_grounding_context_ht_psu_ot_expansions(self):
        """Verifica que gather_grounding_context aplique expansiones para HT PSU OT y VMAT."""
        docs = [
            {"manual": "diagrams", "page": 57, "text": "HT PSU SYSTEM 1024686 Area 17 T4 SW2 SW1 BLA."},
            {"manual": "diagrams", "page": 159, "text": "PRF Interlocks 4513 330 7021 DIE-HTB PL2-a3 ITEM 251 HT PSU OT."},
            {"manual": "ht_rf", "page": 92, "text": "DIE-HTB monitors HT OVERTEMP DETECTOR Item 251 SW1 SW2 Item 330 Chargerate."},
            {"manual": "ht_rf", "page": 225, "text": "HT PSU charge rate test Item 330 TPU1-8 TPU1-1."},
            {"manual": "power_supplies", "page": 78, "text": "i251 HT PSU OT TS22 TS22A Area 22 Waveguide interlocks."},
            {"manual": "corrective", "page": 419, "text": "Corrective maintenance drawing 4513 330 7021 HT PSU OT SW1 SW2."},
            {"manual": "planned", "page": 298, "text": "Planned maintenance heat exchanger loop auxiliary pump TS1 TS2."},
            {"manual": "item part", "page": 145, "text": "i251 HT PSU OT HT over temperature Drawing 4513 330 7021."},
        ]
        engine = SearchEngine(docs)
        ctx, cmap = gather_grounding_context(
            engine,
            ["ht psu ot", "error ocurre cuando realizan tratamientos vmat"],
            max_pages=16,
        )
        manuals_cited = {v["manual"] for v in cmap.values()}
        self.assertIn("diagrams", manuals_cited)
        self.assertIn("ht_rf", manuals_cited)
        self.assertIn("power_supplies", manuals_cited)
        self.assertIn("corrective", manuals_cited)
        self.assertIn("planned", manuals_cited)
        self.assertIn("item part", manuals_cited)

    def test_generate_local_failover_diagnosis_ht_con_k(self):
        """Verifica que el diagnóstico de 'ht con k' filtre esquemas, coordenadas y razone la secuencia física."""
        docs = [
            {"manual": "diagrams", "page": 63, "text": "CONTACTOR K CON-K CON-A CON-D CON-J DIE-HTA PCB 16M RL4 DIE-HTB PCB 16N CON_K_MON 1024690 PCB 72H."},
            {"manual": "diagrams", "page": 159, "text": "Drawing 4513 330 7021 DIE-HTB CON_K_MON RAD_ON."},
            {"manual": "ht_rf", "page": 110, "text": "CON-K High Tension contactor sequence CON_K_MON feedback line."},
            {"manual": "power_supplies", "page": 45, "text": "CON-K auxiliary contact microswitch RL4 on DIE-HTA."},
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["ht con k"], engine)

        # 1. Subsistema adecuado
        self.assertIn("Alta Tensión", failover["subsystem"])

        # 2. Boards no deben incluir coordenadas como PCB 72H ni números de esquema
        boards = failover["associated_boards"]
        self.assertNotIn("PCB 72H", boards)
        self.assertNotIn("1024690", boards)
        self.assertNotIn("45133307021", boards)
        self.assertTrue(any("DIE-ICA" in b or "IRC" in b or "ROC-ICA" in b for b in boards))

        # 3. Señales no deben incluir números de plano
        signals = failover["test_points_and_signals"]
        self.assertNotIn("1024690", signals)
        self.assertNotIn("45133307021", signals)
        self.assertTrue(any("CON-K" in s or "ITEM 79" in s for s in signals))

    def test_generate_local_failover_diagnosis_item_79_grounds_correctly(self):
        """Verifica que el diagnóstico de 'item 79' se asocie con DIE-ICA (Área 72) e IRC-A/B (Área 74), sin DIE-HTB ni Área 16."""
        docs = [
            {"manual": "diagrams", "page": 63, "text": "ITEM 79 HT CON K DIE-ICA PCB 72H IRC-A PCB 74A IRC-B PCB 74B ROC-ICA AREA 72 AREA 74."},
            {"manual": "power_supplies", "page": 73, "text": "i79 CON-K DIE-ICA ICCA RTU A ROC-ICA AREA 72."},
            {"manual": "power_supplies", "page": 93, "text": "Check input to DIE-ICA PCB area 72 slot H on PL2 pin C7/C8... i79 inhibit."},
            {"manual": "item part", "page": 77, "text": "i79 Contactor CON-K monitor HT con K."},
        ]
        engine = SearchEngine(docs)
        failover = generate_local_failover_diagnosis(["item 79"], engine)

        # 1. Subsistema de potencia / contactores
        self.assertIn("Alta Tensión", failover["subsystem"])

        # 2. Boards asociadas: DIE-ICA, IRC-A, IRC-B o ROC-ICA
        boards = failover["associated_boards"]
        self.assertTrue(any("DIE-ICA" in b or "IRC" in b or "ROC-ICA" in b for b in boards))
        # No debe contener DIE-HTB
        self.assertNotIn("DIE-HTB", boards)

        # 3. Señales: ITEM 79 presente
        signals = failover["test_points_and_signals"]
        self.assertTrue(any("79" in s for s in signals))

        # 4. Causa raíz y explicación no deben citar DIE-HTB ni Área 16 para ITEM 79
        root = failover["root_cause"]
        expl = failover["explanation"]
        self.assertNotIn("DIE-HTB", root)
        self.assertNotIn("DIE-HTB", expl)
        self.assertNotIn("Área 16", root)
        self.assertNotIn("Área 16", expl)
        self.assertIn("DIE-ICA", expl)

        # 5. Genera 5 hallazgos con causas físicas y soluciones
        findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
        self.assertEqual(len(findings), 5)
        for f in findings:
            self.assertTrue(len(f["title"]) > 10)
            self.assertTrue(len(f["cause_mechanism"]) > 40)
            self.assertTrue(len(f["solution_procedure"]) > 40)
            self.assertNotIn("DIE-HTB", f["cause_mechanism"])

        # 4. Hallazgos diagnósticos integrados (hasta 5)
        findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
        self.assertTrue(1 <= len(findings) <= 5)
        for f in findings:
            self.assertIn("cause_mechanism", f)
            self.assertIn("solution_procedure", f)
            self.assertIn("title", f)
            self.assertTrue(len(f["cause_mechanism"]) > 20)
            self.assertTrue(len(f["solution_procedure"]) > 20)
            self.assertNotIn("PCB 72H", f["title"])
            self.assertNotIn("1024690", f["title"])

        # 5. Cero IA / AI
        serialized = str(failover).lower()
        self.assertNotIn("inteligencia artificial", serialized)
        import re
        self.assertFalse(bool(re.search(r"\b(?:ia|ai)\b", serialized)))

    def test_is_drawing_or_schematic_number(self):
        """Verifica la detección de números de planos, códigos 12NC y coordenadas de esquemas."""
        self.assertTrue(_is_drawing_or_schematic_number("1024690"))
        self.assertTrue(_is_drawing_or_schematic_number("1024686"))
        self.assertTrue(_is_drawing_or_schematic_number("1512977"))
        self.assertTrue(_is_drawing_or_schematic_number("45133307021"))
        self.assertTrue(_is_drawing_or_schematic_number("4513 330 7021"))
        self.assertTrue(_is_drawing_or_schematic_number("4513-330-7021"))
        self.assertTrue(_is_drawing_or_schematic_number("PCB 72H"))
        self.assertTrue(_is_drawing_or_schematic_number("72H"))
        self.assertTrue(_is_drawing_or_schematic_number("WD-14"))
        self.assertTrue(_is_drawing_or_schematic_number("P/N 12345"))
        # Componentes legítimos no deben ser clasificados como planos
        self.assertFalse(_is_drawing_or_schematic_number("DIE-HTA"))
        self.assertFalse(_is_drawing_or_schematic_number("PCB 16M"))
        self.assertFalse(_is_drawing_or_schematic_number("PCB 16N"))
        self.assertFalse(_is_drawing_or_schematic_number("CON-K"))
        self.assertFalse(_is_drawing_or_schematic_number("CON_K_MON"))
        self.assertFalse(_is_drawing_or_schematic_number("ITEM 251"))

    def test_sanitize_root_cause_user_case(self):
        """Verifica que _sanitize_root_cause elimine limpiamente coordenadas y esquemas sin dejar conjunciones residuales."""
        raw = "Disparo en lazo de seguridad de Distribución de Potencia y Fuentes DC (Power Supplies & Contactors), comprometiendo PCB 72H y señales 1024690, 45133307021"
        cleaned = _sanitize_root_cause(raw)
        self.assertEqual(
            cleaned,
            "Disparo en lazo de seguridad de Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)"
        )
        self.assertNotIn("PCB 72H", cleaned)
        self.assertNotIn("1024690", cleaned)
        self.assertNotIn("45133307021", cleaned)
        self.assertNotIn("comprometiendo", cleaned)

    def test_sanitize_root_cause_preserves_valid_boards_and_signals(self):
        """Verifica que conserve tarjetas y señales válidas al limpiar planos adyacentes."""
        raw = "Disparo en lazo de seguridad de Distribución de Potencia, comprometiendo DIE-HTA y señales 1024690"
        cleaned = _sanitize_root_cause(raw)
        self.assertEqual(cleaned, "Disparo en lazo de seguridad de Distribución de Potencia, comprometiendo DIE-HTA")

        raw_sig = "Disparo en lazo de seguridad de Distribución de Potencia, comprometiendo PCB 72H y señales CON_K_MON"
        cleaned_sig = _sanitize_root_cause(raw_sig)
        self.assertEqual(cleaned_sig, "Disparo en lazo de seguridad de Distribución de Potencia, comprometiendo señales CON_K_MON")

    def test_sanitize_explanation_user_case(self):
        """Verifica que _sanitize_explanation elimine citas a manuales, páginas, coordenadas y comas repetidas."""
        raw = (
            "Análisis documental de Distribución de Potencia y Fuentes DC (Power Supplies & Contactors): "
            "Las señales analizadas (1024690, 45133307021, ITEM 26) convergen en la supervisión operativa de PCB 72H, TS22A, MLC. "
            "La documentación técnica contrastada en diagrams.pdf (Página 63), diagrams.pdf (Página 159), item part.pdf (Página 77), "
            "accessory.pdf (Página 24) evidencia que una discrepancia en el lazo de interbloqueo maestro genera el corte."
        )
        cleaned = _sanitize_explanation(raw)
        self.assertNotIn(".pdf", cleaned)
        self.assertNotIn("diagrams.pdf", cleaned)
        self.assertNotIn("Página", cleaned)
        self.assertNotIn("1024690", cleaned)
        self.assertNotIn("45133307021", cleaned)
        self.assertNotIn("PCB 72H", cleaned)
        self.assertNotIn("(, ,", cleaned)
        self.assertIn("ITEM 26", cleaned)
        self.assertIn("TS22A", cleaned)
        self.assertIn("El análisis del sistema evidencia que", cleaned)

    def test_all_failover_subsystems_generate_5_rich_findings_with_solutions(self):
        """Verifica que todos los subsistemas failover generen hasta 5 hallazgos con causas físicas y soluciones técnicas."""
        subsystems_to_test = [
            (["d1 force", "item 475"], "Dosimetría"),
            (["vacuum", "ion pump", "sw1"], "Vacío"),
            (["magnetron", "tiratrón", "prf"], "Alta Tensión y Generación de RF"),
            (["collimator leaf", "encoder position"], "Control de Movimiento"),
            (["general interlock loop"], "Sistema General"),
        ]
        docs = [
            {"manual": "dosimetry", "page": 10, "text": "ITEM 475 DIE-RHA dosimetry channel."},
            {"manual": "vacuum", "page": 10, "text": "Vacuum ion pump SW1 pressure switch."},
            {"manual": "ht_rf", "page": 10, "text": "Magnetron thyratron RF pulse system."},
            {"manual": "movement", "page": 10, "text": "Collimator leaf encoder position error."},
            {"manual": "diagrams", "page": 10, "text": "General safety loop interlock relay chain."},
        ]
        engine = SearchEngine(docs)

        for symptoms, expected_sub in subsystems_to_test:
            failover = generate_local_failover_diagnosis(symptoms, engine)
            findings = failover.get("diagnostic_findings") or failover.get("differential_diagnoses") or []
            self.assertEqual(len(findings), 5, f"Fallo para síntomas: {symptoms}")
            for idx, f in enumerate(findings):
                self.assertTrue(len(f["title"]) > 10, f"Título muy corto en hallazgo {idx+1} para {symptoms}")
                self.assertTrue(len(f["cause_mechanism"]) > 40, f"Causa física muy corta en hallazgo {idx+1} para {symptoms}")
                self.assertTrue(len(f["solution_procedure"]) > 40, f"Solución técnica muy corta en hallazgo {idx+1} para {symptoms}")
                # No debe tener etiquetas de probabilidad en el título
                self.assertFalse(any(p in f["title"].lower() for p in ["probabilidad", "prioridad"]))
                # No debe enumerar archivos .pdf en la causa
                self.assertNotIn(".pdf", f["cause_mechanism"])


if __name__ == "__main__":
    unittest.main()
