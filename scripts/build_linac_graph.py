"""Entrypoint retrocompatible para la compilación del Grafo de Conocimiento Linac.

Delega la ejecución al paquete modular scripts/tools/build_linac_graph.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.build_linac_graph import (
    ROOT_DIR,
    DATA_DIR,
    STATIC_DIR,
    build_graph,
    main,
)

if __name__ == "__main__":
    main()
