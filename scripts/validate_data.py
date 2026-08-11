"""Valida el índice maestro sin depender del directorio de ejecución."""

from collections import Counter
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "all_manuals.json"


with DATA_PATH.open("r", encoding="utf-8") as file:
    data = json.load(file)

required = {"manual", "page", "text"}
invalid = [index for index, record in enumerate(data) if not isinstance(record, dict) or not required.issubset(record)]
duplicates = len(data) - len({(record["manual"], record["page"]) for record in data if isinstance(record, dict) and required.issubset(record)})
empty = sum(not str(record.get("text", "")).strip() for record in data if isinstance(record, dict))
manuals = Counter(record["manual"] for record in data if isinstance(record, dict) and "manual" in record)

print("Total páginas:", len(data))
print("Manuales:", len(manuals))
print("Registros inválidos:", len(invalid))
print("Páginas duplicadas:", duplicates)
print("Textos vacíos:", empty)
for manual, count in sorted(manuals.items()):
    print(f"- {manual}: {count}")

if invalid or duplicates or empty:
    raise SystemExit(1)
