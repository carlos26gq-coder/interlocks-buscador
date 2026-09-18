import unittest
import os
import sys
import math

# Ensure scripts dir is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

from log_parser_service import (
    parse_log_text,
    parse_timestamp,
    detect_date_locale,
    map_identifier_to_tp,
    mapIdentifierToTP,
)

class TestLogParser(unittest.TestCase):
    def test_parse_timestamp_iso(self):
        ts = parse_timestamp("2026-09-15 10:55:57.123")
        self.assertGreater(ts, 0)
        
    def test_parse_timestamp_ticks(self):
        ts = parse_timestamp("1614523456789")
        self.assertEqual(ts, 1614523456.789)

    def test_parse_timestamp_us_unequivocal(self):
        # Fecha US inequivoca: 12/25/2026 08:00:00 (mes 12, dia 25)
        ts = parse_timestamp("12/25/2026 08:00:00")
        self.assertGreater(ts, 0)

    def test_parse_timestamp_euro_unequivocal(self):
        # Fecha Euro inequivoca: 25/12/2026 08:00:00 (dia 25, mes 12)
        ts = parse_timestamp("25/12/2026 08:00:00")
        self.assertGreater(ts, 0)

    def test_parse_timestamp_invalid_not_nan(self):
        # Fechas invalidas o corruptas deben devolver 0.0 y nunca NaN
        ts = parse_timestamp("invalid 99/99/9999 99:99:99")
        self.assertFalse(math.isnan(ts))
        self.assertEqual(ts, 0.0)

        ts_empty = parse_timestamp("")
        self.assertFalse(math.isnan(ts_empty))
        self.assertEqual(ts_empty, 0.0)

    def test_detect_date_locale(self):
        us_log = "12/25/2026 08:00:00 ERROR Subsystem down"
        euro_log = "25/12/2026 08:00:00 ERROR Subsystem down"
        ambiguous_log = "05/06/2026 08:00:00 INFO System started"
        
        self.assertTrue(detect_date_locale(us_log))
        self.assertFalse(detect_date_locale(euro_log))
        self.assertFalse(detect_date_locale(ambiguous_log))  # Default euro

    def test_map_identifier_to_tp_strict(self):
        # ITEM 130 no debe devolver TP3 por contener el digito '3' ni caer en falso positivo
        self.assertNotEqual(mapIdentifierToTP("ITEM 130"), "TP3")
        self.assertIsNone(mapIdentifierToTP("ITEM 130"))

        # ERROR 53 no debe devolver TP5 por contener el digito '5' ni caer en falso positivo
        self.assertNotEqual(mapIdentifierToTP("ERROR 53"), "TP5")
        self.assertIsNone(mapIdentifierToTP("ERROR 53"))

        # Tokens reales validos deben mapear a sus TPs correspondientes
        self.assertEqual(mapIdentifierToTP("TP1"), "TP1")
        self.assertEqual(mapIdentifierToTP("TP3"), "TP3")
        self.assertEqual(mapIdentifierToTP("THYRATRON"), "TP3")
        self.assertEqual(mapIdentifierToTP("ITEM 474"), "TP3")
        self.assertEqual(mapIdentifierToTP("PCB 16N"), "TP5")
        self.assertEqual(mapIdentifierToTP("INTERLOCK 283"), "TP2")
        self.assertEqual(mapIdentifierToTP("ITEM 112"), "TP_VAC")
        self.assertEqual(map_identifier_to_tp("VAC_ION"), "TP_VAC")
        self.assertEqual(mapIdentifierToTP("TP7"), "TP7")
        self.assertEqual(mapIdentifierToTP("TP_DOSE1"), "TP_DOSE1")
        self.assertEqual(mapIdentifierToTP("TP_DOSE2"), "TP_DOSE2")
        self.assertEqual(mapIdentifierToTP("DOSE 1"), "TP_DOSE1")
        self.assertEqual(mapIdentifierToTP("GEN_CONT_LOOP"), "GEN_CONT_LOOP")
        self.assertEqual(mapIdentifierToTP("GEN_VOLT_15"), "GEN_VOLT_15")
        self.assertEqual(mapIdentifierToTP("GEN_VOLT_5"), "GEN_VOLT_5")
        self.assertIsNone(mapIdentifierToTP(None))
        self.assertIsNone(mapIdentifierToTP(""))
        self.assertIsNone(mapIdentifierToTP("   "))

    def test_us_dates_separate_cascades_not_merged(self):
        # Dos fallas separadas por 6 horas en formato US (12/25/2026) NO deben fusionarse en una cascada falsa
        log_data = """12/25/2026 08:00:00 ERROR ITEM 112 failed
12/25/2026 14:00:00 FATAL INTERLOCK 283 tripped cascade
"""
        res = parse_log_text(log_data)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["cascades"]), 2, "Dos fallas separadas por horas deben formar 2 cascadas distintas")
        self.assertEqual(len(res["cascades"][0]), 1)
        self.assertEqual(len(res["cascades"][1]), 1)
        self.assertGreater(res["cascades"][0][0]["timestamp"], 0)
        self.assertGreater(res["cascades"][1][0]["timestamp"], 0)
        self.assertNotEqual(res["cascades"][0][0]["timestamp"], res["cascades"][1][0]["timestamp"])

    def test_precursor_warning_detection(self):
        # WARNING ocurrido 1 segundo antes de la falla debe ser detectado como precursor
        log_data = """2026-09-15 10:55:57.000 WARNING Dosis rate mismatch
2026-09-15 10:55:58.000 ERROR ITEM 112 failed
2026-09-15 10:55:58.500 FATAL INTERLOCK 283 tripped cascade
"""
        res = parse_log_text(log_data)
        self.assertEqual(len(res["cascades"]), 1)
        cascade = res["cascades"][0]
        self.assertEqual(len(cascade), 2)  # ERROR y FATAL
        root_event = cascade[0]
        self.assertEqual(len(root_event.get("precursors", [])), 1)
        self.assertEqual(root_event["precursors"][0]["severity"], "WARNING")
        self.assertIn("Dosis rate mismatch", root_event["precursors"][0]["raw"])

    def test_precursor_outside_window_not_included(self):
        # WARNING ocurrido 12 segundos antes de la falla NO debe ser detectado como precursor (ventana de 5s)
        log_data = """2026-09-15 10:55:40.000 WARNING Pre-existing transient warning
2026-09-15 10:55:58.000 ERROR ITEM 112 failed
"""
        res = parse_log_text(log_data)
        self.assertEqual(len(res["cascades"]), 1)
        root_event = res["cascades"][0][0]
        self.assertEqual(len(root_event.get("precursors", [])), 0)

    def test_file_level_locale_detection_early_lines(self):
        # 05/01/2026 es ambiguo (5 de enero o 1 de mayo), pero 05/20/2026 es inequivoco US (mayo 20)
        # Ambas lineas deben parsearse bajo la convención US (mes 5)
        log_data = """05/01/2026 10:00:00 ERROR Event May 1st
05/20/2026 10:00:00 ERROR Event May 20th
"""
        res = parse_log_text(log_data)
        self.assertEqual(len(res["events"]), 2)
        import datetime
        dt1 = datetime.datetime.fromtimestamp(res["events"][0]["timestamp"])
        self.assertEqual(dt1.month, 5)
        self.assertEqual(dt1.day, 1)
        dt2 = datetime.datetime.fromtimestamp(res["events"][1]["timestamp"])
        self.assertEqual(dt2.month, 5)
        self.assertEqual(dt2.day, 20)

    def test_empty_or_whitespace_log(self):
        res = parse_log_text("   \n\n   \n")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["events"]), 0)
        self.assertEqual(len(res["cascades"]), 0)

    def test_parse_log_text(self):
        log_data = """2026-09-15 10:55:57.123 INFO Starting Linac
2026-09-15 10:55:58.000 ERROR ITEM 112 failed
2026-09-15 10:55:58.500 FATAL INTERLOCK 283 tripped cascade
2026-09-15 10:55:59.100 ERROR W12 signal lost
2026-09-15 10:56:10.000 INFO Recovery
"""
        res = parse_log_text(log_data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_lines"], 5)
        self.assertEqual(len(res["cascades"]), 1)
        self.assertEqual(len(res["cascades"][0]), 3)
        self.assertEqual(res["summary"]["fatals"], 1)
        self.assertEqual(res["summary"]["errors"], 2)
        
    def test_dirty_lines(self):
        log_data = "Just some random text\nERROR at 1614523456789 INTERLOCK 283"
        res = parse_log_text(log_data)
        self.assertEqual(res["total_lines"], 2)
        self.assertEqual(res["events"][1]["severity"], "ERROR")
        self.assertEqual(res["events"][1]["identifiers"], ["INTERLOCK 283"])

    def test_parse_timestamp_nanoseconds(self):
        # Timestamps con más de 6 dígitos fraccionarios deben parsearse truncando microsegundos sin fallar
        ts_iso = parse_timestamp("2026-09-15 10:55:57.123456789")
        self.assertGreater(ts_iso, 0.0)

        ts_slash = parse_timestamp("12/25/2026 08:00:00.987654321", is_us=True)
        self.assertGreater(ts_slash, 0.0)

    def test_untimestamped_distant_lines_not_merged(self):
        # Dos fallas sin timestamp (o con fecha corrupta) distantes entre sí NO deben formar una falsa cascada
        log_data = "line 10: corrupt_ts ERROR Primer fallo\n" + ("line normal: info\n" * 100) + "line 500: corrupt_ts ERROR Segundo fallo lejano\n"
        res = parse_log_text(log_data)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["cascades"]), 2, "Fallas sin timestamp separadas por 100 líneas no deben fusionarse")

    def test_untimestamped_consecutive_lines_merged(self):
        # Dos fallas sin timestamp en líneas consecutivas inmediatas SÍ pertenecen a la misma cascada
        log_data = "line 10: corrupt_ts ERROR Primer fallo consecutivo\nline 11: corrupt_ts FATAL Segundo fallo consecutivo\n"
        res = parse_log_text(log_data)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["cascades"]), 1)
        self.assertEqual(len(res["cascades"][0]), 2)

    def test_map_identifier_parity_tokens(self):
        # Tokens de paridad Linac específicos
        self.assertEqual(mapIdentifierToTP("MODULATOR"), "TP_HT")
        self.assertEqual(mapIdentifierToTP("MODULATION FAULT"), "TP_HT")
        self.assertEqual(mapIdentifierToTP("HT"), "TP_HT")
        self.assertEqual(mapIdentifierToTP("HT TRIP"), "TP_HT")
        self.assertEqual(mapIdentifierToTP("VACUUM"), "TP_VAC")
        self.assertEqual(mapIdentifierToTP("INTERLOCK 2"), "TP2")
        self.assertEqual(mapIdentifierToTP("PCB 3"), "TP3")
        self.assertEqual(mapIdentifierToTP("PCB 5"), "TP5")
        self.assertEqual(mapIdentifierToTP("KLYSTRON"), "TP_RF")
        self.assertEqual(mapIdentifierToTP("DOSIS"), "TP100")
        self.assertEqual(mapIdentifierToTP("DOSE"), "TP100")

    def test_api_logs_parse_endpoint(self):
        # Prueba de integración contra la API Flask /logs/parse
        import api
        client = api.app.test_client()
        payload = {
            "text": "12/25/2026 08:00:00 WARNING Pre-warning\n12/25/2026 08:00:02 ERROR ITEM 112 failed\n12/25/2026 14:00:00 FATAL INTERLOCK 283 tripped\n"
        }
        res = client.post("/logs/parse", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["cascades"]), 2)
        self.assertEqual(len(data["cascades"][0][0]["precursors"]), 1)
        self.assertIn("Pre-warning", data["cascades"][0][0]["precursors"][0]["raw"])

        # Verificación de validación de texto vacío
        res_err = client.post("/logs/parse", json={"text": ""})
        self.assertEqual(res_err.status_code, 400)
        data_err = res_err.get_json()
        self.assertFalse(data_err["ok"])
        self.assertEqual(data_err["error"], "validation_error")

    def test_static_js_parities_and_protections(self):
        js_path = os.path.join(os.path.dirname(__file__), '../scripts/static/log-parser.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_code = f.read()

        # P0-1: No debe existir 'const primaryId = identifiers[0]' huérfano
        self.assertNotIn("const primaryId = identifiers[0]", js_code)
        self.assertIn("rootEvent.identifiers", js_code)

        # P0-3: No debe existir catch-all suelto id.includes("3") o id.includes("5")
        self.assertNotIn('id.includes("3")', js_code)
        self.assertNotIn('id.includes("5")', js_code)

        # P0-4: Validacion de Number.isFinite
        self.assertIn("Number.isFinite", js_code)

        # P2-1: Uso de chunkResults en vez de concat cuadratico
        self.assertIn("chunkResults", js_code)

        # P2-3: Streaming TextDecoder
        self.assertIn("TextDecoder", js_code)

        # P3: Deteccion de precursores
        self.assertIn("precursor", js_code.lower())

    def test_no_ai_terminology(self):
        import re
        pattern = re.compile(r"\b(ai|ia)\b|inteligencia\s+artificial", re.IGNORECASE)
        for filename in ['../scripts/log_parser_service.py', '../scripts/static/log-parser.js']:
            with open(os.path.join(os.path.dirname(__file__), filename), 'r', encoding='utf-8') as f:
                content = f.read()
                matches = pattern.findall(content)
                self.assertEqual(matches, [], f"Se encontraron menciones prohibidas en {filename}: {matches}")

if __name__ == '__main__':
    unittest.main()

