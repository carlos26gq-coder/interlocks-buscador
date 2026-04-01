import json
from pathlib import Path

PAGES_DIR = Path("data/pages")
OUTPUT_FILE = Path("data/all_manuals.json")

all_pages = []

for json_file in PAGES_DIR.glob("*_pages.json"):
    with open(json_file, "r", encoding="utf-8") as f:
        pages = json.load(f)
        all_pages.extend(pages)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(all_pages, f, ensure_ascii=False, indent=2)

print(f"✔ Índice creado con {len(all_pages)} páginas")
