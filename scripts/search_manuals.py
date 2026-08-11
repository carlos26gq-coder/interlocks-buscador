"""Buscador de consola que usa el mismo motor indexado que la aplicación."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from search_engine import SearchEngine


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "all_manuals.json"


def load_engine() -> SearchEngine:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        return SearchEngine(json.load(file))


def search_manuals(query: str, manual_filter: str = "", limit: int = 25) -> list[dict]:
    return load_engine().search(query, manual_filter, offset=0, limit=limit)["results"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Buscar texto dentro de los manuales de SOLVI")
    parser.add_argument("query", nargs="?", help="Texto a buscar")
    parser.add_argument("--manual", default="", help="Filtrar por nombre de manual")
    parser.add_argument("--limit", type=int, default=25, help="Máximo de resultados")
    args = parser.parse_args()
    engine = load_engine()

    query = args.query
    while query is None:
        query = input("Palabra o frase ('salir' para terminar): ").strip()
        if query.lower() == "salir":
            return
        if not query:
            query = None

    data = engine.search(query, args.manual, offset=0, limit=max(1, min(args.limit, 100)))
    print(f"Resultados: {len(data['results'])} de {data['total']}")
    for result in data["results"]:
        print(f"\n[{result['manual']}] Página {result['page']}\n{result['context']}")


if __name__ == "__main__":
    main()
