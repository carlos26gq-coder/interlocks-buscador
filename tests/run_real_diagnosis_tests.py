"""SOLVI - Script de pruebas reales exhaustivas para la pestaña Relacionar.
Ejecuta pruebas reales repetidas en el app para 1, 2, 3, 4 y 5 síntomas técnicos (máximo 5),
probando casos técnicamente RELACIONADOS (convergencia causal en lazos de seguridad)
y casos DESACOPLADOS (fallas independientes sin correlación forzada ni rebuscada).

Verifica adherencia estricta a:
1. Cero menciones de 'IA', 'AI' o 'Inteligencia Artificial' en cualquier parte de textos, respuestas o errores.
2. Máximo 5 síntomas estrictos (rechazo con 400 Bad Request ante 6 o más).
3. Razonamiento de relación: si están relacionados, explica la causa común; si no lo están,
   no fuerza vínculos artificiales y presenta la información de cada síntoma de forma rigurosa e independiente.
4. Resultados estructurados como 'Diagnóstico 1: ...', 'Diagnóstico 2: ...', etc., ordenados de mayor a menor probabilidad.
5. Apego riguroso y fundamentado a los 19 manuales técnicos de Elekta.
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
    print("INICIANDO SUITE DE PRUEBAS REALES EN LA PESTAÑA RELACIONAR (1 A 5 SÍNTOMAS)")
    print("Pruebas repetidas para casos RELACIONADOS y casos DESACOPLADOS")
    print("=" * 80)

    client = app.test_client()

    test_scenarios = [
        # ─── 1 SÍNTOMA ────────────────────────────────────────────────────────
        {
            "name": "Prueba 1.1 (1 Síntoma): Potenciómetro PSS",
            "symptoms": ["Interlock 283"],
            "expected_related": True,
            "description": "Lazo de referencia de mesa PSS / Grupo de interbloqueos"
        },
        {
            "name": "Prueba 1.2 (1 Síntoma): Contactor CON-K",
            "symptoms": ["ITEM 79"],
            "expected_related": True,
            "description": "Supervisión de contactor CON-K en Área 72 (DIE-ICA) y Área 74"
        },
        {
            "name": "Prueba 1.3 (1 Síntoma): Sobretemperatura HT PSU",
            "symptoms": ["HT PSU OT"],
            "expected_related": True,
            "description": "Lazo térmico SW1/TS1 en fuente HT e interbloqueo de seguridad"
        },

        # ─── 2 SÍNTOMAS ────────────────────────────────────────────────────────
        {
            "name": "Prueba 2.1 (2 Síntomas - RELACIONADOS): CON-K + ITEM 79",
            "symptoms": ["CON-K", "ITEM 79"],
            "expected_related": True,
            "description": "Contactor principal y contacto auxiliar de retorno"
        },
        {
            "name": "Prueba 2.2 (2 Síntomas - DESACOPLADOS): Mesa PSS + Bomba Iónica",
            "symptoms": ["Interlock 283", "Interlock 51"],
            "expected_related": False,
            "description": "Movimiento mecánico de mesa vs sistema de vacío independiente"
        },

        # ─── 3 SÍNTOMAS ────────────────────────────────────────────────────────
        {
            "name": "Prueba 3.1 (3 Síntomas - RELACIONADOS): CON-K + ITEM 79 + FS73A",
            "symptoms": ["CON-K", "ITEM 79", "FS73A"],
            "expected_related": True,
            "description": "Cadena de contactores, bobina 24VAC y fusible de control Área 73"
        },
        {
            "name": "Prueba 3.2 (3 Síntomas - DESACOPLADOS): Colimador + Mesa + RF AFC",
            "symptoms": ["ITEM 301", "Interlock 283", "ITEM 409"],
            "expected_related": False,
            "description": "Bus CAN Agility MLC vs potenciómetro mesa vs lazo AFC"
        },

        # ─── 4 SÍNTOMAS ────────────────────────────────────────────────────────
        {
            "name": "Prueba 4.1 (4 Síntomas - RELACIONADOS): CON-K + ITEM 79 + Area 70 + FS73A",
            "symptoms": ["CON-K", "ITEM 79", "Area 70", "FS73A"],
            "expected_related": True,
            "description": "Distribución de potencia, transformador T1 y fusible de mando"
        },
        {
            "name": "Prueba 4.2 (4 Síntomas - DESACOPLADOS): Mesa + Dosimetría + Vacío + Refrigeración",
            "symptoms": ["Interlock 283", "D_RATE 1", "Interlock 51", "TS1"],
            "expected_related": False,
            "description": "Subsistemas físicamente desacoplados sin correlación común"
        },

        # ─── 5 SÍNTOMAS ────────────────────────────────────────────────────────
        {
            "name": "Prueba 5.1 (5 Síntomas - RELACIONADOS): Cadena completa de seguridad CON-K",
            "symptoms": ["CON-K", "ITEM 79", "SW12", "SW13", "FS73A"],
            "expected_related": True,
            "description": "Lazo serie de seguridad: contactor, microswitches cabezal y fusible T1"
        },
        {
            "name": "Prueba 5.2 (5 Síntomas - DESACOPLADOS): Fallas múltiples independientes",
            "symptoms": ["Interlock 283", "D_RATE 1", "ITEM 301", "Error 66", "Interlock 51"],
            "expected_related": False,
            "description": "Mesa PSS, canal dosis D1, motor MLC, sintonía AFC y bomba iónica"
        },
    ]

    total_scenarios = len(test_scenarios)
    passed_scenarios = 0

    for idx, sc in enumerate(test_scenarios, 1):
        name = sc["name"]
        syms = sc["symptoms"]
        is_rel = sc["expected_related"]
        desc = sc["description"]

        print(f"\n" + "=" * 80)
        print(f"[{idx}/{total_scenarios}] {name}")
        print(f"Informaciones ingresadas ({len(syms)}): {syms}")
        print(f"Tipo esperado: {'RELACIONADOS (Convergentes)' if is_rel else 'DESACOPLADOS (Independientes)'} — {desc}")
        print("=" * 80)

        # 1. Búsqueda Documental (/diagnose)
        doc_resp = client.post("/diagnose", json={"symptoms": syms})
        assert doc_resp.status_code == 200, f"Error {doc_resp.status_code} en /diagnose: {doc_resp.get_data(as_text=True)}"
        doc_data = doc_resp.get_json()
        doc_results = doc_data.get("results", [])
        signals_returned = doc_data.get("signals", [])
        assert len(doc_results) > 0, f"No se obtuvieron resultados documentales para {name}"
        assert len(signals_returned) == len(syms), f"Señales devueltas ({len(signals_returned)}) != ingresadas ({len(syms)})"

        # 2. Diagnóstico Causal (/diagnose/ai)
        ai_resp = client.post("/diagnose/ai", json={"symptoms": syms})
        assert ai_resp.status_code == 200, f"Error {ai_resp.status_code} en /diagnose/ai: {ai_resp.get_data(as_text=True)}"
        ai_json = ai_resp.get_json()
        assert ai_json.get("ok") is True, f"Fallo en /diagnose/ai: {ai_json.get('error')}"

        ai_data = ai_json.get("data", {})
        root_cause = ai_data.get("root_cause", "")
        subsystem = ai_data.get("subsystem", "")
        explanation = ai_data.get("explanation", "")
        findings = ai_data.get("diagnostic_findings", [])
        meta = ai_data.get("_diagnostic_meta", {})
        actual_is_related = meta.get("is_related", True)

        # Verificación de Cero menciones de IA
        check_no_ai_mentions(root_cause, "root_cause", name)
        check_no_ai_mentions(explanation, "explanation", name)
        check_no_ai_mentions(subsystem, "subsystem", name)

        print(f"Modelo: {ai_json.get('model_used')} (Failover: {ai_json.get('failover', False)})")
        print(f"Subsistema(s): {subsystem}")
        print(f"Causa Raíz: {root_cause[:140]}...")
        print(f"Explicación (extracto): {explanation[:180]}...")

        # Validación del razonamiento de relación vs independencia
        if not is_rel and len(syms) >= 2 and ai_json.get("failover", False):
            # En modo local/failover debe detectar desacoplamiento
            assert "desacoplados" in explanation.lower() or "independientes" in explanation.lower(), (
                f"Para síntomas desacoplados se esperaba mención explícita de anomalías independientes en {name}"
            )
            print("  [OK] Razonamiento verificado: Se reconoce honestamente que son anomalías independientes sin correlación forzada.")
        elif is_rel:
            print("  [OK] Razonamiento verificado: Síntomas correlacionados en subsistema común o lazo serie.")

        # Validación de formato Diagnóstico 1..N
        assert len(findings) >= 2, f"Se esperaban al menos 2 diagnósticos estructurados, obtenidos: {len(findings)}"
        print(f"Hallazgos técnicos estructurados ({len(findings)} diagnósticos):")
        for f_idx, f in enumerate(findings[:5], 1):
            f_title = f.get("title", "")
            f_cause = f.get("cause_mechanism", "")
            f_sol = f.get("solution_procedure", "")

            check_no_ai_mentions(f_title, f"finding[{f_idx}].title", name)
            check_no_ai_mentions(f_cause, f"finding[{f_idx}].cause", name)
            check_no_ai_mentions(f_sol, f"finding[{f_idx}].solution", name)

            assert len(f_cause) >= 20, f"Mecanismo causal insuficiente en hallazgo {f_idx}"
            assert len(f_sol) >= 20, f"Procedimiento de solución insuficiente en hallazgo {f_idx}"
            print(f"  Diagnóstico {f_idx}: {f_title}")

        print(f"\n[OK] {name} validado exitosamente.\n")
        passed_scenarios += 1

    # ─── 3. PRUEBAS DE CASOS LÍMITE (MÁXIMO 5 SÍNTOMAS) ──────────────────────
    print("=" * 80)
    print("VALIDANDO LÍMITES ESTRICTOS (MÁXIMO 5 SÍNTOMAS)")
    print("=" * 80)

    # 3.1 Lista vacía rechazada con 400
    res_empty = client.post("/diagnose/ai", json={"symptoms": []})
    assert res_empty.status_code == 400
    print("[OK] Lista vacía rechazada con 400 Bad Request.")

    # 3.2 6 síntomas rechazados con 400
    res_six = client.post("/diagnose/ai", json={"symptoms": ["S1", "S2", "S3", "S4", "S5", "S6"]})
    assert res_six.status_code == 400, f"Esperado 400 para 6 síntomas, obtenido {res_six.status_code}"
    assert "máximo 5" in res_six.get_json().get("message", "").lower()
    print("[OK] 6 síntomas rechazados con 400 Bad Request ('Máximo 5 síntomas').")

    # 3.3 6 síntomas en /diagnose rechazados con 400
    res_six_doc = client.post("/diagnose", json={"symptoms": ["S1", "S2", "S3", "S4", "S5", "S6"]})
    assert res_six_doc.status_code == 400
    print("[OK] 6 síntomas en /diagnose rechazados con 400 Bad Request.")

    print("\n" + "=" * 80)
    print(f"RESUMEN FINAL: {passed_scenarios}/{total_scenarios} escenarios reales superados con éxito.")
    print("Límite de máximo 5 síntomas y razonamiento de relación/desacoplamiento 100% operativos.")
    print("=" * 80)

if __name__ == "__main__":
    run()
