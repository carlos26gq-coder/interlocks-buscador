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
        mock_resp = MagicMock()
        mock_resp.text = '{"root_cause": "Tarjeta de control de Gantry", "subsystem": "Gantry Motion", "confidence": "alta", "explanation": "Falla en encoder", "associated_boards": ["PCB 16N"], "manual_references": ["movement.pdf"], "action_steps": ["1. Revisar voltajes"], "safety_warning": "Desconectar HT"}'
        mock_client.models.generate_content.return_value = mock_resp

        res = analyze_with_gemini(["el gantry se frena"], self.engine, api_key="fake-test-key")
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["root_cause"], "Tarjeta de control de Gantry")
        self.assertEqual(res["data"]["subsystem"], "Gantry Motion")
        self.assertEqual(res["data"]["confidence"], "alta")


if __name__ == "__main__":
    unittest.main()
