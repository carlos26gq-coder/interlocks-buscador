"""
SOLVI - Log Engine: RTDManifest Parser
Dedicated parser for Elekta RTD Linac Console Manifest files (RTDManifest.txt).
"""

import os
import re
from typing import Optional, Dict, Any
from .base_parser import BaseLogParser, LogCategory, LogParseResult


class RTDManifestParser(BaseLogParser):
    """Parses Elekta RTD Console Manifest files containing system specs and beam hours."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.RTD_MANIFEST

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        lower_name = os.path.basename(filename).lower()
        if "manifest" in lower_name and lower_name.endswith(".txt"):
            return True
        sample_text = sample_bytes[:512].decode("utf-8", errors="replace")
        return "RTD Linac Console Manifest" in sample_text or "Linac Parameter Scale" in sample_text

    def parse_file(self, file_path: str, max_records: Optional[int] = None, **kwargs) -> LogParseResult:
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
            return self._parse_content(content, os.path.basename(file_path))
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"Failed to read manifest file: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "RTDManifest.txt", max_records: Optional[int] = None, **kwargs) -> LogParseResult:
        try:
            content = data.decode("utf-8", errors="replace")
            return self._parse_content(content, source_name)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Failed to decode manifest bytes: {str(e)}"]
            )

    def _parse_content(self, content: str, source_name: str) -> LogParseResult:
        metadata: Dict[str, Any] = {}
        patterns = {
            "created": r"Created:\s*([^\r\n]+)",
            "host_name": r"Host Name[\s\.]*:\s*([^\r\n]+)",
            "linac_id": r"Linac ID\s*:\s*([^\r\n]+)",
            "linac_name": r"Linac Name\s*:\s*([^\r\n]+)",
            "linac_scale": r"Linac Parameter Scale\s*:\s*([^\r\n]+)",
            "ht_hours": r"HT Hours\s*:\s*([^\r\n]+)",
            "lt_hours": r"LT Hours\s*:\s*([^\r\n]+)",
            "mac_address": r"Physical Address[\s\.]*:\s*([^\r\n]+)",
            "ip_address": r"IPv4 Address[\s\.]*:\s*([^\r\n]+)",
        }

        for key, pat in patterns.items():
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                metadata[key] = m.group(1).strip()

        # Extract beam hours as float numbers if present
        ht_val = None
        lt_val = None
        try:
            if "ht_hours" in metadata:
                ht_val = float(metadata["ht_hours"])
            if "lt_hours" in metadata:
                lt_val = float(metadata["lt_hours"])
        except ValueError:
            pass

        summary = {
            "linac_id": metadata.get("linac_id", "Unknown"),
            "linac_name": metadata.get("linac_name", "Unknown"),
            "console_host": metadata.get("host_name", "Unknown"),
            "ht_hours": ht_val,
            "lt_hours": lt_val,
            "scale": metadata.get("linac_scale", "IEC1217"),
        }

        return LogParseResult(
            success=True,
            category=self.category,
            source_name=source_name,
            metadata=metadata,
            summary=summary,
            events=[]
        )
