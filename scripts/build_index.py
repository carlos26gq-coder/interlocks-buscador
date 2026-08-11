"""Construye el índice maestro y los fragmentos compactos para uso offline.

Ejecutar desde cualquier carpeta:
    python scripts/build_index.py
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata


BASE_DIR = Path(__file__).resolve().parent.parent
PAGES_DIR = BASE_DIR / "data" / "pages"
OUTPUT_FILE = BASE_DIR / "data" / "all_manuals.json"
SEARCH_DIR = BASE_DIR / "data" / "search"


def slugify(value: str) -> str:
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "manual"


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def load_and_validate() -> list[dict]:
    all_pages = []
    seen_pages = set()
    for json_file in sorted(PAGES_DIR.glob("*_pages.json"), key=lambda item: item.name.lower()):
        with json_file.open("r", encoding="utf-8") as file:
            pages = json.load(file)
        if not isinstance(pages, list):
            raise ValueError(f"{json_file.name}: la raíz debe ser una lista")
        for position, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or not {"manual", "page", "text"}.issubset(page):
                raise ValueError(f"{json_file.name}: registro {position} incompleto")
            manual = str(page["manual"]).strip().lower()
            page_number = int(page["page"])
            text = str(page["text"]).strip()
            key = (manual, page_number)
            if key in seen_pages:
                raise ValueError(f"Página duplicada: {manual} {page_number}")
            seen_pages.add(key)
            all_pages.append({"manual": manual, "page": page_number, "text": text})
    if not all_pages:
        raise ValueError(f"No se encontraron índices en {PAGES_DIR}")
    return all_pages


def main() -> None:
    pages = load_and_validate()
    master_content = compact_json(pages)
    atomic_write(OUTPUT_FILE, master_content)

    grouped: dict[str, list[list]] = {}
    for page in pages:
        grouped.setdefault(page["manual"], []).append([page["page"], page["text"]])

    catalog_entries = []
    current_files = {"catalog.json"}
    for manual, documents in sorted(grouped.items()):
        payload = {"version": 1, "manual": manual, "documents": documents}
        content = compact_json(payload)
        digest = hashlib.sha256(content).hexdigest()[:12]
        filename = f"{slugify(manual)}.{digest}.json"
        current_files.add(filename)
        atomic_write(SEARCH_DIR / filename, content)
        catalog_entries.append({
            "name": manual,
            "pages": len(documents),
            "bytes": len(content),
            "file": f"/data/search/{filename}",
        })

    version_source = "|".join(entry["file"] for entry in catalog_entries).encode("utf-8")
    catalog = {
        "version": hashlib.sha256(version_source).hexdigest()[:12],
        "documents": len(pages),
        "manuals": catalog_entries,
    }
    atomic_write(SEARCH_DIR / "catalog.json", compact_json(catalog))

    for stale_file in SEARCH_DIR.glob("*.json"):
        if stale_file.name not in current_files:
            stale_file.unlink()

    counts = Counter(page["manual"] for page in pages)
    print(f"Índice creado: {len(pages)} páginas, {len(counts)} manuales")
    print(f"Versión offline: {catalog['version']}")
    for manual, count in sorted(counts.items()):
        print(f"  - {manual}: {count} páginas")


if __name__ == "__main__":
    main()
