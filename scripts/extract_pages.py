"""Entrypoint retrocompatible para la extracción de páginas PDF con PyMuPDF.

Delega la ejecución al paquete modular scripts/tools/extract_pages.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.extract_pages import (
    BASE_DIR as TOOL_BASE_DIR,
    DEFAULT_MANUALS_DIR,
    DEFAULT_OUTPUT_DIR,
    REPORT_PATH,
    clean_text,
    compact_write,
    extract_page_text,
    extract_pdf,
    find_pdfs,
    main,
)

BASE_DIR = TOOL_BASE_DIR

if __name__ == "__main__":
    main()
