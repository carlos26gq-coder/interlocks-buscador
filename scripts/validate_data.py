"""Entrypoint retrocompatible para la validación del índice maestro.

Delega la ejecución a scripts/tools/validate_data.py manteniendo compatibilidad
con scripts existentes y automatizaciones CI/CD.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.validate_data import BASE_DIR as TOOL_BASE_DIR, main, validate_master_data

# Alias para compatibilidad con código que inspeccione BASE_DIR
BASE_DIR = TOOL_BASE_DIR

if __name__ == "__main__":
    main()
