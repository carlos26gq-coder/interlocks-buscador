"""SOLVI - Servicio de Multímetro Digital, Puntos de Prueba y Tolerancias Eléctricas Linac.

Proporciona catálogo de puntos de prueba de los 5 subsistemas de aceleradores Elekta,
reglas de tolerancia eléctrica, diagnóstico de desviaciones y motor de simulación.
"""

from __future__ import annotations

import math
import random
import re
from typing import Any


TEST_POINTS_CATALOG: dict[str, dict[str, Any]] = {
    "TP1": {
        "id": "TP1",
        "code": "TP1",
        "name": "Punto de Prueba TP1",
        "subsystem": "safety_loop",
        "subsystem_name": "Bucle de Seguridad de Interlocks",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 24.0,
        "tolerance_min": 23.2,
        "tolerance_max": 24.8,
        "warning_low": 23.5,
        "warning_high": 24.5,
        "spec": "24.0V DC ± 0.8V (Alimentación primaria de bucle de seguridad)",
        "manual": "diagrams",
        "page": 14,
        "role": "Monitor de tensión positiva de entrada de cadena de paradas",
        "notes": "Verificar fusible FS1 y tensión de salida de fuente PSU 24V si la lectura es inferior a 23.2V.",
    },
    "TP2": {
        "id": "TP2",
        "code": "TP2",
        "name": "Punto de Prueba TP2",
        "subsystem": "safety_loop",
        "subsystem_name": "Bucle de Seguridad de Interlocks",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 24.0,
        "tolerance_min": 23.0,
        "tolerance_max": 24.8,
        "warning_low": 23.4,
        "warning_high": 24.5,
        "spec": "24.0V DC (Retorno pulsadores de emergencia cerrado)",
        "manual": "diagrams",
        "page": 15,
        "role": "Verificación de continuidad en bucle de setas de parada",
        "notes": "Si TP1 tiene 24V y TP2 tiene < 1V, al menos una seta de emergencia (Consola, Gantry o Búnker) está pulsada o con contacto abierto.",
    },
    "TP5": {
        "id": "TP5",
        "code": "TP5",
        "name": "Punto de Prueba TP5",
        "subsystem": "safety_loop",
        "subsystem_name": "Bucle de Seguridad de Interlocks",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 24.0,
        "tolerance_min": 22.8,
        "tolerance_max": 25.0,
        "warning_low": 23.2,
        "warning_high": 24.6,
        "spec": "24.0V DC (Driver de contactores activo / permisivo OK)",
        "manual": "diagrams",
        "page": 16,
        "role": "Salida de control hacia bobinas de contactores K1 y K2",
        "notes": "Controlado por PCB 16N tras verificar toda la cadena de enclavamientos cerrada.",
    },
    "TP3": {
        "id": "TP3",
        "code": "TP3",
        "name": "Punto de Prueba TP3",
        "subsystem": "radiation_beam",
        "subsystem_name": "Habilitación de Radiación y Modulador RF",
        "mode": "voltage_pulse",
        "unit": "V",
        "nominal": 800.0,
        "tolerance_min": 720.0,
        "tolerance_max": 880.0,
        "warning_low": 740.0,
        "warning_high": 860.0,
        "spec": "800V pico / 3.5µs (Pulso de rejilla de tiratrón)",
        "manual": "ht_rf",
        "page": 26,
        "role": "Monitor de forma de onda del pulso de disparo de conmutador rápido",
        "notes": "Requiere sonda de alta tensión atenuadora 100:1 o divisor resistivo para multímetro.",
    },
    "TP_HT": {
        "id": "TP_HT",
        "code": "TP_HT",
        "name": "Punto de Prueba TP_HT",
        "subsystem": "radiation_beam",
        "subsystem_name": "Habilitación de Radiación y Modulador RF",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 14.0,
        "tolerance_min": 10.0,
        "tolerance_max": 18.0,
        "warning_low": 11.0,
        "warning_high": 17.0,
        "spec": "Divisor resistivo 1:1000 (1V medido = 1kV en tanque)",
        "manual": "ht_rf",
        "page": 35,
        "role": "Monitoreo seguro de la tensión continua del modulador de alta tensión",
        "notes": "Una lectura de 14.2V equivale exactamente a 14.2 kV DC en el banco de condensadores PFN.",
    },
    "TP_RF": {
        "id": "TP_RF",
        "code": "TP_RF",
        "name": "Punto de Prueba TP_RF",
        "subsystem": "radiation_beam",
        "subsystem_name": "Habilitación de Radiación y Modulador RF",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 5.0,
        "tolerance_min": 4.2,
        "tolerance_max": 5.8,
        "warning_low": 4.5,
        "warning_high": 5.5,
        "spec": "Muestreador atenuador coaxial de -50dB (Envolvente detectada)",
        "manual": "ht_rf",
        "page": 50,
        "role": "Punto de muestreo de potencia para detector y control automático",
        "notes": "Representa el nivel rectificado de RF entregado a la guía aceleradora.",
    },
    "TP100": {
        "id": "TP100",
        "code": "TP100",
        "name": "Punto de Prueba TP100",
        "subsystem": "dosimetry",
        "subsystem_name": "Dosimetría y Doble Canal Independiente",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 400.0,
        "tolerance_min": 395.0,
        "tolerance_max": 405.0,
        "warning_low": 397.0,
        "warning_high": 403.0,
        "spec": "+400.0V DC ± 2V (Monitor de Polarización Cámara)",
        "manual": "dosimetry",
        "page": 13,
        "role": "Verificación de estabilidad de la tensión de polarización de cámara de ionización",
        "notes": "Cualquier fluctuación mayor a ±5V altera la recombinación iónica y calibración del haz.",
    },
    "TP_DOSE1": {
        "id": "TP_DOSE1",
        "code": "TP_DOSE1",
        "name": "Punto de Prueba TP_DOSE1",
        "subsystem": "dosimetry",
        "subsystem_name": "Dosimetría y Doble Canal Independiente",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 4.0,
        "tolerance_min": 0.0,
        "tolerance_max": 10.0,
        "warning_low": 0.1,
        "warning_high": 9.5,
        "spec": "0-10V DC (1V = 100 cGy/min calibrado)",
        "manual": "dosimetry",
        "page": 27,
        "role": "Lectura directa en multímetro de la tasa de dosis del canal primario",
        "notes": "En reposo debe medir 0.0V ± 0.02V. Con haz de 400 cGy/min debe indicar exactamente 4.00V.",
    },
    "TP_DOSE2": {
        "id": "TP_DOSE2",
        "code": "TP_DOSE2",
        "name": "Punto de Prueba TP_DOSE2",
        "subsystem": "dosimetry",
        "subsystem_name": "Dosimetría y Doble Canal Independiente",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 4.0,
        "tolerance_min": 0.0,
        "tolerance_max": 10.0,
        "warning_low": 0.1,
        "warning_high": 9.5,
        "spec": "0-10V DC (Calibrado a tasa secundaria redundante)",
        "manual": "dosimetry",
        "page": 33,
        "role": "Punto de prueba para contraste de calibración entre canal 1 y canal 2",
        "notes": "La diferencia |TP_DOSE1 - TP_DOSE2| no debe superar 0.12V (3%) durante emisión continua.",
    },
    "TP_SPEED": {
        "id": "TP_SPEED",
        "code": "TP_SPEED",
        "name": "Punto de Prueba TP_SPEED",
        "subsystem": "gantry_collimator",
        "subsystem_name": "Accionamiento de Gantry y Colimador",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 0.0,
        "tolerance_min": -10.0,
        "tolerance_max": 10.0,
        "warning_low": -9.0,
        "warning_high": 9.0,
        "spec": "±10.0V DC proporcional a RPM de gantry",
        "manual": "movement",
        "page": 50,
        "role": "Monitoreo del lazo analógico de velocidad taquimétrica",
        "notes": "0V en estático. Signo positivo en sentido horario (CW) y negativo en antihorario (CCW).",
    },
    "TP_POS": {
        "id": "TP_POS",
        "code": "TP_POS",
        "name": "Punto de Prueba TP_POS",
        "subsystem": "gantry_collimator",
        "subsystem_name": "Accionamiento de Gantry y Colimador",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 5.0,
        "tolerance_min": 0.0,
        "tolerance_max": 10.0,
        "warning_low": 0.5,
        "warning_high": 9.5,
        "spec": "0-10V DC correspondiente exactamente a 0° - 360°",
        "manual": "movement",
        "page": 57,
        "role": "Comprobación de linealidad del ángulo de gantry",
        "notes": "0.0V = 0°, 2.5V = 90°, 5.0V = 180°, 7.5V = 270°, 10.0V = 360°.",
    },
    "TP_VAC": {
        "id": "TP_VAC",
        "code": "TP_VAC",
        "name": "Punto de Prueba TP_VAC",
        "subsystem": "vacuum_gun",
        "subsystem_name": "Control de Vacío y Cañón de Electrones",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 2.0,
        "tolerance_min": 1.2,
        "tolerance_max": 2.8,
        "warning_low": 1.5,
        "warning_high": 2.5,
        "spec": "1V DC por década (ej: 2.0V = 1.0x10^-8 Torr)",
        "manual": "vacuum",
        "page": 20,
        "role": "Monitor analógico directo de presión de vacío de acelerador",
        "notes": "Si la tensión sube de 3.0V (5.0x10^-7 Torr), el interlock ITEM 112 dispara de inmediato.",
    },
    "TP_GUN": {
        "id": "TP_GUN",
        "code": "TP_GUN",
        "name": "Punto de Prueba TP_GUN",
        "subsystem": "vacuum_gun",
        "subsystem_name": "Control de Vacío y Cañón de Electrones",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 1.8,
        "tolerance_min": 1.7,
        "tolerance_max": 1.9,
        "warning_low": 1.72,
        "warning_high": 1.88,
        "spec": "1.8V DC (1V medido = 1.0A de corriente de filamento)",
        "manual": "ht_rf",
        "page": 54,
        "role": "Comprobación de la corriente exacta de caldeo del cátodo",
        "notes": "Corriente estabilizada requerida para emisión termoiónica estable a 1050°C.",
    },
    "TP7": {
        "id": "TP7",
        "code": "TP7",
        "name": "Punto de Prueba TP7",
        "subsystem": "vacuum_gun",
        "subsystem_name": "Control de Vacío y Cañón de Electrones",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": -150.0,
        "tolerance_min": -165.0,
        "tolerance_max": -135.0,
        "warning_low": -160.0,
        "warning_high": -140.0,
        "spec": "Tensión de polarización de corte de rejilla cañón (-150V DC)",
        "manual": "ht_rf",
        "page": 57,
        "role": "Verificación de polarización negativa de corte de inyección de haz",
        "notes": "Durante pulso activo sube a 0V para permitir inyección al tubo acelerador.",
    },
    "GEN_VOLT_24": {
        "id": "GEN_VOLT_24",
        "code": "GEN +24V",
        "name": "Línea Genérica +24V DC",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 24.0,
        "tolerance_min": 23.0,
        "tolerance_max": 25.0,
        "warning_low": 23.3,
        "warning_high": 24.7,
        "spec": "24.0V DC ± 1.0V",
        "manual": "power_supplies",
        "page": 10,
        "role": "Alimentación de relés, bobinas y lógica industrial",
        "notes": "Línea principal de automatización y bucles de control.",
    },
    "GEN_VOLT_15": {
        "id": "GEN_VOLT_15",
        "code": "GEN +15V",
        "name": "Línea Analógica +15V DC",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 15.0,
        "tolerance_min": 14.5,
        "tolerance_max": 15.5,
        "warning_low": 14.7,
        "warning_high": 15.3,
        "spec": "15.0V DC ± 0.5V",
        "manual": "power_supplies",
        "page": 12,
        "role": "Alimentación positiva de amplificadores operacionales",
        "notes": "Utilizado en circuitos de dosimetría, integradores y servocontrol.",
    },
    "GEN_VOLT_M15": {
        "id": "GEN_VOLT_M15",
        "code": "GEN -15V",
        "name": "Línea Analógica -15V DC",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": -15.0,
        "tolerance_min": -15.5,
        "tolerance_max": -14.5,
        "warning_low": -15.3,
        "warning_high": -14.7,
        "spec": "-15.0V DC ± 0.5V",
        "manual": "power_supplies",
        "page": 12,
        "role": "Alimentación negativa de amplificadores operacionales",
        "notes": "Riel simétrico complementario a la línea +15V.",
    },
    "GEN_VOLT_12": {
        "id": "GEN_VOLT_12",
        "code": "GEN +12V",
        "name": "Línea Control +12V DC",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 12.0,
        "tolerance_min": 11.4,
        "tolerance_max": 12.6,
        "warning_low": 11.6,
        "warning_high": 12.4,
        "spec": "12.0V DC ± 0.6V",
        "manual": "power_supplies",
        "page": 14,
        "role": "Alimentación de ventiladores y drivers auxiliares",
        "notes": "Línea estabilizada para módulos de control intermedio.",
    },
    "GEN_VOLT_5": {
        "id": "GEN_VOLT_5",
        "code": "GEN +5V",
        "name": "Línea Lógica TTL +5V DC",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "voltage_dc",
        "unit": "V",
        "nominal": 5.0,
        "tolerance_min": 4.75,
        "tolerance_max": 5.25,
        "warning_low": 4.85,
        "warning_high": 5.15,
        "spec": "5.0V DC ± 0.25V (Tolerancia estándar TTL 5%)",
        "manual": "power_supplies",
        "page": 16,
        "role": "Alimentación de microcontroladores y lógica digital TTL",
        "notes": "Caídas por debajo de 4.75V provocan reinicios intempestivos de microprocesadores.",
    },
    "GEN_CONT_LOOP": {
        "id": "GEN_CONT_LOOP",
        "code": "CONT BUCL",
        "name": "Continuidad de Contactos / Pulsadores",
        "subsystem": "general",
        "subsystem_name": "Líneas de Alimentación General",
        "mode": "resistance_continuity",
        "unit": "Ω",
        "nominal": 0.2,
        "tolerance_min": 0.0,
        "tolerance_max": 0.8,
        "warning_low": 0.0,
        "warning_high": 0.5,
        "spec": "< 0.5 Ω (Contacto cerrado óptimo)",
        "manual": "technical",
        "page": 30,
        "role": "Medición de resistencia ohmica de contactos secos de seguridad",
        "notes": "Resistencias > 1.0 Ω indican carbonización o desajuste mecánico de contactos.",
    },
}


