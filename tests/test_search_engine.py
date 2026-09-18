"""SOLVI - Pruebas Unitarias del Motor de Búsqueda Indexado y Diagnóstico Relacional."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from search_engine import SearchEngine, normalize, tokens, _phrase_pattern, _query_tokens


class SearchEngineSuite(unittest.TestCase):
    """Pruebas exhaustivas para normalización, indexación invertida, búsqueda y diagnóstico."""

    @classmethod
    def setUpClass(cls):
        cls.sample_docs = [
            {
                "manual": "movement",
                "page": 10,
                "text": "Interlock 283 and Error 66. Reset motors. Check MLC leaf calibration when leaf is missing.",
            },
            {
                "manual": "movement",
                "page": 11,
                "text": "Interlock 283 can also occur after communication timeout. Restart the controller.",
            },
            {
                "manual": "vacuum",
                "page": 4,
                "text": "Error: 66. Examine the vacuum pump and verify the pressure sensor on PCB 14.",
            },
            {
                "manual": "technical",
                "page": 2,
                "text": "Calibración del movimiento de las láminas del colimador multiláminas (MLC).",
            },
            {
                "manual": "dosimetry",
                "page": 99,
                "text": "Calibrating the low dose rate monitor on dual channel ionization chamber.",
            },
            {
                "manual": "radiation",
                "page": 45,
                "text": "ITEM 409 and ITEM 474: High voltage modulator thyratron trigger pulse missing.",
            },
        ]
        cls.engine = SearchEngine(cls.sample_docs)

    # ─── 1. NORMALIZACIÓN Y TOKENIZACIÓN ─────────────────────────────────────

    def test_normalize_strips_accents_and_lowercases(self):
        """Verifica que la normalización elimine diacríticos y pase a minúsculas."""
        self.assertEqual(normalize("Calibración"), "calibracion")
        self.assertEqual(normalize("LÁMINAS"), "laminas")
        self.assertEqual(normalize("Cañón de Electrones"), "canon de electrones")
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize(None), "")

    def test_tokens_and_query_tokens(self):
        """Verifica extracción de tokens y filtrado de palabras vacías."""
        all_toks = tokens("El colimador y la dosis")
        self.assertEqual(all_toks, ["el", "colimador", "y", "la", "dosis"])

        q_toks = _query_tokens("El colimador y la dosis de radiación en 24V")
        self.assertIn("colimador", q_toks)
        self.assertIn("dosis", q_toks)
        self.assertIn("radiacion", q_toks)
        self.assertIn("24v", q_toks)
        self.assertNotIn("el", q_toks)
        self.assertNotIn("la", q_toks)
        self.assertNotIn("de", q_toks)
        self.assertNotIn("en", q_toks)

    def test_phrase_pattern_regex_generation(self):
        """Verifica que el patrón de frase admita separadores y palabras de enlace."""
        pat = _phrase_pattern("dose rate monitor")
        self.assertIsNotNone(pat)
        self.assertTrue(pat.search("low dose rate monitor"))
        self.assertTrue(pat.search("dose - rate - monitor"))
        self.assertTrue(pat.search("dose of rate in monitor"))
        self.assertFalse(pat.search("dose other word rate different monitor"))

    # ─── 2. BÚSQUEDA EXACTA Y TOLERANCIA ─────────────────────────────────────

    def test_exact_search_is_accent_insensitive(self):
        """Verifica que buscar sin tildes encuentre términos acentuados y viceversa."""
        res_no_acc = self.engine.search("calibracion", limit=10)
        self.assertEqual(res_no_acc["total"], 1)
        self.assertEqual(res_no_acc["results"][0]["manual"], "technical")

        res_with_acc = self.engine.search("calibración", limit=10)
        self.assertEqual(res_with_acc["total"], 1)
        self.assertEqual(res_with_acc["results"][0]["page"], 2)

    def test_exact_word_search_rejects_partial_substrings(self):
        """Rechaza subcadenas falsas: 'art' no debe coincidir con 'Restart' ni 'interl' con 'Interlock'."""
        res_partial = self.engine.search("interl", limit=10)
        self.assertEqual(res_partial["total"], 0, "No debe coincidir con prefijos parciales")

        res_inside = self.engine.search("art", limit=10)
        self.assertEqual(res_inside["total"], 0, "No debe coincidir con 'art' dentro de 'Restart'")

        res_full = self.engine.search("interlock", limit=10)
        self.assertEqual(res_full["total"], 2)

    def test_punctuation_tolerance(self):
        """Verifica que caracteres de puntuación entre términos no impidan la coincidencia."""
        res = self.engine.search("error 66", limit=10)
        # Debe coincidir en movement (pág 10: 'Error 66') y vacuum (pág 4: 'Error: 66.')
        self.assertEqual(res["total"], 2)

    def test_multi_word_avoids_scattered_false_positives(self):
        """Palabras que aparecen dispersas en un documento sin formar frase no deben dar falso positivo."""
        res = self.engine.search("vacuum leaf", limit=10)
        self.assertEqual(res["total"], 0)

    # ─── 3. PAGINACIÓN Y LÍMITES ─────────────────────────────────────────────

    def test_pagination_offset_and_limits(self):
        """Verifica límites de paginación y banderas has_more."""
        res_page1 = self.engine.search("interlock 283", offset=0, limit=1)
        self.assertEqual(res_page1["total"], 2)
        self.assertEqual(len(res_page1["results"]), 1)
        self.assertTrue(res_page1["has_more"])
        self.assertEqual(res_page1["offset"], 0)

        res_page2 = self.engine.search("interlock 283", offset=1, limit=1)
        self.assertEqual(len(res_page2["results"]), 1)
        self.assertFalse(res_page2["has_more"])
        self.assertNotEqual(res_page1["results"][0]["page"], res_page2["results"][0]["page"])

    def test_empty_and_whitespace_queries(self):
        """Entradas vacías o de sólo espacios devuelven lista vacía sin excepciones."""
        self.assertEqual(self.engine.search("")["total"], 0)
        self.assertEqual(self.engine.search("   ")["total"], 0)
        self.assertEqual(self.engine.search(None)["total"], 0)

    # ─── 4. DIAGNÓSTICO RELACIONAL MULTI-SEÑAL ───────────────────────────────

    def test_diagnose_symptoms_prioritizes_intersecting_evidence(self):
        """Verifica que el diagnóstico multi-síntoma priorice la página con mayor intersección de fallas."""
        symptoms = ["Interlock 283", "Error 66", "leaf missing"]
        res = self.engine.diagnose_symptoms(symptoms, limit=3)
        self.assertIn("results", res)
        self.assertGreater(len(res["results"]), 0)

        top_match = res["results"][0]
        self.assertEqual(top_match["manual"], "movement")
        self.assertEqual(top_match["page"], 10)
        self.assertEqual(top_match["confidence"], "alta")
        self.assertGreaterEqual(top_match["matched_count"], 2)

    def test_diagnose_legacy_dict_compatibility(self):
        """Verifica compatibilidad hacia atrás con el diccionario clásico de señales."""
        signals = {
            "interlock": "283",
            "error": "66",
            "message": "reset motors",
            "observations": "",
        }
        res = self.engine.diagnose(signals, limit=3)
        self.assertGreater(len(res["results"]), 0)
        self.assertEqual(res["results"][0]["page"], 10)

    # ─── 5. RESILIENCIA Y FUZZING ANTE REDOS ──────────────────────────────────

    def test_phrase_pattern_fuzzing_and_redos_resilience(self):
        """Verifica que entradas adversariales largas con separadores repetitivos no causen ReDoS ni excepciones."""
        import time
        # 1. Entrada larga con repetición de palabras clave y símbolos especiales
        adversarial_input = ("interlock " * 25) + ("--__///... " * 15) + "283"
        t0 = time.perf_counter()
        pat = _phrase_pattern(adversarial_input)
        self.assertIsNotNone(pat)
        target_text = "interlock " + ("_.- " * 400) + "283 safe"
        _ = pat.search(target_text)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.15, f"La ejecución del patrón tomó {elapsed:.4f}s; riesgo de ReDoS")

        # 2. Caracteres especiales de escape regex
        escaped_input = "interlock [283] (HT) +24V * ? ^ $ \\"
        pat_escaped = _phrase_pattern(escaped_input)
        self.assertIsNotNone(pat_escaped)
        self.assertTrue(bool(pat_escaped.pattern))


if __name__ == "__main__":
    unittest.main()
