"""add_manual.py — Incorpora, indexa y optimiza PDFs para SOLVI.

Detecta qué PDFs son nuevos o han cambiado (hash MD5). Solo reprocesa los necesarios.
Automáticamente:
1. Extrae el texto y genera el índice de búsqueda (online + offline).
2. Genera el PDF con "Fast Web View" (linearizado) en manuals/Comprimidos/ListosParaWeb/
   listo para subir a Cloudflare R2 sin configuraciones adicionales.

Uso:
    python scripts/add_manual.py                              # Procesa nuevos/cambiados
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

try:
    import pikepdf
    PIKEPDF_OK = True
except ImportError:
    PIKEPDF_OK = False

try:
    import pymupdf as fitz
    PYMUPDF_OK = True
except ImportError:
    try:
        import fitz
        PYMUPDF_OK = True
    except ImportError:
        PYMUPDF_OK = False


BASE_DIR     = Path(__file__).resolve().parent.parent
MANUALS_DIR  = BASE_DIR / "manuals"
COMPRESS_DIR = MANUALS_DIR / "Comprimidos"
LISTOS_DIR   = COMPRESS_DIR / "ListosParaWeb"
PAGES_DIR    = BASE_DIR / "data" / "pages"
HASH_CACHE   = BASE_DIR / "data" / "pdf_hashes.json"
REPORT_PATH  = BASE_DIR / "data" / "extraction_report.json"

PAGES_DIR.mkdir(parents=True, exist_ok=True)
COMPRESS_DIR.mkdir(parents=True, exist_ok=True)
LISTOS_DIR.mkdir(parents=True, exist_ok=True)


# ─── TEXT UTILITIES ──────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    text = re.sub(r"-\s*\n\s*", "", raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page) -> str:
    """Extracción multi-estrategia de texto."""
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


# ─── FAST WEB VIEW (LINEARIZACIÓN) ───────────────────────────────────────────

def linearize_pdf(source: Path, dest: Path) -> bool:
    """Estructura el PDF con Fast Web View (linearizado) para carga instantánea."""
    if not PIKEPDF_OK:
        return False
    try:
        with pikepdf.open(str(source)) as pdf:
            pdf.save(str(dest), linearize=True)
        return True
    except Exception as exc:
        print(f"      [!] Error linearizando {source.name}: {exc}")
        return False


# ─── EXTRACTION ──────────────────────────────────────────────────────────────

def extract_pdf(pdf_path: Path) -> dict:
    manual_name = pdf_path.stem.lower().strip()
    pages: list[dict] = []
    empty_pages: list[int] = []
    errors: list[dict] = []
    started = time.perf_counter()

    print(f"\n  [PDF] {pdf_path.name}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for i, page in tqdm(enumerate(pdf.pages, start=1), total=total, unit="pag", ncols=72):
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
        print(f"  [ERR] Error abriendo el PDF: {exc}")
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
    status = "[OK]" if pct >= 60 else "[!]"
    print(f"  {status}  {len(pages)}/{total} paginas ({pct}%) con texto · {len(empty_pages)} sin texto · {elapsed}s")

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
            raise SystemExit(f"[ERR] No se encontro el archivo: {p}")
        return [p]
    folder = Path(args.folder).resolve() if args.folder else MANUALS_DIR
    if not folder.exists():
        raise SystemExit(f"[ERR] La carpeta no existe: {folder}")
    # Excluir subcarpetas
    pdfs = sorted(p for p in folder.glob("*.pdf") if p.parent == folder)
    if not pdfs:
        raise SystemExit(f"[ERR] No hay archivos PDF en: {folder}")
    return pdfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incorpora, indexa y optimiza PDFs para SOLVI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python scripts/add_manual.py\n"
            "  python scripts/add_manual.py --pdf \"manuals/nuevo.pdf\"\n"
            "  python scripts/add_manual.py --folder \"C:/Documents/manuales\"\n"
            "  python scripts/add_manual.py --force\n"
        ),
    )
    parser.add_argument("--pdf",    type=Path, metavar="ARCHIVO", help="Procesa un solo PDF")
    parser.add_argument("--folder", type=Path, metavar="CARPETA", help="Carpeta con PDFs (alternativa a manuals/)")
    parser.add_argument("--force",  action="store_true",          help="Reprocesa todos los PDFs aunque no hayan cambiado")
    args = parser.parse_args()

    pdf_files  = find_pdfs(args)
    hash_cache = load_hash_cache()
    to_process: list[tuple[Path, str]] = []
    skipped:    list[str] = []

    for pdf in pdf_files:
        current_hash = md5_file(pdf)
        if not args.force and hash_cache.get(pdf.name) == current_hash:
            skipped.append(pdf.name)
        else:
            to_process.append((pdf, current_hash))

    print(f"\n[SOLVI] Incorporador de manuales")
    print(f"    PDFs encontrados  : {len(pdf_files)}")
    print(f"    Sin cambios       : {len(skipped)}")
    print(f"    A procesar        : {len(to_process)}")
    if skipped:
        print(f"    (usa --force para reprocesar todos)")

    if not to_process:
        print("\n[OK]  Nada que procesar. El indice ya esta actualizado.\n")
        return

    # Load previous extraction reports
    prev_reports: dict[str, dict] = {}
    if REPORT_PATH.exists():
        try:
            prev_reports = {
                r["manual"]: r
                for r in json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("manuals", [])
            }
        except Exception:
            pass

    total_start  = time.perf_counter()
    processed_ok = 0
    ready_for_r2: list[Path] = []

    for pdf_path, pdf_hash in to_process:
        # 1. Extraer texto para el índice
        report = extract_pdf(pdf_path)
        prev_reports[report["manual"]] = report
        if report.get("ok", True):
            hash_cache[pdf_path.name] = pdf_hash
            processed_ok += 1
        else:
            hash_cache.pop(pdf_path.name, None)
            continue

        # 2. Generar versión optimizada para web (Fast Web View)
        # Si el usuario colocó una versión comprimida en manuals/Comprimidos/, usamos esa.
        # De lo contrario, linearizamos el original de manuals/.
        compressed_source = COMPRESS_DIR / pdf_path.name
        source_for_web = compressed_source if compressed_source.exists() else pdf_path
        dest_web = LISTOS_DIR / pdf_path.name

        print(f"  [WEB] Optimizando para web (Fast Web View): {pdf_path.name}...")
        ok_linear = linearize_pdf(source_for_web, dest_web)
        if ok_linear:
            mb = round(dest_web.stat().st_size / 1048576, 1)
            print(f"        -> manuals/Comprimidos/ListosParaWeb/{dest_web.name} ({mb} MB)")
            ready_for_r2.append(dest_web)
        else:
            print(f"        [!] No se pudo linearizar. Sube {source_for_web.name} directamente.")

    save_hash_cache(hash_cache)
    compact_write(
        REPORT_PATH,
        {"manuals": [prev_reports[k] for k in sorted(prev_reports)]},
    )

    total_elapsed = round(time.perf_counter() - total_start, 1)
    print(f"\n  [T]  Procesamiento completo: {total_elapsed}s · {processed_ok}/{len(to_process)} OK")

    if processed_ok == 0:
        print("  [ERR] No se pudo procesar ningun PDF. Revisa data/extraction_report.json")
        sys.exit(1)

    # 3. Reconstruir índice online + offline
    print("\n  [BUILD]  Reconstruyendo indice (online + offline)...")
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "build_index.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in result.stdout.strip().splitlines():
            print(f"      {line}")
        if result.returncode != 0:
            print(f"  [!]  build_index.py termino con error:\n{result.stderr.strip()}")
            sys.exit(1)
    except Exception as exc:
        print(f"  [!]  No se pudo ejecutar build_index.py: {exc}")
        print("      Ejecuta manualmente: python scripts/build_index.py")
        sys.exit(1)

    # 4. Instrucciones finales
    print("\n" + "=" * 60)
    print("  PROXIMOS PASOS:")
    print("=" * 60)
    if ready_for_r2:
        print("  1. SUBIR A CLOUDFLARE R2:")
        print("     Sube los archivos de la carpeta 'manuals/Comprimidos/ListosParaWeb/':")
        for r in ready_for_r2:
            print(f"       -> {r.name} ({round(r.stat().st_size / 1048576, 1)} MB)")
    print("\n  2. ACTUALIZAR EN GITHUB / RENDER:")
    print("     git add data/ scripts/")
    print("     git commit -m 'Actualizar manuales'")
    print("     git push")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
