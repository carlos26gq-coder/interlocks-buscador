import unittest
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "scripts" / "static"
CIRCUIT_VISUALIZER_JS = STATIC_DIR / "circuit-visualizer.js"
MULTIMETER_JS = STATIC_DIR / "multimeter.js"
SCHEMATICS_JSON = STATIC_DIR / "circuit_schematics.json"

class TechnicalWorkflowSuite(unittest.TestCase):
    def setUp(self):
        with open(CIRCUIT_VISUALIZER_JS, "r", encoding="utf-8") as f:
            self.cv_js = f.read()
        with open(MULTIMETER_JS, "r", encoding="utf-8") as f:
            self.mm_js = f.read()
        if SCHEMATICS_JSON.exists():
            with open(SCHEMATICS_JSON, "r", encoding="utf-8") as f:
                self.schematics = json.load(f)
        else:
            self.schematics = {}

    def test_workflow_schema_loading(self):
        """Verificar flujo de carga de esquemas."""
        self.assertIn("fetch(\"/static/circuit_schematics.json\")", self.cv_js)
        self.assertTrue(len(self.schematics) > 0, "Debe haber esquemas generados.")

    def test_workflow_tp_interaction(self):
        """Verificar interacción con puntos de prueba (TP)."""
        self.assertIn("inspeccionarNodo", self.cv_js)
        self.assertIn("medirEnMultimetro", self.cv_js)
        self.assertIn("exportarAApuntes", self.mm_js)

    def test_workflow_fault_simulation(self):
        """Verificar simulación de falla en componentes."""
        self.assertIn("function toggleNodeState", self.cv_js)
        self.assertIn("node._simState ===", self.cv_js)
        self.assertIn("FALLA/ABIERTO", self.cv_js)

    def test_workflow_search_and_filter(self):
        """Verificar búsqueda/filtro de cables y TPs."""
        self.assertIn("function buscarEnEsquema(texto)", self.cv_js)
        self.assertIn("_activeSubsystem.wires.forEach", self.cv_js)
        self.assertIn("_filterQuery.includes(\"POTENCIA\")", self.cv_js)
        self.assertIn("_filterQuery.includes(\"CONTROL\")", self.cv_js)

if __name__ == "__main__":
    unittest.main()