NODE_TO_TP_MAP: dict[str, str] = {
    "PSU_24V": "GEN_VOLT_24",
    "PSU1 +24V": "GEN_VOLT_24",
    "ESTOP_CONSOLE": "GEN_CONT_LOOP",
    "ESTOP_GANTRY": "GEN_CONT_LOOP",
    "ESTOP_ROOM": "GEN_CONT_LOOP",
    "DOOR_SW_283": "GEN_CONT_LOOP",
    "COLLISION_HEAD": "GEN_CONT_LOOP",
    "KEY_SERVICE": "GEN_CONT_LOOP",
    "K1_K2_DRV": "TP5",
    "GUN_FILAMENT": "TP_GUN",
    "VAC_PUMP": "TP_VAC",
    "ION_CHAMBER": "TP100",
}


def get_all_test_points() -> list[dict[str, Any]]:
    """Retorna la lista completa de puntos de prueba con sus especificaciones."""
    return list(TEST_POINTS_CATALOG.values())


def get_test_point(tp_id: str) -> dict[str, Any] | None:
    """Obtiene la ficha técnica de un punto de prueba por su código o identificador."""
    key = str(tp_id or "").strip()
    if not key:
        return None
    if key in TEST_POINTS_CATALOG:
        return TEST_POINTS_CATALOG[key]

    key_upper = key.upper()
    if key_upper in TEST_POINTS_CATALOG:
        return TEST_POINTS_CATALOG[key_upper]

    if key_upper in NODE_TO_TP_MAP:
        mapped_id = NODE_TO_TP_MAP[key_upper]
        if mapped_id in TEST_POINTS_CATALOG:
            return TEST_POINTS_CATALOG[mapped_id]

    for tp in TEST_POINTS_CATALOG.values():
        if tp["code"].upper() == key_upper or tp["id"].upper() == key_upper:
            return tp

    match = re.match(r"^(TP\w*|GEN_\w+)", key_upper)
    if match:
        prefix = match.group(1)
        if prefix in TEST_POINTS_CATALOG:
            return TEST_POINTS_CATALOG[prefix]

    return None


