import re
import datetime

# Timestamps: ISO, European, American, or Linac millisecond ticks
# Severities: FATAL/CRÍTICO, ERROR, WARNING/ADVERTENCIA, INFO
# Identifiers: INTERLOCK 283, ITEM 112, ERROR 409, PCB 16N, W12, COLLISION, VAC_ION, etc.

TIMESTAMP_PATTERNS = [
    # ISO: 2026-09-15 10:55:57.123
    r"(?P<iso>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    # European or US slash dates: 15/09/2026 10:55:57 or 09/15/2026 10:55:57
    r"(?P<slash>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    # Ticks: 1614523456789 (13 digits)
    r"(?P<ticks>\b\d{13}\b)",
]

TS_REGEX = re.compile("|".join(TIMESTAMP_PATTERNS))

SEVERITY_REGEX = re.compile(r"\b(FATAL|CR[ÍI]TICO|ERROR|WARNING|ADVERTENCIA|INFO)\b", re.IGNORECASE)

IDENTIFIERS_REGEX = re.compile(r"\b(INTERLOCK \d+|ITEM \d+|ERROR \d+|PCB \w+|W\d+|COLLISION|VAC_ION)\b", re.IGNORECASE)


def detect_date_locale(text: str) -> bool:
    """
    Escanea el texto buscando una fecha inequivoca con barras (DD/MM/YYYY vs MM/DD/YYYY).
    Retorna True si el formato es estadounidense (US: MM/DD/YYYY).
    Retorna False si el formato es europeo (Euro: DD/MM/YYYY) o no concluyente.
    """
    if not text:
        return False
    for m in re.finditer(r"\b(\d{2})/(\d{2})/(\d{4})\b", text):
        p1 = int(m.group(1))
        p2 = int(m.group(2))
        if p1 > 12 and p2 <= 12:
            return False  # Dia > 12 -> DD/MM/YYYY (Euro)
        if p1 <= 12 and p2 > 12:
            return True   # Dia > 12 en segunda posicion -> MM/DD/YYYY (US)
    return False


def parse_timestamp(ts_str: str, is_us: bool = None) -> float:
    if not ts_str:
        return 0.0
    match = TS_REGEX.search(ts_str)
    if not match:
        return 0.0
    if match.group("ticks"):
        try:
            return float(match.group("ticks")) / 1000.0
        except (ValueError, TypeError):
            return 0.0
    
    # Try ISO
    s = match.group("iso")
    if s:
        s = s.replace("T", " ")
        if "." in s:
            base_part, ms_part = s.split(".", 1)
            s = f"{base_part}.{ms_part[:6]}"
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return 0.0

    # Try slash format (Euro or US)
    s = match.group("slash") if "slash" in match.groupdict() else None
    if not s and "euro" in match.groupdict():
        s = match.group("euro")
    if not s and "us" in match.groupdict():
        s = match.group("us")

    if s:
        if "." in s:
            base_part, ms_part = s.split(".", 1)
            s = f"{base_part}.{ms_part[:6]}"

        # Heuristica para llamadas directas sin is_us explicito
        target_is_us = is_us
        if target_is_us is None:
            date_part = s.split(" ")[0]
            parts = date_part.split("/")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                p1, p2 = int(parts[0]), int(parts[1])
                if p1 <= 12 and p2 > 12:
                    target_is_us = True
                elif p1 > 12 and p2 <= 12:
                    target_is_us = False
                else:
                    target_is_us = False
            else:
                target_is_us = False

        if target_is_us:
            fmts = [
                "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S"
            ]
        else:
            fmts = [
                "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S"
            ]

        for fmt in fmts:
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return 0.0
            
    return 0.0


def map_identifier_to_tp(identifier: str) -> str:
    if not identifier:
        return "TP1"
    ident = str(identifier).strip().upper()
    
    if re.search(r"\b(TP2|INTERLOCK\s*(?:283|2\b)|DOOR|E-?STOP)\b", ident):
        return "TP2"
    if re.search(r"\b(FS1|24V|PSU)\b", ident):
        return "GEN_VOLT_24"
    if re.search(r"\b(GUN|FILAMENT)\b", ident):
        return "TP_GUN"
    if re.search(r"\b(TP_VAC|VAC\w*|VAC_ION|ITEM\s*112)\b", ident):
        return "TP_VAC"
    if re.search(r"\b(TP100|DOS(?:E|IS)\w*|ION\s*CHAMBER)\b", ident):
        return "TP100"
    if re.search(r"\b(TP_HT|MODULAT\w*|PFN|HT(?:\s*SUPPLY)?)\b", ident):
        return "TP_HT"
    if re.search(r"\b(TP3|THYRATRON|PCB\s*(?:22|3\b)|ITEM\s*474|PULSE)\b", ident):
        return "TP3"
    if re.search(r"\b(TP_RF|RF|MAGNETRON|KLYSTRON)\b", ident):
        return "TP_RF"
    if re.search(r"\b(TP_SPEED|SPEED|TACHO|TG1)\b", ident):
        return "TP_SPEED"
    if re.search(r"\b(TP_POS|POS|GANTRY|ENCODER)\b", ident):
        return "TP_POS"
    if re.search(r"\b(TP5|PCB\s*(?:16N?|5\b)|16N|RELAY\s*K[12]|K1|K2|W12)\b", ident):
        return "TP5"
        
    return "TP1"

mapIdentifierToTP = map_identifier_to_tp


def parse_log_text(text: str) -> dict:
    lines = text.splitlines()
    events = []
    
    is_us = detect_date_locale(text)
    
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        ts_match = TS_REGEX.search(line)
        ts_val = 0.0
        ts_str = ""
        if ts_match:
            ts_str = ts_match.group(0)
            ts_val = parse_timestamp(ts_str, is_us=is_us)
            
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
            "identifiers": ids,
            "precursors": []
        })
        
    # Group cascades (within 2 seconds)
    events.sort(key=lambda x: (x["timestamp"], x["line_number"]))
    cascades = []
    current_cascade = []
    
    for ev in events:
        if ev["severity"] not in ("FATAL", "ERROR"):
            continue
            
        if not current_cascade:
            current_cascade = [ev]
        else:
            in_cascade = False
            if ev["timestamp"] > 0 and current_cascade[0]["timestamp"] > 0:
                diff = ev["timestamp"] - current_cascade[0]["timestamp"]
                in_cascade = (0.0 <= diff <= 2.0)
            else:
                # Si falta timestamp, solo agrupar lineas consecutivas inmediatas (<= 2 lineas)
                in_cascade = abs(ev["line_number"] - current_cascade[-1]["line_number"]) <= 2

            if in_cascade:
                current_cascade.append(ev)
            else:
                cascades.append(current_cascade)
                current_cascade = [ev]
                
    if current_cascade:
        cascades.append(current_cascade)

    # Detect precursor WARNING events (within 5 seconds prior to root of each cascade)
    used_precursors = set()
    for cascade in cascades:
        root = cascade[0]
        root_t = root["timestamp"]
        root_line = root["line_number"]
        precursors = []

        for ev in events:
            if ev["severity"] != "WARNING":
                continue
            if ev["line_number"] in used_precursors:
                continue

            is_candidate = False
            if root_t > 0 and ev["timestamp"] > 0:
                diff = root_t - ev["timestamp"]
                if 0.0 <= diff <= 5.0 and ev["line_number"] < root_line:
                    is_candidate = True
            elif 0 < (root_line - ev["line_number"]) <= 5:
                is_candidate = True

            if is_candidate:
                precursors.append(ev)
                used_precursors.add(ev["line_number"])

        root["precursors"] = precursors
        
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
