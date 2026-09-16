"""Entrypoint retrocompatible para la ingesta y optimización web de PDFs.

Delega la ejecución al paquete modular scripts/tools/add_manual.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.tools.add_manual import (
    BASE_DIR as TOOL_BASE_DIR,
    COMPRESS_DIR,
    HASH_CACHE,
    LISTOS_DIR,
    MANUALS_DIR,
    PAGES_DIR,
    REPORT_PATH,
    clean_text,
    extract_page_text,
    extract_pdf_pages,
    find_pdfs,
    linearize_pdf,
    load_hash_cache,
    main,
    save_hash_cache,
)

BASE_DIR = TOOL_BASE_DIR

if __name__ == "__main__":
    main()
