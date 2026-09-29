"""
Unit tests for SOLVI Log Engine parsers.
Verifies all 7 dedicated parsers against synthetic payloads and real linaclog files.
"""

import os
import sys
import unittest

# Ensure scripts is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from log_engine import (
    LogCategory,
    LogParseResult,
    RTDManifestParser,
    AuditTrailParser,
    RtUdpLogParser,
    CcpLogParser,
    TrfLogParser,
    ControllerLogParser,
    OpticalCalibParser,
    LinacFolderAnalyzer,
    LinacExcelExporter,
    get_parser_for_file,
    parse_linac_log,
)

LINACLOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "linaclog"))


class TestLogEngineParsers(unittest.TestCase):

    def test_rtd_manifest_synthetic(self):
        sample = (
            "RTD Linac Console Manifest File\n"
            "Host Name . . . . . . . . . . . . : LinacHost01\n"
            "Linac ID                            : 9999\n"
            "Linac Name                          : TestLinac\n"
            "HT Hours                            : 123.4\n"
            "LT Hours                            : 567.8\n"
            "Linac Parameter Scale               : IEC1217\n"
        ).encode("utf-8")
        parser = RTDManifestParser()
        self.assertTrue(parser.can_parse("RTDManifest.txt", sample))
        res = parser.parse_bytes(sample)
        self.assertTrue(res.success)
        self.assertEqual(res.category, LogCategory.RTD_MANIFEST)
        self.assertEqual(res.summary["linac_id"], "9999")
        self.assertEqual(res.summary["ht_hours"], 123.4)
        self.assertEqual(res.summary["lt_hours"], 567.8)

    def test_rtd_manifest_real_file(self):
        fpath = os.path.join(LINACLOG_DIR, "RTDManifest.txt")
        if not os.path.exists(fpath):
            self.skipTest("RTDManifest.txt not in linaclog")
        res = parse_linac_log(fpath)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["linac_id"], "4574")
        self.assertEqual(res.summary["console_host"], "Elekta5")
        self.assertEqual(res.summary["ht_hours"], 712.1)

    def test_audit_trail_synthetic(self):
        header = "OCCURRED                        AUDIT_TRAIL_HOST_NAME                                           RT_EVENT_ID                     RT_EVENT_NAME                                                   RT_USER_ID                      RT_USER_NAME                    PATIENT_KEY                     PATIENT_ID                      LINAC_ID                        LINAC_NAME\n"
        dashes = "-" * 384 + "\n"
        row1 = (
            "2026-09-21 10:00:00.000         "  # 32
            "ELEKTA5                                                         "  # 64
            "12005                           "  # 32
            "Select Machine State Linac Reset                                "  # 64
            "7                               "  # 32
            "tecnologo                       "  # 32
            "                                "  # 32
            "                                "  # 32
            "4574                            "  # 32
            "05Elekta                        \n"  # 32
        )
        sample = (header + dashes + row1).encode("utf-8")
        parser = AuditTrailParser()
        self.assertTrue(parser.can_parse("AUDIT_TRAIL.TXT", sample))
        res = parser.parse_bytes(sample)
        self.assertTrue(res.success)
        self.assertEqual(len(res.events), 1)
        self.assertEqual(res.events[0]["event_name"], "Select Machine State Linac Reset")
        self.assertEqual(res.events[0]["user_name"], "tecnologo")
        self.assertEqual(res.events[0]["linac_id"], "4574")

    def test_audit_trail_real_file_bounded(self):
        fpath = os.path.join(LINACLOG_DIR, "AUDIT_TRAIL.TXT")
        if not os.path.exists(fpath):
            self.skipTest("AUDIT_TRAIL.TXT not in linaclog")
        res = parse_linac_log(fpath, max_records=50)
        self.assertTrue(res.success)
        self.assertGreater(len(res.events), 0)
        self.assertIn("linac_reset_count", res.summary)

    def test_rt_udp_synthetic_collisions_and_suspends(self):
        payload = (
            "9/18/2026 3:00:00 PM:\n"
            "MLC Collision (0): 15, dist: 450x10^-3, mod setpoint\n"
            "Suspend - Item     501  Code      74  value       2\n"
            "Suspend - Item     750  Code     162  value  -24063\n"
            "MLC NOT OK 07300\n"
        ).encode("utf-8")
        parser = RtUdpLogParser()
        self.assertTrue(parser.can_parse("rt-udp.0.log", payload))
        res = parser.parse_bytes(payload)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["total_collision_warnings"], 1)
        self.assertEqual(res.summary["total_suspension_interlocks"], 2)
        self.assertEqual(res.summary["mlc_not_ok_events"], 1)
        
        # Check details
        col_ev = [e for e in res.events if e["event_type"] == "MLC_COLLISION_WARNING"][0]
        self.assertEqual(col_ev["leaf_pair"], 15)
        self.assertEqual(col_ev["distance_mm"], 0.45)
        self.assertTrue(col_ev["setpoint_modified"])

        sus_ev = [e for e in res.events if e.get("item_id") == 750][0]
        self.assertIn("Y1 Leaf Bank", sus_ev["description"])

    def test_rt_udp_real_file(self):
        fpath = os.path.join(LINACLOG_DIR, "rt-udp.0.log")
        if not os.path.exists(fpath):
            self.skipTest("rt-udp.0.log not in linaclog")
        res = parse_linac_log(fpath, max_records=20)
        self.assertTrue(res.success)
        self.assertGreater(len(res.events), 0)

    def test_ccp_log_synthetic(self):
        payload = (
            "2026-09-21 01:27:33,855: WARN  - Elekta.CCP.Supervisor.Common.HeartbeatTracker - Missed heartbeat from 'Controller' 8192 time(s)\n"
            "2026-09-21 04:30:28,196: INFO  - Elekta.CCP.NetMQComms.NetMqComms - Added connection for the peer: peerId = Controller\n"
            "2026-09-21 05:10:04,112: ERROR - Elekta.CCP.NetMQComms.NetMqComms - Failed to send 'Heartbeat' message\n"
        ).encode("utf-8")
        parser = CcpLogParser()
        self.assertTrue(parser.can_parse("Elekta.CCP.Agent.SYSTEM.log", payload))
        res = parser.parse_bytes(payload)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["heartbeat_misses_count"], 1)
        self.assertEqual(res.summary["netmq_socket_failures"], 1)
        self.assertEqual(len(res.events), 3)

    def test_optical_calib_real_file(self):
        fpath = os.path.join(LINACLOG_DIR, "OPT Y1.xml")
        if not os.path.exists(fpath):
            self.skipTest("OPT Y1.xml not in linaclog")
        res = parse_linac_log(fpath)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["linac_id"], "4574")
        self.assertEqual(res.summary["total_leaves_calibrated"], 80)
        self.assertGreater(len(res.events), 0)

    def test_controller_log_real_file(self):
        fpath = os.path.join(LINACLOG_DIR, "LOG0001")
        if not os.path.exists(fpath):
            self.skipTest("LOG0001 not in linaclog")
        res = parse_linac_log(fpath, max_records=20)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["log_index"], 1)
        self.assertGreater(len(res.events), 0)
        # Check signal names are resolved
        sig_names = [e["signal_name"] for e in res.events]
        self.assertTrue(any("Leaf" in s for s in sig_names))

    def test_trf_real_file(self):
        import glob
        matches = glob.glob(os.path.join(LINACLOG_DIR, "*.trf"))
        if not matches:
            self.skipTest("No .trf files found in linaclog")
        res = parse_linac_log(matches[0], max_records=25)
        self.assertTrue(res.success)
        self.assertEqual(res.summary["linac_id"], "4574")
        self.assertGreater(res.summary["total_duration_sec"], 0)
        self.assertGreater(len(res.events), 0)
        # Check timeline event format
        ev0 = res.events[0]
        self.assertIn("time_sec", ev0)
        self.assertIn("dose_rate_mu_min", ev0)
        self.assertIn("gantry_deg", ev0)

    def test_dispatcher_routing(self):
        p_trf = get_parser_for_file("beam.trf")
        self.assertIsInstance(p_trf, TrfLogParser)

        p_audit = get_parser_for_file("AUDIT_TRAIL.TXT")
        self.assertIsInstance(p_audit, AuditTrailParser)

        p_udp = get_parser_for_file("rt-udp.1.log")
        self.assertIsInstance(p_udp, RtUdpLogParser)

        p_ccp = get_parser_for_file("Elekta.CCP.Agent.SYSTEM.log")
        self.assertIsInstance(p_ccp, CcpLogParser)

        p_ctl = get_parser_for_file("LOG0042")
        self.assertIsInstance(p_ctl, ControllerLogParser)

        p_opt = get_parser_for_file("OPT Y2.xml")
        self.assertIsInstance(p_opt, OpticalCalibParser)

        p_man = get_parser_for_file("RTDManifest.txt")
        self.assertIsInstance(p_man, RTDManifestParser)

    def test_api_linaclog_profile_endpoint(self):
        import api
        client = api.app.test_client()
        res = client.get("/api/linaclog/profile")
        self.assertIn(res.status_code, [200, 404])
        if res.status_code == 200:
            data = res.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["data"]["summary"]["linac_id"], "4574")

    def test_api_linaclog_files_endpoint(self):
        import api
        client = api.app.test_client()
        res = client.get("/api/linaclog/files")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("categories", data)
        self.assertIn("trf_treatment", data["categories"])

    def test_api_linaclog_parse_endpoint_file_name(self):
        import api
        client = api.app.test_client()
        res = client.post("/api/linaclog/parse", json={"file_name": "rt-udp.0.log", "max_records": 10})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["category"], "rt_udp_telemetry")

    def test_api_linaclog_parse_validation_error(self):
        import api
        client = api.app.test_client()
        res = client.post("/api/linaclog/parse", json={})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "validation_error")

    def test_api_linaclog_parse_file_upload(self):
        import api
        import io
        client = api.app.test_client()
        fake_manifest = b"RTD Linac Console Manifest File\nHost Name: TestHost\nLinac ID: 1234\n"
        data = {
            "file": (io.BytesIO(fake_manifest), "RTDManifest.txt"),
            "max_records": "10"
        }
        res = client.post("/api/linaclog/parse", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_data = res.get_json()
        self.assertTrue(res_data["ok"])
        self.assertEqual(res_data["result"]["category"], "rtd_manifest")

    def test_linac_folder_analyzer_real_folder(self):
        if not os.path.exists(LINACLOG_DIR):
            self.skipTest("linaclog directory not present")
        analyzer = LinacFolderAnalyzer(LINACLOG_DIR)
        res = analyzer.analyze(max_audit_records=50, max_trf_records=10)
        self.assertIn("executive_summary", res)
        self.assertIn("correlations", res)
        self.assertIn("inventory", res)
        exec_s = res["executive_summary"]
        self.assertEqual(exec_s["linac_id"], "4574")
        self.assertGreater(exec_s["total_files_scanned"], 0)
        self.assertGreater(exec_s["total_beams_delivered"], 0)
        self.assertGreater(exec_s["total_suspension_interlocks"], 0)

    def test_linac_folder_analyzer_nonexistent(self):
        analyzer = LinacFolderAnalyzer("non_existent_folder_dir_12345")
        with self.assertRaises(FileNotFoundError):
            analyzer.analyze()

    def test_linac_excel_exporter(self):
        self.assertTrue(LinacExcelExporter.is_available())
        import io
        import openpyxl

        mock_data = {
            "profile": {
                "linac_id": "4574",
                "linac_name": "05Elekta",
                "console_host": "ELEKTA5",
                "software_version": "Integrity 4.0.6",
                "ht_hours": 712.1,
                "lt_hours": 2578.0,
                "scale": "IEC1217",
            },
            "executive_summary": {
                "linac_id": "4574",
                "linac_name": "05Elekta",
                "console_host": "ELEKTA5",
                "software_version": "Integrity 4.0.6",
                "ht_hours": 712.1,
                "lt_hours": 2578.0,
                "scale": "IEC1217",
                "total_files_scanned": 11975,
                "total_volume_mb": 3221.5,
                "total_beams_delivered": 775,
                "total_mu_delivered": 664071.1,
                "total_suspension_interlocks": 7072,
                "total_mlc_collision_warnings": 41021,
                "total_linac_resets": 133,
                "total_heartbeat_misses": 1187,
            },
            "interlocks": {
                "total_suspensions": 7072,
                "total_collisions": 41021,
                "top_suspension_interlocks": [
                    {"item_id": 501, "description": "Interlock Maestro de Suspensión", "subsystem": "Hardware", "count": 4395},
                    {"item_id": 750, "description": "Error de Tolerancia de Posición Láminas Y1", "subsystem": "MLC Agility", "count": 2050},
                ],
                "suspension_events": [
                    {"timestamp": "2026-09-18 15:00:00", "item": 501, "code": 74, "value": 2, "description": "Interlock Maestro"},
                ],
                "collision_warnings": [
                    {"timestamp": "2026-09-18 15:00:00", "channel": 0, "leaf": 15, "dist_microns": 450, "dist_mm": 0.45},
                ],
            },
            "treatments": {
                "total_beams_count": 1,
                "total_mu_delivered": 100.5,
                "deliveries": [
                    {
                        "beam_name": "TestBeam",
                        "date_utc": "2026-09-18",
                        "total_duration_sec": 12.5,
                        "final_mu": 100.5,
                        "max_dose_rate_mu_min": 600,
                        "gantry_start": 0.0,
                        "gantry_end": 180.0,
                        "final_state": "Complete",
                    }
                ],
            },
            "audit_trail": {
                "total_events_scanned": 10,
                "linac_reset_count": 1,
                "login_count": 2,
                "records": [
                    {"occurred": "2026-09-18 12:00:00", "event_name": "Linac Reset", "user_name": "tecnologo", "details": "Reset"},
                ],
            },
            "supervisor": {
                "heartbeat_misses_count": 5,
                "netmq_errors_count": 2,
                "events": [
                    {"timestamp": "2026-09-18 12:00:00", "level": "WARN", "message": "Heartbeat dropped"},
                ],
            },
            "optical": {
                "leaf_bank": "Y1",
                "total_leaves_calibrated": 80,
                "overall_max_distortion_microns": 420.5,
                "leaves": [
                    {"leaf_index": 15, "calibration_points": 50, "max_distortion_microns": 420.5, "mean_distortion_microns": 210.0},
                ],
            },
            "correlations": [
                {
                    "title": "Correlación Causal Crítica",
                    "severity": "CRITICAL",
                    "detail": "Test correlation",
                }
            ],
        }

        buf = io.BytesIO()
        LinacExcelExporter.export(mock_data, output=buf)
        buf.seek(0)
        bytes_out = buf.getvalue()
        self.assertGreater(len(bytes_out), 0)
        # Verify valid ZIP / xlsx magic signature
        self.assertTrue(bytes_out.startswith(b"PK\x03\x04"))

        # Verify all 7 sheets exist
        wb = openpyxl.load_workbook(buf)
        expected_sheets = [
            "Resumen_Ejecutivo",
            "Interlocks_Hardware",
            "Colisiones_MLC_Agility",
            "Tratamientos_TRF",
            "Auditoria_Clinica",
            "Supervisor_CCP",
            "Calibracion_Optica",
        ]
        for s in expected_sheets:
            self.assertIn(s, wb.sheetnames)

    def test_api_linaclog_analyze_folder_endpoint(self):
        import api
        client = api.app.test_client()
        res = client.post("/api/linaclog/analyze-folder", json={"max_audit_records": 20, "max_trf_records": 5})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("executive_summary", data["data"])
        self.assertEqual(data["data"]["executive_summary"]["linac_id"], "4574")

    def test_api_linaclog_export_excel_endpoint(self):
        import api
        client = api.app.test_client()
        res = client.get("/api/linaclog/export-excel")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self.assertIn("attachment; filename=", res.headers.get("Content-Disposition", ""))
        self.assertTrue(res.data.startswith(b"PK\x03\x04"))

    def test_api_linaclog_upload_folder_endpoint(self):
        import api
        import io
        client = api.app.test_client()
        fake_manifest = b"RTD Linac Console Manifest File\nHost Name: UploadHost\nLinac ID: 8888\nHT Hours: 50.0\nLT Hours: 100.0\n"
        data = {
            "files": (io.BytesIO(fake_manifest), "RTDManifest.txt"),
            "max_audit_records": "10",
            "max_trf_records": "5",
        }
        res = client.post("/api/linaclog/upload-folder", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        res_data = res.get_json()
        self.assertTrue(res_data["ok"])
        self.assertEqual(res_data["files_processed"], 1)
        self.assertEqual(res_data["data"]["profile"]["linac_id"], "8888")


    def test_api_linaclog_analyze_folder_quoted_path(self):
        import api
        client = api.app.test_client()
        # Verify path with surrounding quotes is cleanly stripped and processed
        quoted_path = f'"{api.LINACLOG_DIR}"'
        res = client.post("/api/linaclog/analyze-folder", json={"folder_path": quoted_path, "max_audit_records": 10})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["profile"]["linac_id"], "4574")

    def test_api_linaclog_chunked_upload_flow(self):
        import api
        import io
        client = api.app.test_client()
        session_id = "test_chunk_sess_123"

        # Chunk 1: Manifest
        fake_manifest = b"RTD Linac Console Manifest File\nHost Name: ChunkHost\nLinac ID: 9999\nHT Hours: 12.3\nLT Hours: 45.6\n"
        data1 = {
            "session_id": session_id,
            "files": (io.BytesIO(fake_manifest), "RTDManifest.txt")
        }
        res1 = client.post("/api/linaclog/upload-chunk", data=data1, content_type="multipart/form-data")
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.get_json()["ok"])

        # Chunk 2: Fake audit file
        fake_audit = b"2026-09-20 10:00:00 [INFO] System reset completed\n"
        data2 = {
            "session_id": session_id,
            "files": (io.BytesIO(fake_audit), "AuditTrail.txt")
        }
        res2 = client.post("/api/linaclog/upload-chunk", data=data2, content_type="multipart/form-data")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json()["ok"])

        # Finalize
        res_fin = client.post("/api/linaclog/finalize-upload", json={"session_id": session_id})
        self.assertEqual(res_fin.status_code, 200)
        fin_data = res_fin.get_json()
        self.assertTrue(fin_data["ok"])
        self.assertEqual(fin_data["files_processed"], 2)
        self.assertEqual(fin_data["data"]["profile"]["linac_id"], "9999")


if __name__ == "__main__":
    unittest.main()


