"""Extrae texto de PDFs y genera un informe de calidad de la extracción.

Ejemplos:
    python scripts/extract_pages.py
    python scripts/extract_pages.py --pdf "manuals/nuevo manual.pdf"

Después de extraer, ejecutar ``python scripts/build_index.py``.
Los diagramas que sean imágenes sin capa de texto requieren OCR externo y quedan
identificados como páginas sin texto en el informe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import pdfplumber
from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MANUALS_DIR = BASE_DIR / "manuals"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "pages"
REPORT_PATH = BASE_DIR / "data" / "extraction_report.json"


def compact_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def clean_text(raw: str) -> str:
    """Post-process extracted text: join hyphenated line-breaks, normalize whitespace."""
    # Rejoin words split at end of line with a hyphen (e.g., "inter-\nlock" → "interlock")
    text = re.sub(r"-\s*\n\s*", "", raw)
    # Collapse tabs and multiple spaces to a single space
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse more than 2 consecutive newlines to a paragraph break
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page) -> str:
    """Try multiple extraction strategies and return the best result.

    Strategy 1 — Standard extraction with fine tolerances.
    Strategy 2 — Layout-aware extraction (better for multi-column/complex pages).
    Strategy 3 — Table cell extraction (appended if it adds significant content).
    Pages with fewer than 20 useful chars are considered image-only and return "".
    """
    # Strategy 1: standard
    try:
        text1 = page.extract_text(x_tolerance=3, y_tolerance=4) or ""
    except Exception:
        text1 = ""

    # Strategy 2: layout-aware (only if strategy 1 yielded little text)
    text2 = ""
    if len(text1.strip()) < 50:
        try:
            text2 = page.extract_text(layout=True, x_tolerance=3, y_tolerance=4) or ""
        except Exception:
            pass

    # Strategy 3: table cells (concatenated as supplementary text)
    table_text = ""
    try:
        tables = page.extract_tables()
        if tables:
            cells = [
                str(cell).strip()
                for table in tables
                for row in table
                for cell in row
                if cell and str(cell).strip()
            ]
            table_text = " ".join(cells)
    except Exception:
        pass

    # Choose the richer of strategy 1 and 2
    raw = text1 if len(text1) >= len(text2) else text2

    # Append table text if it carries significant extra content
    if table_text and len(table_text) > 30:
        raw = (raw + "\n" + table_text).strip() if raw else table_text

    cleaned = clean_text(raw)
    # Discard pages with too little useful content (likely image-only or blank)
    useful_chars = len(cleaned.replace(" ", "").replace("\n", ""))
    return cleaned if useful_chars >= 20 else ""


def extract_pdf(pdf_path: Path, output_dir: Path) -> dict:
    manual_name = pdf_path.stem.lower().strip()
    pages = []
    empty_pages = []
    extraction_errors = []
    started = time.perf_counter()

    print(f"\nProcesando: {pdf_path.name}")
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for index, page in tqdm(enumerate(pdf.pages, start=1), total=total_pages):
            try:
                text = extract_page_text(page)
            except Exception as error:
                text = ""
                extraction_errors.append({"page": index, "error": type(error).__name__})
            if text:
                pages.append({"manual": manual_name, "page": index, "text": text})
            else:
                empty_pages.append(index)

    output_file = output_dir / f"{manual_name}_pages.json"
    compact_write(output_file, pages)
    report = {
        "manual": manual_name,
        "source": pdf_path.name,
        "total_pages": total_pages,
        "searchable_pages": len(pages),
        "pages_without_text": empty_pages,
        "extraction_errors": extraction_errors,
        "seconds": round(time.perf_counter() - started, 2),
    }
    print(
        f"Generado {output_file.name}: {len(pages)}/{total_pages} páginas con texto; "
        f"{len(empty_pages)} requieren revisión/OCR"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extrae texto searchable de los manuales PDF")
    parser.add_argument("--pdf", type=Path, help="Procesa solo este PDF")
    parser.add_argument("--manuals-dir", type=Path, default=DEFAULT_MANUALS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manuals_dir = args.manuals_dir.resolve()
    output_dir = args.output_dir.resolve()
    pdf_files = [args.pdf.resolve()] if args.pdf else sorted(manuals_dir.glob("*.pdf"))
    if not pdf_files:
        raise SystemExit(f"No se encontraron PDF en {manuals_dir}")

    previous_reports = {}
    if REPORT_PATH.exists():
        try:
            previous_reports = {
                report["manual"]: report
                for report in json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("manuals", [])
            }
        except (ValueError, KeyError, TypeError):
            previous_reports = {}

    for pdf_file in pdf_files:
        report = extract_pdf(pdf_file, output_dir)
        previous_reports[report["manual"]] = report

    compact_write(REPORT_PATH, {"manuals": [previous_reports[key] for key in sorted(previous_reports)]})
    print(f"\nInforme de extracción: {REPORT_PATH}")
    print("Siguiente paso: python scripts/build_index.py")


if __name__ == "__main__":
    main()
