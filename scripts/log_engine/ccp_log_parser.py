"""
SOLVI - Log Engine: CCP Supervisor Log Parser
Dedicated parser for Elekta Common Core Platform (CCP) and Supervisor logs (Elekta.CCP.*.log).
"""

import os
import re
from typing import Optional, Dict, Any, List
from collections import Counter
from .base_parser import BaseLogParser, LogCategory, LogParseResult


class CcpLogParser(BaseLogParser):
    """Parses log4net supervisor logs recording controller heartbeats, NetMQ messaging, and fault handler requests."""

    @property
    def category(self) -> LogCategory:
        return LogCategory.CCP_SUPERVISOR

    def can_parse(self, filename: str, sample_bytes: bytes) -> bool:
        lower = os.path.basename(filename).lower()
        if "elekta.ccp" in lower:
            return True
        sample_str = sample_bytes[:256].decode("utf-8", errors="replace")
        return "Elekta.CCP." in sample_str and ("HeartbeatTracker" in sample_str or "NetMqComms" in sample_str or "FaultHandler" in sample_str)

    def parse_file(self, file_path: str, max_records: Optional[int] = 500, min_level: Optional[str] = None, **kwargs) -> LogParseResult:
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
            return self._parse_lines(content.splitlines(), os.path.basename(file_path), max_records, min_level)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=os.path.basename(file_path),
                errors=[f"Error reading CCP log file: {str(e)}"]
            )

    def parse_bytes(self, data: bytes, source_name: str = "Elekta.CCP.log", max_records: Optional[int] = 500, min_level: Optional[str] = None, **kwargs) -> LogParseResult:
        try:
            content = data.decode("utf-8", errors="replace")
            return self._parse_lines(content.splitlines(), source_name, max_records, min_level)
        except Exception as e:
            return LogParseResult(
                success=False,
                category=self.category,
                source_name=source_name,
                errors=[f"Error decoding CCP bytes: {str(e)}"]
            )

    def _parse_lines(self, lines: List[str], source_name: str, max_records: Optional[int], min_level: Optional[str]) -> LogParseResult:
        events: List[Dict[str, Any]] = []
        level_counter = Counter()
        component_counter = Counter()
        
        # Count key biomedical fault patterns
        heartbeat_misses = 0
        netmq_failures = 0
        critical_fault_requests = 0

        # Regex for: 2026-09-21 01:27:33,855: WARN  - Elekta.CCP.Supervisor.Common.HeartbeatTracker - Message
        re_log = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+):\s*([A-Z]+)\s*-\s*([^\s]+)\s*-\s*(.*)$")

        level_hierarchy = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "FATAL": 50}
        min_threshold = level_hierarchy.get(min_level.upper(), 0) if min_level else 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            m = re_log.match(line_str)
            if not m:
                continue

            timestamp = m.group(1)
            level = m.group(2).upper()
            full_component = m.group(3)
            component = full_component.split(".")[-1]
            message = m.group(4)

            level_counter[level] += 1
            component_counter[component] += 1

            if "Missed heartbeat from 'Controller'" in message:
                heartbeat_misses += 1
            if "NetMqComms" in full_component and ("Failed to send" in message or "Failed to bind" in message):
                netmq_failures += 1
            if "Raising Critical error request" in message:
                critical_fault_requests += 1

            if min_threshold and level_hierarchy.get(level, 0) < min_threshold:
                continue

            ev = {
                "timestamp": timestamp,
                "level": level,
                "component": component,
                "message": message,
            }
            if max_records is None or len(events) < max_records:
                events.append(ev)

        summary = {
            "returned_entries_count": len(events),
            "level_counts": dict(level_counter),
            "heartbeat_misses_count": heartbeat_misses,
            "netmq_socket_failures": netmq_failures,
            "critical_fault_requests": critical_fault_requests,
            "top_components": dict(component_counter.most_common(5)),
        }

        return LogParseResult(
            success=True,
            category=self.category,
            source_name=source_name,
            summary=summary,
            events=events
        )
