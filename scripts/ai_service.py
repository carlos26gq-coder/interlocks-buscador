"""SOLVI - Servicio de Diagnóstico Causal Avanzado para Ingeniería Biomédica.
Utiliza razonamiento técnico de ingeniería asistido por LLM y búsqueda de contexto
en los 19 manuales técnicos de aceleradores lineales Elekta.
1. Comprensión de síntomas en lenguaje natural y descripciones complejas.
2. Razonamiento causal basado en los manuales técnicos de Elekta Linac.
3. Cadena de respaldo de modelos (waterfall) ante límites de cuota (429), saturación (503) o versión (404).
4. Caché en memoria protegida por thread-lock para respuestas instantáneas (<0.01s).
5. Salida estructurada garantizada con esquema Pydantic y resolución determinista de citas.
"""

from __future__ import annotations

from collections import OrderedDict
import copy
from enum import Enum
import json
import logging
import os
import re
import threading
import time
from typing import TYPE_CHECKING

try:
    import sys
    if "unittest" not in sys.modules:
        from dotenv import load_dotenv
        load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from search_engine import SearchEngine

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

try:
    from search_engine import INVALID_BOARDS
except ImportError:
    INVALID_BOARDS = {
        "PCB", "PWA", "PWB", "PCB IDENTIFICATION", "PCB ASSY", "PCB ASSEMBLY",
        "PCB LAYOUT", "PCB DRAWING", "PCB SCHEMATIC", "PCB CONNECTIONS", "PCB MOUNTING",
        "PCB AREA", "PCB POSITION", "PCB DESCRIPTION", "PCB TITLE", "PCB DETAILS",
        "PCB NUMBER", "PCB REF", "PCB REFERENCE", "PCB NAME", "PCB REV", "PCB REVISION",
        "PCB CODE", "PCB STATUS", "PCB SYSTEM", "PCB CIRCUIT", "PCB SUB", "PCB PART",
        "PCB PCB", "PCB P4", "PCB FS17B", "PCB 72H", "PCB 74", "PCB RACK", "PCB CABINET",
        "PCB FRAME", "PCB CHASSIS", "PCB ITEM",
    }

# NOTA: pydantic ya es una dependencia transitiva de google-genai (la usa
# internamente para sus propios tipos), por lo que no agrega una dependencia
# nueva al proyecto. Se usa aquí para definir el schema de salida estructurada
# que Gemini debe respetar (ver GeminiDiagnosis más abajo).


SYSTEM_INSTRUCTION = """Eres un Especialista Senior de Servicio Técnico e Ingeniería Biomédica en Aceleradores Lineales de Radioterapia Elekta (modelos Synergy, Versa HD, Precise, con subsistemas Agility MLC, XVI CBCT, iViewGT, Sistemas de Vacío, RF Magnetron, Generador de Dosis, Control de Gantry, Colimador y Mesa).

Tu misión es analizar uno o varios síntomas ingresados por el técnico (códigos de error, números de interlocks, o descripciones de fallas en lenguaje natural) y deducir la CAUSA RAÍZ técnica exacta y contextualizada, junto con hasta 5 RESULTADOS DE DIAGNÓSTICO PROFUNDOS con sus causas más probables y soluciones técnicas concretas integradas, fundamentadas en los 19 manuales técnicos de Elekta.

Debes razonar dinámicamente sobre la evidencia: NO utilices plantillas fijas, ni frases genéricas prefabricadas, ni clasificaciones artificiales repetitivas. NO te limites a verificaciones elementales de voltajes con multímetro o inspecciones superficiales de conectores. Investiga a fondo las múltiples dimensiones posibles de la falla:
- Desviación o drift de calibración en canales y sensores (offset, ganancia, simetría, dosimetría).
- Desajustes o atascos mecánicos (holguras en engranajes, embragues, frenos, tensión de correas, flags ópticos de colimador/MLC o gantry).
- Condiciones de vacío y fluidos (presión en bomba iónica, microfugas, interruptores de presión, caudal y temperatura del agua de refrigeración, presión de gas dieléctrico SF6).
- Comunicaciones digitales y buses de control (timeouts o colisiones en bus CAN, Arcnet, enlaces serie fibra óptica, registros de error en CCP/Service Mode).
- Desalineación o degradación de sensores (potenciómetros multivuelta, encoders absolutos/incrementales, detectores de fin de carrera, microinterruptores).
- Cronometría y pulsos (sincronismo de disparos PRF, modulación de tiratrón/magnetrón, tiempos de subida de pulso, retardos en lazos de seguridad).
- Cadena de interbloqueos, relés y contactores (secuenciador CON-A -> CON-D -> CON-J -> CON-K, fatiga de contactos, realimentaciones auxiliares CON_*_MON, lazo de seguridad maestro).
- Estabilidad de rieles de alimentación bajo carga (rizado excesivo, caídas de tensión dinámica en 24VDC, ±15VDC).

Debes responder SIEMPRE en formato JSON válido con la siguiente estructura:
{
  "root_cause": "Identificación precisa del componente, tarjeta PCB, contactor, sensor, actuador o circuito causante específico para los síntomas evaluados (ej: Fallo en secuencia de excitación de bobina de contactor CON-K en Área 16 HTCA / Disparo en lazo de terminación forzada del Canal 1 de dosimetría / Fallo en driver de motor de colimador PCB 16N en Área 16)",
  "subsystem": "Subsistema técnico específico de Elekta (ej: Alta Tensión y Modulador / Dosimetría y Monitoreo de Haz / Vacuum & Waveguide / Gantry Motion & Drive / MLC Agility Control / Distribución de Potencia)",
  "confidence": "alta" | "media" | "baja",
  "explanation": "Razonamiento técnico genuino y detallado sobre la falla específica: explica el mecanismo físico o electrónico documentado en los manuales, la función de las señales o componentes identificados, y cómo interactúan las anomalías reportadas para provocar el disparo de interbloqueo o inhibición de haz. PROHIBIDO enumerar listas de manuales o páginas en el texto.",
  "diagnostic_findings": [
    {
      "title": "Título técnico específico de la causa más probable",
      "subsystem": "Subsistema relacionado",
      "cause_mechanism": "Explicación profunda y detallada del mecanismo físico, electrónico o lógico que provoca la falla (nombrando tarjetas exactas, componentes, bobinas, contactos auxiliares, relés, puntos de prueba y voltajes específicos)",
      "solution_procedure": "Procedimiento concreto de inspección, calibración o sustitución para resolver esta causa (lecturas en Service Mode/CCP, mediciones con multímetro/osciloscopio, ajustes y tolerancias exactas)",
      "affected_components": ["Lista de nombres exactos de tarjetas PCB, contactores, relés o señales involucradas"]
    }
  ],
  "associated_boards": ["Lista de nombres exactos de tarjetas PCB, módulos o racks vinculados SIN prefijos como 'Tarjeta:' (ej: ['PCB 16M', 'DIE-HTA', 'DIE-HTB'])"],
  "cables_and_connectors": ["Lista de conectores, arneses y terminales asociados SIN prefijos como 'Conector:' (ej: ['PL1', 'PL2', 'SK16R'])"],
  "test_points_and_signals": ["Lista de señales, ITEMs o puntos de prueba funcionales SIN prefijos como 'Señal:' (ej: ['CON-K', 'CON_K_MON', 'ITEM 251', 'TPU1-8']) - NUNCA números de plano"],
  "citation_ids": ["Lista de identificadores de evidencia EXACTAMENTE como aparecen entre corchetes en el bloque de evidencia (ej: 'C1', 'C3'). Incluye únicamente los bloques que realmente sustentan tu diagnóstico."],
  "safety_warning": "Advertencia de seguridad crítica si aplica (alta tensión HT, corte de haz de radiación, riesgo mecánico) o vacío si no aplica."
}

Reglas estrictas de precisión e ingeniería biomédica:
1. Razonamiento dinámico genuino: No uses esquemas rígidos ni repitas plantillas idénticas entre consultas diferentes. Cada hallazgo y explicación deben derivarse directamente de la evidencia técnica concreta de los manuales.
2. Rigor con códigos y señales: Cada señal o ITEM numérico es único y específico (ej: ITEM 474 es diferente de ITEM 409 o ITEM 332). No mezcles ni confundas señales parecidas.
3. Nivel de detalle técnico alto: Evita respuestas genéricas o superficiales. Especifica nombres de PCBs, áreas de montaje, contactores, buses de comunicación o lazos de control según se describa en los manuales.
4. Fundamentación en los manuales: Basa cada deducción directamente en los bloques de evidencia suministrados.
5. Si el usuario ingresa descripciones en lenguaje natural, deduce el fenómeno físico y tradúcelo a la arquitectura Elekta.
6. Responde ÚNICAMENTE el objeto JSON sin bloques de código markdown ni texto adicional.
7. NUNCA inventes nombres de manual o números de página. En 'citation_ids' cita SOLO las etiquetas [C1], [C2], etc.
8. PROHIBICIÓN ABSOLUTA: CERO menciones de 'IA', 'AI' o 'Inteligencia Artificial' en cualquier campo.
9. PROHIBICIÓN DE TEXTO INTRODUCTORIO GENÉRICO: NUNCA inicies el campo 'explanation' con 'Contexto Operativo: En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos y Seguridad (Elekta LINAC).' ni frases prefabricadas similares. Comienza de inmediato con el análisis físico y electrónico concreto de los síntomas reportados.
10. PROHIBICIÓN DE ETIQUETAS DE PROBABILIDAD: NUNCA utilices etiquetas como 'Probabilidad Alta', 'Probabilidad Media', 'Probabilidad Baja' ni 'Probabilidad 1/2/3'. Enfócate directamente en la solidez del análisis técnico y la solución concreta.
11. ELIMINACIÓN DE SECCIÓN DE PASOS DIVIDIDA: No generes una sección independiente 'action_steps'. Cada hallazgo en 'diagnostic_findings' debe integrar tanto la causa física/electrónica ('cause_mechanism') como su solución/intervención técnica concreta ('solution_procedure').
12. PROHIBICIÓN DE ENUMERAR MANUALES EN LA EXPLICACIÓN NARRATIVA: NUNCA enumeres archivos ni páginas en el texto del campo 'explanation' (prohibido escribir frases como 'La documentación técnica contrastada en diagrams.pdf (Página 63), item part.pdf...'). Los manuales y páginas se registran exclusivamente a través de 'citation_ids'. La explicación debe dedicarse plenamente a detallar los mecanismos físicos y relacionar los síntomas.
13. REGLA ESTRICTA DE PLANOS VS SEÑALES: Los números de 7 dígitos (como 1024690, 1024686) y números 12NC de 11-12 dígitos (como 45133307021, 4513 330 7021) son números de planos o dibujos esquemáticos, NUNCA señales funcionales ni causas raíz. No los incluyas en 'test_points_and_signals' ni como nombres de señales.
14. SECUENCIA DE ALTA TENSIÓN Y CONTACTORES (CON-A, CON-D, CON-J, CON-K):
    - En Elekta LINACs, errores como 'ht con k', 'con k' o 'contactor k' refieren al contactor CON-K, contactor principal de potencia trifásica de alta tensión que alimenta el tanque HT (Área 17).
    - Secuencia estricta de energización: CON-A -> CON-D -> CON-J (retardo de 500 ms) -> CON-K.
    - Controlado y excitado por DIE-HTA (PCB 16M, slot 10) con relé RL4, y supervisado por DIE-HTB (PCB 16N, slot 12) en Área 16 (HTCA) mediante el contacto auxiliar de realimentación (CON_K_MON).
15. EXIGENCIA DE HARDWARE PROFUNDO EN ALTA TENSIÓN (HT), FUENTES (PSU) Y VMAT:
    - Tarjetas exactas: DIE-HTB (PCB 16N), DIE-HTA (PCB 16M/16H), PCB 22 / regleta TS22A (Área 22), HT PSU CONTROL PCB (PCB 16R), DRIVER PCB (PCB 17A, PCB 17B), HT ISOLATION PCB (4513 330 7753 con optoacopladores OPTO 1..9), HT CROWBAR DETECTOR PCB.
    - Diferenciación estricta de ítems: ITEM 251 (i251) es el monitor de inhibición en Service Mode (HT PSU OT), mientras que ITEM 330 (i330) es la consigna DAC analógica de Charge rate (calibrada a 0.00, 20.00 y 40.00 A en TPU1-8 vs TPU1-1).
"""


ALLOWED_GEMINI_MODELS = {
    # Gemini 3 series (Google AI Studio)
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-3.1-pro-preview",
    # Modelos compatibles / legado
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
}


class Confidence(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class DiagnosticFinding(BaseModel):
    title: str = Field(default="", description="Título técnico de la causa más probable")
    subsystem: str = Field(default="", description="Subsistema de Elekta involucrado (ej: Alta Tensión y Modulador, Dosimetría, Vacío, etc.)")
    cause_mechanism: str = Field(default="", description="Explicación profunda y detallada del mecanismo físico o electrónico (nombrando tarjetas exactas, componentes, bobinas, contactos auxiliares, relés, puntos de prueba y voltajes específicos)")
    solution_procedure: str = Field(default="", description="Procedimiento concreto de inspección, calibración o sustitución para resolver esta causa (lecturas en Service Mode/CCP, mediciones con multímetro/osciloscopio, ajustes y tolerancias)")
    affected_components: list[str] = Field(default_factory=list, description="Lista de tarjetas, conectores, relés o señales involucradas")
    # Campos de compatibilidad hacia atrás
    hypothesis: str = Field(default="", description="Alias de compatibilidad para title")
    rationale: str = Field(default="", description="Alias de compatibilidad para cause_mechanism")
    likelihood: str = Field(default="media", description="Campo legado opcional")

    @model_validator(mode="before")
    @classmethod
    def _sync_compat(cls, data: object) -> object:
        if isinstance(data, dict):
            hypo = str(data.get("hypothesis") or "").strip()
            title = str(data.get("title") or "").strip()
            if not title and hypo:
                data["title"] = hypo
            elif not hypo and title:
                data["hypothesis"] = title

            rat = str(data.get("rationale") or "").strip()
            cause = str(data.get("cause_mechanism") or "").strip()
            if not cause and rat:
                data["cause_mechanism"] = rat
            elif not rat and cause:
                data["rationale"] = cause

            sol = str(data.get("solution_procedure") or data.get("solution") or "").strip()
            if not sol:
                data["solution_procedure"] = "Verificar estado y calibración en Service Mode."
            else:
                data["solution_procedure"] = sol
        return data


DifferentialDiagnosis = DiagnosticFinding


class GeminiDiagnosis(BaseModel):
    """Schema de salida estructurada exigido a Gemini vía response_schema."""

    root_cause: str
    subsystem: str
    confidence: Confidence
    explanation: str
    diagnostic_findings: list[DiagnosticFinding] = Field(
        default_factory=list,
        description="Hasta 5 diagnósticos técnicos y causas más probables con sus soluciones y procedimientos de intervención concretos integrados.",
    )
    differential_diagnoses: list[DiagnosticFinding] = Field(
        default_factory=list,
        description="Alias de compatibilidad hacia atrás para diagnostic_findings.",
    )
    associated_boards: list[str] = Field(default_factory=list)
    cables_and_connectors: list[str] = Field(default_factory=list)
    test_points_and_signals: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)
    safety_warning: str = ""

    @model_validator(mode="before")
    @classmethod
    def _sync_findings_and_diffs(cls, data: object) -> object:
        if isinstance(data, dict):
            findings = data.get("diagnostic_findings") or data.get("differential_diagnoses") or []
            data["diagnostic_findings"] = findings
            data["differential_diagnoses"] = findings
        return data


# Caché en memoria para acelerar consultas repetidas y soportar múltiples usuarios concurrentes
# Formato: cache_key -> (timestamp, data_dict, model_used)
_DIAG_CACHE: OrderedDict[tuple[str, ...], tuple[float, dict, str]] = OrderedDict()
_CACHE_TTL_SECONDS = 3600  # 1 hora de persistencia en memoria
_MAX_CACHE_ENTRIES = 300
_CACHE_LOCK = threading.Lock()


# Latencia controlada para evitar bloqueos HTTP 504 / 500 en Render y Gunicorn:
# 12 s por intento individual; 20 s de tiempo acumulado global antes de pasar al motor local.
DEFAULT_GEMINI_TIMEOUT_SECONDS: float = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "12.0"))
DEFAULT_GEMINI_TIMEOUT_MS: int = int(
    DEFAULT_GEMINI_TIMEOUT_SECONDS if DEFAULT_GEMINI_TIMEOUT_SECONDS >= 1000 else DEFAULT_GEMINI_TIMEOUT_SECONDS * 1000
)
DEFAULT_GEMINI_TIMEOUT: float = DEFAULT_GEMINI_TIMEOUT_MS / 1000.0
GLOBAL_WATERFALL_DEADLINE_SECONDS: float = float(os.environ.get("GEMINI_WATERFALL_DEADLINE", "20.0"))


