"""Registro de mediciones manuales verificadas para SOLVI.

No representa un multímetro conectado, no inyecta señales y no convierte una
lectura en una aprobación clínica/técnica si el manual no publica ese umbral.
El catálogo JSON compartido es la única fuente de datos para el servidor y la
PWA, de modo que ambos muestran exactamente el mismo alcance documental.
"""

from __future__ import annotations

import json
import math
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
MEASUREMENT_CATALOG_FILE = ROOT_DIR / "data" / "verified_measurement_catalog.json"
VOLTAGE_UNITS = {"v", "vdc", "volt", "volts", "volt dc", "v dc"}


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold()


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Any], ...]:
    """Carga y valida el registro publicable de mediciones documentadas."""
    try:
        payload = json.loads(MEASUREMENT_CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("No se pudo cargar el catálogo de mediciones verificadas.") from exc

    records = payload.get("catalog") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not records:
        raise RuntimeError("El catálogo de mediciones verificadas no contiene registros publicables.")

    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise RuntimeError("El catálogo de mediciones contiene un identificador inválido.")
        record_id = record["id"].strip()
        if not record_id or record_id in seen:
            raise RuntimeError("El catálogo de mediciones contiene identificadores duplicados o vacíos.")
        if record.get("evaluation_policy") != "reference_only":
            raise RuntimeError("Solo se pueden publicar mediciones sin umbral no verificado.")
        if not isinstance(record.get("documented_reference_value"), (int, float)):
            raise RuntimeError(f"La medición '{record_id}' no tiene referencia numérica verificable.")
        if not isinstance(record.get("citations"), list) or not record["citations"]:
            raise RuntimeError(f"La medición '{record_id}' no tiene citas documentales.")
        seen.add(record_id)
        parsed.append(record)
    return tuple(parsed)


def get_all_test_points() -> list[dict[str, Any]]:
    """Compatibilidad de API: devuelve solo registros de medición publicados."""
    return [dict(record) for record in _catalog()]


def get_test_point(identifier: str | None) -> dict[str, Any] | None:
    """Resuelve solo un id o alias explícito; nunca infiere puntos de prueba."""
    target = _normalise(identifier)
    if not target:
        return None
    for record in _catalog():
        candidates = [record["id"], *(record.get("aliases") or [])]
        if any(_normalise(candidate) == target for candidate in candidates):
            return dict(record)
    return None


def evaluate_measurement(tp_id: str, measured_value: float | int, unit: str = "V DC") -> dict[str, Any]:
    """Registra una lectura frente a una referencia, sin dictaminar conformidad.

    Los límites i189 publicados por el manual son parámetros codificados de
    calibración y no se reinterpretan como una tolerancia universal de DMM.
    """
    record = get_test_point(tp_id)
    if not record:
        raise ValueError("No hay una medición documentada para el identificador indicado.")
    try:
        value = float(measured_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("El valor medido debe ser numérico.") from exc
    if not math.isfinite(value):
        raise ValueError("El valor medido debe ser un número finito.")
    if _normalise(unit) not in VOLTAGE_UNITS:
        raise ValueError("La unidad debe ser V DC para esta medición documentada.")

    reference = float(record["documented_reference_value"])
    return {
        "test_point_id": record["id"],
        "test_point_code": record["id"],
        "test_point_name": record["title"],
        "measurement_type": record["measurement_type"],
        "unit": record["unit"],
        "measured_value": round(value, 4),
        "documented_reference_value": reference,
        "delta_from_reference": round(value - reference, 4),
        "status": "REFERENCE_ONLY",
        "status_badge": "SIN UMBRAL",
        "status_label": "REGISTRADA · SIN UMBRAL PUBLICADO",
        "is_pass_fail": False,
        "evaluation_policy": record["evaluation_policy"],
        "recommendation": record["evaluation_notice"],
        "measurement_location": record["measurement_location"],
        "procedure_context": record["procedure_context"],
        "route_id": record.get("route_id"),
        "citations": list(record["citations"]),
        "safety_notice": record["safety_notice"],
        "alias_caveat": record.get("alias_caveat"),
        "is_known_test_point": True,
    }


# Alias explícito para consumidores antiguos que inspeccionan el catálogo.
TEST_POINTS_CATALOG = {record["id"]: record for record in _catalog()}