def evaluate_measurement(
    tp_id: str,
    measured_value: float | int,
    unit: str = "V",
    custom_nominal: float | None = None,
    custom_tolerance_pct: float | None = None,
) -> dict[str, Any]:
    """Evalúa una lectura contra los límites de tolerancia del punto de prueba.

    Retorna un diccionario completo con:
    - status: 'DENTRO_DE_TOLERANCIA', 'ADVERTENCIA_MARGINAL', 'FUERA_DE_TOLERANCIA'
    - delta: diferencia numérica respecto al valor nominal
    - percent_error: porcentaje de desviación
    - recommendation: sugerencia técnica determinista de actuación
    """
    tp = get_test_point(tp_id)

    try:
        val = float(measured_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor medido inválido: {measured_value}") from exc

    if not math.isfinite(val):
        raise ValueError("El valor medido debe ser un número finito.")

    if tp:
        nominal = float(tp["nominal"])
        t_min = float(tp["tolerance_min"])
        t_max = float(tp["tolerance_max"])
        w_low = float(tp.get("warning_low", t_min))
        w_high = float(tp.get("warning_high", t_max))
        tp_name = tp["name"]
        subsystem = tp["subsystem_name"]
        role = tp["role"]
        notes = tp["notes"]
        expected_unit = tp["unit"]
        is_known = True

        # P0-7: Validar que la unidad suministrada sea compatible con la unidad esperada del TP
        if unit:
            u_clean = str(unit).strip().lower()
            exp_clean = expected_unit.lower()
            volt_aliases = {"v", "volt", "volts", "vdc", "vac"}
            ohm_aliases = {"ω", "ohm", "ohms", "o"}
            if exp_clean in volt_aliases:
                if u_clean not in volt_aliases:
                    raise ValueError(
                        f"Unidad incompatible '{unit}' para el punto de prueba '{tp['id']}'. "
                        f"Se requiere '{expected_unit}'."
                    )
            elif exp_clean in ohm_aliases:
                if u_clean not in ohm_aliases:
                    raise ValueError(
                        f"Unidad incompatible '{unit}' para el punto de prueba '{tp['id']}'. "
                        f"Se requiere '{expected_unit}'."
                    )
            elif u_clean != exp_clean:
                raise ValueError(
                    f"Unidad incompatible '{unit}' para el punto de prueba '{tp['id']}'. "
                    f"Se requiere '{expected_unit}'."
                )
    else:
        # P0-3: Si el TP no existe en catálogo y no se suministra un nominal personalizado, rechazar con error
        if custom_nominal is None:
            raise ValueError(
                f"Punto de prueba desconocido '{tp_id}'. "
                "Especifique un identificador válido o proporcione un valor nominal personalizado."
            )
        is_known = False
        nominal = float(custom_nominal)
        tol_pct = float(custom_tolerance_pct if custom_tolerance_pct is not None else 5.0)
        margin = abs(nominal * (tol_pct / 100.0))
        if margin == 0:
            margin = 0.5
        t_min = nominal - margin
        t_max = nominal + margin
        w_low = nominal - (margin * 0.75)
        w_high = nominal + (margin * 0.75)
        tp_name = f"Punto Personalizado ({tp_id or 'GEN'})"
        subsystem = "Personalizado / Medición Libre"
        role = "Punto de prueba auxiliar"
        notes = f"Tolerancia configurada al ±{tol_pct:.1f}%."
        expected_unit = unit or "V"

    delta = round(val - nominal, 4)

    # P0-5: Con nominal negativo, no invertir el signo de delta; con nominal cero, retornar None (N/A en frontend)
    if abs(nominal) > 1e-6:
        percent_error: float | None = round((delta / abs(nominal)) * 100.0, 2)
    else:
        percent_error = None

    if t_min <= val <= t_max:
        if w_low <= val <= w_high:
            status = "DENTRO_DE_TOLERANCIA"
            status_badge = "OK"
            status_label = "Dentro de tolerancia normal"
            color = "#4ade80"
            recommendation = "Valor nominal en rango óptimo de operación. No se requieren ajustes."
        else:
            status = "ADVERTENCIA_MARGINAL"
            status_badge = "MARGINAL"
            status_label = "Margen de tolerancia cercano al límite"
            color = "#f59e0b"
            recommendation = (
                f"Lectura próxima al límite permitido [{t_min} a {t_max} {expected_unit}]. "
                "Supervisar estabilidad y verificar posibles cargas excesivas o calentamiento."
            )
    else:
        status = "FUERA_DE_TOLERANCIA"
        status_badge = "FALLA"
        status_label = "Fuera de tolerancia requerida"
        color = "#ef4444"
        err_fmt = f"{percent_error:+g}%" if percent_error is not None else "N/A"
        if val < t_min:
            recommendation = (
                f"Tensión/valor inferior al mínimo permitido ({val:.2f} {expected_unit} < {t_min:.2f} {expected_unit}). "
                f"Δ = {delta:+.2f} {expected_unit} ({err_fmt}). {notes}"
            )
        else:
            recommendation = (
                f"Tensión/valor superior al máximo permitido ({val:.2f} {expected_unit} > {t_max:.2f} {expected_unit}). "
                f"Δ = {delta:+.2f} {expected_unit} ({err_fmt}). Riesgo de sobretensión. "
                "Inspeccionar reguladores y fuentes antes de operar."
            )

    return {
        "test_point_id": tp_id,
        "test_point_code": tp.get("code", tp_id) if tp else tp_id,
        "test_point_name": tp_name,
        "subsystem": subsystem,
        "role": role,
        "manual": tp.get("manual", "") if tp else "",
        "page": tp.get("page", 0) if tp else 0,
        "measured_value": round(val, 4),
        "nominal_value": nominal,
        "tolerance_min": round(t_min, 4),
        "tolerance_max": round(t_max, 4),
        "unit": expected_unit,
        "delta": delta,
        "percent_error": percent_error,
        "status": status,
        "status_badge": status_badge,
        "status_label": status_label,
        "color": color,
        "recommendation": recommendation,
        "technical_notes": notes,
        "is_known_test_point": is_known,
    }


def simulate_reading(
    tp_id: str,
    fault_type: str = "normal",
    add_noise: bool = True,
    noise_amplitude_pct: float = 0.5,
) -> dict[str, Any]:
    """Genera una lectura simulada realista para un punto de prueba.

    Tipos de falla admitidos:
    - 'normal': valor nominal con pequeña fluctuación de ADC.
    - 'open_circuit': circuito abierto (tensión flotante ~ 0.02 - 0.15 V o continuidad infinita).
    - 'resistive_drop': caída resistiva por contacto deficiente (~70-80% de nominal).
    - 'short_circuit': cortocircuito a chasis (0.00 - 0.02 V o ~0.02 Ω).
    - 'overvoltage': sobretensión por falla de regulación (+15% a +25%).
    """
    tp = get_test_point(tp_id)
    if not tp:
        raise ValueError(f"Punto de prueba desconocido para simulación: '{tp_id}'.")

    nominal = float(tp["nominal"])
    mode = tp["mode"]
    unit = tp["unit"]

    fault = str(fault_type or "normal").lower().strip()

    if fault == "open_circuit":
        if mode == "resistance_continuity":
            base_val = 999999.0
        else:
            base_val = 0.05
    elif fault == "resistive_drop":
        if mode == "resistance_continuity":
            base_val = 15.8
        else:
            base_val = nominal * 0.74
    elif fault == "short_circuit":
        if mode == "resistance_continuity":
            base_val = 0.01
        else:
            base_val = 0.00
    elif fault == "overvoltage":
        if mode == "resistance_continuity":
            base_val = 50.0
        else:
            base_val = nominal * 1.20
    else:  # 'normal'
        base_val = nominal

    if add_noise and fault != "open_circuit":
        spread = max(abs(base_val) * (noise_amplitude_pct / 100.0), 0.02)
        noise = random.uniform(-spread, spread)
        simulated_value = round(base_val + noise, 3)
    else:
        simulated_value = round(base_val, 3)

    if mode == "resistance_continuity":
        simulated_value = max(0.001, simulated_value)

    evaluation = evaluate_measurement(tp["id"], simulated_value, unit=unit)
    evaluation["fault_injected"] = fault
    evaluation["is_simulation"] = True

    return evaluation
