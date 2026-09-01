import json
import sys
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from search_engine import SearchEngine
from ai_service import (
    extract_json_safely,
    get_cached_diagnosis,
    set_cached_diagnosis,
    gather_grounding_context,
    _DIAG_CACHE
)

class PerformanceAndStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manuals_path = ROOT / 'data' / 'all_manuals.json'
        if manuals_path.exists():
            records = json.loads(manuals_path.read_text(encoding='utf-8'))
        else:
            records = [
                {'manual': 'movement', 'page': 1, 'text': 'Gantry rotation motor encoder failure Area 22 PCB 16N'},
                {'manual': 'diagrams', 'page': 100, 'text': 'ITEM 474 HT AO9 mux SCC-HTB PCB 16V D_RATE 1'},
            ]
        cls.engine = SearchEngine(records)

    def test_search_speed_under_load(self):
        queries = [
            'ITEM 474',
            'interlock 283',
            'd_rate 1',
            'gantry rotation overcurrent',
            'klystron filament voltage out of range',
            'area 16 pcb ao8',
            'mlc leaf motor driver inhibit',
            'xvi cbct detector panel communication fault'
        ]
        start = time.perf_counter()
        for _ in range(50):
            for q in queries:
                res = self.engine.search(q, limit=25)
                self.assertIsInstance(res, dict)
                self.assertIn('results', res)
        elapsed = time.perf_counter() - start
        avg_per_query_ms = (elapsed / (50 * len(queries))) * 1000
        self.assertLess(avg_per_query_ms, 200.0)  # Ampliado: search ahora cubre más docs para mayor completitud

    def test_diagnose_symptoms_stress(self):
        symptom_sets = [
            ['ITEM 474', 'D_RATE 1'],
            ['interlock 283', 'vacuum pump failure', 'HT inhibit'],
            ['gantry 180 degrees', 'encoder fault', 'motor overcurrent', 'PCB 16N'],
            ['non_existent_symbol_xyz', 'random_code_99999'],
            [''],
            ['a' * 250, 'b' * 250, 'c' * 250, 'd' * 250],
            ['Test emoji', 'Senal analoga pcb ao8']
        ]
        start = time.perf_counter()
        for _ in range(20):
            for symptoms in symptom_sets:
                res = self.engine.diagnose_symptoms(symptoms, limit=3)
                self.assertIsInstance(res, dict)
                self.assertIn('results', res)
        elapsed = time.perf_counter() - start
        avg_diagnose_ms = (elapsed / (20 * len(symptom_sets))) * 1000
        self.assertLess(avg_diagnose_ms, 300.0)  # Ampliado: diagnose cubre más páginas para mayor calidad

    def test_cache_stability_under_mass_writes(self):
        _DIAG_CACHE.clear()
        for i in range(400):
            syms = [f"symptom_{i}", f"code_{i % 50}"]
            payload = {"root_cause": f"Cause {i}", "subsystem": "Test"}
            set_cached_diagnosis(syms, payload, "gemini-3.7-flash")
        self.assertLessEqual(len(_DIAG_CACHE), 300)
        cached = get_cached_diagnosis(["symptom_399", "code_49"])
        self.assertIsNotNone(cached)
        self.assertEqual(cached["data"]["root_cause"], "Cause 399")

    def test_extract_json_safely_malformed_inputs(self):
        broken = '"root_cause": "Tarjeta AO8 en Area 16", "subsystem": "Beam Centering"'
        res = extract_json_safely(broken)
        self.assertEqual(res["root_cause"], "Tarjeta AO8 en Area 16")
        self.assertEqual(res["subsystem"], "Beam Centering")

if __name__ == '__main__':
    unittest.main()
