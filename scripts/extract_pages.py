import pdfplumber
import json
from pathlib import Path
from tqdm import tqdm

MANUALS_DIR = Path("manuals")
OUTPUT_DIR = Path("data/pages")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for pdf_path in MANUALS_DIR.glob("*.pdf"):
    manual_name = pdf_path.stem.lower()  # nombre del manual
    pages = []

    print(f"\n📘 Procesando manual: {manual_name}")

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in tqdm(enumerate(pdf.pages), total=len(pdf.pages)):
            text = page.extract_text()
            if text:
                pages.append({
                    "manual": manual_name,
                    "page": i + 1,
                    "text": text.strip()
                })

    output_file = OUTPUT_DIR / f"{manual_name}_pages.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    print(f"✔ Generado: {output_file}")
