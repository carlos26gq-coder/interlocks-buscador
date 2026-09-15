import re
import datetime

# Timestamps: ISO, European, American, or Linac millisecond ticks
# Severities: FATAL/CRÍTICO, ERROR, WARNING/ADVERTENCIA, INFO
# Identifiers: INTERLOCK 283, ITEM 112, ERROR 409, PCB 16N, W12, COLLISION, VAC_ION, etc.

TIMESTAMP_PATTERNS = [
    # ISO: 2026-09-15 10:55:57.123
    r"(?P<iso>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    # European: 15/09/2026 10:55:57
    r"(?P<euro>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    # American: 09/15/2026 10:55:57
    r"(?P<us>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    # Ticks: 1614523456789 (13 digits)
    r"(?P<ticks>\b\d{13}\b)",
]

TS_REGEX = re.compile("|".join(TIMESTAMP_PATTERNS))

SEVERITY_REGEX = re.compile(r"\b(FATAL|CR[ÍI]TICO|ERROR|WARNING|ADVERTENCIA|INFO)\b", re.IGNORECASE)

IDENTIFIERS_REGEX = re.compile(r"\b(INTERLOCK \d+|ITEM \d+|ERROR \d+|PCB \w+|W\d+|COLLISION|VAC_ION)\b", re.IGNORECASE)

def parse_timestamp(ts_str: str) -> float:
    match = TS_REGEX.search(ts_str)
    if not match:
        return 0.0
    if match.group("ticks"):
        return float(match.group("ticks")) / 1000.0
    
    # Try ISO
    s = match.group("iso")
    if s:
        s = s.replace("T", " ")
        try:
            if "." in s:
                dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
            else:
                dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except:
            pass
    # Try Euro
    s = match.group("euro")
    if s:
        try:
            if "." in s:
                dt = datetime.datetime.strptime(s, "%d/%m/%Y %H:%M:%S.%f")
            else:
                dt = datetime.datetime.strptime(s, "%d/%m/%Y %H:%M:%S")
            return dt.timestamp()
        except:
            pass
            
    # Try US
    s = match.group("us")
    if s:
        try:
            if "." in s:
                dt = datetime.datetime.strptime(s, "%m/%d/%Y %H:%M:%S.%f")
            else:
                dt = datetime.datetime.strptime(s, "%m/%d/%Y %H:%M:%S")
            return dt.timestamp()
        except:
            pass
            
    return 0.0

def parse_log_text(text: str) -> dict:
    lines = text.splitlines()
    events = []
    
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        ts_match = TS_REGEX.search(line)
        ts_val = 0.0
        ts_str = ""
        if ts_match:
            ts_str = ts_match.group(0)
            ts_val = parse_timestamp(ts_str)
            
        sev_match = SEVERITY_REGEX.search(line)
        severity = sev_match.group(0).upper() if sev_match else "INFO"
        if severity in ("CRÍTICO", "CRITICO"):
            severity = "FATAL"
        elif severity == "ADVERTENCIA":
            severity = "WARNING"
            
        ids = [m.group(0).upper() for m in IDENTIFIERS_REGEX.finditer(line)]
        
        events.append({
            "line_number": i + 1,
            "raw": line,
            "timestamp": ts_val,
            "timestamp_str": ts_str,
            "severity": severity,
            "identifiers": ids
        })
        
    # Group cascades (within 2 seconds)
    events.sort(key=lambda x: x["timestamp"])
    cascades = []
    current_cascade = []
    
    for ev in events:
        if ev["severity"] not in ("FATAL", "ERROR"):
            continue
            
        if not current_cascade:
            current_cascade = [ev]
        else:
            if ev["timestamp"] - current_cascade[0]["timestamp"] <= 2.0:
                current_cascade.append(ev)
            else:
                if current_cascade:
                    cascades.append(current_cascade)
                current_cascade = [ev]
                
    if current_cascade:
        cascades.append(current_cascade)
        
    return {
        "ok": True,
        "total_lines": len(lines),
        "events": events,
        "cascades": cascades,
        "summary": {
            "fatals": sum(1 for e in events if e["severity"] == "FATAL"),
            "errors": sum(1 for e in events if e["severity"] == "ERROR"),
            "warnings": sum(1 for e in events if e["severity"] == "WARNING"),
            "infos": sum(1 for e in events if e["severity"] == "INFO"),
        }
    }
