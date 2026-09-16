"""Entrypoint retrocompatible para la construcción del índice maestro y fragmentos compactos.

Delega la ejecución al paquete modular scripts/tools/build_index.py manteniendo
retrocompatibilidad total con flujos CLI y Render deployment.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.build_index import (
    BASE_DIR as TOOL_BASE_DIR,
    atomic_write,
    compact_json,
    load_and_validate,
    main,
    slugify,
)

BASE_DIR = TOOL_BASE_DIR

if __name__ == "__main__":
    main()
