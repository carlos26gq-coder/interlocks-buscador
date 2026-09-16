"""Entrypoint retrocompatible para el buscador interactivo CLI.

Delega la ejecución al paquete modular scripts/tools/search_manuals.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.search_manuals import (
    BASE_DIR as TOOL_BASE_DIR,
    load_engine,
    main,
    search_manuals,
)

BASE_DIR = TOOL_BASE_DIR

if __name__ == "__main__":
    main()
