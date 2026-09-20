"""Catálogo de referencias y rutas de señal documentadas para el visor SOLVI.

Este módulo no modela cableado por inferencia. Cada ruta funcional visible debe
referenciar una afirmación de ``data/documentary_traceability.json``. Las hojas
de esquema que solo contienen etiquetas se exponen como referencias, no como
rutas eléctricas ni como fuente de códigos de error.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
CATALOG_FILE = ROOT_DIR / "data" / "verified_signal_paths.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Carga el único catálogo publicable del explorador documental."""
    with CATALOG_FILE.open(encoding="utf-8") as file:
        catalog = json.load(file)
    if not isinstance(catalog.get("catalog"), list):
        raise ValueError("El catálogo de rutas verificadas no contiene una lista válida.")
    return catalog


def get_all_subsystems() -> list[dict[str, Any]]:
    """Compatibilidad de API: devuelve tarjetas de referencias verificadas."""
    result = []
    for item in load_catalog()["catalog"]:
        result.append({
            "id": item["id"],
            "name": item["title"],
            "short_name": item["title"],
            "description": item["summary"],
            "kind": item["kind"],
            "status": item["status"],
            "tags": item.get("tags", []),
            "steps_count": len(item.get("steps", [])),
        })
    return result


def get_subsystem(subsystem_id: str) -> dict[str, Any] | None:
    """Devuelve una ruta o referencia documental por su identificador estable."""
    clean_id = str(subsystem_id or "").strip()
    for item in load_catalog()["catalog"]:
        if item["id"] == clean_id:
            return item
    return None


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def match_subsystem_for_trace(components: list[str]) -> dict[str, Any]:
    """Encuentra referencias por etiquetas sin inventar una ruta eléctrica.

    ``subsystem_id`` se conserva para clientes antiguos. Cuando no hay
    coincidencia, siempre es ``None``: no se elige un esquema arbitrario.
    """
    if isinstance(components, str):
        components = [components]
    if not isinstance(components, list):
        components = []
    query = _normalize(" ".join(str(value)[:100] for value in components[:50]))
    if not query:
        return {"subsystem_id": None, "matched_nodes": [], "matches": []}

    matches: list[dict[str, Any]] = []
    for item in load_catalog()["catalog"]:
        tags = [_normalize(tag) for tag in item.get("tags", [])]
        score = sum(1 for tag in tags if tag and (tag in query or query in tag))
        if score:
            matching_steps = [
                step["id"] for step in item.get("steps", [])
                if _normalize(step.get("label", "")) in query
                or _normalize(step.get("role", "")) in query
            ]
            matches.append({"id": item["id"], "score": score, "matched_steps": matching_steps})

    matches.sort(key=lambda item: (-item["score"], item["id"]))
    best = matches[0] if matches else None
    return {
        "subsystem_id": best["id"] if best else None,
        "matched_nodes": best["matched_steps"] if best else [],
        "matches": matches,
    }
