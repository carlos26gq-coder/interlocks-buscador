"""
SOLVI - Log Engine: RT-UDP Telemetry & Interlocks Parser
Dedicated parser for Elekta Real-Time UDP datagram logs (rt-udp.*.log).
"""

import os
import re
from typing import Optional, Dict, Any, List
from collections import Counter
from .base_parser import BaseLogParser, LogCategory, LogParseResult

# Biomedical hardware mapping for Elekta Integrity internal suspension items
SUSPEND_ITEM_DESCRIPTIONS = {
    501: "Master Linac Controller Interlock (Radiation Beam Inhibit)",
    99: "MLC Subsystem Interlock (Agility Comm / Leaf Velocity Fault)",
    750: "Y1 Leaf Bank Positioning Tolerance Exceeded (Bank 1)",
    765: "Y2 Leaf Bank Positioning Tolerance Exceeded (Bank 2)",
    752: "Agility Leaf Travel Limit Exceeded",
    201: "Gantry Rotational Motion Tolerance Exceeded",
    218: "Patient Couch / Table Motion Position Error",
    419: "Dosimetry Channel / Pulse Repetition Frequency (PRF) Interlock",
}


class RtUdpLogParser(BaseLogParser):
    """Parses real-time UDP diagnostics recording MLC leaf collision warnings and hardware suspension interlocks."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.RT_UDP_TELEMETRY

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        lower = os.path.basename(filename).lower()
        if "rt-udp" in lower and lower.endswith(".log"):
            return True
        sample_str = sample_bytes[:256].decode("utf-8", errors="replace")
        return "MLC Collision" in sample_str or "MLC NOT OK" in sample_str or "Suspend - Item" in sample_str

    def parse_file(self, file_path: str, max_records: Optional[int] = 500, **kwargs) -> LogParseResult:
        if not os.path.exists(file_path):
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"File not found: {file_path}"]
            )
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._parse_lines(content.splitlines(), os.path.basename(file_path), max_records)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"Error parsing rt-udp log: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "rt-udp.log", max_records: Optional[int] = 500, **kwargs) -> LogParseResult:
        try:
            content = data.decode("utf-8", errors="replace")
            return self._parse_lines(content.splitlines(), source_name, max_records)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Error decoding rt-udp bytes: {str(e)}"]
            )

    def _parse_lines(self, lines: List[str], source_name: str, max_records: Optional[int]) -> LogParseResult:
        events: List[Dict[str, Any]] = []
        interlock_counts = Counter()
        collision_leaves = Counter()
        current_timestamp = "Unknown"

        re_time = re.compile(r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+(?:AM|PM))", re.IGNORECASE)
        re_collision = re.compile(r"MLC Collision \((\d+)\):\s*(\d+),\s*dist:\s*([-\d]+)x10\^-3(?:,\s*(mod setpoint))?")
        re_suspend = re.compile(r"Suspend - Item\s+(\d+)\s+Code\s+(\d+)\s+value\s+([-\d]+)")

        mlc_fault_count = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Update timestamp if this line contains it
            tm = re_time.search(line_str)
            if tm:
                current_timestamp = tm.group(1)

            # Check MLC collision
            cm = re_collision.search(line_str)
            if cm:
                col_type = int(cm.group(1))
                leaf_id = int(cm.group(2))
                dist_raw = int(cm.group(3))
                dist_mm = dist_raw / 1000.0
                mod_setpoint = bool(cm.group(4))

                collision_leaves[leaf_id] += 1

                ev = {
                    "event_type": "MLC_COLLISION_WARNING",
                    "timestamp": current_timestamp,
                    "severity": "WARNING",
                    "leaf_pair": leaf_id,
                    "collision_type": col_type,
                    "distance_mm": round(dist_mm, 3),
                    "setpoint_modified": mod_setpoint,
                    "description": f"MLC leaf {leaf_id} distance approached {dist_mm:.3f} mm (anti-collision engaged)",
                }
                if max_records is None or len(events) < max_records:
                    events.append(ev)
                continue

            # Check hardware interlock suspend
            sm = re_suspend.search(line_str)
            if sm:
                item_id = int(sm.group(1))
                code = int(sm.group(2))
                val = int(sm.group(3))

                interlock_counts[item_id] += 1
                desc = SUSPEND_ITEM_DESCRIPTIONS.get(
                    item_id, f"Hardware Suspension Item {item_id} (Code {code})"
                )

                ev = {
                    "event_type": "HARDWARE_SUSPENSION_INTERLOCK",
                    "timestamp": current_timestamp,
                    "severity": "CRITICAL",
                    "item_id": item_id,
                    "code": code,
                    "value": val,
                    "description": desc,
                }
                if max_records is None or len(events) < max_records:
                    events.append(ev)
                continue

            # Check MLC Fault / State change
            if "MLC NOT OK" in line_str:
                mlc_fault_count += 1
                ev = {
                    "event_type": "MLC_STATE_FAULT",
                    "timestamp": current_timestamp,
                    "severity": "ERROR",
                    "raw_state": line_str,
                    "description": "MLC Collimator reported NOT OK state",
                }
                if max_records is None or len(events) < max_records:
                    events.append(ev)

        summary = {
            "total_collision_warnings": sum(collision_leaves.values()),
            "total_suspension_interlocks": sum(interlock_counts.values()),
            "mlc_not_ok_events": mlc_fault_count,
            "top_interlocked_items": [
                {
                    "item_id": item_id,
                    "count": count,
                    "description": SUSPEND_ITEM_DESCRIPTIONS.get(item_id, f"Item {item_id}")
                }
                for item_id, count in interlock_counts.most_common(5)
            ],
            "top_collision_leaf_pairs": dict(collision_leaves.most_common(5)),
        }

        return LogParseResult(
            success=True,
            category=self.category,
            source_name=source_name,
            summary=summary,
            events=events
        )
