"""Extrae texto de PDFs con PyMuPDF (alta velocidad y fidelidad en esquemas).

Ejemplos:
    python scripts/extract_pages.py
    python scripts/extract_pages.py --pdf "manuals/nuevo manual.pdf"

Después de extraer, ejecutar ``python scripts/build_index.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

try:
    import pymupdf as fitz
except ImportError:
    import fitz

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
    """Post-procesamiento del texto: une guiones de fin de línea y normaliza espacios."""
    text = re.sub(r"-\s*\n\s*", "", raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page) -> str:
    """Extrae texto de una página con PyMuPDF preservando bloques y etiquetas técnicas."""
    try:
        # Modo estándar con preservación de bloques de texto
        raw = page.get_text("text") or ""
    except Exception:
        raw = ""

    cleaned = clean_text(raw)
    useful_chars = len(cleaned.replace(" ", "").replace("\n", ""))
    return cleaned if useful_chars >= 15 else ""


def extract_pdf(pdf_path: Path, output_dir: Path) -> dict:
    manual_name = pdf_path.stem.lower().strip()
    pages = []
    empty_pages = []
    extraction_errors = []
    started = time.perf_counter()

    print(f"\nProcesando: {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    for index in tqdm(range(total_pages), total=total_pages, unit="pag", ncols=72):
        page_num = index + 1
        try:
            page = doc[index]
            text = extract_page_text(page)
        except Exception as error:
            text = ""
            extraction_errors.append({"page": page_num, "error": type(error).__name__})
        if text:
            pages.append({"manual": manual_name, "page": page_num, "text": text})
        else:
            empty_pages.append(page_num)
    doc.close()

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
        f"{len(empty_pages)} sin texto"
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
    # Excluir subcarpetas
    pdf_files = [args.pdf.resolve()] if args.pdf else sorted(
        p for p in manuals_dir.glob("*.pdf") if p.parent == manuals_dir
    )
    if not pdf_files:
        raise SystemExit(f"No se encontraron PDF en {manuals_dir}")

    previous_reports = {}
    if REPORT_PATH.exists():
        try:
            previous_reports = {
                item["manual"]: item
                for item in json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("manuals", [])
            }
        except Exception:
            previous_reports = {}

    for pdf_path in pdf_files:
        report = extract_pdf(pdf_path, output_dir)
        previous_reports[report["manual"]] = report

    compact_write(
        REPORT_PATH,
        {"manuals": [previous_reports[key] for key in sorted(previous_reports)]},
    )
    print("\nExtracción completada. Recuerda ejecutar scripts/build_index.py si cambiaste manuales.")


if __name__ == "__main__":
    main()
