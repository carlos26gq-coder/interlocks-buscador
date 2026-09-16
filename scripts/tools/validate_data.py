"""Valida el índice maestro sin depender del directorio de ejecución."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BASE_DIR / "data" / "all_manuals.json"


def validate_master_data(data_path: Path = DATA_PATH) -> dict:
    with data_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    required = {"manual", "page", "text"}
    invalid = [index for index, record in enumerate(data) if not isinstance(record, dict) or not required.issubset(record)]
    duplicates = len(data) - len({(record["manual"], record["page"]) for record in data if isinstance(record, dict) and required.issubset(record)})
    empty = sum(not str(record.get("text", "")).strip() for record in data if isinstance(record, dict))
    manuals = Counter(record["manual"] for record in data if isinstance(record, dict) and "manual" in record)

    return {
        "total": len(data),
        "manuals_count": len(manuals),
        "invalid": len(invalid),
        "duplicates": duplicates,
        "empty": empty,
        "manuals": manuals,
    }


def main() -> None:
    res = validate_master_data()
    print("Total páginas:", res["total"])
    print("Manuales:", res["manuals_count"])
    print("Registros inválidos:", res["invalid"])
    print("Páginas duplicadas:", res["duplicates"])
    print("Textos vacíos:", res["empty"])
    for manual, count in sorted(res["manuals"].items()):
        print(f"- {manual}: {count}")

    if res["invalid"] or res["duplicates"] or res["empty"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
