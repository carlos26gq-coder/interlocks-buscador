"""
SOLVI - Log Engine: Controller Log Parser
Dedicated parser for Elekta Linac internal real-time controller circular buffer logs (LOGxxxx).
"""

import os
import struct
import datetime
import json
from typing import Optional, Dict, Any, List
from .base_parser import BaseLogParser, LogCategory, LogParseResult

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "elekta_item_parts.json")

_CACHED_ITEM_NAMES: Optional[Dict[str, str]] = None

def _get_item_name_map() -> Dict[str, str]:
    global _CACHED_ITEM_NAMES
    if _CACHED_ITEM_NAMES is None:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                _CACHED_ITEM_NAMES = data.get("item_part_names", {})
        else:
            _CACHED_ITEM_NAMES = {}
    return _CACHED_ITEM_NAMES


class ControllerLogParser(BaseLogParser):
    """Parses binary sequential circular buffer parameter logs from the Linac Controller (LOGxxxx)."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.CONTROLLER_LOG

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        base = os.path.basename(filename)
        # Match pattern LOG0001, LOG9317 (starts with LOG and has 4 digits, no extension)
        if base.startswith("LOG") and len(base) == 7 and base[3:].isdigit():
            return True
        if len(sample_bytes) >= 18:
            # Check year byte 18..26 in uint16
            y = struct.unpack("<H", sample_bytes[:2])[0]
            if 15 <= y <= 35:
                # Check unix timestamp at offset 14..18
                ts = struct.unpack("<I", sample_bytes[14:18])[0]
                return 1500000000 <= ts <= 1900000000
        return False

    def parse_file(self, file_path: str, max_records: Optional[int] = 100, **kwargs) -> LogParseResult:
        if not os.path.exists(file_path):
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"File not found: {file_path}"]
            )
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            return self.parse_bytes(data, os.path.basename(file_path), max_records=max_records)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"Error reading controller log file: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "LOG0001", max_records: Optional[int] = 100, **kwargs) -> LogParseResult:
        if len(data) < 36:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=["File data is smaller than minimum controller header (36 bytes)"]
            )

        try:
            y, d, m = struct.unpack("<3H", data[:6])
            year = 2000 + y if y < 100 else y
            date_str = f"{year:04d}-{m:02d}-{d:02d}"

            unix_ts = struct.unpack("<I", data[14:18])[0]
            dt = datetime.datetime.fromtimestamp(unix_ts, datetime.timezone.utc)
            timestamp_iso = dt.isoformat()

            log_index = struct.unpack("<H", data[18:20])[0]
            scale_min, scale_max = struct.unpack("<HH", data[20:24])

            name_map = _get_item_name_map()

            # Parse parameter records in the payload (records are 6 bytes: item_id, property_code, value)
            events: List[Dict[str, Any]] = []
            
            # Start after header
            offset = 36
            while offset + 6 <= len(data):
                item_id, prop_code, raw_val = struct.unpack("<HHh", data[offset : offset + 6])
                offset += 6

                # Filter valid item_ids
                if item_id == 0 or item_id > 3000 or prop_code > 500:
                    continue

                sig_key = f"{item_id}_{prop_code}"
                sig_name = name_map.get(sig_key)
                if not sig_name:
                    continue

                # Scale value (positions and angles divided by 100.0 or 10.0 depending on property)
                scaled_val = raw_val / 100.0 if prop_code == 129 else float(raw_val)

                events.append({
                    "item_id": item_id,
                    "property_code": prop_code,
                    "signal_name": sig_name,
                    "raw_value": raw_val,
                    "scaled_value": round(scaled_val, 2),
                })

                if max_records and len(events) >= max_records:
                    break

            metadata = {
                "log_index": log_index,
                "recorded_date": date_str,
                "timestamp_utc": timestamp_iso,
                "total_file_bytes": len(data),
            }

            summary = {
                "log_index": log_index,
                "timestamp": timestamp_iso,
                "total_signals_extracted": len(events),
            }

            return LogParseResult(
                success=True,
                category=self.category,
                source_name=source_name,
                metadata=metadata,
                summary=summary,
                events=events
            )
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Error decoding controller log: {str(e)}"]
            )
