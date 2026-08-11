"""Comprobación manual rápida; las pruebas automatizadas están en tests/."""

from search_manuals import search_manuals


if __name__ == "__main__":
    results = search_manuals("dose rate mon", "dosimetry", limit=3)
    print("Resultados encontrados:", len(results))
    for result in results:
        print("-" * 50)
        print("Manual:", result["manual"])
        print("Página:", result["page"])
        print("Contexto:", result["context"])
