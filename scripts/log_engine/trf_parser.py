"""
SOLVI - Log Engine: TRF Treatment Record Parser
Dedicated parser for Elekta Linac binary Treatment Record Files (*.trf) at 25 Hz.
"""

import os
import re
import json
import struct
from typing import Optional, Dict, Any, List, Tuple
from .base_parser import BaseLogParser, LogCategory, LogParseResult

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "elekta_item_parts.json")

_CACHED_CONFIG: Optional[Dict[str, Any]] = None

def _get_config() -> Dict[str, Any]:
    global _CACHED_CONFIG
    if _CACHED_CONFIG is None:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _CACHED_CONFIG = json.load(f)
        else:
            _CACHED_CONFIG = {}
    return _CACHED_CONFIG


class TrfLogParser(BaseLogParser):
    """Parses high-frequency (25 Hz / 40 ms) binary treatment delivery logs recorded by Elekta Integrity."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.TRF_TREATMENT

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        if filename.lower().endswith(".trf"):
            return True
        if len(sample_bytes) > 20 and sample_bytes[0] in [0x12, 0x13, 0x14, 0x15]:
            # Pascal string with date pattern e.g. 26/09/14 or 20/09/14
            s = sample_bytes[1:20].decode("ascii", errors="replace")
            return bool(re.match(r"\d\d[/|-]\d\d[/|-]\d\d \d\d:\d\d:\d\d", s))
        return False

    def parse_header(self, buf: bytes) -> Tuple[Dict[str, Any], int, List[Tuple[int, int]]]:
        """Decodes Pascal-string header, MU, version and channel item parts."""
        regex_trf = (
            rb"[\x00-\x19]"
            + rb"(\d\d[/|-]\d\d[/|-]\d\d \d\d:\d\d:\d\d Z)"
            + rb"[\x00-\x19]"
            + rb"([\+|\-]\d\d:\d\d)"
            + rb"[\x00-\x32]"
            + rb"([\x20-\x7F]*)"
            + rb"[\x00-\x10]"
            + rb"([\x20-\x7F]*)"
            + rb"([\x00-\xFF]*)"
        )
        m = re.match(regex_trf, buf[:2048])
        if not m:
            raise ValueError("TRF binary header format does not match Elekta specification")

        date_utc = m.group(1).decode("ascii")
        timezone = m.group(2).decode("ascii")
        beam_name = m.group(3).decode("ascii")
        linac_id = m.group(4).decode("ascii")
        
        span_end = m.span(4)[1]
        rest = buf[span_end:]
        
        mu_raw = struct.unpack("<d", rest[:8])[0]
        version = struct.unpack("<i", rest[8:12])[0]
        item_parts_num = struct.unpack("<i", rest[12:16])[0]
        
        header_len = span_end + 16 + 4 * item_parts_num
        ip_bytes = rest[16 : 16 + 4 * item_parts_num]
        ip_pairs = [struct.unpack("<hh", ip_bytes[i:i+4]) for i in range(0, len(ip_bytes), 4)]

        # Field label / Field name separation if present (e.g. "1-1/AP G0")
        field_label = ""
        field_name = beam_name
        if "/" in beam_name:
            parts = beam_name.split("/", 1)
            field_label, field_name = parts[0], parts[1]

        header_dict = {
            "date_utc": date_utc,
            "timezone": timezone,
            "field_label": field_label,
            "field_name": field_name,
            "beam_name": beam_name,
            "linac_id": linac_id,
            "mu_set": round(mu_raw / 10.0 if version >= 3 else mu_raw, 2),
            "version": version,
            "item_parts_count": len(ip_pairs),
        }
        return header_dict, header_len, ip_pairs

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
                errors=[f"Error reading TRF file: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "delivery.trf", max_records: Optional[int] = 100, **kwargs) -> LogParseResult:
        try:
            header_dict, header_len, ip_pairs = self.parse_header(data)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Failed to parse TRF header: {str(e)}"]
            )

        cfg = _get_config()
        linac_states = cfg.get("linac_state_codes", {})
        ip_name_map = cfg.get("item_part_names", {})

        # Map channel indices of critical physical parameters
        idx_gantry = None
        idx_collimator = None
        idx_dose_rate = None
        idx_step_dose = None
        idx_linac_state = None
        idx_y1_leaf40 = None
        idx_y2_leaf40 = None
        leaf_error_indices = []

        for idx, (it_id, pr_id) in enumerate(ip_pairs):
            k = f"{it_id}_{pr_id}"
            if it_id == 2224 and pr_id == 129:
                idx_gantry = idx
            elif it_id == 2225 and pr_id == 129:
                idx_collimator = idx
            elif it_id == 2542 and pr_id == 111:
                idx_dose_rate = idx
            elif it_id == 2238 and pr_id == 111:
                idx_step_dose = idx
            elif it_id == 2543 and pr_id == 111:
                idx_linac_state = idx
            elif it_id == 2499 and pr_id == 129: # Y1 Leaf 40
                idx_y1_leaf40 = idx
            elif it_id == 2419 and pr_id == 129: # Y2 Leaf 40
                idx_y2_leaf40 = idx
            elif pr_id == 220: # Positional Error
                leaf_error_indices.append(idx)

        # Table rows layout: 8 bytes int64 timestamp + len(ip_pairs) * 2 bytes int16
        num_items = len(ip_pairs)
        row_len = 8 + num_items * 2
        table_bytes = data[header_len:]
        num_rows = len(table_bytes) // row_len

        total_duration_sec = num_rows * 0.04
        dose_rate_values = []
        step_dose_final = 0.0
        gantry_start = None
        gantry_end = None
        max_leaf_error_mm = 0.0
        final_state = "Unknown"
        rad_on_samples = 0

        # Sample timeline evenly for visualization
        if max_records and num_rows > max_records:
            step = num_rows / max_records
            sampled_indices = [int(i * step) for i in range(max_records)]
            if sampled_indices[-1] != num_rows - 1 and num_rows > 0:
                sampled_indices[-1] = num_rows - 1
        else:
            sampled_indices = list(range(num_rows))

        timeline_events = []
        for r_idx in range(num_rows):
            offset = r_idx * row_len
            row = table_bytes[offset : offset + row_len]
            if len(row) < row_len:
                break
            
            vals = struct.unpack(f"<{num_items}h", row[8:])
            
            # Dose rate and dose
            d_rate = vals[idx_dose_rate] if idx_dose_rate is not None else 0
            dose_rate_values.append(d_rate)
            if d_rate > 0:
                rad_on_samples += 1

            s_dose = (vals[idx_step_dose] / 10.0) if idx_step_dose is not None else 0.0
            step_dose_final = s_dose

            # Gantry
            if idx_gantry is not None:
                g_val = vals[idx_gantry] / 10.0
                if gantry_start is None:
                    gantry_start = g_val
                gantry_end = g_val

            # Linac State
            st_code = str(vals[idx_linac_state]) if idx_linac_state is not None else "0"
            st_name = linac_states.get(st_code, f"State {st_code}")
            final_state = st_name

            # Check max leaf error
            for err_idx in leaf_error_indices:
                err_mm = abs(vals[err_idx]) / 10.0
                if err_mm > max_leaf_error_mm:
                    max_leaf_error_mm = err_mm

            # Record sampled event
            if r_idx in sampled_indices:
                t_sec = round(r_idx * 0.04, 2)
                y1_40 = (vals[idx_y1_leaf40] / 10.0) if idx_y1_leaf40 is not None else None
                y2_40 = (vals[idx_y2_leaf40] / 10.0) if idx_y2_leaf40 is not None else None
                timeline_events.append({
                    "time_sec": t_sec,
                    "gantry_deg": round(vals[idx_gantry] / 10.0, 1) if idx_gantry is not None else None,
                    "collimator_deg": round(vals[idx_collimator] / 10.0, 1) if idx_collimator is not None else None,
                    "dose_rate_mu_min": d_rate,
                    "step_dose_mu": round(s_dose, 2),
                    "linac_state": st_name,
                    "y1_leaf40_pos_mm": y1_40,
                    "y2_leaf40_pos_mm": y2_40,
                })

        summary = {
            "linac_id": header_dict["linac_id"],
            "beam_name": header_dict["beam_name"],
            "date_utc": header_dict["date_utc"],
            "total_duration_sec": round(total_duration_sec, 2),
            "radiation_on_sec": round(rad_on_samples * 0.04, 2),
            "final_mu_delivered": round(step_dose_final, 2),
            "max_dose_rate_mu_min": max(dose_rate_values) if dose_rate_values else 0,
            "mean_dose_rate_mu_min": round(sum(dose_rate_values) / len(dose_rate_values), 1) if dose_rate_values else 0,
            "gantry_start_deg": gantry_start,
            "gantry_end_deg": gantry_end,
            "gantry_arc_span_deg": round(abs((gantry_end or 0) - (gantry_start or 0)), 1) if (gantry_start and gantry_end) else 0.0,
            "max_leaf_position_error_mm": round(max_leaf_error_mm, 2),
            "final_linac_state": final_state,
            "delivery_successful": "ok" in final_state.lower() or final_state == "Closed",
            "total_timepoints_recorded": num_rows,
        }

        return LogParseResult(
            success=True,
            category=self.category,
            source_name=source_name,
            metadata=header_dict,
            summary=summary,
            events=timeline_events
        )
