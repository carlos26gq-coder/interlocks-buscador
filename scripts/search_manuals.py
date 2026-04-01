from pathlib import Path
import json
from action_extractor import extract_action

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "all_manuals.json"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    manuals = json.load(f)

print("🔍 Buscador técnico (ENTER = todos los manuales, 'salir' para terminar)\n")

while True:
    keyword = input("Palabra a buscar: ").strip().lower()
    if keyword == "salir":
        break

    manual_filter = input("Filtrar por manual (opcional): ").strip().lower()
    found = False

    for page in manuals:

        if manual_filter and page["manual"] != manual_filter:
            continue

        if keyword in page["text"].lower():

            text = page["text"].lower()
            pos = text.find(keyword)
            start = max(0, pos - 60)
            end = min(len(text), pos + 60)
            context = page["text"][start:end].replace("\n", " ")
            action = extract_action(page["text"], keyword)

            print(f"\n📘 Manual: {page['manual']}")
            print(f"📄 Página: {page['page']}")
            print(f"🧠 Contexto: ...{context}...")
            if action:
                print(f"🛠 Acción sugerida: {action}")
            else:
                print("🛠 Acción sugerida: Revisar sección completa del manual.")

            found = True

    if not found:
        print("\n❌ No se encontraron resultados\n")
