"""
SOLVI - Log Engine: Optical Calibration XML Parser
Dedicated parser for Elekta Agility MLC optical leaf calibration files (OPT Y1.xml, OPT Y2.xml).
"""

import os
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from .base_parser import BaseLogParser, LogCategory, LogParseResult


class OpticalCalibParser(BaseLogParser):
    """Parses XML optical distortion calibration curves for the 160 leaves of the Elekta Agility MLC."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.OPTICAL_CALIBRATION

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        lower = os.path.basename(filename).lower()
        if lower.startswith("opt y") and lower.endswith(".xml"):
            return True
        sample_str = sample_bytes[:256].decode("utf-8", errors="replace")
        return "<Chart>" in sample_str and "optics distortion" in sample_str

    def parse_file(self, file_path: str, max_records: Optional[int] = 80, **kwargs) -> LogParseResult:
        if not os.path.exists(file_path):
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"File not found: {file_path}"]
            )
        try:
            tree = ET.parse(file_path)
            return self._parse_tree(tree.getroot(), os.path.basename(file_path), max_records)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"Error parsing XML file: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "OPT.xml", max_records: Optional[int] = 80, **kwargs) -> LogParseResult:
        try:
            root = ET.fromstring(data)
            return self._parse_tree(root, source_name, max_records)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Error decoding XML bytes: {str(e)}"]
            )

    def _parse_tree(self, root: ET.Element, source_name: str, max_records: Optional[int]) -> LogParseResult:
        linac_elem = root.find("Linac")
        linac_id = linac_elem.get("Id", "Unknown") if linac_elem is not None else "Unknown"
        
        version_elem = root.find("Version")
        version_str = version_elem.get("Version", "1.0") if version_elem is not None else "1.0"

        series_elems = root.findall(".//series")
        total_leaves = len(series_elems)

        bank = "Y1 (Left Bank)" if "y1" in source_name.lower() else "Y2 (Right Bank)"

        leaf_summaries: List[Dict[str, Any]] = []
        max_distortions = []

        for idx, series in enumerate(series_elems):
            if max_records and idx >= max_records:
                break

            title = series.get("title", f"Leaf {idx+1}")
            pts_elem = series.find("points")
            pt_count = int(pts_elem.get("count", "0")) if pts_elem is not None else 0

            distortions = []
            sample_curve = []

            if pts_elem is not None:
                all_pts = pts_elem.findall("point")
                for pt in all_pts:
                    try:
                        x_mm = float(pt.get("X", 0)) / 1000.0
                        y_um = int(pt.get("Y", 0))
                        distortions.append(abs(y_um))
                    except ValueError:
                        continue

                # Sample 10 points along travel range for compact plotting
                if all_pts:
                    step = max(1, len(all_pts) // 10)
                    for i in range(0, len(all_pts), step):
                        p = all_pts[i]
                        sample_curve.append({
                            "position_mm": round(float(p.get("X", 0)) / 1000.0, 2),
                            "distortion_microns": int(p.get("Y", 0))
                        })

            peak_dist_um = max(distortions) if distortions else 0
            mean_dist_um = (sum(distortions) / len(distortions)) if distortions else 0
            max_distortions.append(peak_dist_um)

            leaf_summaries.append({
                "leaf_index": idx + 1,
                "title": title,
                "calibration_points_count": pt_count,
                "peak_distortion_microns": peak_dist_um,
                "mean_distortion_microns": round(mean_dist_um, 1),
                "samples_curve": sample_curve
            })

        summary = {
            "linac_id": linac_id,
            "leaf_bank": bank,
            "total_leaves_calibrated": total_leaves,
            "overall_max_distortion_microns": max(max_distortions) if max_distortions else 0,
            "overall_mean_distortion_microns": round(sum(max_distortions) / len(max_distortions), 1) if max_distortions else 0,
        }

        return LogParseResult(
            success=True,
            category=self.category,
            source_name=source_name,
            metadata={"version": version_str, "linac_id": linac_id},
            summary=summary,
            events=leaf_summaries
        )
