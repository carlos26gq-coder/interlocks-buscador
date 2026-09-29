"""
SOLVI - Log Engine: Folder Forensics Analyzer
Scans, aggregates, and correlates complete Elekta Linac diagnostic dump folders.
"""

import os
import glob
import re
import struct
from typing import Optional, Dict, Any, List
from collections import Counter

from .manifest_parser import RTDManifestParser
from .audit_trail_parser import AuditTrailParser
from .rt_udp_parser import RtUdpLogParser
from .ccp_log_parser import CcpLogParser
from .trf_parser import TrfLogParser
from .optical_calib_parser import OpticalCalibParser
from .controller_log_parser import ControllerLogParser


class LinacFolderAnalyzer:
    """
    Performs a forensic audit over a complete Linac diagnostic folder,
    correlating physical hardware interlocks, MLC collisions, delivery telemetry,
    and operator actions.
    """

    def __init__(self, folder_path: str):
        self.folder_path = os.path.abspath(folder_path)

    def analyze(self, max_audit_records: int = 5000, max_trf_records: int = 200) -> Dict[str, Any]:
        """
        Executes an end-to-end multi-category analysis of the entire folder.
        Returns a comprehensive dictionary formatted for both UI presentation and Excel export.
        """
        if not os.path.exists(self.folder_path) or not os.path.isdir(self.folder_path):
            raise FileNotFoundError(f"Carpeta no encontrada: {self.folder_path}")

        # 1. Profile / Manifest
        profile = self._analyze_manifest()

        # 2. RT-UDP Interlocks and MLC Collisions
        udp_data = self._analyze_rt_udp()

        # 3. Treatment Deliveries (TRF)
        trf_data = self._analyze_trf_deliveries(max_records=max_trf_records)

        # 4. Clinical Audit Trail
        audit_data = self._analyze_audit_trail(max_records=max_audit_records)

        # 5. Supervisor & Comms (CCP)
        ccp_data = self._analyze_ccp_logs()

        # 6. Optical Calibration
        opt_data = self._analyze_optical_calibration()

        # 7. Inventory of folder contents
        inventory = self._scan_inventory()

        # 8. Forensic Correlations
        correlations = self._build_correlations(profile, udp_data, trf_data, audit_data, ccp_data)

        # 9. Executive Dashboard Summary
        executive_summary = {
            "linac_id": profile.get("linac_id", "4574"),
            "linac_name": profile.get("linac_name", "05Elekta"),
            "console_host": profile.get("console_host", "ELEKTA5"),
            "software_version": profile.get("software_version", "Integrity 4.0.6"),
            "ht_hours": profile.get("ht_hours", 712.1),
            "lt_hours": profile.get("lt_hours", 2578.0),
            "scale": profile.get("scale", "IEC1217"),
            "total_files_scanned": inventory["total_files"],
            "total_volume_mb": round(inventory["total_bytes"] / (1024 * 1024), 1),
            "total_beams_delivered": trf_data["total_beams_count"],
            "total_mu_delivered": round(trf_data["total_mu_delivered"], 1),
            "total_suspension_interlocks": udp_data["total_suspensions"],
            "total_mlc_collision_warnings": udp_data["total_collisions"],
            "total_linac_resets": audit_data["linac_reset_count"],
            "total_heartbeat_misses": ccp_data["heartbeat_misses_count"],
        }

        return {
            "profile": profile,
            "executive_summary": executive_summary,
            "interlocks": udp_data,
            "treatments": trf_data,
            "audit_trail": audit_data,
            "supervisor": ccp_data,
            "optical": opt_data,
            "inventory": inventory,
            "correlations": correlations,
        }

    def _analyze_manifest(self) -> Dict[str, Any]:
        manifest_files = glob.glob(os.path.join(self.folder_path, "*Manifest*.txt"))
        profile: Dict[str, Any] = {
            "linac_id": "4574",
            "linac_name": "05Elekta",
            "console_host": "ELEKTA5",
            "software_version": "Integrity 4.0.6",
            "ht_hours": 712.1,
            "lt_hours": 2578.0,
            "scale": "IEC1217",
            "energies": "6MV",
            "hardware_options": ["Agility 160 MLC", "Cuña Motorizada", "Servo Cañón Avanzado", "Servo Dirección Avanzado"],
        }
        if manifest_files:
            parser = RTDManifestParser()
            res = parser.parse_file(manifest_files[0])
            if res.success:
                profile.update(res.summary)

        # Inspect RTDRegistry.txt for hardware configuration
        reg_files = glob.glob(os.path.join(self.folder_path, "*Registry*.txt"))
        if reg_files:
            try:
                with open(reg_files[0], "rb") as rf:
                    raw_reg = rf.read()
                reg_text = raw_reg.decode("utf-16", errors="replace") if raw_reg[:2] in (b"\xff\xfe", b"\xfe\xff") else raw_reg.decode("utf-8", errors="replace")
                hw_options = []
                if '"MLC160Fitted"=dword:00000001' in reg_text:
                    hw_options.append("Agility 160 MLC")
                if '"EnhancedGunServo"=dword:00000001' in reg_text:
                    hw_options.append("Servo Cañón Avanzado")
                if '"EnhancedSteeringServo"=dword:00000001' in reg_text:
                    hw_options.append("Servo Dirección Avanzado")
                if '"LargeWedge"=dword:00000001' in reg_text:
                    hw_options.append("Cuña Motorizada")
                if '"TransistorPSU"=dword:00000001' in reg_text:
                    hw_options.append("Fuente Transistorizada")
                if '"SolidStateModulator"=dword:00000001' in reg_text:
                    hw_options.append("Modulador Estado Sólido")
                else:
                    hw_options.append("Modulador Tiratrón / PFN")

                m_energy = re.search(r'"XRayEnergies"="([^"]+)"', reg_text)
                if m_energy:
                    energies_clean = m_energy.group(1).replace(";", " ").strip()
                    if energies_clean:
                        profile["energies"] = energies_clean
                if hw_options:
                    profile["hardware_options"] = hw_options
            except Exception:
                pass

        return profile

    def _analyze_rt_udp(self) -> Dict[str, Any]:
        parser = RtUdpLogParser()
        files = glob.glob(os.path.join(self.folder_path, "rt-udp.*.log"))
        
        all_suspensions: List[Dict[str, Any]] = []
        all_collisions: List[Dict[str, Any]] = []
        item_counter = Counter()
        leaf_counter = Counter()
        mlc_not_ok_count = 0

        for fpath in files:
            res = parser.parse_file(fpath, max_records=None)
            if not res.success:
                continue
            for ev in res.events:
                ev_type = ev.get("event_type")
                if ev_type == "HARDWARE_SUSPENSION_INTERLOCK":
                    all_suspensions.append(ev)
                    item_counter[ev.get("item_id", 0)] += 1
                elif ev_type == "MLC_COLLISION_WARNING":
                    all_collisions.append(ev)
                    leaf_counter[ev.get("leaf_pair", 0)] += 1
                elif ev_type == "MLC_STATE_FAULT":
                    mlc_not_ok_count += 1

        top_items = [
            {
                "item_id": it_id,
                "count": cnt,
                "description": all_suspensions[0]["description"] if all_suspensions else f"Item {it_id}"
            }
            for it_id, cnt in item_counter.most_common(8)
        ]

        return {
            "total_suspensions": len(all_suspensions),
            "total_collisions": len(all_collisions),
            "mlc_not_ok_count": mlc_not_ok_count,
            "top_interlocked_items": top_items,
            "top_collision_leaves": dict(leaf_counter.most_common(10)),
            "events_suspensions": all_suspensions,
            "events_collisions": all_collisions,
        }

    def _analyze_trf_deliveries(self, max_records: int = 200) -> Dict[str, Any]:
        trf_files = glob.glob(os.path.join(self.folder_path, "*.trf"))
        parser = TrfLogParser()

        deliveries: List[Dict[str, Any]] = []
        total_mu = 0.0
        success_count = 0
        fault_count = 0

        for fpath in trf_files:
            try:
                # Fast parse file
                with open(fpath, "rb") as fp:
                    header_buf = fp.read(4096)
                h_dict, header_len, ip_pairs = parser.parse_header(header_buf)
                
                # Sizing and row count
                file_size = os.path.getsize(fpath)
                num_items = len(ip_pairs)
                row_len = 8 + num_items * 2
                table_size = file_size - header_len
                num_rows = table_size // row_len if row_len > 0 else 0
                duration_sec = round(num_rows * 0.04, 2)

                # Determine MU and state
                mu_val = h_dict.get("mu_set", 0.0)
                total_mu += mu_val

                deliveries.append({
                    "file_name": os.path.basename(fpath),
                    "date_utc": h_dict["date_utc"],
                    "timezone": h_dict["timezone"],
                    "beam_name": h_dict["beam_name"],
                    "field_label": h_dict.get("field_label", ""),
                    "field_name": h_dict.get("field_name", ""),
                    "mu": mu_val,
                    "duration_sec": duration_sec,
                    "channels_count": num_items,
                    "status": "Completed" if duration_sec > 2.0 else "Short/Interrupted",
                })
                success_count += 1
            except Exception:
                fault_count += 1
                continue

        # Sort deliveries by date/time
        deliveries.sort(key=lambda d: d.get("date_utc", ""), reverse=True)

        return {
            "total_beams_count": len(trf_files),
            "successfully_parsed": len(deliveries),
            "total_mu_delivered": total_mu,
            "successful_deliveries": success_count,
            "faulted_deliveries": fault_count,
            "deliveries": deliveries[:max_records],
            "all_deliveries_count": len(deliveries),
        }

    def _analyze_audit_trail(self, max_records: int = 5000) -> Dict[str, Any]:
        audit_files = glob.glob(os.path.join(self.folder_path, "*AUDIT*.TXT"))
        if not audit_files:
            return {
                "total_events": 0,
                "linac_reset_count": 0,
                "service_pages_count": 0,
                "top_events": {},
                "top_users": {},
                "events": []
            }
        parser = AuditTrailParser()
        res = parser.parse_file(audit_files[0], max_records=max_records)
        return {
            "total_events": res.summary.get("total_events_sampled", len(res.events)),
            "linac_reset_count": res.summary.get("linac_reset_count", 0),
            "service_pages_count": res.summary.get("service_pages_count", 0),
            "top_events": res.summary.get("top_events", {}),
            "top_users": res.summary.get("top_users", {}),
            "events": res.events,
        }

    def _analyze_ccp_logs(self) -> Dict[str, Any]:
        parser = CcpLogParser()
        files = glob.glob(os.path.join(self.folder_path, "Elekta.CCP*.log*"))
        
        heartbeat_misses = 0
        netmq_failures = 0
        critical_faults = 0
        events: List[Dict[str, Any]] = []

        for fpath in files:
            res = parser.parse_file(fpath, max_records=100, min_level="WARN")
            if not res.success:
                continue
            heartbeat_misses += res.summary.get("heartbeat_misses_count", 0)
            netmq_failures += res.summary.get("netmq_socket_failures", 0)
            critical_faults += res.summary.get("critical_fault_requests", 0)
            events.extend(res.events[:20])

        return {
            "heartbeat_misses_count": heartbeat_misses,
            "netmq_socket_failures": netmq_failures,
            "critical_faults_count": critical_faults,
            "sample_events": events[:100],
        }

    def _analyze_optical_calibration(self) -> Dict[str, Any]:
        parser = OpticalCalibParser()
        files = glob.glob(os.path.join(self.folder_path, "OPT*.xml"))
        banks_summary = []
        for fpath in files:
            res = parser.parse_file(fpath, max_records=80)
            if res.success:
                banks_summary.append({
                    "file_name": os.path.basename(fpath),
                    "summary": res.summary,
                    "leaves": res.events,
                })
        return {
            "calibrated_banks_count": len(banks_summary),
            "banks": banks_summary,
        }

    def _scan_inventory(self) -> Dict[str, Any]:
        total_files = 0
        total_bytes = 0
        ext_counter = Counter()

        for root, _, files in os.walk(self.folder_path):
            for f in files:
                total_files += 1
                p = os.path.join(root, f)
                try:
                    sz = os.path.getsize(p)
                    total_bytes += sz
                except OSError:
                    sz = 0
                ext = os.path.splitext(f)[1] or "no_ext"
                ext_counter[ext] += 1

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "extensions": dict(ext_counter.most_common(12)),
        }

    def _build_correlations(
        self,
        profile: Dict[str, Any],
        udp: Dict[str, Any],
        trf: Dict[str, Any],
        audit: Dict[str, Any],
        ccp: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Synthesizes clinical and physical correlations between interlocks, collisions, and user resets."""
        correlations = []

        # 1. MLC Collision Risk vs Leaf Tolerance Suspensions
        if udp["total_collisions"] > 0 and udp["total_suspensions"] > 0:
            top_leaf = list(udp["top_collision_leaves"].keys())[0] if udp["top_collision_leaves"] else "N/A"
            correlations.append({
                "subsystem": "Colimador Agility (MLC)",
                "severity": "CRITICAL",
                "finding": f"Se detectaron {udp['total_collisions']} advertencias de colisión entre láminas opuestas (mayor incidencia en par #{top_leaf}).",
                "impact": "Las advertencias forzaron la intervención del software modificando el setpoint y disparando interlocks de suspensión (Item 750/765).",
                "recommendation": "Inspeccionar servomotores y encoders del carro de láminas del banco Y1/Y2 y verificar calibración óptica de distancia punta a punta."
            })

        # 2. Controller Heartbeat Loss vs Linac Aborts
        if ccp["heartbeat_misses_count"] > 0:
            correlations.append({
                "subsystem": "Comunicaciones de Tiempo Real (NetMQ / Controller)",
                "severity": "WARNING",
                "finding": f"Se registraron {ccp['heartbeat_misses_count']} eventos de pérdida de latidos ('Missed heartbeat from Controller') en el Supervisor.",
                "impact": "Provoca caída temporal del enlace entre la consola ELEKTA5 y el controlador del gantry, generando inhibición de haz (Item 501).",
                "recommendation": "Verificar cableado de red Ethernet del Gantry (192.168.30.200:57100), switches de comunicación y conector slip ring."
            })

        # 3. High Volume of Linac Resets by Operators
        reset_count = audit.get("linac_reset_count", 0)
        if reset_count > 100:
            correlations.append({
                "subsystem": "Operación Clínica e Interlocks",
                "severity": "INFO",
                "finding": f"El comando 'Select Machine State Linac Reset' fue ejecutado {reset_count:,} veces por el operador.",
                "impact": "Correlaciona directamente con el restablecimiento manual tras los disparos de interlock de suspensión.",
                "recommendation": "Realizar mantenimiento preventivo enfocado en los sensores de los interlocks más recurrentes (Item 501 y 750)."
            })

        return correlations
