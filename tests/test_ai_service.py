import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from search_engine import SearchEngine  # noqa: E402
from ai_service import extract_keywords_for_retrieval, gather_grounding_context, analyze_with_gemini  # noqa: E402


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine([
            {
                "manual": "movement",
                "page": 10,
                "text": "Gantry drive motor M1 overcurrent detected. Check PCB 16N and Area 22 encoder connection.",
            },
            {
                "manual": "diagrams",
                "page": 167,
                "text": "1.79 Beam centering system Sheet 3 ITEM 409 HT AO8 mux SCC-HTB PCB 16V ITEM 332 HTCA AREA 16.",
            },
        ])

    def test_extract_keywords_for_retrieval(self):
        symptoms = ["el gantry se frena al girar en sentido horario y hay sobrecorriente"]
        kws = extract_keywords_for_retrieval(symptoms)
        self.assertIn("gantry", kws)
        self.assertIn("sobrecorriente", kws)

    def test_gather_grounding_context(self):
        symptoms = ["ITEM 409", "ITEM 332"]
        context = gather_grounding_context(self.engine, symptoms)
        self.assertIn("diagrams", context)
        self.assertIn("Página 167", context)

    def test_analyze_with_gemini_without_key_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            res = analyze_with_gemini(["falla de motor"], self.engine, api_key="")
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"], "no_api_key")

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_success_mock(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
    def test_extract_json_safely(self):
        from ai_service import extract_json_safely
        raw = '''```json
        {
            "root_cause": "Tarjeta AO8 en Area 16",
            "subsystem": "Beam Centering",
            "confidence": "alta",
            "explanation": "Detalle técnico de prueba",
            "associated_boards": ["AO8", "PCB 16V",],
            "manual_references": ["diagrams.pdf (Pág 167)"],
            "action_steps": ["Paso 1"],
            "safety_warning": "Peligro",
        }
        ```'''
        data = extract_json_safely(raw)
        self.assertEqual(data["root_cause"], "Tarjeta AO8 en Area 16")
        self.assertEqual(data["associated_boards"], ["AO8", "PCB 16V"])

    def test_diagnosis_cache_memory(self):
        from ai_service import get_cached_diagnosis, set_cached_diagnosis
        symptoms = ["ITEM 409", "ITEM 332"]
        payload = {"root_cause": "Tarjeta AO8"}
        set_cached_diagnosis(symptoms, payload, "gemini-3.7-flash")

        # Recuperar con síntomas en distinto orden / mayúsculas
        cached = get_cached_diagnosis(["item 332", "item 409"])
        self.assertIsNotNone(cached)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["data"]["root_cause"], "Tarjeta AO8")

    @patch("ai_service.genai.Client")
    def test_analyze_with_gemini_falls_back_on_429_quota(self, mock_client_cls):
        from ai_service import _DIAG_CACHE
        _DIAG_CACHE.clear()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Simular que el primer modelo da 429 RESOURCE_EXHAUSTED y el segundo responde con éxito
        success_resp = MagicMock()
        success_resp.text = '{"root_cause": "Causa secundaria", "subsystem": "Prueba", "confidence": "alta", "explanation": "Ok", "associated_boards": [], "manual_references": [], "action_steps": [], "safety_warning": ""}'

        mock_client.models.generate_content.side_effect = [
            Exception("429 RESOURCE_EXHAUSTED. Quota exceeded for metric"),
            success_resp
        ]

        res = analyze_with_gemini(["falla rara 99"], self.engine, api_key="fake-key")
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["root_cause"], "Causa secundaria")


if __name__ == "__main__":
    unittest.main()

