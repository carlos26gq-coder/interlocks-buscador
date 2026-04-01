import json
from collections import Counter

DATA_PATH = "data/all_manuals.json"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Total páginas indexadas:", len(data))

manuals = Counter(p["manual"] for p in data)
print("\nManuales detectados:")
for m, c in manuals.items():
    print(f"- {m}: {c} páginas")

sample = data[0]
print("\nEjemplo de registro:")
for k in sample:
    print(f"{k}: {sample[k][:80] if isinstance(sample[k], str) else sample[k]}")