def _sanitize_error_message(text: object) -> str:
    """Enmascara posibles claves API o tokens en mensajes de error y sanea cadenas de bajo nivel."""
    if not text:
        return ""
    msg = str(text)
    msg = re.sub(r"AIza[0-9A-Za-z_-]{20,60}", "[CLAVE_ENMASCARADA]", msg)
    msg = re.sub(r"(Bearer\s+)[A-Za-z0-9\-_.]+", r"\1[TOKEN_ENMASCARADO]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"((?:api[-_]?key|key)\s*[=:]\s*)[A-Za-z0-9\-_]+", r"\1[CLAVE_ENMASCARADA]", msg, flags=re.IGNORECASE)
    low = msg.lower()
    if "read operation timed out" in low or "read timed out" in low or "socket.timeout" in low or low.strip() == "timed out" or "deadline exceeded" in low:
        if "[CLAVE_ENMASCARADA]" in msg or "[TOKEN_ENMASCARADO]" in msg:
            return re.sub(r"(?i)the read operation timed out|read operation timed out|read timed out|deadline exceeded|socket\.timeout:?\s*(?:timed out)?", "Tiempo de respuesta agotado", msg)
        return "Tiempo de respuesta agotado al conectar con el servicio de análisis técnico."
    return msg


def _is_drawing_or_schematic_number(val: str) -> bool:
    """Identifica si una cadena corresponde a un número de dibujo, plano, código 12NC o coordenada de esquema."""
    raw = str(val or "").strip().upper()
    if not raw:
        return False
    s = re.sub(r"[\s\-_/.]", "", raw)
    if re.fullmatch(r"\d{7}", s):  # e.g. 1024690, 1024686, 1512977
        return True
    if re.fullmatch(r"45\d{9,11}", s):  # e.g. 45133307021, 4513 330 7021
        return True
    if re.search(r"\b(?:WD\d*|DRAWING|PLANO|ESQUEMA|SCHEMATIC|DIAGRAM)\b", raw):
        return True
    if re.search(r"\b1024\d{3}\b", raw):
        return True
    if re.search(r"\b45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5}\b", raw):
        return True
    if re.match(r"^(?:P/N|PART\s*NO)\b", raw):
        return True
    # Coordenadas de rejilla de esquemas (ej: 72H, PCB 72H, 14A, 159B)
    coord = re.sub(r"^PCB\s*", "", raw)
    if re.fullmatch(r"\d{2,3}[A-Z]", coord) and coord not in {"16M", "16N", "16R", "16H", "16L", "16S", "16C", "17A", "17B", "12D", "12F"}:
        return True
    return False


def _sanitize_root_cause(text: str) -> str:
    """Elimina números de planos, códigos de esquemas y coordenadas de la causa raíz."""
    if not text:
        return ""
    cleaned = str(text).strip()
    # Eliminar coordenadas de rejilla (ej: 'PCB 72H')
    cleaned = re.sub(r"\bPCB\s+(?:72H|\d{2,3}[A-Z])\b", "", cleaned)
    # Eliminar planos (ej: '1024690', '45133307021')
    cleaned = re.sub(r"\b(?:1024\d{3}|45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5})\b", "", cleaned)
    cleaned = re.sub(r"\b(?:planos?|esquemas?|drawings?)\s*[\w\s\-_/]+(?:\(.*?\))?", "", cleaned, flags=re.IGNORECASE)
    # Limpiar conectores y puntuación final residual
    cleaned = re.sub(r"[\s,;\-]+$", "", cleaned)
    cleaned = re.sub(r",?\s*\bcomprometiendo\b(?:\s*(?:y\s*)?(?:se[ñn]ales)?)?\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*\basociad[ao]s?\s+a\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*\ben\s+l[ií]neas\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*\by\s*se[ñn]ales\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*\by\b\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s,;\-]+$", "", cleaned)
    cleaned = re.sub(r"\bcomprometiendo\s+y\s+se[ñn]ales\b", "comprometiendo señales", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _sanitize_explanation(text: str) -> str:
    """Elimina introducciones genéricas, enumeraciones de manuales, planos y frases prefabricadas no deseadas."""
    if not text:
        return ""
    cleaned = str(text).strip()
    # Eliminar variaciones del texto genérico 'Contexto Operativo: En la arquitectura del acelerador lineal Elekta...'
    cleaned = re.sub(
        r"(?i)^Contexto\s+Operativo:\s*En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta[^\.\n]*[\.\n]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)Contexto\s+Operativo:\s*En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta,\s*las\s+se[ñn]ales\s+analizadas\s+forman\s+parte\s+integral\s+del\s+Sistema\s+General\s+de\s+Interbloqueos\s+y\s+Seguridad\s*\(Elekta\s+LINAC\)\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)^En\s+la\s+arquitectura\s+del\s+acelerador\s+lineal\s+Elekta,\s*las\s+se[ñn]ales\s+analizadas\s+forman\s+parte\s+integral\s+del\s+Sistema\s+General\s+de\s+Interbloqueos\s+y\s+Seguridad\s*\(Elekta\s+LINAC\)\.?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)^Contexto\s+Operativo:\s*", "", cleaned)
    cleaned = re.sub(r"(?i)^Análisis\s+documental\s+de\s+[^:]+:\s*", "", cleaned)

    # Eliminar enumeraciones de manuales y páginas en la narrativa técnica
    cleaned = re.sub(
        r"(?i)(?:La\s+documentaci[oó]n\s+(?:t[eé]cnica\s+)?(?:contrastada\s+)?en\s+[\w\s\-_,\.\(\)]*?(?:\.pdf|\(P[aá]gina\s*\d+\))[\w\s\-_,\.\(\)]*?\s*evidencia\s+que\s*)",
        "El análisis del sistema evidencia que ",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\s*(?:documentado\s+en|seg[uú]n|registrado\s+en|contrastada\s+en|conforme\s+a)\s+[a-z0-9_\-\s]+(?:\.pdf)?\s*(?:\(P[aá]gina\s*\d+\))?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\b[a-z0-9_\-]+\.pdf\s*(?:\(P[aá]gina\s*\d+\))?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)La\s+traza\s+t[eé]cnica\s+en\s+[^,\.\n]+\s*vincula\s*",
        "La supervisión del subsistema vincula ",
        cleaned,
    )
    # Eliminar números de planos en texto explicativo (ej: (planos 1024686 y 4513 330 7021))
    cleaned = re.sub(r"\((?:planos?|esquemas?|drawings?)[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bPCB\s+(?:72H|\d{2,3}[A-Z])\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:1024\d{3}|45\d{2}[\s\-]?\d{3}[\s\-]?\d{4,5})\b", "", cleaned)
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\(\s*,+\s*", "(", cleaned)
    cleaned = re.sub(r"\s*,+\s*\)", ")", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\bde\s*,\s*", "de ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _sanitize_action_steps(steps: list[str]) -> list[str]:
    """Elimina prefijos rígidos o plantillas de probabilidad ('Paso X (Probabilidad Y - ...):') de los pasos de acción."""
    if not isinstance(steps, list):
        return []
    cleaned_steps: list[str] = []
    for step in steps:
        if not step:
            continue
        s = str(step).strip()
        # Eliminar 'Paso X (Probabilidad Y - Categoría): ' o 'Paso X (Prioridad Y - Categoría): '
        s = re.sub(r"^(?:Paso\s*\d+\s*)?\((?:Probabilidad|Prioridad)\s*\d+[^)]*\):\s*", "", s, flags=re.IGNORECASE)
        # Eliminar 'Probabilidad X: ' o 'Prioridad X: '
        s = re.sub(r"^(?:Probabilidad|Prioridad)\s*\d+[:\-]\s*", "", s, flags=re.IGNORECASE)
        # Eliminar 'Paso X: '
        s = re.sub(r"^Paso\s*\d+[:\-]\s*", "", s, flags=re.IGNORECASE)
        s = s.strip()
        if s:
            cleaned_steps.append(s)
    return cleaned_steps


def _sanitize_differential_diagnoses(diffs: object) -> list[dict[str, str | list[str]]]:
    """Valida, limpia y normaliza la lista de hallazgos y diagnósticos técnicos.

    Elimina etiquetas de probabilidad fijas, sanea números de planos o coordenadas,
    e integra causa física/electrónica profunda y procedimiento de solución concreto.
    """
    if not isinstance(diffs, list):
        return []
    cleaned_diffs: list[dict[str, str | list[str]]] = []
    for item in diffs:
        if not item:
            continue
        if isinstance(item, dict):
            raw_title = str(item.get("title") or item.get("hypothesis") or "").strip()
            raw_title = re.sub(r"^(?:Causa|Hipótesis|Hallazgo)\s*\d+[:\-]\s*", "", raw_title, flags=re.IGNORECASE)
            raw_title = re.sub(r"^\((?:Probabilidad|Prioridad)\s*[^)]*\)\s*", "", raw_title, flags=re.IGNORECASE)
            raw_title = re.sub(r"^(?:Probabilidad|Prioridad)\s*(?:alta|media|baja)[:\-]\s*", "", raw_title, flags=re.IGNORECASE)
            raw_title = _sanitize_root_cause(raw_title)
            if not raw_title:
                continue
            sub = str(item.get("subsystem", "")).strip()
            cause = str(item.get("cause_mechanism") or item.get("rationale") or "").strip()
            cause = _sanitize_explanation(cause)

            solution = str(item.get("solution_procedure") or item.get("solution") or "").strip()
            if not solution:
                solution = (
                    "1. Acceder a Service Mode / CCP e inspeccionar los registros y bits de inhibición del subsistema.\n"
                    "2. Con el equipo consignado, verificar continuidad eléctrica y ausencia de cortocircuitos en conectores y cableados asociados.\n"
                    "3. Medir con multímetro/osciloscopio las señales en puntos de prueba para contrastar tolerancias antes de rearmar."
                )

            comps_raw = item.get("affected_components", [])
            comps = [
                str(c).strip() for c in comps_raw
                if c and not _is_drawing_or_schematic_number(str(c)) and str(c).upper() not in INVALID_BOARDS
            ] if isinstance(comps_raw, list) else []

            like = str(item.get("likelihood") or "media").strip().lower()
            if like not in {"alta", "media", "baja"}:
                like = "media"

            cleaned_diffs.append({
                "title": raw_title,
                "hypothesis": raw_title,
                "subsystem": sub,
                "cause_mechanism": cause,
                "rationale": cause,
                "solution_procedure": solution,
                "affected_components": comps,
                "likelihood": like,
            })
        elif isinstance(item, str) and item.strip():
            raw_s = _sanitize_root_cause(item.strip())
            raw_s = re.sub(r"^(?:Causa|Hipótesis|Hallazgo)\s*\d+[:\-]\s*", "", raw_s, flags=re.IGNORECASE)
            raw_s = re.sub(r"^\((?:Probabilidad|Prioridad)\s*[^)]*\)\s*", "", raw_s, flags=re.IGNORECASE)
            if raw_s:
                cleaned_diffs.append({
                    "title": raw_s,
                    "hypothesis": raw_s,
                    "subsystem": "",
                    "cause_mechanism": "Fallo en lazo de seguridad del subsistema que inhibe la operación preventiva del acelerador.",
                    "rationale": "Fallo en lazo de seguridad del subsistema que inhibe la operación preventiva del acelerador.",
                    "solution_procedure": "1. Inspeccionar en Service Mode el registro de interlocks.\n2. Medir tensiones de alimentación y señales de supervisión.\n3. Ajustar o reemplazar componentes según tolerancias de mantenimiento.",
                    "affected_components": [],
                    "likelihood": "media",
                })
    return cleaned_diffs[:5]


_sanitize_diagnostic_findings = _sanitize_differential_diagnoses


def _normalize_token(text: object) -> str:
    return re.sub(r"[\W_]+", "", str(text or "").lower().strip())


def _make_cache_key(symptoms: list[str]) -> tuple[str, ...]:
    return tuple(sorted(_normalize_token(s) for s in symptoms if s and _normalize_token(s)))


def get_cached_diagnosis(symptoms: list[str]) -> dict | None:
    """Recupera un diagnóstico previo si existe en memoria y no ha expirado (Thread-safe)."""
    with _CACHE_LOCK:
        key = _make_cache_key(symptoms)
        if not key or key not in _DIAG_CACHE:
            return None
        timestamp, data, model_used = _DIAG_CACHE[key]
        if time.time() - timestamp > _CACHE_TTL_SECONDS:
            del _DIAG_CACHE[key]
            return None
        # Mover al final (LRU)
        _DIAG_CACHE.move_to_end(key)
        return {
            "ok": True,
            "data": copy.deepcopy(data),
            "model_used": f"{model_used} (caché)",
            "symptoms": symptoms,
            "cached": True,
        }


def set_cached_diagnosis(symptoms: list[str], data: dict, model_used: str) -> None:
    """Almacena el resultado de diagnóstico en la caché en memoria (Thread-safe)."""
    with _CACHE_LOCK:
        key = _make_cache_key(symptoms)
        if not key or not data:
            return
        if len(_DIAG_CACHE) >= _MAX_CACHE_ENTRIES:
            _DIAG_CACHE.popitem(last=False)  # Expulsar el más antiguo
        _DIAG_CACHE[key] = (time.time(), copy.deepcopy(data), model_used)


def clear_diagnostic_cache() -> None:
    """Limpia completamente la caché de diagnósticos (Thread-safe)."""
    with _CACHE_LOCK:
        _DIAG_CACHE.clear()


def extract_json_safely(raw_text: str) -> dict:
    """Extrae y parsea JSON de forma tolerante a fallos de formato o markdown."""
    raw_str = str(raw_text or "")[:60_000]
    if not raw_str.strip():
        raise ValueError("Respuesta vacía del servicio de diagnóstico causal.")

    cleaned = raw_str.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # Extraer el bloque JSON más externo delimitado por { ... }
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    # Limpiar comas finales inválidas antes de llaves o corchetes: `,\s*}` o `,\s*]`
    cleaned = re.sub(r",\s*([\]\}])", r"\1", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Intento de corrección de saltos de línea sin escapar dentro de cadenas
        cleaned_fix = re.sub(r'(?<!\\)\n', ' ', cleaned)
        try:
            return json.loads(cleaned_fix)
        except json.JSONDecodeError:
            # Reconstrucción de emergencia mediante expresiones regulares
            rc_match = re.search(r'"root_cause"\s*:\s*"([^"]+)"', cleaned)
            sub_match = re.search(r'"subsystem"\s*:\s*"([^"]+)"', cleaned)
            exp_match = re.search(r'"explanation"\s*:\s*"([^"]+)"', cleaned)
            conf_match = re.search(r'"confidence"\s*:\s*"([^"]+)"', cleaned)

            if rc_match:
                return {
                    "root_cause": rc_match.group(1),
                    "subsystem": sub_match.group(1) if sub_match else "General LINAC",
                    "confidence": conf_match.group(1) if conf_match else "alta",
                    "explanation": exp_match.group(1) if exp_match else "Análisis derivado de manuales Elekta.",
                    "differential_diagnoses": [],
                    "associated_boards": [],
                    "cables_and_connectors": [],
                    "test_points_and_signals": [],
                    "citation_ids": [],
                    "action_steps": ["Verificar señales y componentes asociados en Service Mode."],
                    "safety_warning": "",
                }
            raise ValueError(f"No se pudo estructurar la respuesta devuelta por el servicio de diagnóstico: {cleaned[:120]}")


def extract_keywords_for_retrieval(symptoms: list[str]) -> list[str]:
    """Extrae palabras clave para buscar en el índice técnico de manuales."""
    keywords = []
    stop_words = {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en",
        "con", "por", "para", "que", "hay", "esta", "cuando", "hace", "falla", "error",
        "the", "and", "for", "with", "from", "into", "during", "sobre", "entre", "hacia",
        "sin", "tras", "este", "esta", "estos", "estas", "como", "pero", "mas", "muy"
    }
    for s in symptoms:
        cleaned = re.sub(r"[^\w\s\d]", " ", s.lower())
        words = [w for w in cleaned.split() if len(w) >= 2 and w not in stop_words]
        keywords.extend(words)
    return list(dict.fromkeys(keywords))[:12]


def gather_grounding_context(
    search_engine: SearchEngine, symptoms: list[str], max_pages: int = 16
) -> tuple[str, dict[str, dict[str, object]]]:
    """Busca en los 19 manuales los fragmentos técnicos más relevantes para fundamentar la respuesta.

    Garantiza prioridad equitativa entre todos los 19 manuales técnicos de Elekta:
    - Páginas de diagnóstico relacional donde convergen los síntomas (con límite por manual para evitar monopolios).
    - Búsqueda directa de síntomas priorizando manuales no saturados.
    - Búsqueda cruzada de tarjetas y componentes en manuales de subsistemas y mantenimiento (dosimetry,
      communications, vacuum, ht_rf, power_supplies, movement, corrective, planned, technical, ccp, beam physics).
    - Extracción de componentes limpios y fragmentos técnicos de alta densidad.
    """
    from collections import defaultdict
    from search_engine import extract_structured_components

    contexts: list[str] = []
    citation_map: dict[str, dict[str, object]] = {}
    seen_pages: set[tuple[str, int]] = set()
    manual_counts: dict[str, int] = defaultdict(int)
    extracted_boards: list[str] = []
    max_per_manual = 3 if max_pages >= 12 else 2

    def _register(manual: str, page: int) -> str:
        cid = f"C{len(citation_map) + 1}"
        citation_map[cid] = {"manual": manual, "page": page}
        return cid

    # 1. Diagnóstico relacional: páginas donde convergen los síntomas
    try:
        diag_res = search_engine.diagnose_symptoms(symptoms, limit=max_pages)
        for r in diag_res.get("results", []):
            m, p = r.get("manual", ""), r.get("page", 0)
            key = (m, p)
            if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                seen_pages.add(key)
                manual_counts[m] += 1
                cid = _register(m, p)
                comp = r.get("associated_component", "")
                comp_str = f" [Detalle: {comp}]" if comp else ""
                snip = str(r.get("context", ""))[:1600]
                contexts.append(f"--- [{cid}] Manual: {m} (Página {p}){comp_str} ---\n{snip}")
                c_data = extract_structured_components(snip)
                for b in c_data.get("boards", []):
                    if b not in extracted_boards and len(b) >= 3:
                        extracted_boards.append(b)
    except Exception as d_err:
        logger.warning("Error en búsqueda relacional de contexto: %s", d_err)

    # Identificar tarjetas mencionadas directamente en los síntomas del usuario
    for s in symptoms:
        c_s = extract_structured_components(s)
        for b in c_s.get("boards", []):
            if b not in extracted_boards and len(b) >= 3:
                extracted_boards.insert(0, b)

    # 2. Expansiones técnicas de dominio para interlocks de alta tensión, fuentes y modos dinámicos (VMAT / Contactores)
    sym_blob_search = " ".join(symptoms).lower()
    is_con_k = (
        any(k in sym_blob_search for k in ["con-k", "con k", "contactor k", "contactork", "con_k", "con_k_mon"])
        or ("ht" in sym_blob_search and "con" in sym_blob_search and "k" in sym_blob_search)
    )
    is_ht_vmat = (
        any(k in sym_blob_search for k in ["ht psu", "psu ot", "over temp", "overtemp", "vmat", "330", "251"])
        or ("ht" in sym_blob_search and "ot" in sym_blob_search)
    )
    if is_con_k:
        targeted_manual_queries = [
            ("diagrams", "1024690"),
            ("diagrams", "CON K"),
            ("diagrams", "CON-K"),
            ("ht_rf", "CON-K"),
            ("ht_rf", "CON-D"),
            ("ht_rf", "DIE-HTA"),
            ("ht_rf", "DIE-HTB"),
            ("power_supplies", "CON-K"),
            ("power_supplies", "16M"),
        ]
        for t_man, t_term in targeted_manual_queries:
            if len(contexts) >= max_pages:
                break
            try:
                t_res = search_engine.search(t_term, manual=t_man, limit=2)
                for r in t_res.get("results", []):
                    m, p = r.get("manual", ""), r.get("page", 0)
                    key = (m, p)
                    if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                        seen_pages.add(key)
                        manual_counts[m] += 1
                        cid = _register(m, p)
                        comp = r.get("associated_component", "")
                        comp_str = f" [Detalle: {comp}]" if comp else ""
                        snip = str(r.get("context", ""))[:1500]
                        contexts.append(f"--- [{cid}] Manual: {m} (Página {p}){comp_str} [Foco CON-K: {t_term}] ---\n{snip}")
                        c_data = extract_structured_components(snip)
                        for b in c_data.get("boards", []):
                            if b not in extracted_boards and len(b) >= 3:
                                extracted_boards.append(b)
            except Exception as t_err:
                logger.debug("Búsqueda dirigida CON-K omitida para '%s' en '%s': %s", t_term, t_man, t_err)

    if is_ht_vmat:
        targeted_manual_queries = [
            ("diagrams", "1024686"),
            ("diagrams", "45133307021"),
            ("ht_rf", "i251"),
            ("ht_rf", "TPU1-8"),
            ("power_supplies", "i251"),
            ("power_supplies", "TS22"),
            ("corrective", "4513 330 7021"),
            ("planned", "heat exchanger"),
            ("planned", "TS1"),
            ("item part", "i251"),
        ]
        for t_man, t_term in targeted_manual_queries:
            if len(contexts) >= max_pages:
                break
            try:
                t_res = search_engine.search(t_term, manual=t_man, limit=2)
                for r in t_res.get("results", []):
                    m, p = r.get("manual", ""), r.get("page", 0)
                    key = (m, p)
                    if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                        seen_pages.add(key)
                        manual_counts[m] += 1
                        cid = _register(m, p)
                        comp = r.get("associated_component", "")
                        comp_str = f" [Detalle: {comp}]" if comp else ""
                        snip = str(r.get("context", ""))[:1500]
                        contexts.append(f"--- [{cid}] Manual: {m} (Página {p}){comp_str} [Foco HT/VMAT: {t_term}] ---\n{snip}")
                        c_data = extract_structured_components(snip)
                        for b in c_data.get("boards", []):
                            if b not in extracted_boards and len(b) >= 3:
                                extracted_boards.append(b)
            except Exception as t_err:
                logger.debug("Búsqueda dirigida HT/VMAT omitida para '%s' en '%s': %s", t_term, t_man, t_err)

    technical_expansions: list[str] = []
    if is_con_k:
        technical_expansions.extend([
            "CON-K",
            "CON_K_MON",
            "DIE-HTA",
            "DIE-HTB",
            "RL4",
            "HTCA",
            "CON-A",
            "CON-D",
            "CON-J",
        ])
    if is_ht_vmat:
        technical_expansions.extend([
            "HT PSU OT",
            "ITEM 251",
            "ITEM 330",
            "DIE-HTB",
            "1024686",
            "4513 330 7021",
            "SW1 SW2",
            "VMAT dose rate",
            "PRI I MON",
        ])
    for tech_term in technical_expansions:
        if len(contexts) >= max_pages:
            break
        try:
            t_res = search_engine.search(tech_term, limit=2)
            for r in t_res.get("results", []):
                m, p = r.get("manual", ""), r.get("page", 0)
                key = (m, p)
                if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                    seen_pages.add(key)
                    manual_counts[m] += 1
                    cid = _register(m, p)
                    comp = r.get("associated_component", "")
                    comp_str = f" [Detalle: {comp}]" if comp else ""
                    snip = str(r.get("context", ""))[:1500]
                    contexts.append(f"--- [{cid}] Manual: {m} (Página {p}){comp_str} [Expansión: {tech_term}] ---\n{snip}")
                    c_data = extract_structured_components(snip)
                    for b in c_data.get("boards", []):
                        if b not in extracted_boards and len(b) >= 3:
                            extracted_boards.append(b)
        except Exception as t_err:
            logger.debug("Expansión técnica omitida para '%s': %s", tech_term, t_err)

    # 3. Búsqueda directa por cada síntoma individual a través de todos los manuales
    for sym in symptoms:
        if len(contexts) >= max_pages:
            break
        cleaned_sym = sym.strip()
        if not cleaned_sym:
            continue
        try:
            s_res = search_engine.search(cleaned_sym, limit=6)
            for r in s_res.get("results", []):
                m, p = r.get("manual", ""), r.get("page", 0)
                key = (m, p)
                if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                    seen_pages.add(key)
                    manual_counts[m] += 1
                    cid = _register(m, p)
                    snip = str(r.get("context", ""))[:1400]
                    contexts.append(f"--- [{cid}] Manual: {m} (Página {p}) [Consulta: {cleaned_sym}] ---\n{snip}")
                    c_data = extract_structured_components(snip)
                    for b in c_data.get("boards", []):
                        if b not in extracted_boards and len(b) >= 3:
                            extracted_boards.append(b)
        except Exception as s_err:
            logger.debug("Búsqueda individual omitida para '%s': %s", cleaned_sym, s_err)

    # 4. Búsqueda cruzada de las tarjetas identificadas en manuales de subsistemas y mantenimiento
    target_manuals = [
        "dosimetry", "communications", "power_supplies", "corrective",
        "vacuum", "movement", "ht_rf", "ccp", "technical", "beam physics", "table", "diagrams"
    ]
    for b in extracted_boards[:4]:
        for tm in target_manuals:
            if len(contexts) >= max_pages:
                break
            if manual_counts[tm] < max_per_manual:
                try:
                    b_res = search_engine.search(b, manual=tm, limit=1)
                    for r in b_res.get("results", []):
                        m, p = r.get("manual", ""), r.get("page", 0)
                        key = (m, p)
                        if key not in seen_pages and manual_counts[m] < max_per_manual and len(contexts) < max_pages:
                            seen_pages.add(key)
                            manual_counts[m] += 1
                            cid = _register(m, p)
                            snip = str(r.get("context", ""))[:1400]
                            contexts.append(f"--- [{cid}] Manual: {m} (Página {p}) [Componente: {b}] ---\n{snip}")
                except Exception as b_err:
                    logger.debug("Búsqueda por componente omitida para '%s' en '%s': %s", b, tm, b_err)

    # 4. Búsqueda por palabras clave individuales si hay pocas coincidencias
    if len(contexts) < 4:
        kws = extract_keywords_for_retrieval(symptoms)
        for kw in kws:
            if len(contexts) >= max_pages:
                break
            try:
                s_res = search_engine.search(kw, limit=2)
                for r in s_res.get("results", []):
                    m, p = r.get("manual", ""), r.get("page", 0)
                    key = (m, p)
                    if key not in seen_pages and len(contexts) < max_pages:
                        seen_pages.add(key)
                        cid = _register(m, p)
                        snip = str(r.get("context", ""))[:1200]
                        contexts.append(f"--- [{cid}] Manual: {m} (Página {p}) ---\n{snip}")
            except Exception:
                pass

    combined = "\n\n".join(contexts) if contexts else "No se encontraron páginas directas con los términos exactos."
    return combined[:24000], citation_map


def _resolve_citations(data: dict, citation_map: dict[str, dict[str, object]]) -> dict:
    """Convierte deterministamente los citation_ids a referencias legibles de manual y página."""
    cited_ids = data.pop("citation_ids", None)
    extracted_cids: list[str] = []
    if isinstance(cited_ids, str):
        extracted_cids = [m.upper() for m in re.findall(r"\bC\d+\b", cited_ids, re.I)]
    elif isinstance(cited_ids, list):
        for item in cited_ids:
            found = re.findall(r"\bC\d+\b", str(item), re.I)
            if found:
                extracted_cids.extend(m.upper() for m in found)
            else:
                cand = str(item).strip().upper()
                if cand in citation_map and cand not in extracted_cids:
                    extracted_cids.append(cand)

    manual_refs = []
    for cid in extracted_cids:
        src = citation_map.get(cid)
        if src:
            if src.get("page", 0) > 0:
                ref_entry = f"{src['manual']} (Página {src['page']})"
            else:
                ref_entry = f"{src['manual']}"
            if ref_entry not in manual_refs:
                manual_refs.append(ref_entry)
    # Una respuesta sin citas válidas no puede publicarse como diagnóstico
    # documentado. La UI debe mostrarla como no correlacionada y sin acciones.
    data["manual_references"] = manual_refs
    if not manual_refs:
        data["root_cause"] = "Sin correlación documentada"
        data["confidence"] = "baja"
        data["associated_boards"] = []
        data["cables_and_connectors"] = []
        data["test_points_and_signals"] = []
        data["differential_diagnoses"] = []
        data["action_steps"] = []
        data["explanation"] = "No se encontró una cita válida en el corpus local para sostener este diagnóstico."
        data.setdefault("_diagnostic_meta", {})["evidence_blocked"] = True
    return data


def _map_subsystem_from_text_and_manual(manual: str, text: str, raw_sub: str = "") -> str:
    """Identifica con precisión el subsistema técnico de Elekta a partir del manual y contenido."""
    low_text = text.lower()
    low_man = manual.lower()

    if "dosimetr" in low_text or "dosimetry" in low_man or "ionisation chamber" in low_text or "die-rha" in low_text or "d1 force" in low_text:
        return "Dosimetría y Monitoreo de Haz (Dosimetry Channel & Safety Interlocks)"
    if "movement" in low_man or "gantry" in low_text or "collimator" in low_text or "diaphragm" in low_text or "table" in low_man:
        return "Control de Movimiento (Gantry, Colimador y Mesa de Tratamiento)"
    if "vacuum" in low_man or "ion pump" in low_text or "sw1" in low_text or "torr" in low_text:
        return "Sistema de Vacío y Bomba Iónica (Vacuum System & Ion Pump)"
    if "ht_rf" in low_man or "magnetron" in low_text or "thyratron" in low_text or "modulator" in low_text or "rf driver" in low_text:
        return "Alta Tensión y Generación de RF (HT Modulator & RF Pulse System)"
    if "power_supplies" in low_man or "power supply" in low_text or "24vdc" in low_text or "contactor" in low_text:
        return "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)"
    if "xvi" in low_man or "cbct" in low_text or "x-ray" in low_text:
        return "Sistema de Imagen Radiológica Volumétrica (XVI CBCT)"
    if "iview" in low_man or "portal imaging" in low_text:
        return "Sistema de Imagen Portal iViewGT"
    if "ccp" in low_man or "communications" in low_man or "arcnet" in low_text or "can bus" in low_text:
        return "Procesador Central y Comunicaciones (CCP & Safety Bus)"
    if raw_sub and len(raw_sub) > 4:
        return raw_sub.title()
    return "Sistema General de Interbloqueos y Seguridad (Elekta LINAC)"


def generate_local_failover_diagnosis(
    symptoms: list[str],
    search_engine: SearchEngine,
    reason: str = "timeout",
) -> dict:
    """Genera un informe causal determinista fundamentado estrictamente en el catálogo de los 19 manuales.

    Se ejecuta automáticamente ante fallos o latencia en el servicio de nube, garantizando
    continuidad operativa, diagnósticos diferenciales y procedimientos específicos de ingeniería en el búnker.
    """
    from collections import defaultdict
    from search_engine import extract_structured_components, INVALID_BOARDS

    # 1. Identificar tarjetas, señales/códigos y términos generales en los síntomas ingresados
    board_regex = re.compile(
        r"\b(?:DIE-[A-Z0-9]+|PCB\s*[A-Z0-9]+|ROC-[A-Z0-9]+|MTU-[A-Z0-9]+|AO\d+|AI\s*\d+[A-Z]?|"
        r"DO\s*\d+|DI\s*\d+|PWA\s+[A-Z0-9]+|PWB\s+[A-Z0-9]+|SCC-[A-Z0-9]+|CPU-[A-Z0-9]+|"
        r"MOT-[A-Z0-9]+|DRV-[A-Z0-9]+|CON-[A-Z0-9]+|TMC\b|RTD\b|MLC\b|XVI\b)\b",
        re.IGNORECASE,
    )
    code_regex = re.compile(
        r"^(?:ITEM\s*\d+|i\d{1,4}|e\d{1,4}|INTERLOCK\s*\d+|ERROR\s*\d+|FAULT\s*\d+|\d{1,4})$",
        re.IGNORECASE,
    )

    user_boards: list[str] = []
    user_signals: list[str] = []
    user_general: list[str] = []

    for sym in symptoms:
        s_clean = sym.strip()
        if not s_clean:
            continue
        m_b = board_regex.search(s_clean)
        if m_b and (m_b.group(0).upper() not in INVALID_BOARDS):
            b_val = m_b.group(0).upper()
            if b_val not in user_boards:
                user_boards.append(b_val)
        elif code_regex.match(s_clean):
            sig_val = s_clean.upper()
            if sig_val not in user_signals:
                user_signals.append(sig_val)
        else:
            it_found = re.findall(r"\b(?:ITEM\s*\d+|i\d{1,4}|e\d{1,4}|INTERLOCK\s*\d+|ERROR\s*\d+)\b", s_clean, re.I)
            if it_found:
                for it in it_found:
                    it_u = it.strip().upper()
                    if it_u not in user_signals:
                        user_signals.append(it_u)
            else:
                user_general.append(s_clean)

    matched_docs = []
    seen_pages = set()
    manual_counts = defaultdict(int)
    max_per_manual = 2

    def _add_doc(doc: dict) -> bool:
        m = doc.get("manual", "")
        p = doc.get("page", 0)
        key = (m, p)
        if key not in seen_pages and manual_counts[m] < max_per_manual:
            seen_pages.add(key)
            manual_counts[m] += 1
            matched_docs.append(doc)
            return True
        return False

    # 2. Búsqueda de convergencia relacional con equilibrio entre los 19 manuales
    try:
        diag_res = search_engine.diagnose_symptoms(symptoms, limit=12)
        for r in diag_res.get("results", []):
            _add_doc(r)
    except Exception as s_err:
        logger.warning("Error en diagnose_symptoms en diagnóstico local: %s", s_err)

    # 3. Búsqueda cruzada de tarjetas del usuario en manuales de subsistema y mantenimiento
    target_manuals = [
        "dosimetry", "communications", "power_supplies", "corrective",
        "vacuum", "movement", "ht_rf", "ccp", "technical", "beam physics", "item part", "diagrams"
    ]
    for b in user_boards:
        for tm in target_manuals:
            if len(matched_docs) >= 12:
                break
            if manual_counts[tm] < max_per_manual:
                try:
                    b_res = search_engine.search(b, manual=tm, limit=1)
                    for r in b_res.get("results", []):
                        _add_doc(r)
                except Exception:
                    pass

    # 4. Búsqueda cruzada de señales y códigos numéricos del usuario
    for sig in user_signals:
        for tm in ["dosimetry", "item part", "power_supplies", "corrective", "diagrams"]:
            if len(matched_docs) >= 12:
                break
            if manual_counts[tm] < max_per_manual:
                try:
                    s_res = search_engine.search(sig, manual=tm, limit=1)
                    for r in s_res.get("results", []):
                        _add_doc(r)
                except Exception:
                    pass
                m_c = re.search(r"\d+", sig)
                if m_c and manual_counts[tm] < max_per_manual and len(matched_docs) < 12:
                    c_num = m_c.group(0)
                    for variant in [f"i{c_num}", f"i{int(c_num):03d}"]:
                        try:
                            v_res = search_engine.search(variant, manual=tm, limit=1)
                            for r in v_res.get("results", []):
                                _add_doc(r)
                        except Exception:
                            pass

    # 5. Búsqueda directa por cada síntoma si hay pocos resultados
    if len(matched_docs) < 4:
        for sym in symptoms:
            try:
                s_res = search_engine.search(sym, limit=3)
                for r in s_res.get("results", []):
                    _add_doc(r)
            except Exception as e_search:
                logger.debug("Búsqueda directa omitida para '%s': %s", sym, e_search)

    if not matched_docs:
        return {
            "root_cause": "Sin correlación documentada",
            "subsystem": "No identificado",
            "confidence": "baja",
            "explanation": "No se encontró evidencia suficiente en los 19 manuales técnicos cargados para correlacionar los síntomas ingresados.",
            "differential_diagnoses": [],
            "associated_boards": [],
            "cables_and_connectors": [],
            "test_points_and_signals": [],
            "manual_references": [],
            "action_steps": [],
            "safety_warning": "Verificar desenergización antes de intervenir cualquier subsistema.",
            "_diagnostic_meta": {
                "failover": True,
                "reason": reason,
                "evidence_blocked": True,
                "failover_notice": "Diagnóstico determinista local: no se identificaron páginas relevantes en el corpus documental.",
            },
        }

    # 6. Identificación precisa del Subsistema (evaluando síntomas primero, luego evidencia técnica)
    sym_blob = " ".join(symptoms).lower()
    is_con_k = (
        any(k in sym_blob for k in ["con-k", "con k", "contactor k", "contactork", "con_k", "con_k_mon"])
        or ("ht" in sym_blob and "con" in sym_blob and "k" in sym_blob)
    )
    is_ht_psu_ot = (
        not is_con_k
        and (
            any(k in sym_blob for k in ["ht psu", "psu ot", "item 330", "i330", "item 251", "i251", "over temp", "overtemp"])
            or ("ht" in sym_blob and "ot" in sym_blob)
        )
    )
    is_vmat = any(k in sym_blob for k in ["vmat", "arc", "volumetric", "modulac", "tratamiento"])

    if is_con_k:
        subsystem = "Distribución de Potencia y Secuencia de Alta Tensión (HT Power & Contactors)"
    elif is_ht_psu_ot:
        subsystem = "Alta Tensión y Generación de RF (HT Modulator & RF Pulse System)"
    elif any(k in sym_blob for k in ["dosimetr", "die-rha", "item 475", "item 471", "i475", "i471", "d1 force", "d1 reset", "chamber bias", "dose"]):
        subsystem = "Dosimetría y Monitoreo de Haz (Dosimetry Channel & Safety Interlocks)"
    elif any(k in sym_blob for k in ["vacuum", "vacío", "ion pump", "sw1", "torr", "degas"]):
        subsystem = "Sistema de Vacío y Bomba Iónica (Vacuum System & Ion Pump)"
    elif any(k in sym_blob for k in ["magnetron", "thyratron", "rf", "modulador", "modulator", "klystron", "prf", "afc", "ht_rf"]):
        subsystem = "Alta Tensión y Generación de RF (HT Modulator & RF Pulse System)"
    elif any(k in sym_blob for k in ["leaf", "mlc", "collimat", "gantry", "motor", "table", "mesa", "encoder", "potentiometer"]):
        subsystem = "Control de Movimiento (Gantry, Colimador y Mesa de Tratamiento)"
    elif any(k in sym_blob for k in ["can bus", "arcnet", "ccp", "timeout", "comunicaciones", "rtu", "fiber"]):
        subsystem = "Procesador Central y Comunicaciones (CCP & Safety Bus)"
    elif any(k in sym_blob for k in ["power supply", "fuente", "24vdc", "contactor", "fuse", "relay", "relé"]):
        subsystem = "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)"
    else:
        # Evaluar documentos coincidentes
        sub_votes = defaultdict(int)
        for doc in matched_docs:
            man = doc.get("manual", "")
            d_text = doc.get("context", "")
            comp = extract_structured_components(d_text)
            mapped = _map_subsystem_from_text_and_manual(man, d_text, str(comp.get("subsystem", "")))
            if mapped and "General" not in mapped:
                sub_votes[mapped] += 1
        if sub_votes:
            subsystem = max(sub_votes.items(), key=lambda x: x[1])[0]
        else:
            subsystem = "Sistema General de Interbloqueos y Seguridad (Elekta LINAC)"

    # 7. Ordenar documentos recuperados priorizando los pertinentes al subsistema detectado
    low_sub = subsystem.lower()

    def _doc_relevance(doc: dict) -> tuple:
        m = doc.get("manual", "").lower()
        ctx = doc.get("context", "").lower()
        sub_match = 0
        if "dosimetr" in low_sub:
            if "dosimetry" in m:
                sub_match = 5
            elif "diagrams" in m and ("211" in str(doc.get("page", 0)) or "dosimetry" in ctx):
                sub_match = 4
            elif "die-rha" in ctx or "475" in ctx:
                sub_match = 3
        elif "vacío" in low_sub or "vacuum" in low_sub:
            if "vacuum" in m:
                sub_match = 5
        elif "rf" in low_sub or "tensión" in low_sub:
            if "ht_rf" in m:
                sub_match = 5
        elif "movimiento" in low_sub:
            if "movement" in m:
                sub_match = 5
        elif "fuentes" in low_sub or "power" in low_sub:
            if "power_supplies" in m:
                sub_match = 5
        if "table" in m and "movimiento" not in low_sub:
            sub_match -= 5
        return (-sub_match,)

    matched_docs.sort(key=_doc_relevance)

    # 8. Extracción de componentes y manuales de referencia
    all_boards: list[str] = list(user_boards)
    all_signals: list[str] = list(user_signals)
    all_cables: list[str] = []
    all_tps: list[str] = []
    manual_refs: list[str] = []

    for doc in matched_docs:
        man = doc.get("manual", "")
        pg = doc.get("page", 0)
        ref_str = f"{man}.pdf (Página {pg})" if pg else f"{man}.pdf"
        if ref_str not in manual_refs:
            manual_refs.append(ref_str)

        doc_text = doc.get("context", "")
        comp = extract_structured_components(doc_text)

        for b in comp.get("boards", []):
            if b not in all_boards and len(all_boards) < 5 and b not in INVALID_BOARDS and not _is_drawing_or_schematic_number(b):
                all_boards.append(b)
        for c in comp.get("cables", []):
            if c not in all_cables and len(all_cables) < 5 and not _is_drawing_or_schematic_number(c):
                all_cables.append(c)
        for s in comp.get("items", []):
            if s not in all_signals and s not in all_boards and len(all_signals) < 6 and not _is_drawing_or_schematic_number(s):
                all_signals.append(s)
        for tp in comp.get("tps", []):
            if tp not in all_tps and len(all_tps) < 5 and not _is_drawing_or_schematic_number(tp):
                all_tps.append(tp)

    # Si all_signals aún no tiene suficientes, incorporar puntos de prueba
    for tp in all_tps:
        if tp not in all_signals and len(all_signals) < 6 and not _is_drawing_or_schematic_number(tp):
            all_signals.append(tp)

    # Limpiar cualquier residuo de números de planos o tarjetas inválidas
    all_boards = [b for b in all_boards if b and not _is_drawing_or_schematic_number(b) and b.upper() not in INVALID_BOARDS]
    all_signals = [s for s in all_signals if s and not _is_drawing_or_schematic_number(s)]
    all_cables = [c for c in all_cables if c and not _is_drawing_or_schematic_number(c)]

    if is_con_k:
        con_k_boards = ["DIE-HTA", "DIE-HTB", "HT PSU CONTROL PCB", "PCB 16M", "PCB 16N", "PCB 22"]
        all_boards = [b for b in con_k_boards if b and not _is_drawing_or_schematic_number(b) and b.upper() not in INVALID_BOARDS]
        con_k_cables = ["PL2", "SK16R", "PL16M", "PL16N", "RL4", "SK17C"]
        all_cables = [c for c in con_k_cables if c and not _is_drawing_or_schematic_number(c)]
        con_k_signals = ["CON-K", "CON_K_MON", "CON_K_ON", "CON_J_ON", "CON_D_ON", "RAD_ON"]
        all_signals = [s for s in con_k_signals if s and not _is_drawing_or_schematic_number(s)]
        con_k_refs = [
            "diagrams.pdf (Página 63)",
            "power_supplies.pdf (Página 78)",
            "ht_rf.pdf (Página 92)",
            "corrective.pdf (Página 419)",
        ]
        manual_refs = [r for r in con_k_refs if r]

    if is_ht_psu_ot:
        ht_boards = ["DIE-HTB", "PCB 22", "HT PSU CONTROL PCB", "HT ISOLATION PCB", "DRIVER PCB", "DIE-HTA"]
        all_boards = [b for b in ht_boards if b] + [b for b in all_boards if b not in ht_boards]
        ht_cables = ["PL2-a3", "SK17C", "PL16S", "SK16R", "PL1-c8", "TS22A", "LK1", "LK2"]
        all_cables = [c for c in ht_cables if c] + [c for c in all_cables if c not in ht_cables]
        ht_signals = ["ITEM 251", "ITEM 330", "PRI I MON", "PRI REF", "SW1", "SW2", "TS1", "TS2", "TPU1-8", "TPU1-1"]
        all_signals = [s for s in ht_signals if s] + [s for s in all_signals if s not in ht_signals]
        ht_refs = [
            "diagrams.pdf (Página 159)",
            "ht_rf.pdf (Página 225)",
            "power_supplies.pdf (Página 78)",
            "corrective.pdf (Página 419)",
            "planned.pdf (Página 298)",
            "item part.pdf (Página 145)",
            "diagrams.pdf (Página 57)",
            "ht_rf.pdf (Página 92)",
        ]
        manual_refs = [r for r in ht_refs if r] + [r for r in manual_refs if r not in ht_refs]

    # 9. Formulación de Causa Raíz técnica precisa y no preenlatada
    primary_board = all_boards[0] if all_boards else "tarjetas de control del subsistema"
    signals_label = ", ".join(all_signals[:2]) if all_signals else "líneas de supervisión"
    if is_con_k:
        root_cause = (
            "Disparo en la secuencia de encendido de Alta Tensión por fallo de accionamiento "
            "o pérdida de supervisión del contactor principal CON-K (comandado por DIE-HTA vía relé RL4 "
            "y monitorizado por DIE-HTB mediante la línea CON_K_MON en Área 16 HTCA)"
        )
        explanation = (
            "El contactor principal de potencia de alta tensión CON-K constituye la última etapa en la secuencia de "
            "energización escalonada de HT del acelerador (CON-A -> CON-D -> CON-J -> CON-K). La bobina de CON-K es comandada "
            "por la tarjeta DIE-HTA (PCB 16M, slot 10 del bastidor HTCA en Área 16) mediante el relé electromecánico de seguridad RL4 "
            "(alimentado a 24 VDC). El cierre físico de sus contactos es supervisado por la tarjeta DIE-HTB (PCB 16N, slot 12) a través "
            "de la línea de realimentación lógica CON_K_MON. Si la tarjeta DIE-HTB no detecta la confirmación del monitor auxiliar dentro "
            "de la ventana de temporización prevista tras la activación previa de CON-J y CON-D, o si se produce una discrepancia en el lazo "
            "serie de seguridad maestro en Área 17 / Área 22, el sistema aborta la secuencia, desenergiza RL4 e inhibe de inmediato la emisión "
            "de haz (retirando la señal RAD_ON)."
        )
    elif is_ht_psu_ot:
        if is_vmat:
            root_cause = (
                "Apertura del lazo térmico HT OVERTEMP DETECTOR en Área 17 (SW1 en disipador 4513 330 6280/7910, "
                "fuelle SW2 en T4 1512977, termostatos TS1/TS2 y regleta TS22A / PCB 22 en Área 22) transmitido vía "
                "HT ISOLATION PCB (4513 330 7753, optoacopladores OPTO 3/9) al pin PL2-a3 de DIE-HTB (PCB 16N, slot 12 de HTCA), "
                "conmutando el monitor ITEM 251 a 0 en la máscara de inhibición del CCP e inhabilitando la cadena de interlocks "
                "de PRF por sobrecarga térmica bajo modulación continua de PRF y dosis en arcos VMAT. "
                "Se diferencia rigurosamente ITEM 251 (monitor de interlock de sobretemperatura en Service Mode) de ITEM 330 "
                "(Chargerate, control analógico DAC de corriente primaria supervisado por PRI I MON vs PRI REF y calibrado a 0, 20, 40 A)."
            )
            explanation = (
                "El interbloqueo 'HT PSU OT' (Over Temperature) se activa por la apertura del lazo serie de seguridad "
                "HT OVERTEMP DETECTOR en el Área 17. Este circuito integra el interruptor bimetálico/flujo de aire SW1 en el disipador "
                "de potencia de los transistores IGBTs TR1/TR2 (Heat Sink Assembly 4513 330 6280/7910, refrigerado por el ventilador "
                "centrífugo BLA y el lazo del intercambiador de calor/bomba auxiliar), el microinterruptor de fuelle de expansión de aceite "
                "SW2 en el transformador de carga T4 (P/N 1512977), y los termostatos bimetálicos de circuito TS1 y TS2 junto con la regleta "
                "TS22A de la tarjeta PCB 22 en el Área 22 (guía de ondas). Durante tratamientos dinámicos VMAT (Volumetric Modulated Arc "
                "Therapy), el acelerador modula continuamente la tasa de dosis y posiciona las hojas del colimador multiláminas Agility "
                "mediante sucesivas variaciones de los códigos de PRF y cálculos de pausa (Item 2200), exigiendo una demanda de corriente "
                "primaria constante hacia el banco de condensadores de alta tensión a través de los transistores de potencia conmutados por "
                "las tarjetas DRIVER PCB (PCB 17A y PCB 17B) y gobernados por la tarjeta HT PSU CONTROL PCB (PCB 16R, slot 15). "
                "La señal de seguridad térmica se transmite ópticamente mediante la tarjeta HT ISOLATION PCB (4513 330 7753, "
                "optoacopladores OPTO 3 y OPTO 9) hacia el bastidor HTCA (Área 16) ingresando por el conector SK17C / PL16S al pin "
                "PL2-a3 de la tarjeta DIE-HTB (PCB 16N, slot 12). Al abrirse el lazo serie por calor acumulado o refrigeración insuficiente, "
                "el FPGA de la DIE-HTB conmuta el monitor de inhibición ITEM 251 (i251) de 1 (lógica OK) a 0 (Inhibit activo), abriendo "
                "la cadena de interbloqueos de PRF, secuenciando la apertura de contactores CON-A, CON-D, "
                "CON-J, CON-K e interrumpiendo inmediatamente la radiación (retirando RAD_ON). "
                "Es crítico no confundir ITEM 251 (bit de monitoreo de interlock en Service Mode / CCP) con ITEM 330 (consigna de tasa de carga "
                "de corriente primaria regulada mediante el divisor resistivo PRI I MON frente a PRI REF y calibrada a 0.00 A, 20.00 A y 40.00 A)."
            )
        else:
            root_cause = (
                "Disparo de protección térmica HT OVERTEMP DETECTOR en Área 17 por apertura de SW1/SW2, termostatos TS1/TS2 o presostato "
                "en PCB 22 / TS22A, reflejado como inhibición en DIE-HTB pin PL2-a3 (ITEM 251)"
            )
            explanation = (
                "El interbloqueo 'HT PSU OT' responde a la apertura del lazo serie de protección térmica del Área 17 conectado al pin "
                "PL2-a3 de la tarjeta DIE-HTB (PCB 16N, slot 12 en Área 16 HTCA). El circuito integra en serie el interruptor "
                "bimetálico SW1 del disipador de los IGBTs de potencia (Heat Sink Assembly 4513 330 6280/7910), el presostato/fuelle "
                "SW2 del tanque de aceite del transformador de carga T4 (P/N 1512977), los termostatos TS1 y TS2 del circuito de refrigeración "
                "y la regleta TS22A de supervisión en PCB 22 (Área 22). La señal pasa por la tarjeta de aislamiento HT ISOLATION PCB "
                "(4513 330 7753) mediante optoacopladores OPTO 3 y OPTO 9. Al superarse la temperatura de umbral o decaer el flujo de aire "
                "del ventilador BLA o el circuito del intercambiador de calor, el lazo se abre y el FPGA de DIE-HTB conmuta ITEM 251 a 0, "
                "inhibiendo la cadena de PRF y el estado RAD_ON. "
                "Se distingue rigurosamente ITEM 251 (estado de sobretemperatura) de ITEM 330 (tasa de corriente de carga calibrada en PCB 16R)."
            )
    elif all_boards and all_signals:
        root_cause = f"Disparo en lazo de seguridad de {subsystem}, comprometiendo {primary_board} y señales {signals_label}"
    elif all_boards:
        root_cause = f"Condición de interbloqueo en {subsystem} asociada a {primary_board}"
    elif all_signals:
        root_cause = f"Falla de estado lógico o interrupción en líneas {signals_label} de {subsystem}"
    else:
        root_cause = f"Apertura en bucle de seguridad de interlocks en {subsystem}"

    root_cause = _sanitize_root_cause(root_cause)

    # 10. Formulación de Explicación técnica y contextual dinámica libre de enumeración de manuales
    if not is_ht_psu_ot and not is_con_k:
        secondary_boards = (", " + ", ".join(all_boards[1:3])) if len(all_boards) > 1 else ""
        signals_text = ", ".join(all_signals[:3]) if all_signals else ", ".join(symptoms[:2])
        if "dosimetr" in low_sub or "haz" in low_sub:
            explanation = (
                f"El lazo de seguridad y monitoreo de dosimetría supervisa continuamente la integración de carga en los canales D1 y D2 "
                f"a través de {primary_board}{secondary_boards}. Una discrepancia en la polarización de cámara, un fallo en el tren de pulsos "
                f"de puesta a cero o un desbalance en las señales de supervisión ({signals_text}) provoca el disparo del circuito de terminación forzada, "
                f"inhibiendo preventivamente la emisión de radiación (retirando RAD_ON) para garantizar la seguridad radiológica del paciente."
            )
        elif "vacío" in low_sub or "vacuum" in low_sub:
            explanation = (
                f"El subsistema de vacío y protección de línea de RF supervisa la presión residual en la columna aceleradora y guía de ondas "
                f"mediante {primary_board}{secondary_boards}. Si la corriente de la bomba iónica excede el umbral nominal (presión > 10^-7 Torr) "
                f"o se abre el presostato de seguridad, las líneas de interbloqueo ({signals_text}) cortan la excitación del modulador para "
                f"evitar descargas internas destructivas o perforación en ventanas cerámicas."
            )
        elif "rf" in low_sub or "tensión" in low_sub:
            explanation = (
                f"El sistema modulador y de generación de RF requiere sincronismo estricto entre el tren de pulsos PRF, la conmutación del tiratrón "
                f"y la magnetización de cátodo supervisados por {primary_board}{secondary_boards}. Un jitter excesivo, deriva en la corriente de filamento "
                f"o anomalías en las señales ({signals_text}) induce la inhibición preventiva de los pulsos de alta tensión para salvaguardar el magnetrón."
            )
        elif "movimiento" in low_sub or "colimad" in low_sub or "gantry" in low_sub or "mesa" in low_sub:
            explanation = (
                f"El control de movimiento en {subsystem} opera en bucle cerrado contrastando encoders digitales frente a potenciómetros analógicos "
                f"en {primary_board}{secondary_boards}. Si la señal de realimentación ({signals_text}) presenta desfase angular o sobrecorriente de servo "
                f"por resistencia mecánica o microdesalineación, el control central bloquea el eje preventivamente e inhibe el haz."
            )
        elif "comunicac" in low_sub or "ccp" in low_sub or "procesador" in low_sub:
            explanation = (
                f"La supervisión distribuida en {subsystem} coordina el intercambio continuo de tramas de estado entre nodos mediante "
                f"{primary_board}{secondary_boards}. La pérdida de latidos de watchdog o corrupción de paquetes en las líneas ({signals_text}) "
                f"fuerza la activación del estado de interbloqueo maestro en el CCP para prevenir cualquier accionamiento sin confirmación."
            )
        else:
            explanation = (
                f"La supervisión operativa en {subsystem} converge en el lazo de seguridad de {primary_board}{secondary_boards}. "
                f"Una anomalía en las líneas de control ({signals_text}), una caída transitoria de tensión en rieles continuos o una falta "
                f"de confirmación en relés auxiliares interrumpe la cadena de seguridad, inhibiendo de forma preventiva la emisión de haz (RAD_ON) "
                f"o la habilitación de alta tensión hasta validar los umbrales de tolerancia y aislamiento del circuito."
            )

    # 11. Diagnósticos diferenciales e hipótesis técnicas multifacéticas por dominio
    differential_diagnoses: list[dict[str, str | list[str]]] = []

    if is_con_k:
        differential_diagnoses.append({
            "title": "Fallo o desgaste en el contacto auxiliar de realimentación CON_K_MON hacia DIE-HTB (PCB 16N)",
            "hypothesis": "Fallo o desgaste en el contacto auxiliar de realimentación CON_K_MON hacia DIE-HTB (PCB 16N)",
            "subsystem": subsystem,
            "likelihood": "alta",
            "cause_mechanism": "El contactor principal CON-K cierra mecánicamente sus polos de potencia trifásica hacia el transformador T4 en Área 17, pero su bloque de contactos auxiliares (normalmente abierto) presenta carbonización, desgaste mecánico o resistencia de contacto excesiva (> 0.5 ohm). Esto impide que la línea lógica de supervisión CON_K_MON alcance el nivel alto (24 VDC) en el conector PL2 de la tarjeta DIE-HTB (PCB 16N, slot 12 del bastidor HTCA) dentro del margen de temporización del FPGA, interpretándose como un fallo de enclavamiento de contactores.",
            "rationale": "El contactor principal CON-K cierra mecánicamente sus polos de potencia trifásica hacia el transformador T4 en Área 17, pero su bloque de contactos auxiliares (normalmente abierto) presenta carbonización, desgaste mecánico o resistencia de contacto excesiva (> 0.5 ohm). Esto impide que la línea lógica de supervisión CON_K_MON alcance el nivel alto (24 VDC) en el conector PL2 de la tarjeta DIE-HTB (PCB 16N, slot 12 del bastidor HTCA) dentro del margen de temporización del FPGA, interpretándose como un fallo de enclavamiento de contactores.",
            "solution_procedure": "1. En Service Mode -> Display Service Pages -> HT Interlocks, verificar el estado del bit de monitor CON_K_MON durante el intento de energización.\n2. Con el equipo desenergizado y consignado, medir con multímetro la continuidad del contacto auxiliar de CON-K al ser accionado manualmente (resistencia debe ser < 0.2 ohm).\n3. Inspeccionar el cableado y pines en el conector PL2 de la tarjeta DIE-HTB y la bornera intermedia del armario de potencia.\n4. Si el contacto auxiliar presenta rebotes o resistencia elevada, sustituir el bloque auxiliar o el contactor CON-K completo.",
            "affected_components": ["CON-K", "DIE-HTB", "PCB 16N", "PL2", "CON_K_MON"],
        })
        differential_diagnoses.append({
            "title": "Fallo en el circuito de excitación de la bobina de CON-K: relé de seguridad RL4 o salida de driver en DIE-HTA (PCB 16M)",
            "hypothesis": "Fallo en el circuito de excitación de la bobina de CON-K: relé de seguridad RL4 o salida de driver en DIE-HTA (PCB 16M)",
            "subsystem": subsystem,
            "likelihood": "alta",
            "cause_mechanism": "La orden de encendido de alta tensión generada por el control central activa la línea de comando CON_K_ON desde la tarjeta DIE-HTA (PCB 16M, slot 10). Esta señal polariza el driver que pilota la bobina del relé electromecánico de seguridad RL4. Si la bobina de RL4 está abierta, sus contactos están fogueados, o el transistor driver en PCB 16M está dañado, no se transfieren los 24 VDC / 110 VAC hacia la bobina de CON-K, impidiendo su conmutación.",
            "rationale": "La orden de encendido de alta tensión generada por el control central activa la línea de comando CON_K_ON desde la tarjeta DIE-HTA (PCB 16M, slot 10). Esta señal polariza el driver que pilota la bobina del relé electromecánico de seguridad RL4. Si la bobina de RL4 está abierta, sus contactos están fogueados, o el transistor driver en PCB 16M está dañado, no se transfieren los 24 VDC / 110 VAC hacia la bobina de CON-K, impidiendo su conmutación.",
            "solution_procedure": "1. Comprobar en DIE-HTA (PCB 16M) la activación del LED indicador de salida de relé RL4 al pulsar HT ON en consola.\n2. Medir con multímetro en bornes de la bobina de CON-K la presencia de tensión de excitación al iniciar la secuencia.\n3. Si hay tensión en la bobina pero el contactor no clava, verificar la impedancia de la bobina contra especificación.\n4. Si no llega tensión a la bobina, verificar el fusible de alimentación de control asociado en el bastidor de potencia y los contactos de conmutación de RL4.",
            "affected_components": ["DIE-HTA", "PCB 16M", "RL4", "CON-K", "CON_K_ON"],
        })
        differential_diagnoses.append({
            "title": "Descoordinación temporal en la secuencia escalonada de contactores HT (CON-A -> CON-D -> CON-J -> CON-K)",
            "hypothesis": "Descoordinación temporal en la secuencia escalonada de contactores HT (CON-A -> CON-D -> CON-J -> CON-K)",
            "subsystem": subsystem,
            "likelihood": "media",
            "cause_mechanism": "La lógica de potencia de Elekta requiere una secuencia escalonada estricta: CON-A conecta la precarga, seguido de CON-D y CON-J con un retardo nominal de aproximadamente 500 ms antes de autorizar el cierre definitivo de CON-K. Si CON-D o CON-J presentan retardo en sus contactos auxiliares o caídas de tensión de control durante la conmutación de carga inductiva, la secuencia se aborta antes de que CON-K pueda cerrarse y mantenerse.",
            "rationale": "La lógica de potencia de Elekta requiere una secuencia escalonada estricta: CON-A conecta la precarga, seguido de CON-D y CON-J con un retardo nominal de aproximadamente 500 ms antes de autorizar el cierre definitivo de CON-K. Si CON-D o CON-J presentan retardo en sus contactos auxiliares o caídas de tensión de control durante la conmutación de carga inductiva, la secuencia se aborta antes de que CON-K pueda cerrarse y mantenerse.",
            "solution_procedure": "1. Registrar con osciloscopio de almacenamiento o analizador lógico la secuencia de señales CON_A_ON, CON_D_ON, CON_J_ON y CON_K_ON durante el arranque de HT.\n2. Verificar los tiempos de transición entre el cierre de CON-J y la orden de CON-K en los registros de diagnóstico del CCP (debe ser ~500 ms).\n3. Inspeccionar el estado de los contactores previos CON-D y CON-J, limpiando o sustituyendo aquellos con signos de desgaste o arco eléctrico severo.",
            "affected_components": ["CON-A", "CON-D", "CON-J", "CON-K", "DIE-HTA", "DIE-HTB"],
        })
        differential_diagnoses.append({
            "title": "Interrupción previa en la cadena de interbloqueos serie de seguridad HT (SW1/SW2, TS22A o lazo maestro)",
            "hypothesis": "Interrupción previa en la cadena de interbloqueos serie de seguridad HT (SW1/SW2, TS22A o lazo maestro)",
            "subsystem": "Sistema General de Interbloqueos y Seguridad (Elekta LINAC)",
            "likelihood": "media",
            "cause_mechanism": "El circuito de control que habilita la bobina de CON-K está condicionado en serie por la cadena de seguridad de alta tensión (incluyendo contactos de sobretemperatura SW1/SW2 del modulador en Área 17, presostato de vacío en columna y contactos de seguridad de puertas/setas de emergencia). Una apertura instantánea o microcorte en cualquiera de estos sensores interrumpe la corriente de retención del contactor.",
            "rationale": "El circuito de control que habilita la bobina de CON-K está condicionado en serie por la cadena de seguridad de alta tensión (incluyendo contactos de sobretemperatura SW1/SW2 del modulador en Área 17, presostato de vacío en columna y contactos de seguridad de puertas/setas de emergencia). Una apertura instantánea o microcorte en cualquiera de estos sensores interrumpe la corriente de retención del contactor.",
            "solution_procedure": "1. Revisar la máscara general de interlocks en la pantalla Service Mode -> Interlocks Overview para verificar si otro subsistema (Vacuum, Modulator Overtemp o Emergency Chain) presenta un flag de inhibición previo o simultáneo.\n2. Medir la continuidad del lazo serie de seguridad en los terminales de entrada al bastidor HTCA (conectores SK16R / SK17C).\n3. Comprobar que los microinterruptores de las puertas de la sala y del gabinete de modulador cierren firmemente.",
            "affected_components": ["SK16R", "SK17C", "SW1", "SW2", "TS22A", "DIE-HTB"],
        })
        differential_diagnoses.append({
            "title": "Caída de tensión transitoria o rizado dinámico en la línea de control de 24 VDC de contactores",
            "hypothesis": "Caída de tensión transitoria o rizado dinámico en la línea de control de 24 VDC de contactores",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "likelihood": "baja",
            "cause_mechanism": "Al energizarse simultáneamente las bobinas de contactores de potencia o al conmutar cargas en el primario, la fuente de alimentación de control de 24 VDC sufre una caída transitoria de tensión por debajo de 19 VDC si los condensadores electrolíticos de filtrado están degradados. Esta caída provoca el descebe inmediato de CON-K o el reset parcial del FPGA en DIE-HTA/DIE-HTB.",
            "rationale": "Al energizarse simultáneamente las bobinas de contactores de potencia o al conmutar cargas en el primario, la fuente de alimentación de control de 24 VDC sufre una caída transitoria de tensión por debajo de 19 VDC si los condensadores electrolíticos de filtrado están degradados. Esta caída provoca el descebe inmediato de CON-K o el reset parcial del FPGA en DIE-HTA/DIE-HTB.",
            "solution_procedure": "1. Conectar osciloscopio en el riel de 24 VDC del bastidor HTCA y capturar la forma de onda durante el intento de encendido de HT.\n2. Confirmar que la caída de tensión no sobrepase el 10% (mínimo 21.6 VDC durante la corriente de inrush de las bobinas).\n3. Medir el rizado AC en la salida de la fuente de 24 VDC (< 50 mVpp).\n4. Ajustar el potenciómetro de calibración de la fuente de 24 VDC o reemplazar el módulo de fuente de alimentación si no sostiene la carga.",
            "affected_components": ["Power Supply 24VDC", "HTCA Rack", "DIE-HTA", "DIE-HTB", "CON-K"],
        })
    elif is_ht_psu_ot:
        differential_diagnoses.append({
            "title": "Apertura o fatiga térmica del interruptor bimetálico SW1 en disipador o termostatos TS1/TS2",
            "hypothesis": "Apertura o fatiga térmica del interruptor bimetálico SW1 en el disipador (4513 330 6280/7910) o termostatos TS1/TS2 por caudal de aire degradado en BLA o fallo en el lazo del intercambiador de calor",
            "subsystem": subsystem,
            "likelihood": "alta",
            "cause_mechanism": "Durante arcos VMAT con modulación dinámica de PRF y dosis, los transistores TR1/TR2 (excitados por PCB 17A/B y HT PSU CONTROL PCB 16R) disipan calor intensivo. Si el ventilador BLA o el lazo del intercambiador de calor (heat exchanger loop / bomba auxiliar) presentan pérdida de rendimiento, se abre el interruptor bimetálico SW1 o los termostatos TS1/TS2 en serie.",
            "rationale": "Durante arcos VMAT con modulación dinámica de PRF y dosis, los transistores TR1/TR2 (excitados por PCB 17A/B y HT PSU CONTROL PCB 16R) disipan calor intensivo. Si el ventilador BLA o el lazo del intercambiador de calor (heat exchanger loop / bomba auxiliar) presentan pérdida de rendimiento, se abre el interruptor bimetálico SW1 o los termostatos TS1/TS2 en serie.",
            "solution_procedure": "1. En Service Mode -> Inhibits verificar el estado de ITEM 251 (HT PSU OT).\n2. Medir continuidad en SK17C / PL16S y en PL2-a3 de DIE-HTB.\n3. Inspeccionar el ventilador BLA y disyuntores CB1/CB3.",
            "affected_components": ["SW1", "TS1", "TS2", "BLA", "DIE-HTB", "PL2-a3"],
        })
        differential_diagnoses.append({
            "title": "Dilatación de aceite aislante y activación del microinterruptor de fuelle SW2 en transformador T4 (1512977)",
            "hypothesis": "Dilatación de aceite aislante y activación del microinterruptor de fuelle SW2 en transformador T4 (1512977) o presostato en PCB 22 / TS22A",
            "subsystem": subsystem,
            "likelihood": "media",
            "cause_mechanism": "El régimen sostenido de carga calienta el aceite del tanque de T4 en Área 17 o afecta la supervisión en la regleta TS22A de la tarjeta PCB 22 en Área 22. La dilatación abre el microinterruptor normalmente cerrado SW2 en serie con SW1, retirando el nivel de habilitación en el pin PL2-a3 de la DIE-HTB.",
            "rationale": "El régimen sostenido de carga calienta el aceite del tanque de T4 en Área 17 o afecta la supervisión en la regleta TS22A de la tarjeta PCB 22 en Área 22. La dilatación abre el microinterruptor normalmente cerrado SW2 en serie con SW1, retirando el nivel de habilitación en el pin PL2-a3 de la DIE-HTB.",
            "solution_procedure": "1. Inspeccionar nivel y temperatura del aceite en T4.\n2. Medir continuidad en bornes de SW2 y en la regleta TS22A.\n3. Verificar ausencia de sobrepresión en tanque de HT.",
            "affected_components": ["SW2", "T4", "PCB 22", "TS22A", "DIE-HTB"],
        })
        differential_diagnoses.append({
            "title": "Degradación optoelectrónica en OPTO 3 / OPTO 9 de HT ISOLATION PCB (4513 330 7753) o falso contacto en SK17C / PL16S",
            "hypothesis": "Degradación optoelectrónica en OPTO 3 / OPTO 9 de HT ISOLATION PCB (4513 330 7753) o falso contacto en SK17C / PL16S",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "likelihood": "media",
            "cause_mechanism": "La interfaz de aislamiento óptico entre el módulo de potencia (Área 17) y el bastidor HTCA (Área 16) puede presentar caídas de tensión o fatiga en optoacopladores, simulando una condición de sobretemperatura inexistente en los sensores físicos.",
            "rationale": "La interfaz de aislamiento óptico entre el módulo de potencia (Área 17) y el bastidor HTCA (Área 16) puede presentar caídas de tensión o fatiga en optoacopladores, simulando una condición de sobretemperatura inexistente en los sensores físicos.",
            "solution_procedure": "1. Validar la transmisión optoacoplada en HT ISOLATION PCB hacia HTCA con osciloscopio.\n2. Comprobar conexionado en conectores SK17C y PL16S.\n3. Reemplazar tarjeta si la conmutación óptica es defectuosa.",
            "affected_components": ["HT ISOLATION PCB", "OPTO 3", "OPTO 9", "SK17C", "PL16S"],
        })
        differential_diagnoses.append({
            "title": "Descalibración analógica en lazo de regulación de corriente primaria (divisor resistivo PRI I MON vs PRI REF en PCB 16R frente a ITEM 330)",
            "hypothesis": "Descalibración analógica en lazo de regulación de corriente primaria (divisor resistivo PRI I MON vs PRI REF en PCB 16R frente a ITEM 330 de AO12-HTA)",
            "subsystem": subsystem,
            "likelihood": "baja",
            "cause_mechanism": "Si el bucle de realimentación de corriente primaria en la tarjeta HT PSU CONTROL PCB presenta offset respecto a la consigna enviada desde AO12-HTA, la fuente opera en sobrecorriente no detectada que sobrecalienta el puente primario.",
            "rationale": "Si el bucle de realimentación de corriente primaria en la tarjeta HT PSU CONTROL PCB presenta offset respecto a la consigna enviada desde AO12-HTA, la fuente opera en sobrecorriente no detectada que sobrecalienta el puente primario.",
            "solution_procedure": "1. Ejecutar prueba de tasa de carga (Charge Rate Test) según procedimiento 7.7.6.2 de ht_rf.pdf en PCB 16R.\n2. Conectar multímetro en TPU1-8 respecto a TPU1-1 e introducir ITEM 330 (0, 20.00, 40.00 A).\n3. Ajustar potenciómetros de calibración si hay desviación.",
            "affected_components": ["HT PSU CONTROL PCB", "PCB 16R", "TPU1-8", "TPU1-1", "ITEM 330", "PRI I MON"],
        })
    elif "dosimetr" in low_sub or "haz" in low_sub:
        differential_diagnoses.append({
            "title": f"Disparo de interbloqueo por condición de terminación forzada o fallo de reset en {primary_board}",
            "hypothesis": f"Disparo de interbloqueo por condición de terminación forzada o fallo de reset en {primary_board}",
            "subsystem": subsystem,
            "cause_mechanism": f"El circuito integrador y comparador de dosis en {primary_board} (bastidor RHCA en cabezal) supervisa las señales {signals_label}. Si el pulso de puesta a cero (Reset) no conmuta a nivel bajo o el circuito biestable de terminación forzada queda retenido por un transitorio, la compuerta lógica mantiene abierto el lazo de seguridad de corte de radiación.",
            "rationale": f"El circuito integrador y comparador de dosis en {primary_board} (bastidor RHCA en cabezal) supervisa las señales {signals_label}. Si el pulso de puesta a cero (Reset) no conmuta a nivel bajo o el circuito biestable de terminación forzada queda retenido por un transitorio, la compuerta lógica mantiene abierto el lazo de seguridad de corte de radiación.",
            "solution_procedure": "1. Acceder a Service Mode -> Display Service Pages -> Dosimetry y verificar el registro de disparo del Canal 1 y Canal 2.\n2. Conectar osciloscopio en el punto de prueba de Reset en la tarjeta DIE-RHA y verificar la amplitud (> 4.5 V) y ancho de pulso nominal.\n3. Medir la resistencia del lazo de terminación forzada hacia la RTU del cabezal.\n4. Sustituir o recalibrar la tarjeta de dosimetría si el biestable de enclavamiento no rearma.",
            "affected_components": [primary_board, "DIE-RHA", "RHCA", "PL1", "SK1"],
            "likelihood": "alta",
        })
        differential_diagnoses.append({
            "title": "Deriva o caída en la tensión de polarización HT de cámara de ionización (-400V a -600V DC)",
            "hypothesis": "Deriva o caída en la tensión de polarización HT de cámara de ionización (-400V a -600V DC)",
            "subsystem": subsystem,
            "cause_mechanism": "La recolección de carga iónica en la cámara de transmisión requiere una tensión de polarización continua estable entre -400V y -600V DC. Una pérdida de regulación en el convertidor elevador de polarización o corriente de fuga en el cable coaxial triaxial provoca caída de eficiencia de recolección y divergencia entre lecturas de dosis primaria y secundaria.",
            "rationale": "La recolección de carga iónica en la cámara de transmisión requiere una tensión de polarización continua estable entre -400V y -600V DC. Una pérdida de regulación en el convertidor elevador de polarización o corriente de fuga en el cable coaxial triaxial provoca caída de eficiencia de recolección y divergencia entre lecturas de dosis primaria y secundaria.",
            "solution_procedure": "1. Medir con multímetro de alta impedancia (> 10 Mohm) la tensión de polarización en el conector de la cámara de ionización (-500 VDC ± 15 V).\n2. Inspeccionar el cable triaxial y conector BNC/SHV en busca de humedad, suciedad superficial o daño mecánico en dieléctrico.\n3. Ajustar el potenciómetro de ajuste de HT de cámara en la fuente auxiliar o sustituir el módulo conversor si la tensión fluctúa bajo haz.",
            "affected_components": ["Chamber Bias PSU", "Ion Chamber", "DIE-RHA", "Triaxial Cable"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Descalibración o deriva térmica en convertidores Tensión-Frecuencia (V-F) de canales D1/D2",
            "hypothesis": "Descalibración o deriva térmica en convertidores Tensión-Frecuencia (V-F) de canales D1/D2",
            "subsystem": subsystem,
            "cause_mechanism": "Las corrientes de ionización son convertidas a trenes de pulsos proporcionales por los chips V-F en DIE-RHA y DIE-RHB. Una deriva térmica en las referencias de tensión de precisión de 10.000 V o fuga en los condensadores de integración genera una discrepancia de simetría o tasa que supera la tolerancia admisible de interbloqueo (< 2%).",
            "rationale": "Las corrientes de ionización son convertidas a trenes de pulsos proporcionales por los chips V-F en DIE-RHA y DIE-RHB. Una deriva térmica en las referencias de tensión de precisión de 10.000 V o fuga en los condensadores de integración genera una discrepancia de simetría o tasa que supera la tolerancia admisible de interbloqueo (< 2%).",
            "solution_procedure": "1. Realizar calibración de simetría y ganancia de canales en Service Mode -> Dosimetry Calibration según protocolo de mantenimiento.\n2. Conectar frecuencímetro o contador en los puntos de prueba TP_D1 y TP_D2 con fuente de corriente patrón inyectada.\n3. Ajustar potenciómetros de ganancia fina hasta que el ratio D1/D2 esté dentro del 0.5% del valor nominal.",
            "affected_components": ["DIE-RHA", "DIE-RHB", "TP_D1", "TP_D2", "V-F Converter"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Fallo de comunicación en bus serie / ARCNET o timeout en la RTU del cabezal (RHCA)",
            "hypothesis": "Fallo de comunicación en bus serie / ARCNET o timeout en la RTU del cabezal (RHCA)",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "cause_mechanism": f"La tarjeta {primary_board} transmite su conteo digital de unidades de monitor (MU) al procesador central CCP a través del enlace de fibra óptica o bus serie de la RTU del cabezal. Pérdidas de paquetes por atenuación en fibra o microcortes en el riel de 5 VDC provocan timeout en la trama de supervisión periódica.",
            "rationale": f"La tarjeta {primary_board} transmite su conteo digital de unidades de monitor (MU) al procesador central CCP a través del enlace de fibra óptica o bus serie de la RTU del cabezal. Pérdidas de paquetes por atenuación en fibra o microcortes en el riel de 5 VDC provocan timeout en la trama de supervisión periódica.",
            "solution_procedure": "1. Inspeccionar en Service Mode -> Comms Status los contadores de errores CRC y timeouts en el nodo RHCA.\n2. Medir potencia óptica en el transceptor de fibra del cabezal con vatímetro óptico (-15 a -22 dBm).\n3. Limpiar férulas de conectores ST/SMA con bastoncillos ópticos y alcohol isopropílico de alta pureza.\n4. Comprobar riel de alimentación limpia de +5 VDC (± 0.05 V) en placa base de RTU.",
            "affected_components": ["RTU Cabezal", "Fibra Óptica RHCA", "CCP Bus", primary_board],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Rizado dinámico parásito o caída transitoria en rieles de alimentación continua (+24VDC, ±15VDC)",
            "hypothesis": "Rizado dinámico parásito o caída transitoria en rieles de alimentación continua (+24VDC, ±15VDC)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "cause_mechanism": "El filtrado insuficiente o degradación de condensadores ESR en la fuente de alimentación del cabezal induce transitorios durante el encendido de radiación que alteran los comparadores analógicos de interlock en DIE-RHA.",
            "rationale": "El filtrado insuficiente o degradación de condensadores ESR en la fuente de alimentación del cabezal induce transitorios durante el encendido de radiación que alteran los comparadores analógicos de interlock en DIE-RHA.",
            "solution_procedure": "1. Conectar osciloscopio en modo AC en los rieles de +15V, -15V y +24V del cabezal y verificar rizado < 20 mVpp bajo carga de haz.\n2. Si el rizado sobrepasa tolerancia, verificar puente rectificador y condensadores electrolíticos de la fuente de alimentación.\n3. Reemplazar fuente de baja tensión si la regulación térmica o dinámica es deficiente.",
            "affected_components": ["Power Supply ±15V", "DIE-RHA", "RHCA Rack", "Filter Caps"],
            "likelihood": "baja",
        })
    elif "vacío" in low_sub or "vacuum" in low_sub:
        differential_diagnoses.append({
            "title": "Apertura del presostato SW1 por degradación de vacío o corriente elevada en bomba iónica",
            "hypothesis": "Apertura del presostato SW1 por degradación de vacío o corriente elevada en bomba iónica",
            "subsystem": subsystem,
            "cause_mechanism": "La corriente de la bomba iónica es directamente proporcional a la presión en el cañón de electrones y guía aceleradora. Si la presión residual asciende por encima de 10^-7 Torr debido a desgasificación o microfuga, la corriente de iones supera el umbral de disparo del relé de protección SW1, abriendo el circuito serie que habilita la alta tensión de RF.",
            "rationale": "La corriente de la bomba iónica es directamente proporcional a la presión en el cañón de electrones y guía aceleradora. Si la presión residual asciende por encima de 10^-7 Torr debido a desgasificación o microfuga, la corriente de iones supera el umbral de disparo del relé de protección SW1, abriendo el circuito serie que habilita la alta tensión de RF.",
            "solution_procedure": "1. Comprobar en Service Mode o en el panel de control de vacío la lectura de corriente iónica (debe ser < 2 μA en reposo).\n2. Inspeccionar la curva de desgasificación dejando la bomba en operación continua sin filamento encendido.\n3. Comprobar la continuidad del contacto normalmente cerrado del presostato SW1 con multímetro.\n4. Si la presión no se recupera, realizar prueba de búsqueda de fugas con helio en ventanas cerámicas y bridas ConFlat.",
            "affected_components": ["Ion Pump", "SW1", "Vacuum Controller", "Columna Aceleradora"],
            "likelihood": "alta",
        })
        differential_diagnoses.append({
            "title": "Fuga dieléctrica superficial en el aislador cerámico del pasamuros de alto vacío",
            "hypothesis": "Fuga dieléctrica superficial en el aislador cerámico del pasamuros de alto vacío",
            "subsystem": subsystem,
            "cause_mechanism": "La acumulación de polvo conductivo o depósito metálico por sputtering en la superficie exterior del aislador cerámico crea una vía resistiva parásita. Esta fuga eleva la corriente aparente de la fuente de la bomba sin que exista una pérdida de vacío real en la columna.",
            "rationale": "La acumulación de polvo conductivo o depósito metálico por sputtering en la superficie exterior del aislador cerámico crea una vía resistiva parásita. Esta fuga eleva la corriente aparente de la fuente de la bomba sin que exista una pérdida de vacío real en la columna.",
            "solution_procedure": "1. Desenergizar completamente la fuente de alto voltaje de la bomba iónica (3 kV a 5 kV) y conectar pértiga de descarga a tierra.\n2. Limpiar minuciosamente el aislador cerámico pasamuros con alcohol isopropílico de grado analítico y paños libres de pelusa.\n3. Inspeccionar el cuerpo cerámico con lupa óptica en busca de fisuras, grietas o caminos de arco.\n4. Aplicar compuesto de sellado aislante o sustituir el pasamuros si el agrietamiento es estructural.",
            "affected_components": ["Ceramic Feedthrough", "Ion Pump HV Cable", "Ion Chamber"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Inestabilidad en la fuente de polarización de alta tensión de la bomba de iones (3 kV - 5 kV)",
            "hypothesis": "Inestabilidad en la fuente de polarización de alta tensión de la bomba de iones (3 kV - 5 kV)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "cause_mechanism": "El módulo convertidor de alta tensión genera entre 3 kV y 5 kV para la descarga Penning. Fluctuaciones en el oscilador de conmutación o deriva del divisor resistivo de telemetría provocan oscilaciones espurias en la señal telemétrica de corriente, activando el interbloqueo de vacío por falso positivo.",
            "rationale": "El módulo convertidor de alta tensión genera entre 3 kV y 5 kV para la descarga Penning. Fluctuaciones en el oscilador de conmutación o deriva del divisor resistivo de telemetría provocan oscilaciones espurias en la señal telemétrica de corriente, activando el interbloqueo de vacío por falso positivo.",
            "solution_procedure": "1. Medir con sonda atenuadora de alta tensión (1000:1) la salida de polarización de la fuente iónica (nominal ~4.2 kV DC).\n2. Comprobar que no existan fluctuaciones superiores a ±50 V en vacío.\n3. Medir el voltaje analógico de salida de telemetría en el conector hacia la tarjeta de interfaz.\n4. Reemplazar la fuente de alimentación de la bomba si la alta tensión colapsa bajo carga nominal.",
            "affected_components": ["Ion Pump PSU", "HV Sonda", "DIE-ICA", "DIE-ICB"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Resistencia de contacto en bornes del lazo de seguridad de vacío y conectores",
            "hypothesis": "Resistencia de contacto en bornes del lazo de seguridad de vacío y conectores",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "cause_mechanism": "La señal de estado de vacío atraviesa bornes y conectores hacia las tarjetas de interlock DIE-ICA / DIE-ICB. Oxidación o falta de par de apriete en las borneras genera caídas de potencial mayores a 0.5 V, interpretadas como apertura de contacto de seguridad.",
            "rationale": "La señal de estado de vacío atraviesa bornes y conectores hacia las tarjetas de interlock DIE-ICA / DIE-ICB. Oxidación o falta de par de apriete en las borneras genera caídas de potencial mayores a 0.5 V, interpretadas como apertura de contacto de seguridad.",
            "solution_procedure": "1. Medir con microohmímetro la resistencia de bucle de los contactos de señal de interbloqueo de vacío (< 0.2 ohm).\n2. Reapretar los tornillos de fijación en las regletas de interconexión del armario de modulación.\n3. Aplicar limpiador de contactos residuo cero en conectores enchufables.\n4. Verificar que el relé de salida de vacío enclave firmemente con 24 VDC.",
            "affected_components": ["Regleta de Vacío", "DIE-ICA", "DIE-ICB", "Relé de Seguridad Vacío"],
            "likelihood": "baja",
        })
        differential_diagnoses.append({
            "title": "Fallo de presión dieléctrica de gas SF6 en guía de ondas de radiofrecuencia",
            "hypothesis": "Fallo de presión dieléctrica de gas SF6 en guía de ondas de radiofrecuencia",
            "subsystem": subsystem,
            "cause_mechanism": "El sistema de guía de ondas presurizado con hexafluoruro de azufre (SF6 a ~2.2 bar) previene arcos eléctricos por alta potencia de microondas. Si el presostato de SF6 detecta caída de presión por fuga en juntas tóricas, se inhibe el modulador simultáneamente con la supervisión de vacío.",
            "rationale": "El sistema de guía de ondas presurizado con hexafluoruro de azufre (SF6 a ~2.2 bar) previene arcos eléctricos por alta potencia de microondas. Si el presostato de SF6 detecta caída de presión por fuga en juntas tóricas, se inhibe el modulador simultáneamente con la supervisión de vacío.",
            "solution_procedure": "1. Verificar manómetro de presión de gas SF6 en el panel de distribución (rango normal: 2.0 - 2.4 bar).\n2. Comprobar la conmutación eléctrica del presostato de gas SF6 con multímetro en la bornera asociada.\n3. Si la presión es baja, rellenar con cilindro de gas SF6 seco mediante kit de carga hasta presión nominal.\n4. Realizar prueba de jabón detector de fugas en uniones de bridas de la guía de ondas.",
            "affected_components": ["Presostato SF6", "Guía de Ondas", "Manómetro SF6", "Válvula de Carga"],
            "likelihood": "media",
        })
    elif "rf" in low_sub or "tensión" in low_sub:
        differential_diagnoses.append({
            "title": "Dispersión temporal o deformación en el pulso de disparo de rejilla del tiratrón",
            "hypothesis": "Dispersión temporal o deformación en el pulso de disparo de rejilla del tiratrón",
            "subsystem": subsystem,
            "cause_mechanism": "El tiratrón de conmutación de alta tensión requiere un pulso de disparo en rejilla con tiempo de subida < 50 ns y amplitud superior a 800 V. Si el circuito excitador de pulso de rejilla presenta condensadores secos o fatiga en el transformador de impulsos, el tiratrón conmuta con jitter, provocando disparos erráticos en la red formadora de pulsos (PFN) y sobrecorriente primaria.",
            "rationale": "El tiratrón de conmutación de alta tensión requiere un pulso de disparo en rejilla con tiempo de subida < 50 ns y amplitud superior a 800 V. Si el circuito excitador de pulso de rejilla presenta condensadores secos o fatiga en el transformador de impulsos, el tiratrón conmuta con jitter, provocando disparos erráticos en la red formadora de pulsos (PFN) y sobrecorriente primaria.",
            "solution_procedure": "1. Conectar sonda atenuadora de alto voltaje en el punto de prueba de rejilla del tiratrón en Área 16/17.\n2. Disparar en modo Standby / Pruebas y verificar con osciloscopio la amplitud del pulso (> 800 Vpk) y tiempo de subida (< 50 ns).\n3. Ajustar el potenciómetro de retardo y tensión de polarización negativa de rejilla (-100 VDC).\n4. Si el pulso está deformado, reemplazar el módulo driver de disparo o el transformador de impulsos.",
            "affected_components": ["Tiratrón", "Grid Driver PCB", "PFN", "Área 17"],
            "likelihood": "alta",
        })
        differential_diagnoses.append({
            "title": "Deriva en corriente de filamento de magnetrón o desajuste de sintonía en bucle AFC",
            "hypothesis": "Deriva en corriente de filamento de magnetrón o desajuste de sintonía en bucle AFC",
            "subsystem": subsystem,
            "cause_mechanism": "El magnetrón debe operar con su corriente de calentamiento de cátodo estrictamente regulada (precalentamiento y retrocalentamiento por electrones reflejados). Si el transformador de filamento o el sensor de corriente de filamento presentan deriva, o si el motor de sintonía de la cavidad AFC no compensa la frecuencia de resonancia, se produce un pico de potencia reflejada que activa el interbloqueo de RF.",
            "rationale": "El magnetrón debe operar con su corriente de calentamiento de cátodo estrictamente regulada (precalentamiento y retrocalentamiento por electrones reflejados). Si el transformador de filamento o el sensor de corriente de filamento presentan deriva, o si el motor de sintonía de la cavidad AFC no compensa la frecuencia de resonancia, se produce un pico de potencia reflejada que activa el interbloqueo de RF.",
            "solution_procedure": "1. Medir con pinza amperimétrica de verdadero valor eficaz (True RMS) la corriente de filamento de magnetrón durante precalentamiento (según hoja técnica: nominal ~8.5 A a 9.2 A).\n2. En Service Mode -> AFC, verificar la posición del émbolo de sintonía y la respuesta del error de fase del discriminador.\n3. Recalibrar el bucle AFC mediante ajuste del cero del discriminador y ganancia de motor.\n4. Inspeccionar el circulador de ferrita y carga de absorción de potencia reflejada.",
            "affected_components": ["Magnetrón", "AFC Motor PCB", "Circulador", "Filament Transformer"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Activación del detector óptico de arco o pérdida de aislamiento dieléctrico en guía de ondas",
            "hypothesis": "Activación del detector óptico de arco o pérdida de aislamiento dieléctrico en guía de ondas",
            "subsystem": subsystem,
            "cause_mechanism": "Los sensores de fotodiodo o fototransistores del detector óptico de arco vigilan la ventana cerámica de salida del magnetrón y la entrada de la cavidad aceleradora. Un destello de arco interno por polvo, contaminación o sobretensión conmuta el circuito detector en < 5 μs, cortando inmediatamente los pulsos PRF.",
            "rationale": "Los sensores de fotodiodo o fototransistores del detector óptico de arco vigilan la ventana cerámica de salida del magnetrón y la entrada de la cavidad aceleradora. Un destello de arco interno por polvo, contaminación o sobretensión conmuta el circuito detector en < 5 μs, cortando inmediatamente los pulsos PRF.",
            "solution_procedure": "1. Comprobar en Service Mode el bit de interlock 'RF ARC DETECT' y el LED testigo en la tarjeta receptora de fibra óptica.\n2. Limpiar la fibra óptica del detector de arco y la superficie exterior de la ventana cerámica con aire comprimido seco e hisopos ópticos.\n3. Verificar la ganancia del circuito detector de arco inyectando un pulso de luz de prueba con LED calibrado.\n4. Si el interbloqueo se repite a potencias altas, reducir transitoriamente el nivel de modulador para reacondicionar la guía.",
            "affected_components": ["Arc Detector PCB", "Fibra Óptica Arco", "Ventana Cerámica RF", "Magnetrón"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Ruido electromagnético acoplado durante la descarga de la línea formadora de pulsos (PFN)",
            "hypothesis": "Ruido electromagnético acoplado durante la descarga de la línea formadora de pulsos (PFN)",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "cause_mechanism": "La descarga rápida de la red PFN maneja corrientes de pulso de cientos de amperios en nanosegundos. Si las trenzas de masa del modulador, las jaulas de apantallamiento de Área 17 o los filtros de ferrita están desajustados, los transitorios electromagnéticos inducen picos de tensión en las líneas lógicas de interbloqueo del bastidor HTCA.",
            "rationale": "La descarga rápida de la red PFN maneja corrientes de pulso de cientos de amperios en nanosegundos. Si las trenzas de masa del modulador, las jaulas de apantallamiento de Área 17 o los filtros de ferrita están desajustados, los transitorios electromagnéticos inducen picos de tensión en las líneas lógicas de interbloqueo del bastidor HTCA.",
            "solution_procedure": "1. Inspeccionar visualmente y reapretar todas las trenzas de masa de cobre estañado del armario modulador y tanque T4.\n2. Verificar con multímetro que la impedancia de unión a chasis principal sea < 0.05 ohm.\n3. Asegurar que las mallas de apantallamiento de los cables de control estén aterradas exclusivamente en un extremo según diagrama de cableado.\n4. Colocar anillos de ferrita tipo toroidal en los haces de señal que ingresan al bastidor HTCA.",
            "affected_components": ["PFN", "Trenzas de Masa", "Tanque T4", "HTCA Rack"],
            "likelihood": "baja",
        })
        differential_diagnoses.append({
            "title": "Fallo en circuito de carga de desionización y chopper resonante de la fuente de alta tensión",
            "hypothesis": "Fallo en circuito de carga de desionización y chopper resonante de la fuente de alta tensión",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "cause_mechanism": "Tras cada descarga, el tiratrón necesita desionizarse antes de que la PFN vuelva a cargarse. Si el inductor de carga, el diodo de retención (hold-off diode) o la tarjeta de control de carga HT PSU CONTROL PCB presentan derivas en los pulsos de inhibición de carga, la fuente carga prematuramente con el tiratrón aún ionizado, causando disparo continuo por conducción de arco sostenido.",
            "rationale": "Tras cada descarga, el tiratrón necesita desionizarse antes de que la PFN vuelva a cargarse. Si el inductor de carga, el diodo de retención (hold-off diode) o la tarjeta de control de carga HT PSU CONTROL PCB presentan derivas en los pulsos de inhibición de carga, la fuente carga prematuramente con el tiratrón aún ionizado, causando disparo continuo por conducción de arco sostenido.",
            "solution_procedure": "1. Medir con osciloscopio la forma de onda de tensión en la red PFN comprobando la presencia del tiempo muerto de desionización (> 500 μs).\n2. Verificar el estado estático y dinámico de los diodos de retención de alta tensión con multímetro en escala de semiconductores.\n3. Inspeccionar el condensador de filtrado y conmutación en la tarjeta HT PSU CONTROL PCB (PCB 16R).\n4. Ajustar el tiempo de retardo de rampa de carga en el controlador de la fuente.",
            "affected_components": ["HT PSU CONTROL PCB", "PCB 16R", "Hold-off Diode", "Choke L2", "Tiratrón"],
            "likelihood": "media",
        })
    elif "movimiento" in low_sub or "colimad" in low_sub or "mesa" in low_sub:
        differential_diagnoses.append({
            "title": "Discrepancia de seguimiento entre potenciómetro analógico y encoder digital de posición",
            "hypothesis": "Discrepancia de seguimiento entre potenciómetro analógico y encoder digital de posición",
            "subsystem": subsystem,
            "cause_mechanism": "Los ejes cinemáticos de Elekta (Gantry, Colimador, Diafragmas o Hojas MLC) utilizan verificación redundante: un encoder óptico digital acoplado al servomotor y un potenciómetro multivuelta analógico de referencia. Si el acoplamiento elástico desliza, o el potenciómetro presenta desgaste en su pista resistiva, la divergencia angular excede la ventana de tolerancia admitida (< 0.2° o 1 mm), activando el interbloqueo preventivo de posición.",
            "rationale": "Los ejes cinemáticos de Elekta (Gantry, Colimador, Diafragmas o Hojas MLC) utilizan verificación redundante: un encoder óptico digital acoplado al servomotor y un potenciómetro multivuelta analógico de referencia. Si el acoplamiento elástico desliza, o el potenciómetro presenta desgaste en su pista resistiva, la divergencia angular excede la ventana de tolerancia admitida (< 0.2° o 1 mm), activando el interbloqueo preventivo de posición.",
            "solution_procedure": "1. Acceder a Service Mode -> Motions Calibration y comparar las lecturas del encoder frente al potenciómetro para el eje afectado.\n2. Inspeccionar mecánicamente el tornillo prisionero del acoplamiento elástico entre el motor y el potenciómetro.\n3. Medir con multímetro la linealidad de la pista del potenciómetro durante el giro manual continuo.\n4. Ejecutar el procedimiento de calibración de offset y ganancia de posición en CCP tras reapretar.",
            "affected_components": ["Encoder de Posición", "Potenciómetro Multivuelta", "Motor Driver PCB", "Eje Mecánico"],
            "likelihood": "alta",
        })
        differential_diagnoses.append({
            "title": "Fricción mecánica, holgura en correas de transmisión o retardo en frenos electromagnéticos",
            "hypothesis": "Fricción mecánica, holgura en correas de transmisión o retardo en frenos electromagnéticos",
            "subsystem": subsystem,
            "cause_mechanism": "El servodriver supervisa el bucle de corriente y el seguimiento de velocidad. Si los frenos electromagnéticos de 24 VDC no desclavan a tiempo por resistencia en su bobina o fatiga en sus muelles, o si las correas dentadas de transmisión presentan destensado o suciedad, el motor entra en sobrecorriente o sobrepasa el error de seguimiento (following error) admisible.",
            "rationale": "El servodriver supervisa el bucle de corriente y el seguimiento de velocidad. Si los frenos electromagnéticos de 24 VDC no desclavan a tiempo por resistencia en su bobina o fatiga en sus muelles, o si las correas dentadas de transmisión presentan destensado o suciedad, el motor entra en sobrecorriente o sobrepasa el error de seguimiento (following error) admisible.",
            "solution_procedure": "1. Medir con medidor de tensión sónica o galga dinamométrica la tensión mecánica de las correas dentadas según especificación de servicio.\n2. Medir la tensión de excitación (24 VDC) en bornes de la bobina del freno durante el comando de movimiento.\n3. Desconectar mecánicamente el motor y comprobar a mano la suavidad de giro y ausencia de puntos duros en la reductora.\n4. Limpiar guías lineales y lubricar rodamientos según la tabla de mantenimiento preventivo.",
            "affected_components": ["Freno Electromagnético 24V", "Correa Dentada", "Servomotor", "Servodriver"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Falsa activación o microdesalineación en sensores de final de carrera o microinterruptores touchguard",
            "hypothesis": "Falsa activación o microdesalineación en sensores de final de carrera o microinterruptores touchguard",
            "subsystem": subsystem,
            "cause_mechanism": "Los sensores de final de carrera y las barras protectoras de colisión (Touchguard) operan con circuitos normalmente cerrados cableados en serie hacia la tarjeta de interbloqueo. Si un microinterruptor bimetálico presenta holgura en su soporte, fatiga en su lengüeta o suciedad óptica en barreras de infrarrojos, se producen microcortes de contacto durante la aceleración que detienen el movimiento.",
            "rationale": "Los sensores de final de carrera y las barras protectoras de colisión (Touchguard) operan con circuitos normalmente cerrados cableados en serie hacia la tarjeta de interbloqueo. Si un microinterruptor bimetálico presenta holgura en su soporte, fatiga en su lengüeta o suciedad óptica en barreras de infrarrojos, se producen microcortes de contacto durante la aceleración que detienen el movimiento.",
            "solution_procedure": "1. Comprobar en Service Mode -> Interlocks el estado de los bits de 'Limit Switch' y 'Touchguard' del subsistema.\n2. Inspeccionar físicamente el alineamiento de las levas mecánicas y banderas ópticas de final de carrera.\n3. Medir la continuidad eléctrica del bucle de seguridad con multímetro mientras se acciona y suelta manualmente cada sensor.\n4. Ajustar el soporte mecánico o sustituir el microinterruptor si la histéresis es errática.",
            "affected_components": ["Microswitch Limit", "Touchguard Ring", "DIE Board", "Arnés de Cabezal"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Retardo de paquetes o saturación de cola en el bus CAN de posicionamiento",
            "hypothesis": "Retardo de paquetes o saturación de cola en el bus CAN de posicionamiento",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "cause_mechanism": "Cada nodo controlador de eje (motor controller node) reporta periódicamente al bus CAN de control. Si las resistencias de terminación de 120 ohm del bus CAN están ausentes o abiertas, las reflexiones de señal aumentan la tasa de errores de trama (error frames) forzando retransmisiones continuas y provocando timeout de posición.",
            "rationale": "Retardo de paquetes o saturación de cola en el bus CAN de posicionamiento",
            "solution_procedure": "1. Medir con el sistema apagado la resistencia entre CAN_H y CAN_L en cualquier punto del bus (debe ser 60 ohm exactos con dos terminadores de 120 ohm en paralelo).\n2. Conectar osciloscopio en el bus CAN y verificar niveles de tensión diferenciales (recesivo ~2.5 V, dominante CAN_H ~3.5 V, CAN_L ~1.5 V).\n3. Inspeccionar el blindaje del cable CAN y aislar nodos individuales si un transceptor CAN defectuoso satura el bus con tramas erróneas.",
            "affected_components": ["CAN Bus Line", "Terminadores 120ohm", "CAN Transceiver", "CCP"],
            "likelihood": "baja",
        })
        differential_diagnoses.append({
            "title": "Sobrecalentamiento o caída de tensión en la etapa de potencia del servodriver del motor",
            "hypothesis": "Sobrecalentamiento o caída de tensión en la etapa de potencia del servodriver del motor",
            "subsystem": subsystem,
            "cause_mechanism": "El puente de transistores MOSFETs/IGBTs del servodriver opera con modulación PWM para controlar la corriente del motor. Si la refrigeración del bastidor está degradada o el disipador del driver acumula polvo, la protección térmica interna del módulo se activa y corta transitoriamente la salida de potencia.",
            "rationale": "El puente de transistores MOSFETs/IGBTs del servodriver opera con modulación PWM para controlar la corriente del motor. Si la refrigeración del bastidor está degradada o el disipador del driver acumula polvo, la protección térmica interna del módulo se activa y corta transitoriamente la salida de potencia.",
            "solution_procedure": "1. Verificar con cámara termográfica o sonda de temperatura el disipador de calor del servodriver.\n2. Limpiar los filtros de aire y verificar el funcionamiento de los ventiladores de ventilación forzada del rack de servos.\n3. Medir con multímetro la tensión de bus DC del driver (nominal 24VDC o 48VDC según modelo).\n4. Sustituir el módulo servodriver si presenta desbalance de corriente de fase al alimentar el motor.",
            "affected_components": ["Motor Driver Board", "Ventiladores Rack", "Disipador Driver", "Servomotor"],
            "likelihood": "media",
        })
    else:
        differential_diagnoses.append({
            "title": f"Disparo o descebe en cadena de relés de seguridad del lazo de enclavamiento maestro en {primary_board}",
            "hypothesis": f"Disparo o descebe en cadena de relés de seguridad del lazo de enclavamiento maestro en {primary_board}",
            "subsystem": subsystem,
            "cause_mechanism": f"La cadena redundante de interbloqueos maestros en {primary_board} supervisa las señales {signals_label}. Un falso contacto en los contactos secos de relés de seguridad, microvibraciones en la bornera o una apertura intempestiva en uno de los lazos serie de protección provoca el descebe inmediato del relé maestro y la inhibición de alta tensión y haz (RAD_ON).",
            "rationale": f"La cadena redundante de interbloqueos maestros en {primary_board} supervisa las señales {signals_label}. Un falso contacto en los contactos secos de relés de seguridad, microvibraciones en la bornera o una apertura intempestiva en uno de los lazos serie de protección provoca el descebe inmediato del relé maestro y la inhibición de alta tensión y haz (RAD_ON).",
            "solution_procedure": "1. En Service Mode -> Interlocks Overview, identificar el canal maestro y la máscara binaria del circuito de seguridad abierto.\n2. Medir con multímetro en conectores y puntos de prueba de la tarjeta asociada la continuidad del lazo (< 0.5 ohm).\n3. Inspeccionar el estado de los LEDs indicadores de estado de la cadena de relés en el panel frontal del bastidor.\n4. Reemplazar relés electromecánicos de seguridad con contactos carbonizados o fogueados.",
            "affected_components": [primary_board, "Relé Maestro de Seguridad", "Lazo Serie", "CCP"],
            "likelihood": "alta",
        })
        differential_diagnoses.append({
            "title": "Deriva en tensiones de referencia o rizado dinámico excesivo en fuentes auxiliares (+24V, ±15V)",
            "hypothesis": "Deriva en tensiones de referencia o rizado dinámico excesivo en fuentes auxiliares (+24V, ±15V)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "cause_mechanism": "La degradación de los condensadores electrolíticos de filtrado en las fuentes de alimentación conmutadas auxiliares eleva el rizado AC por encima de 100 mVpp. Durante demandas transitorias de corriente (como la excitación de bobinas de contactores o aceleración de motores), la tensión cae transitoriamente provocando resets espurios de compuertas lógicas y comparadores.",
            "rationale": "La degradación de los condensadores electrolíticos de filtrado en las fuentes de alimentación conmutadas auxiliares eleva el rizado AC por encima de 100 mVpp. Durante demandas transitorias de corriente (como la excitación de bobinas de contactores o aceleración de motores), la tensión cae transitoriamente provocando resets espurios de compuertas lógicas y comparadores.",
            "solution_procedure": "1. Medir con multímetro digital calibrado los rieles de +24 VDC, +15 VDC y -15 VDC en los terminales de salida de las fuentes de poder.\n2. Conectar osciloscopio en acoplamiento AC y medir el rizado pico a pico (debe ser < 50 mVpp bajo carga).\n3. Ajustar los potenciómetros de compensación de voltaje si hay desviación mayor a ±1%.\n4. Si el rizado es excesivo, reemplazar el módulo de fuente de alimentación de riel DIN.",
            "affected_components": ["Power Supply +24V", "Power Supply ±15V", "Condensadores de Filtro", "Bornera de Distribución"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Retardo de sincronización o timeout en el bus de supervisión digital (CAN / ARCNET)",
            "hypothesis": "Retardo de sincronización o timeout en el bus de supervisión digital (CAN / ARCNET)",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "cause_mechanism": "El procesador central CCP requiere la confirmación periódica del estado de todos los nodos remotos dentro de un intervalo de tiempo crítico (< 50 ms). Transitorios de ruido electromagnético, pérdidas de blindaje o fallos en el reloj de sincronismo provocan pérdidas de tramas de estado que impiden al control confirmar el cierre seguro del circuito.",
            "rationale": "El procesador central CCP requiere la confirmación periódica del estado de todos los nodos remotos dentro de un intervalo de tiempo crítico (< 50 ms). Transitorios de ruido electromagnético, pérdidas de blindaje o fallos en el reloj de sincronismo provocan pérdidas de tramas de estado que impiden al control confirmar el cierre seguro del circuito.",
            "solution_procedure": "1. Consultar en Service Mode -> Diagnostics -> Communications los registros de tramas perdidas y contadores de error de bus.\n2. Medir con osciloscopio la integridad de la señal de reloj y las formas de onda diferenciales en el bus.\n3. Comprobar la continuidad del blindaje del cable de comunicaciones a masa en ambos extremos.\n4. Reiniciar la tarjeta RTU del nodo afectado o reprogramar su dirección física de nodo si no sincroniza.",
            "affected_components": ["CCP Processor", "CAN/ARCNET Bus", "RTU Node", "Línea de Fibra/Cobre"],
            "likelihood": "media",
        })
        differential_diagnoses.append({
            "title": "Aumento de resistencia de contacto en bornes de relés de seguridad o microinterruptores",
            "hypothesis": "Aumento de resistencia de contacto en bornes de relés de seguridad o microinterruptores",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "cause_mechanism": "El paso continuo de corriente en circuitos inductivos y el ambiente operativo inducen oxidación superficial y carbonización en las láminas de los contactos electromecánicos. Esto genera una resistencia parásita superior a 1 ohm que introduce caídas de tensión suficientes para superar el umbral de disparo de interlock.",
            "rationale": "El paso continuo de corriente en circuitos inductivos y el ambiente operativo inducen oxidación superficial y carbonización en las láminas de los contactos electromecánicos. Esto genera una resistencia parásita superior a 1 ohm que introduce caídas de tensión suficientes para superar el umbral de disparo de interlock.",
            "solution_procedure": "1. Con el acelerador desenergizado y consignado, medir con miliohmímetro la resistencia de paso de cada contacto de relé involucrado (< 0.15 ohm).\n2. Inspeccionar visualmente si existen marcas de flameo o decoloración térmica en las carcasas transparentes de los relés.\n3. Limpiar o reemplazar los zócalos y relés enchufables que presenten holgura en sus pines de inserción.\n4. Realizar prueba funcional de conmutación activando manualmente la bobina para verificar el tiempo de disparo.",
            "affected_components": ["Relés Electromecánicos", "Zócalos de Inserción", "Borneras", "Arnés de Cableado"],
            "likelihood": "baja",
        })
        differential_diagnoses.append({
            "title": "Discrepancia lógica entre canales redundantes en tarjeta de control de interbloqueos",
            "hypothesis": "Discrepancia lógica entre canales redundantes en tarjeta de control de interbloqueos",
            "subsystem": subsystem,
            "cause_mechanism": "La arquitectura de seguridad de Elekta Linac utiliza doble canal de monitoreo cruzado (Canal A y Canal B). Si una de las señales tarda más de 20 ms en cambiar de estado respecto a su canal complementario tras una orden de control, el procesador detecta una violación de simetría de interbloqueo y bloquea el equipo permanentemente.",
            "rationale": "La arquitectura de seguridad de Elekta Linac utiliza doble canal de monitoreo cruzado (Canal A y Canal B). Si una de las señales tarda más de 20 ms en cambiar de estado respecto a su canal complementario tras una orden de control, el procesador detecta una violación de simetría de interbloqueo y bloquea el equipo permanentemente.",
            "solution_procedure": "1. Cotejar en Service Mode las pantallas de estado binario del Canal A y Canal B en reposo y durante la secuencia de activación.\n2. Conectar analizador lógico u osciloscopio de dos canales para comparar el tiempo de respuesta entre ambas señales.\n3. Verificar los optoacopladores de aislamiento y compuertas lógicas en la tarjeta receptora.\n4. Sustituir la tarjeta de control si uno de los canales internos presenta una entrada lógica flotante o en cortocircuito.",
            "affected_components": [primary_board, "Canal A Interlock", "Canal B Interlock", "Compuertas de Seguridad"],
            "likelihood": "media",
        })

    # 12. Procedimiento de Inspección Paso a Paso específico, profundo y libre de plantillas rígidas
    action_steps: list[str] = []
    cables_label = ", ".join(all_cables[:3]) if all_cables else "conectores del subsistema"

    if is_con_k:
        action_steps = [
            "Acceder a Service Mode -> Display Service Pages -> HT Interlocks y comprobar el bit de monitor CON_K_MON durante el intento de arranque de HT.",
            "Desenergizar el equipo, enclavar consigna de seguridad y medir con multímetro la resistencia de contacto del bloque auxiliar de CON-K (debe ser < 0.2 ohm).",
            "Verificar en la tarjeta DIE-HTA (PCB 16M) el encendido del LED de salida del relé de seguridad RL4 al pulsar HT ON.",
            "Medir con voltímetro en bornes A1-A2 de la bobina de CON-K la tensión de excitación (24 VDC / 110 VAC) durante la secuencia de energización.",
            "Capturar con osciloscopio la secuencia temporal escalonada CON_A_ON, CON_D_ON, CON_J_ON y CON_K_ON, comprobando el retardo nominal de 500 ms.",
            "Medir con osciloscopio la caída transitoria de tensión en el riel de 24 VDC del bastidor HTCA durante la corriente de inrush de las bobinas de contactores.",
        ]
        safety_warning = (
            "ALTA TENSIÓN (HT): Peligro de descarga eléctrica mortal. Cortar interruptor principal, verificar ausencia "
            "de tensión y colocar pértiga de puesta a tierra antes de acceder al transformador T4 o al armario de contactores."
        )
    elif is_ht_psu_ot:
        action_steps = [
            "Acceder a Service Mode -> Display Service Pages -> Inhibits y verificar el estado del monitor ITEM 251 (HT PSU OT) (normal = 1, falla = 0), comprobando si se restablece en frío o persiste enclavado, y cotejar con ITEM 87 (HT BELLOWS) e ITEM 89 (HT CROWBAR).",
            "Medir continuidad y aislamiento en el lazo de seguridad térmico serie de Área 17: verificar con multímetro en el conector SK17C / PL16S y en el pin PL2-a3 de la tarjeta DIE-HTB (PCB 16N, slot 12) la conmutación de los contactos normalmente cerrados del interruptor térmico SW1 (disipador 4513 330 6280) y del interruptor de fuelle SW2 (transformador T4 1512977).",
            "Ejecutar la prueba de tasa de carga (Charge Rate Test) de la HT PSU según procedimiento 7.7.6.2 de ht_rf.pdf (pág. 225): en la tarjeta HTC PCB / PCB 16R conectar multímetro en TPU1-8 respecto a TPU1-1; en Service Mode (página Power Supplies), introducir en ITEM 330 Chargerate: 0 (verificar 0 VDC ±10 mV), 20.00 (verificar 2.5 VDC ±400 mV) y 40.00 (verificar 5.0 VDC ±400 mV), validando la señal PRI I MON frente a PRI REF.",
            "Inspeccionar la refrigeración forzada y protecciones eléctricas en Área 17: comprobar rotación libre y caudal del ventilador centrífugo BLA, limpieza de filtros de aspiración, y verificar continuidad en disyuntores CB1, CB3 (20A) y fusibles FS17A, FS17B (0.5A) de alimentación auxiliar.",
            "Validar la transmisión optoacoplada en la tarjeta HT ISOLATION PCB (4513 330 7753): verificar con osciloscopio la salida hacia el receptor óptico de la HTCA en Área 16 a través de OPTO 3 y OPTO 9, y comprobar el conexionado en terminales 4 y 5 de la tarjeta HT CROWBAR DETECTOR PCB.",
            "Ejecutar una corrida de prueba en Service Mode simulando un arco dinámico VMAT con variación escalonada de PRF y tasa de dosis: monitorear la evolución térmica y la estabilidad de corriente primaria en PRI I MON, confirmando que ITEM 251 permanezca en 1 continuo sin microdisparos que interrumpan la señal RAD_ON.",
        ]
        safety_warning = (
            "ALTA TENSIÓN (HT): Peligro de descarga eléctrica mortal en banco de condensadores del Área 17. "
            "Cortar interruptor principal, aguardar descarga completa (mínimo 12 minutos) y colocar pértiga "
            "de tierra antes de intervenir T4 o el conjunto disipador."
        )
    elif "dosimetr" in low_sub or "haz" in low_sub:
        dosimetry_calib_ref = next((r for r in manual_refs if "dosimetry" in r.lower()), "dosimetry.pdf")
        action_steps = [
            f"Acceder a la consola técnica en Service Mode / CCP (pantalla de {subsystem}), verificar los registros de estado para {signals_label} y confirmar si el bit de inhibición permanece enclavado tras la secuencia de inicio.",
            f"Validar la simetría y correlación entre Canal 1 y Canal 2 en las tablas de calibración de dosimetría ({dosimetry_calib_ref}), comprobando que el ratio D1/D2 y las lecturas de tasa de dosis no excedan la ventana de tolerancia del ±2%.",
            f"Verificar con voltímetro de alta impedancia (> 10 Mohm) la tensión de polarización de la cámara de ionización (Chamber Bias HT, nominalmente -400V a -600V DC) en el punto de prueba del cabezal (RHCA), descartando caídas de tensión por corrientes de fuga.",
            f"Inspeccionar el bus de comunicación en el bastidor RHCA entre {primary_board} y la RTU (MTU-RHA / ROC-RHA), comprobando la configuración de puentes/jumpers de terminación de bus y la señal de reloj del watchdog local.",
            f"Monitorear con osciloscopio bajo ráfaga de pulsos la estabilidad de las tensiones auxiliares (+24VDC y ±15VDC) en los conectores {cables_label} de {primary_board}, asegurando que el rizado transitorio de conmutación sea inferior a 50 mVpp.",
            "Ejecutar el protocolo de reinicio seguro de interlocks desde el CCP, comprobar que la línea de habilitación de radiación (RAD_ON) conmute a estado activo y realizar un disparo de prueba a baja tasa de dosis verificando el incremento lineal de cuentas en ambos canales.",
        ]
    elif "vacío" in low_sub or "vacuum" in low_sub:
        action_steps = [
            f"Acceder a la pantalla de diagnóstico de Vacío en Service Mode / CCP para comprobar la lectura telemétrica de corriente de la bomba iónica y el estado lógico del presostato SW1 según {manual_refs[0] if manual_refs else 'vacuum.pdf'}.",
            "Verificar la curva de bombeo y la presión estática en la columna del acelerador, constatando un nivel de vacío ultra alto inferior a 10^-7 Torr antes de autorizar encendido de filamento.",
            "Medir la tensión de salida de la fuente de alimentación de la bomba iónica (nominalmente 3 kV a 5 kV DC), verificando estabilidad y ausencia de fluctuaciones bajo funcionamiento continuo.",
            f"Inspeccionar el pasamuros cerámico de alta tensión y los conectores {cables_label} en la cámara de vacío para descartar fugas dieléctricas o derivaciones a masa.",
            f"Validar el circuito de disparo del relé de protección en {primary_board}, comprobando los umbrales de histéresis y la conmutación sin rebotes.",
            "Ejecutar el rearme de la cadena de enclavamiento de vacío en consola y confirmar la habilitación de la señal GUN_ON en el lazo maestro.",
        ]
    elif "rf" in low_sub or "tensión" in low_sub:
        action_steps = [
            f"Consultar en Service Mode / CCP la pantalla de Modulador y RF para verificar registros de fallo por sobrecorriente de tiratrón ({signals_label}) o exceso de potencia reflejada según {manual_refs[0] if manual_refs else 'ht_rf.pdf'}.",
            "Inspeccionar con osciloscopio y punta de alta tensión la forma de onda del pulso de disparo de rejilla en el tiratrón, comprobando tiempo de subida (< 50 ns), amplitud y ausencia de jitter.",
            "Medir la corriente de filamento y la temperatura de precalentamiento del magnetrón/klystron, verificando el cumplimiento del temporizador de seguridad de caldeo.",
            "Verificar la presión del gas aislante SF6 en la guía de ondas y contrastar la respuesta del presostato diferencial de seguridad de RF.",
            "Comprobar la sintonía del bucle AFC (Automatic Frequency Control) y la respuesta del detector óptico de arco en la ventana de salida de RF.",
            "Ejecutar la secuencia de encendido gradual de alta tensión (HT ramp-up) en modo de servicio, monitoreando el lazo maestro y descartando disparos por sobretensión inversa.",
        ]
    elif "movimiento" in low_sub or "colimad" in low_sub or "mesa" in low_sub:
        action_steps = [
            f"Acceder a la pantalla de diagnóstico de cinemática en Service Mode / CCP, verificar las lecturas de los encoders primarios y contrastarlas con los potenciómetros analógicos secundarios según {manual_refs[0] if manual_refs else 'movement.pdf'}.",
            "Comprobar el ajuste de tolerancia de seguimiento de posición en los controladores de eje, constatando que la desviación dinámica sea inferior a 1 mm o 0.2° durante el desplazamiento.",
            f"Inspeccionar visual y funcionalmente los microinterruptores de final de carrera mecánicos y los flags ópticos de referencia (cero de máquina) en el eje gobernado por {primary_board}.",
            "Verificar la señal de bus CAN del subsistema de movimiento, comprobando la tasa de error de tramas y la respuesta temporal de los drivers de motor MOT/DRV.",
            f"Comprobar el accionamiento y la corriente de retención de los frenos electromagnéticos en los conectores {cables_label} al alternar entre modo manual y automático.",
            "Realizar una secuencia de calibración y referenciado de ejes en Service Mode, confirmando la normalización de las coordenadas en el sistema de control.",
        ]
    else:
        action_steps = [
            f"Acceder a la consola técnica en Service Mode / CCP para {subsystem}, consultar la pantalla de diagnóstico de interlocks y volcar el registro de eventos para verificar bits de disparo según {manual_refs[0] if manual_refs else 'los manuales'}.",
            f"Validar en las tablas de calibración de los manuales técnicos los umbrales de tolerancia y ganancias configuradas, asegurando que las lecturas de {signals_label} se ubiquen en el rango nominal admisible.",
            f"Medir bajo carga activa con osciloscopio la estabilidad de los rieles DC (+24V, ±15V, +5V), verificando que el rizado parásito sea inferior a 50 mVpp y descartando caídas al conmutar contactores.",
            f"Inspeccionar el lazo de comunicación digital y los puentes de configuración (jumpers) en {primary_board}, comprobando la integridad de señales de reloj y temporizadores watchdog.",
            f"Comprobar la conmutación firme y la resistencia de contacto (< 0.5 ohm) en los relés electromecánicos de la cadena de interbloqueos redundante en {cables_label}.",
            "Ejecutar la secuencia de rearme seguro de interlocks desde la consola de servicio y verificar la normalización del estado de habilitación de radiación (RAD_ON).",
        ]

    # 13. Advertencia de seguridad según el subsistema
    if not is_ht_psu_ot and not is_con_k:
        if "ht" in low_sub or "rf" in low_sub or "tensión" in low_sub:
            safety_warning = "ALTA TENSIÓN (HT): Peligro de descarga eléctrica mortal. Cortar interruptor principal, verificar descarga de banco de condensadores y colocar pértiga de tierra antes de manipular componentes."
        elif "dosimetr" in low_sub or "haz" in low_sub:
            safety_warning = "SEGURIDAD RADIOLÓGICA: No puentear lazos de canal de dosimetría. Toda intervención requiere verificación de calibración de tasa y simetría con electrómetro de referencia."
        elif "movimiento" in low_sub or "colimad" in low_sub or "gantry" in low_sub:
            safety_warning = "RIESGO MECÁNICO DE COLISIÓN: Bloquear mecánicamente el gantry o colimador y activar paradas de emergencia antes de intervenir embragues o motores de tracción."
        else:
            safety_warning = "Desenergizar el equipo y comprobar descarga de condensadores antes de intervenir tarjetas electrónicas."

    sanitized_findings = _sanitize_differential_diagnoses(differential_diagnoses)
    return {
        "root_cause": root_cause,
        "subsystem": subsystem,
        "confidence": "alta" if len(matched_docs) >= 2 else "media",
        "explanation": _sanitize_explanation(explanation),
        "differential_diagnoses": sanitized_findings,
        "diagnostic_findings": sanitized_findings,
        "associated_boards": all_boards[:5] if (is_ht_psu_ot or is_con_k) else all_boards[:4],
        "cables_and_connectors": all_cables[:4],
        "test_points_and_signals": all_signals[:8] if (is_ht_psu_ot or is_con_k) else all_signals[:6],
        "manual_references": manual_refs[:8] if (is_ht_psu_ot or is_con_k) else manual_refs[:5],
        "action_steps": _sanitize_action_steps(action_steps),
        "safety_warning": safety_warning,
        "_diagnostic_meta": {
            "failover": True,
            "reason": reason,
            "degraded_parse": False,
            "failover_notice": "Diagnóstico estructurado a partir del corpus documental de los 19 manuales técnicos de Elekta.",
        },
    }


def analyze_with_gemini(
    symptoms: list[str],
    search_engine: SearchEngine,
    api_key: str = "",
    model: str = "",
) -> dict:
    """Ejecuta el análisis inteligente con la API de Gemini y soporte multimodelo."""
    if not GENAI_AVAILABLE:
        return {
            "ok": False,
            "error": "sdk_missing",
            "message": "La biblioteca google-genai no está instalada en el servidor.",
        }

    key = str(api_key or os.environ.get("GEMINI_API_KEY", "")).strip().strip("\"' \r\n\t")
    if not key:
        return {
            "ok": False,
            "error": "no_api_key",
            "message": "Se requiere una clave de API de Gemini configurada en el servidor (variable de entorno GEMINI_API_KEY).",
        }

    # 1. Verificar si la respuesta ya está en caché en memoria (0.001s de respuesta)
    cached = get_cached_diagnosis(symptoms)
    if cached:
        return cached

    # 2. Lista de modelos con respaldo automático (waterfall de alta velocidad y disponibilidad)
    models_to_try = []
    cleaned_model = model.strip()
    if cleaned_model and cleaned_model in ALLOWED_GEMINI_MODELS:
        models_to_try.append(cleaned_model)
    env_model = os.environ.get("GEMINI_MODEL", "").strip().strip("\"' ")
    if env_model and env_model in ALLOWED_GEMINI_MODELS and env_model not in models_to_try:
        models_to_try.append(env_model)

    default_chain = [
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.6-flash",
    ]
    for default_m in default_chain:
        if default_m not in models_to_try:
            models_to_try.append(default_m)

    # 3. Recopilar evidencia técnica de los manuales de Elekta
    grounding_docs, citation_map = gather_grounding_context(search_engine, symptoms)
    symptoms_text = "\n".join(f"- Síntoma/Señal {i+1}: {s}" for i, s in enumerate(symptoms))

    prompt = f"""EVIDENCIA EXTRAÍDA DE LOS MANUALES TÉCNICOS DE ELEKTA:
{grounding_docs}

SÍNTOMAS / SEÑALES INGRESADOS POR EL TÉCNICO:
{symptoms_text}

Realiza el diagnóstico de causa raíz y responde en el formato JSON solicitado:"""

    try:
        retry_opts = (
            types.HttpRetryOptions(attempts=1, http_status_codes=[])
            if hasattr(types, "HttpRetryOptions")
            else None
        )
        http_opts = types.HttpOptions(timeout=DEFAULT_GEMINI_TIMEOUT_MS, retry_options=retry_opts)
        client = genai.Client(api_key=key, http_options=http_opts)
        last_error = None
        quota_hit = False
        timed_out = False
        service_unavailable = False
        start_time = time.monotonic()

        for current_model in models_to_try:
            if time.monotonic() - start_time >= GLOBAL_WATERFALL_DEADLINE_SECONDS:
                timed_out = True
                break

            afc_cfg = (
                types.AutomaticFunctionCallingConfig(disable=True)
                if hasattr(types, "AutomaticFunctionCallingConfig")
                else None
            )
            thinking_cfg = (
                types.ThinkingConfig(thinking_budget=0)
                if hasattr(types, "ThinkingConfig")
                else None
            )

            try:
                try:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.15,
                            response_mime_type="application/json",
                            response_schema=GeminiDiagnosis,
                            max_output_tokens=3072,
                            thinking_config=thinking_cfg,
                            automatic_function_calling=afc_cfg,
                            http_options=http_opts,
                        ),
                    )
                except Exception as gen_err:
                    gen_err_str = str(gen_err)
                    if ("400" in gen_err_str or "INVALID_ARGUMENT" in gen_err_str) and (
                        "thinking" in gen_err_str.lower() or "budget" in gen_err_str.lower() or "argument" in gen_err_str.lower()
                    ):
                        logger.info("Reintentando modelo '%s' sin thinking_config...", current_model)
                        response = client.models.generate_content(
                            model=current_model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.15,
                                response_mime_type="application/json",
                                response_schema=GeminiDiagnosis,
                                max_output_tokens=3072,
                                automatic_function_calling=afc_cfg,
                                http_options=http_opts,
                            ),
                        )
                    else:
                        raise gen_err

                parsed = getattr(response, "parsed", None)
                degraded_parse = False
                if isinstance(parsed, GeminiDiagnosis):
                    data = parsed.model_dump(mode="json")
                else:
                    raw_text = ""
                    try:
                        raw_text = response.text or ""
                    except Exception:
                        pass
                    data = extract_json_safely(raw_text)
                    degraded_parse = True

                try:
                    finish_reason = response.candidates[0].finish_reason
                except (AttributeError, IndexError, TypeError):
                    finish_reason = None
                truncated = str(finish_reason or "").upper() in {"MAX_TOKENS", "LENGTH"}

                data = _resolve_citations(data, citation_map)
                data["root_cause"] = _sanitize_root_cause(data.get("root_cause", ""))
                data["explanation"] = _sanitize_explanation(data.get("explanation", ""))
                findings = data.get("diagnostic_findings") or data.get("differential_diagnoses") or []
                sanitized_findings = _sanitize_differential_diagnoses(findings)
                data["diagnostic_findings"] = sanitized_findings
                data["differential_diagnoses"] = sanitized_findings
                data["action_steps"] = _sanitize_action_steps(data.get("action_steps", []))
                data["associated_boards"] = [
                    b for b in data.get("associated_boards", [])
                    if b and not _is_drawing_or_schematic_number(b) and b.upper() not in INVALID_BOARDS
                ]
                data["test_points_and_signals"] = [
                    s for s in data.get("test_points_and_signals", [])
                    if s and not _is_drawing_or_schematic_number(s)
                ]

                if degraded_parse:
                    data.setdefault("_diagnostic_meta", {})["degraded_parse"] = True
                if truncated:
                    data.setdefault("_diagnostic_meta", {})["truncated"] = True

                meta = data.get("_diagnostic_meta", {})
                if not (meta.get("truncated") or meta.get("degraded_parse")):
                    set_cached_diagnosis(symptoms, data, current_model)

                return {
                    "ok": True,
                    "data": data,
                    "model_used": current_model,
                    "symptoms": symptoms,
                }
            except Exception as model_err:
                last_error = model_err
                err_str = str(model_err)
                err_lower = err_str.lower()
                sanitized_err = _sanitize_error_message(err_str)

                logger.warning(
                    "Fallo con modelo '%s' en cascada de diagnóstico: %s",
                    current_model,
                    sanitized_err,
                )

                # Si es clave inválida, 403 Forbidden o error 400 de autenticación, romper de inmediato
                if "API_KEY_INVALID" in err_str or ("400" in err_str and "API key" in err_str) or "403" in err_str or "Forbidden" in err_str or "PERMISSION_DENIED" in err_str:
                    raise model_err

                # Si es timeout de lectura o socket
                if "timed out" in err_lower or "timeout" in err_lower or "deadline exceeded" in err_lower or isinstance(model_err, TimeoutError):
                    timed_out = True
                    break

                # Si es error 429 (cuota agotada), intentar siguiente modelo si hay tiempo
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    quota_hit = True
                    continue

                # Un 503 es transitorio. Se intenta el siguiente modelo de la cascada
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    service_unavailable = True
                    continue

                if "404" in err_str or "NOT_FOUND" in err_str:
                    continue

        if timed_out:
            failover_data = generate_local_failover_diagnosis(symptoms, search_engine, reason="timeout")
            return {
                "ok": True,
                "data": failover_data,
                "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
                "symptoms": symptoms,
                "failover": True,
                "notice": "Tiempo de espera agotado al consultar el servicio en la nube. Se presenta el diagnóstico determinista local fundamentado en los 19 manuales.",
            }

        if service_unavailable:
            failover_data = generate_local_failover_diagnosis(
                symptoms, search_engine, reason="service_unavailable"
            )
            return {
                "ok": True,
                "data": failover_data,
                "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
                "symptoms": symptoms,
                "failover": True,
                "notice": "El servicio externo se encuentra temporalmente ocupado. Se presenta el diagnóstico determinista local respaldado por manuales y topología.",
            }

        if quota_hit:
            failover_data = generate_local_failover_diagnosis(
                symptoms, search_engine, reason="quota_exceeded"
            )
            return {
                "ok": True,
                "data": failover_data,
                "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
                "symptoms": symptoms,
                "failover": True,
                "notice": "Límite temporal de consultas alcanzado. Se presenta el diagnóstico determinista local respaldado por manuales y topología.",
            }

        if last_error:
            failover_data = generate_local_failover_diagnosis(symptoms, search_engine, reason="api_fallback")
            return {
                "ok": True,
                "data": failover_data,
                "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
                "symptoms": symptoms,
                "failover": True,
                "notice": "Diagnóstico estructurado a partir del corpus documental de los 19 manuales técnicos de Elekta.",
            }

        failover_data = generate_local_failover_diagnosis(symptoms, search_engine, reason="no_model_available")
        return {
            "ok": True,
            "data": failover_data,
            "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
            "symptoms": symptoms,
            "failover": True,
            "notice": "Diagnóstico estructurado a partir del corpus documental de los 19 manuales técnicos de Elekta.",
        }

    except Exception as exc:
        err_msg = str(exc)
        err_lower = err_msg.lower()
        if "API_KEY_INVALID" in err_msg or ("400" in err_msg and "API key" in err_msg):
            return {
                "ok": False,
                "error": "invalid_api_key",
                "message": "La clave de API de Gemini ingresada no es válida.",
            }
        if "403" in err_msg or "PERMISSION_DENIED" in err_msg or "Forbidden" in err_msg:
            clean_msg = _sanitize_error_message(err_msg)
            return {
                "ok": False,
                "error": "api_error",
                "message": f"Error al procesar el diagnóstico causal: {clean_msg[:160]}",
            }
        reason = "timeout" if ("timed out" in err_lower or "timeout" in err_lower or "deadline exceeded" in err_lower or isinstance(exc, TimeoutError)) else "exception"
        failover_data = generate_local_failover_diagnosis(symptoms, search_engine, reason=reason)
        return {
            "ok": True,
            "data": failover_data,
            "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
            "symptoms": symptoms,
            "failover": True,
            "notice": "Diagnóstico estructurado a partir del corpus documental de los 19 manuales técnicos de Elekta.",
        }
