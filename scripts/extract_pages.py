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
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                text = text.strip()
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
