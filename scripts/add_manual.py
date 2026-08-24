"""add_manual.py — Incorpora PDFs nuevos o actualizados al índice de SOLVI.

Detecta qué PDFs son nuevos o han cambiado comparando hashes MD5. Solo reprocesa
los necesarios. Al terminar reconstruye el índice online y offline automáticamente.

Uso:
    python scripts/add_manual.py                              # Nuevos/cambiados en manuals/
    python scripts/add_manual.py --pdf "manuals/nuevo.pdf"   # Un PDF específico
    python scripts/add_manual.py --folder "C:/mis_pdfs"      # Carpeta externa
    python scripts/add_manual.py --force                     # Reprocesa todos
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pdfplumber
from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
MANUALS_DIR = BASE_DIR / "manuals"
PAGES_DIR = BASE_DIR / "data" / "pages"
HASH_CACHE = BASE_DIR / "data" / "pdf_hashes.json"
REPORT_PATH = BASE_DIR / "data" / "extraction_report.json"
PAGES_DIR.mkdir(parents=True, exist_ok=True)


# ─── TEXT UTILITIES ──────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    text = re.sub(r"-\s*\n\s*", "", raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page) -> str:
    """Multi-strategy text extraction. Returns cleaned text or empty string."""
    try:
        text1 = page.extract_text(x_tolerance=3, y_tolerance=4) or ""
    except Exception:
        text1 = ""

    text2 = ""
    if len(text1.strip()) < 50:
        try:
            text2 = page.extract_text(layout=True, x_tolerance=3, y_tolerance=4) or ""
        except Exception:
            pass

    table_text = ""
    try:
        tables = page.extract_tables()
        if tables:
            cells = [
                str(c).strip()
                for t in tables
                for r in t
                for c in r
                if c and str(c).strip()
            ]
            table_text = " ".join(cells)
    except Exception:
        pass

    raw = text1 if len(text1) >= len(text2) else text2
    if table_text and len(table_text) > 30:
        raw = (raw + "\n" + table_text).strip() if raw else table_text

    cleaned = clean_text(raw)
    useful = len(cleaned.replace(" ", "").replace("\n", ""))
    return cleaned if useful >= 20 else ""


# ─── HASH UTILITIES ──────────────────────────────────────────────────────────

def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hash_cache() -> dict[str, str]:
    if HASH_CACHE.exists():
        try:
            return json.loads(HASH_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_hash_cache(cache: dict[str, str]) -> None:
    HASH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    HASH_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── COMPACT WRITE ───────────────────────────────────────────────────────────

def compact_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


# ─── EXTRACTION ──────────────────────────────────────────────────────────────

def extract_pdf(pdf_path: Path) -> dict:
    manual_name = pdf_path.stem.lower().strip()
    pages: list[dict] = []
    empty_pages: list[int] = []
    errors: list[dict] = []
    started = time.perf_counter()

    print(f"\n  📄 {pdf_path.name}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for i, page in tqdm(enumerate(pdf.pages, start=1), total=total, unit="pág", ncols=72):
                try:
                    text = extract_page_text(page)
                except Exception as exc:
                    text = ""
                    errors.append({"page": i, "error": type(exc).__name__})
                if text:
                    pages.append({"manual": manual_name, "page": i, "text": text})
                else:
                    empty_pages.append(i)
    except Exception as exc:
        print(f"  ⛔ Error abriendo el PDF: {exc}")
        return {
            "manual": manual_name,
            "source": pdf_path.name,
            "total_pages": 0,
            "searchable_pages": 0,
            "pages_without_text": [],
            "extraction_errors": [{"page": 0, "error": str(exc)}],
            "seconds": 0,
            "ok": False,
        }

    output_file = PAGES_DIR / f"{manual_name}_pages.json"
    compact_write(output_file, pages)

    pct = round(len(pages) / max(total, 1) * 100)
    elapsed = round(time.perf_counter() - started, 1)
    status = "✅" if pct >= 60 else "⚠️"
    print(f"  {status}  {len(pages)}/{total} páginas ({pct}%) con texto · {len(empty_pages)} sin texto · {elapsed}s")
    if empty_pages and len(empty_pages) <= 8:
        print(f"     Sin texto (imágenes/diagramas): {empty_pages}")
    elif empty_pages:
        print(f"     {len(empty_pages)} páginas sin texto → revisar o usar OCR externo")

    return {
        "manual": manual_name,
        "source": pdf_path.name,
        "total_pages": total,
        "searchable_pages": len(pages),
        "pages_without_text": empty_pages,
        "extraction_errors": errors,
        "seconds": elapsed,
        "ok": True,
    }


# ─── MAIN ────────────────────────────────────────────────────────────────────

def find_pdfs(args: argparse.Namespace) -> list[Path]:
    if args.pdf:
        p = Path(args.pdf).resolve()
        if not p.exists():
            raise SystemExit(f"⛔ No se encontró el archivo: {p}")
        return [p]
    folder = Path(args.folder).resolve() if args.folder else MANUALS_DIR
    if not folder.exists():
        raise SystemExit(f"⛔ La carpeta no existe: {folder}")
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"⛔ No hay archivos PDF en: {folder}")
    return pdfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incorpora PDFs al índice de SOLVI. Solo reprocesa archivos nuevos o modificados.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python scripts/add_manual.py\n"
            "  python scripts/add_manual.py --pdf \"manuals/nuevo.pdf\"\n"
            "  python scripts/add_manual.py --folder \"C:/Documents/manuales\"\n"
            "  python scripts/add_manual.py --force\n"
        ),
    )
    parser.add_argument("--pdf", type=Path, metavar="ARCHIVO", help="Procesa un solo PDF")
    parser.add_argument("--folder", type=Path, metavar="CARPETA", help="Carpeta con PDFs (alternativa a manuals/)")
    parser.add_argument("--force", action="store_true", help="Reprocesa todos los PDFs aunque no hayan cambiado")
    args = parser.parse_args()

    pdf_files = find_pdfs(args)
    hash_cache = load_hash_cache()
    to_process: list[tuple[Path, str]] = []
    skipped: list[str] = []

    for pdf in pdf_files:
        current_hash = md5_file(pdf)
        if not args.force and hash_cache.get(pdf.name) == current_hash:
            skipped.append(pdf.name)
        else:
            to_process.append((pdf, current_hash))

    print(f"\n🔎  SOLVI — Incorporador de manuales")
    print(f"    PDFs encontrados  : {len(pdf_files)}")
    print(f"    Sin cambios       : {len(skipped)}")
    print(f"    A procesar        : {len(to_process)}")
    if skipped:
        print(f"    (usa --force para reprocesar todos)")

    if not to_process:
        print("\n✅  Nada que procesar. El índice ya está actualizado.\n")
        return

    # Load previous extraction reports to update incrementally
    prev_reports: dict[str, dict] = {}
    if REPORT_PATH.exists():
        try:
            prev_reports = {
                r["manual"]: r
                for r in json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("manuals", [])
            }
        except Exception:
            pass

    total_start = time.perf_counter()
    processed_ok = 0

    for pdf_path, pdf_hash in to_process:
        report = extract_pdf(pdf_path)
        prev_reports[report["manual"]] = report
        if report.get("ok", True):
            hash_cache[pdf_path.name] = pdf_hash
            processed_ok += 1
        else:
            # Don't cache failed extractions — retry next run
            hash_cache.pop(pdf_path.name, None)

    save_hash_cache(hash_cache)
    compact_write(
        REPORT_PATH,
        {"manuals": [prev_reports[k] for k in sorted(prev_reports)]},
    )

    total_elapsed = round(time.perf_counter() - total_start, 1)
    print(f"\n  ⏱  Extracción completa: {total_elapsed}s · {processed_ok}/{len(to_process)} procesados")

    if processed_ok == 0:
        print("  ⛔ No se pudo procesar ningún PDF. Revisa data/extraction_report.json")
        sys.exit(1)

    # Auto-rebuild index
    print("\n  🔨  Reconstruyendo índice (online + offline)...")
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "build_index.py")],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().splitlines():
            print(f"      {line}")
        if result.returncode != 0:
            print(f"  ⚠️  build_index.py terminó con error:\n{result.stderr.strip()}")
            sys.exit(1)
    except Exception as exc:
        print(f"  ⚠️  No se pudo ejecutar build_index.py: {exc}")
        print("      Ejecuta manualmente: python scripts/build_index.py")
        sys.exit(1)

    print("\n  🚀  Próximos pasos:")
    for pdf_path, _ in to_process:
        print(f"      → Sube '{pdf_path.name}' a Cloudflare R2 (si es nuevo o actualizado)")
    print("      → git add data/ && git commit -m 'Actualizar manuales' && git push")
    print("      → Render desplegará automáticamente.\n")


if __name__ == "__main__":
    main()
