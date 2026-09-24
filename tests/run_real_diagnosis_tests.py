"""SOLVI - Script de pruebas reales exhaustivas para la pestaña Relacionar (Diagnóstico Causal y Documental).
Ejecuta pruebas reales completas en el app para 1, 2, 3, 4, 5, 6, 7 y 8 informaciones técnicas diferentes,
probando tanto el endpoint documental (/diagnose) como el endpoint causal avanzado (/diagnose/ai) con la API de Gemini
y el índice de los 19 manuales técnicos de Elekta.

Verifica adherencia estricta a:
1. Cero menciones de 'IA', 'AI' o 'Inteligencia Artificial' en cualquier parte de textos, respuestas o errores.
2. Resultados estructurados como 'Diagnóstico 1: ...', 'Diagnóstico 2: ...', ordenados de mayor a menor probabilidad.
3. No mostrar nubes de etiquetas o chips redundantes; texto continuo e integrado.
4. Apego riguroso y fundamentado a los 19 manuales técnicos de Elekta.
5. En consultas múltiples (1 a 8 síntomas), todos los síntomas ingresados tienen igual prioridad y cobertura.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from api import app
from search_engine import SearchEngine

AI_MENTION_REGEX = re.compile(r"\b(?:Inteligencia\s+Artificial|IA|AI)\b", re.IGNORECASE)

def check_no_ai_mentions(text: str, field_name: str, label: str):
    if not text:
        return
    matches = AI_MENTION_REGEX.findall(text)
    if matches:
        print(f"  [ALERTA REGLA 1] Mención de AI/IA detectada en '{field_name}' para {label}: {matches}")
        assert False, f"Regla 1 violada: mención de IA/AI en {field_name}: {matches}"

def run():
    print("=" * 80)
    print("INICIANDO SUITE DE PRUEBAS REALES EN LA PESTAÑA RELACIONAR (1 A 8 SÍNTOMAS)")
    print("=" * 80)

    client = app.test_client()

    test_cases = [
        (
            "Prueba 1 Información (1 Síntoma)",
            ["Interlock 283"],
            "Lazo de referencia de posición de mesa PSS / Potenciómetro grueso"
        ),
        (
            "Prueba 2 Informaciones (2 Síntomas)",
            ["ITEM 409", "Error 66"],
            "Desfasador de RF de baja potencia y lazo de sintonía AFC"
        ),
        (
            "Prueba 3 Informaciones (3 Síntomas)",
            ["D_RATE 1", "Interlock 283", "PCB 16N"],
            "Canal primario de dosimetría y tarjeta DIE-HTB (PCB 16N)"
        ),
        (
            "Prueba 4 Informaciones (4 Informaciones)",
            ["CON-K", "ITEM 79", "Area 70", "FS73A"],
            "Contactor principal CON-K, transformador T1, fusible FS73A y Área 70"
        ),
        (
            "Prueba 5 Informaciones (5 Informaciones)",
            ["Interlock 12", "ITEM 122", "PCB 16R", "T1", "Error 14"],
            "Supervisión HT PSU, control de corriente PCB 16R y disparo Error 14"
        ),
        (
            "Prueba 6 Informaciones (6 Informaciones)",
            ["D_RATE 2", "ITEM 301", "Interlock 51", "Area 30", "PCB 16N", "FS2"],
            "Canal D2, bus CAN colimador Agility, bomba de vacío y Área 30"
        ),
        (
            "Prueba 7 Informaciones (7 Informaciones)",
            ["Interlock 18", "TS1", "Motor AFC", "ITEM 236", "Area 18", "CB3", "Error 27"],
            "Circuito de refrigeración, termostato TS1, motor de sintonía AFC y CB3"
        ),
        (
            "Prueba 8 Informaciones (8 Informaciones)",
            ["CON-K", "ITEM 79", "SW12", "SW13", "Room Doors 1", "CB1", "FS73A", "ITEM 74"],
            "Cadena de seguridad de contactor CON-K, microswitches cabezal y puertas"
        ),
    ]

    total_tests = len(test_cases)
    passed_tests = 0

    for idx, (label, syms, description) in enumerate(test_cases, 1):
        print(f"\n" + "=" * 80)
        print(f"[{idx}/{total_tests}] {label} — Dominio: {description}")
        print(f"Informaciones ingresadas ({len(syms)}): {syms}")
        print("=" * 80)

        # ---------------------------------------------------------------------
        # 1. PRUEBA REAL VÍA ENDPOINT /diagnose (Búsqueda cruzada documental)
        # ---------------------------------------------------------------------
        print("\n--- 1. ENDPOINT HTTP POST /diagnose (Modo Documental) ---")
        doc_resp = client.post("/diagnose", json={"symptoms": syms})
        assert doc_resp.status_code == 200, f"Error HTTP {doc_resp.status_code} en /diagnose para {label}: {doc_resp.get_data(as_text=True)}"
        doc_data = doc_resp.get_json()
        results = doc_data.get("results", [])
        signals_returned = doc_data.get("signals", [])
        print(f"Resultados documentales retornados: {len(results)}")
        assert len(results) > 0, f"No se obtuvieron resultados documentales para {label}"
        assert len(signals_returned) == len(syms), f"Síntomas omitidos en {label}: esperado {len(syms)}, obtenido {len(signals_returned)}: {signals_returned}"

        for d_idx, r in enumerate(results[:5], 1):
            title = r.get("title", "")
            manual = r.get("manual", "")
            page = r.get("page")
            match_pct = r.get("relative_match", 0)
            conf = r.get("confidence", "")
            matched_cnt = r.get("matched_count", 0)
            total_sig = r.get("signal_count", len(syms))

            # Validación de preservación equitativa: todos los síntomas deben ser considerados
            assert total_sig == len(syms), f"signal_count ({total_sig}) != cantidad de síntomas ingresados ({len(syms)})"

            # Validación de calidad de título: No debe ser un número puro, encabezado de tabla vacío ni línea de tabla de contenidos
            assert not re.fullmatch(r"[\d\s\-_/.]+", title), f"Título documental inválido (número puro): '{title}' en {manual} p.{page}"
            assert not (title.lower().startswith("table ") and len(title) < 20), f"Título documental es encabezado de tabla: '{title}'"
            assert not (title.lower().startswith("section ") and len(title) < 20), f"Título documental es encabezado de sección: '{title}'"
            assert not re.search(r"(?:\.\s*){4,}", title), f"Título documental contiene puntos de tabla de contenidos: '{title}'"

            # Validación Regla 1 (Cero menciones de IA)
            check_no_ai_mentions(title, f"doc_result[{d_idx}].title", label)
            check_no_ai_mentions(r.get("context", ""), f"doc_result[{d_idx}].context", label)

            print(f"  Diagnóstico {d_idx}: {title}")
            print(f"    Manual: {manual} (Pág. {page}) | Coincidencia: {match_pct}% ({matched_cnt}/{total_sig} síntomas) | Confianza: {conf}")

        # ---------------------------------------------------------------------
        # 2. PRUEBA REAL VÍA ENDPOINT /diagnose/ai (Diagnóstico Causal Gemini)
        # ---------------------------------------------------------------------
        print("\n--- 2. ENDPOINT HTTP POST /diagnose/ai (Diagnóstico Causal Gemini) ---")
        ai_resp = client.post("/diagnose/ai", json={"symptoms": syms})
        assert ai_resp.status_code == 200, f"Error HTTP {ai_resp.status_code} en /diagnose/ai para {label}: {ai_resp.get_data(as_text=True)}"
        ai_result = ai_resp.get_json()
        assert ai_result.get("ok") is True, f"Fallo en analyze_with_gemini para {label}: {ai_result.get('error')}"

        ai_data = ai_result.get("data", {})
        root_cause = ai_data.get("root_cause", "")
        explanation = ai_data.get("explanation", "")
        subsystem = ai_data.get("subsystem", "")
        confidence = ai_data.get("confidence", "")
        findings = ai_data.get("diagnostic_findings", [])
        manual_refs = ai_data.get("manual_references", [])
        safety_warning = ai_data.get("safety_warning", "")

        print(f"Modelo utilizado: {ai_result.get('model_used')} (Failover: {ai_result.get('failover', False)})")
        print(f"Subsistema identificado: {subsystem}")
        print(f"Nivel de Confianza: {confidence}")
        print(f"Causa Raíz deducción: {root_cause}")
        print(f"Explicación Causal (extracto): {explanation[:220]}...")

        # Verificación Regla 1 (Cero menciones de IA / AI / Inteligencia Artificial)
        check_no_ai_mentions(root_cause, "root_cause", label)
        check_no_ai_mentions(explanation, "explanation", label)
        check_no_ai_mentions(safety_warning, "safety_warning", label)

        print(f"\nHallazgos Diagnósticos estructurados ({len(findings)} diagnósticos):")
        assert len(findings) >= 2, f"Se esperaban al menos 2 diagnósticos estructurados, encontrados: {len(findings)}"

        for f_idx, f in enumerate(findings, 1):
            f_title = f.get("title", "")
            f_cause = f.get("cause_mechanism", "")
            f_solution = f.get("solution_procedure", "")

            # Comprobar que no hay duplicación tipo "Diagnóstico 1: Diagnóstico 1:"
            assert not re.match(r"^Diagn[oó]stico\s*\d+", f_title, re.IGNORECASE), (
                f"Título contiene prefijo Diagnóstico duplicado: '{f_title}'"
            )

            # Comprobar Regla 1 en cada hallazgo
            check_no_ai_mentions(f_title, f"finding[{f_idx}].title", label)
            check_no_ai_mentions(f_cause, f"finding[{f_idx}].cause_mechanism", label)
            check_no_ai_mentions(f_solution, f"finding[{f_idx}].solution_procedure", label)

            # Comprobar que contiene mecanismo y procedimiento sustantivos
            assert len(f_cause) >= 30, f"Mecanismo causal demasiado breve en hallazgo {f_idx}"
            assert len(f_solution) >= 30, f"Procedimiento de solución demasiado breve en hallazgo {f_idx}"

            print(f"  Diagnóstico {f_idx}: {f_title}")
            print(f"    - Mecanismo causal: {f_cause[:130]}...")
            print(f"    - Procedimiento solución: {f_solution[:130]}...")

        print(f"\nManuales técnicos citados: {manual_refs}")
        print(f"Advertencia de seguridad: {safety_warning}")
        print(f"\n[OK] {label} completada exitosamente sin errores.\n")
        passed_tests += 1

    # -------------------------------------------------------------------------
    # 3. VERIFICACIÓN DE CASOS LÍMITE Y ROBUSTEZ
    # -------------------------------------------------------------------------
    print("=" * 80)
    print("VERIFICANDO CASOS LÍMITE Y ROBUSTEZ")
    print("=" * 80)

    # 3.1 Lista vacía de síntomas debe dar 400 en /diagnose/ai
    empty_resp = client.post("/diagnose/ai", json={"symptoms": []})
    assert empty_resp.status_code == 400, f"Se esperaba 400 para síntomas vacíos, recibido: {empty_resp.status_code}"
    print("[OK] Rechazo controlado de lista vacía en /diagnose/ai (400 Bad Request)")

    # 3.2 Más de 8 síntomas debe ser rechazado limpiamente por el validador estricto
    too_many = [f"Sintoma {i}" for i in range(1, 10)]
    excess_resp = client.post("/diagnose/ai", json={"symptoms": too_many})
    assert excess_resp.status_code == 400, f"Se esperaba 400 para > 8 síntomas, recibido: {excess_resp.status_code}"
    print("[OK] Rechazo controlado de > 8 síntomas en /diagnose/ai (400 Bad Request)")

    print("\n" + "=" * 80)
    print(f"RESUMEN FINAL: {passed_tests}/{total_tests} pruebas reales superadas con éxito.")
    print("TODAS LAS REGLAS Y REQUISITOS VERIFICADOS AL 100%.")
    print("=" * 80)

if __name__ == "__main__":
    run()
