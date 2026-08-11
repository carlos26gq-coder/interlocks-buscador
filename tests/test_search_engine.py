import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from search_engine import SearchEngine, normalize  # noqa: E402


class SearchEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine([
            {
                "manual": "movement",
                "page": 10,
                "text": "Interlock 283 and Error 66. Reset motors. Check MLC calibration when a leaf is missing.",
            },
            {
                "manual": "movement",
                "page": 11,
                "text": "Interlock 283 can also occur after a communication timeout. Restart the controller.",
            },
            {
                "manual": "vacuum",
                "page": 4,
                "text": "Error: 66. Examine the vacuum pump and verify the pressure sensor.",
            },
            {"manual": "technical", "page": 2, "text": "Calibración del movimiento de las láminas."},
            {"manual": "dosimetry", "page": 99, "text": "Calibrating the low dose rate monitor."},
        ])

    def test_normalization_removes_accents(self):
        self.assertEqual(normalize("Calibración"), "calibracion")

    def test_exact_search_is_accent_insensitive(self):
        result = self.engine.search("calibracion", limit=10)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["manual"], "technical")

    def test_search_paginates(self):
        result = self.engine.search("interlock 283", offset=0, limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["results"]), 1)
        self.assertTrue(result["has_more"])

    def test_partial_word_search_keeps_previous_behavior(self):
        result = self.engine.search("interl", limit=10)
        self.assertEqual(result["total"], 2)

        phrase_result = self.engine.search("dose rate mon", limit=10)
        self.assertEqual(phrase_result["total"], 1)

    def test_search_tolerates_punctuation_between_terms(self):
        result = self.engine.search("error 66", limit=10)
        self.assertEqual(result["total"], 2)

    def test_diagnosis_prioritizes_combined_evidence(self):
        result = self.engine.diagnose({
            "interlock": "283",
            "error": "66",
            "message": "reset motors leaf missing",
            "observations": "",
        })
        self.assertGreaterEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["page"], 10)
        self.assertGreaterEqual(len(result["results"][0]["matched_signals"]), 3)

    def test_diagnosis_returns_at_most_six_results(self):
        result = self.engine.diagnose({"message": "calibration"})
        self.assertLessEqual(len(result["results"]), 6)


if __name__ == "__main__":
    unittest.main()
