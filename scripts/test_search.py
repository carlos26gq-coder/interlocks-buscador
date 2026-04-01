from search_manuals import search_manuals

results = search_manuals(
    query="dose rate mon",
    manual_filter="dosimetry"
)

print("Resultados encontrados:", len(results))
for r in results[:3]:
    print("-" * 50)
    print("Manual:", r["manual"])
    print("Página:", r["page"])
    print("Contexto:", r["context"])
