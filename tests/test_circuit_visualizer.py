"""SOLVI - Pruebas Unitarias del Visualizador Interactivo de Esquemas SVG (Circuit Visualizer)."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api import app
from circuit_data import SUBSYSTEMS, get_all_subsystems, get_subsystem, match_subsystem_for_trace


class CircuitVisualizerSuite(unittest.TestCase):
    """Pruebas del catálogo de subsistemas, topología de circuitos SVG y resolución."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    # ─── 1. INTEGRIDAD DE LOS 5 SUBSISTEMAS ──────────────────────────────────

    def test_all_five_key_subsystems_exist(self):
        """Verifica que los 5 subsistemas de aceleradores Elekta estén definidos."""
        expected_ids = {
            "safety_loop",
            "radiation_beam",
            "dosimetry",
            "gantry_collimator",
            "vacuum_gun"
        }
        self.assertEqual(set(SUBSYSTEMS.keys()), expected_ids)

        all_subs = get_all_subsystems()
        self.assertEqual(len(all_subs), 5)
        for s in all_subs:
            self.assertIn("id", s)
            self.assertIn("name", s)
            self.assertIn("short_name", s)
            self.assertIn("badge", s)
            self.assertIn("icon", s)
            self.assertGreater(s["nodes_count"], 10)
            self.assertGreater(s["wires_count"], 10)
            self.assertGreater(len(s["manual_references"]), 0)

    def test_subsystem_nodes_and_coordinates_validity(self):
        """Verifica que todos los nodos tengan coordenadas, tipos válidos y especificaciones técnicas."""
        valid_types = {
            "pcb", "cable", "relay", "test_point", "interlock",
            "switch", "source", "sensor", "load", "connector", "signal"
        }

        for sub_id, sub in SUBSYSTEMS.items():
            self.assertIn("viewBox", sub)
            vb_parts = [int(p) for p in sub["viewBox"].split()]
            self.assertEqual(len(vb_parts), 4)
            vb_w, vb_h = vb_parts[2], vb_parts[3]

            node_ids = set()
            tps_count = 0
            pcbs_count = 0

            for node in sub["nodes"]:
                n_id = node["id"]
                self.assertNotIn(n_id, node_ids, f"ID duplicado '{n_id}' en subsistema {sub_id}")
                node_ids.add(n_id)

                self.assertIn("name", node)
                self.assertIn("code", node)
                self.assertIn(node["type"], valid_types, f"Tipo inválido '{node['type']}' en {n_id}")
                self.assertTrue(node.get("spec"), f"Falta especificación técnica en {n_id}")
                self.assertIn("manual", node)
                self.assertGreater(node.get("page", 0), 0)

                # Coordenadas dentro del viewBox
                self.assertGreaterEqual(node["x"], 0)
                self.assertGreaterEqual(node["y"], 0)
                self.assertLessEqual(node["x"] + node["width"], vb_w)
                self.assertLessEqual(node["y"] + node["height"], vb_h)

                if node["type"] == "test_point":
                    tps_count += 1
                elif node["type"] == "pcb":
                    pcbs_count += 1

            self.assertGreater(tps_count, 0, f"Subsistema {sub_id} debe tener puntos de prueba TP")
            self.assertGreater(pcbs_count, 0, f"Subsistema {sub_id} debe tener placas PCB")

    def test_subsystem_wires_connectivity(self):
        """Verifica que todas las conexiones entre nodos sean consistentes y apunten a nodos existentes."""
        for sub_id, sub in SUBSYSTEMS.items():
            node_ids = {n["id"] for n in sub["nodes"]}
            self.assertGreater(len(sub["wires"]), 10)
            for wire in sub["wires"]:
                self.assertIn("id", wire)
                self.assertIn(wire["from"], node_ids, f"Wire {wire['id']} 'from' {wire['from']} no existe en {sub_id}")
                self.assertIn(wire["to"], node_ids, f"Wire {wire['id']} 'to' {wire['to']} no existe en {sub_id}")
                self.assertIn("type", wire)
                self.assertGreaterEqual(len(wire.get("points", [])), 2)

    # ─── 2. EMPAREJAMIENTO DE SUBSISTEMAS Y TRAZAS ───────────────────────────

    def test_match_subsystem_for_trace_safety_loop(self):
        """Verifica resolución hacia bucle de seguridad con síntomas de interlock 283 o pulsador."""
        match = match_subsystem_for_trace(["INTERLOCK 283", "DOOR_SW_283", "E-STOP CON"])
        self.assertEqual(match["subsystem_id"], "safety_loop")
        self.assertIn("DOOR_SW_283", match["matched_nodes"])

    def test_match_subsystem_for_trace_radiation_beam(self):
        """Verifica resolución hacia modulador y radiación con ITEM 409 o tiratrón."""
        match = match_subsystem_for_trace(["ITEM 409", "modulador tiratron", "PCB 22"])
        self.assertEqual(match["subsystem_id"], "radiation_beam")
        self.assertIn("ITEM_409", match["matched_nodes"])

    def test_match_subsystem_for_trace_dosimetry(self):
        """Verifica resolución hacia dosimetría con cámara de ionización y canales."""
        match = match_subsystem_for_trace(["cámara de ionización", "dosis canal 1", "PCB 17"])
        self.assertEqual(match["subsystem_id"], "dosimetry")
        self.assertIn("ION_CHAMBER", match["matched_nodes"])

    def test_match_subsystem_for_trace_gantry_motion(self):
        """Verifica resolución hacia movimiento de gantry y colimador."""
        match = match_subsystem_for_trace(["gantry rotacion", "encoder servo", "PCB 25"])
        self.assertEqual(match["subsystem_id"], "gantry_collimator")
        self.assertIn("ENCODER_G", match["matched_nodes"])

    def test_match_subsystem_for_trace_vacuum_gun(self):
        """Verifica resolución hacia vacío y cañón de electrones."""
        match = match_subsystem_for_trace(["bomba de vacio ionica", "filamento cañon", "PCB 14"])
        self.assertEqual(match["subsystem_id"], "vacuum_gun")
        self.assertTrue(any("ION_PUMP" in n for n in match["matched_nodes"]))

    def test_generic_words_do_not_produce_false_subsystem_matches(self):
        """Términos genéricos como 'interlock' o 'cable' no deben forzar coincidencias espurias."""
        match = match_subsystem_for_trace(["interlock", "cable", "falla"])
        self.assertEqual(match["subsystem_id"], "safety_loop")
        self.assertEqual(len(match["matched_nodes"]), 0)

    # ─── 3. ACTIVOS ESTÁTICOS Y PARIDAD ──────────────────────────────────────

    def test_pattern_matching_word_boundaries_on_original_strings(self):
        """Verifica que el emparejador de nodos reconozca números de señal como '409' dentro de 'ITEM 409'."""
        match = match_subsystem_for_trace(["ITEM 409"])
        self.assertEqual(match["subsystem_id"], "radiation_beam")
        self.assertIn("ITEM_409", match["matched_nodes"])

    def test_cable_identifier_exactness(self):
        """Verifica que 'W10' resuelva hacia CABLE_W10 en safety_loop."""
        match = match_subsystem_for_trace(["CABLE W10"])
        self.assertEqual(match["subsystem_id"], "safety_loop")
        self.assertIn("CABLE_W10", match["matched_nodes"])

    def test_sw_bypasses_circuits_api(self):
        """Verifica que sw.js incluya /circuits en la lista de exclusión directa."""
        sw_code = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('url.pathname.startsWith("/circuits")', sw_code)

    def test_static_circuit_assets_served_cleanly(self):
        """Verifica que el frontend SVG y la definición JSON se sirvan sin fugas de descriptores."""
        with self.client.get("/static/circuit-visualizer.js") as res_js:
            self.assertEqual(res_js.status_code, 200)
            self.assertIn("CircuitVisualizer", res_js.get_data(as_text=True))

        with self.client.get("/static/circuit_schematics.json") as res_json:
            self.assertEqual(res_json.status_code, 200)
            json_data = res_json.get_json()
            self.assertIn("safety_loop", json_data)
            self.assertEqual(len(json_data), 5)


if __name__ == "__main__":
    unittest.main()
