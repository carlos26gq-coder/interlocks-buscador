"""
SOLVI - Log Engine: Base Parser and Common Types
Architecture: Modular, decoupled log parser suite for Elekta Linear Accelerators.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import os


class LogCategory(str, Enum):
    TRF_TREATMENT = "trf_treatment"
    AUDIT_TRAIL = "audit_trail"
    RT_UDP_TELEMETRY = "rt_udp_telemetry"
    CCP_SUPERVISOR = "ccp_supervisor"
    CONTROLLER_LOG = "controller_log"
    OPTICAL_CALIBRATION = "optical_calibration"
    RTD_MANIFEST = "rtd_manifest"
    UNKNOWN = "unknown"


@dataclass
class LogParseResult:
    """Standardized output structure for all SOLVI log parsers."""
    success: bool
    category: LogCategory
    source_name: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "category": self.category.value,
            "source_name": self.source_name,
            "metadata": self.metadata,
            "summary": self.summary,
            "events": self.events,
            "errors": self.errors,
        }


class BaseLogParser(ABC):
    """Abstract base class for all specific log type parsers."""

    @property
    @abstractmethod
    def category(self) -> LogCategory:
        """Returns the specific log category handled by this parser."""
        pass

    @abstractmethod
    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        """Determines if this parser is suitable for the given file."""
        pass

    @abstractmethod
    def parse_file(self, file_path: str, max_records: Optional[int] = None, **kwargs) -> LogParseResult:
        """Parses a file from disk and returns a standardized LogParseResult."""
        pass

    @abstractmethod
    def parse_bytes(self, data: bytes, source_name: str = "stream", max_records: Optional[int] = None, **kwargs) -> LogParseResult:
        """Parses raw in-memory bytes and returns a standardized LogParseResult."""
        pass
