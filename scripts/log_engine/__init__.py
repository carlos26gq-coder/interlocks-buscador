"""
SOLVI - Log Engine Package
Modular, independent log parsing suite for Elekta Linear Accelerators.
"""

import os
from typing import Optional, Union, Dict, Any, List

from .base_parser import BaseLogParser, LogCategory, LogParseResult
from .manifest_parser import RTDManifestParser
from .audit_trail_parser import AuditTrailParser
from .rt_udp_parser import RtUdpLogParser
from .ccp_log_parser import CcpLogParser
from .trf_parser import TrfLogParser
from .controller_log_parser import ControllerLogParser
from .optical_calib_parser import OpticalCalibParser
from .folder_analyzer import LinacFolderAnalyzer
from .excel_exporter import LinacExcelExporter

__all__ = [
    "BaseLogParser",
    "LogCategory",
    "LogParseResult",
    "RTDManifestParser",
    "AuditTrailParser",
    "RtUdpLogParser",
    "CcpLogParser",
    "TrfLogParser",
    "ControllerLogParser",
    "OpticalCalibParser",
    "LinacFolderAnalyzer",
    "LinacExcelExporter",
    "get_parser_for_file",
    "parse_linac_log",
]

_PARSER_REGISTRY: List[BaseLogParser] = [
    TrfLogParser(),
    AuditTrailParser(),
    RtUdpLogParser(),
    CcpLogParser(),
    ControllerLogParser(),
    OpticalCalibParser(),
    RTDManifestParser(),
]


def get_parser_for_file(filename: str, sample_bytes: bytes = b"") -> Optional[BaseLogParser]:
    """Finds the appropriate dedicated parser based on filename and header signature."""
    for parser in _PARSER_REGISTRY:
        if parser.can_parse(filename, sample_bytes):
            return parser
    return None


def parse_linac_log(
    source: Union[str, bytes],
    filename: Optional[str] = None,
    max_records: Optional[int] = 500,
    **kwargs
) -> LogParseResult:
    """
    Unified entry point for parsing any Elekta Linac log file.
    Automatically detects format and delegates to the dedicated parser without mixing logic.
    """
    if isinstance(source, str):
        # File path on disk
        if not os.path.exists(source):
            return LogParseResult(
                success=False,
                category=LogCategory.UNKNOWN,
                source_name=os.path.basename(source),
                errors=[f"File does not exist: {source}"]
            )
        fname = filename or os.path.basename(source)
        try:
            with open(source, "rb") as f:
                sample = f.read(512)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=LogCategory.UNKNOWN,
                source_name=fname,
                errors=[f"Unable to read file: {str(e)}"]
            )
        parser = get_parser_for_file(fname, sample)
        if not parser:
            return LogParseResult(
                success=False,
                category=LogCategory.UNKNOWN,
                source_name=fname,
                errors=[f"No dedicated parser available for file format '{fname}'"]
            )
        return parser.parse_file(source, max_records=max_records, **kwargs)

    elif isinstance(source, (bytes, bytearray)):
        fname = filename or "memory_log.dat"
        sample = bytes(source[:512])
        parser = get_parser_for_file(fname, sample)
        if not parser:
            return LogParseResult(
                success=False,
                category=LogCategory.UNKNOWN,
                source_name=fname,
                errors=[f"No dedicated parser available for in-memory stream '{fname}'"]
            )
        return parser.parse_bytes(bytes(source), source_name=fname, max_records=max_records, **kwargs)

    else:
        return LogParseResult(
            success=False,
            category=LogCategory.UNKNOWN,
            source_name="unknown",
            errors=["Unsupported source type (must be str file path or bytes)"]
        )
