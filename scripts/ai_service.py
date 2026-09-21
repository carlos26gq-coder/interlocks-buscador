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

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from search_engine import SearchEngine

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# NOTA: pydantic ya es una dependencia transitiva de google-genai (la usa
# internamente para sus propios tipos), por lo que no agrega una dependencia
# nueva al proyecto. Se usa aquí para definir el schema de salida estructurada
# que Gemini debe respetar (ver GeminiDiagnosis más abajo).


SYSTEM_INSTRUCTION = """Eres un Especialista Senior de Servicio Técnico e Ingeniería Biomédica en Aceleradores Lineales de Radioterapia Elekta (modelos Synergy, Versa HD, Precise, con subsistemas Agility MLC, XVI CBCT, iViewGT, Sistemas de Vacío, RF Magnetron, Generador de Dosis, Control de Gantry, Colimador y Mesa).

Tu misión es analizar uno o varios síntomas ingresados por el técnico (códigos de error, números de interlocks, o descripciones de fallas en lenguaje natural) y deducir la CAUSA RAÍZ técnica exacta y contextualizada, junto con DIAGNÓSTICOS DIFERENCIALES e hipótesis alternativas fundamentadas en la evidencia de los 19 manuales técnicos de Elekta suministrados.

Debes razonar dinámicamente sobre la evidencia: NO utilices plantillas fijas, ni frases genéricas prefabricadas, ni clasificaciones artificiales repetitivas. NO te limites a verificaciones elementales de voltajes con multímetro o inspecciones superficiales de conectores. Investiga a fondo las múltiples dimensiones posibles de la falla:
- Desviación o drift de calibración en canales y sensores (offset, ganancia, simetría, dosimetría).
- Desajustes o atascos mecánicos (holguras en engranajes, embragues, frenos, tensión de correas, flags ópticos de colimador/MLC o gantry).
- Condiciones de vacío y fluidos (presión en bomba iónica, microfugas, interruptores de presión, caudal y temperatura del agua de refrigeración, presión de gas dieléctrico SF6).
- Comunicaciones digitales y buses de control (timeouts o colisiones en bus CAN, Arcnet, enlaces serie fibra óptica, registros de error en CCP/Service Mode).
- Desalineación o degradación de sensores (potenciómetros multivuelta, encoders absolutos/incrementales, detectores de fin de carrera, microinterruptores).
- Cronometría y pulsos (sincronismo de disparos PRF, modulación de tiratrón/magnetrón, tiempos de subida de pulso, retardos en lazos de seguridad).
- Cadena de interbloqueos y relés (fatiga de contactos de relé, lazo de seguridad maestro, cadenas de interlock redundantes).
- Estabilidad de rieles de alimentación bajo carga (rizado excesivo, caídas de tensión dinámica).

Debes responder SIEMPRE en formato JSON válido con la siguiente estructura:
{
  "root_cause": "Identificación precisa del componente, tarjeta PCB, sensor, actuador o circuito causante específico para los síntomas evaluados (ej: Disparo en lazo de terminación forzada del Canal 1 de dosimetría / Fallo en driver de motor de colimador PCB 16N en Área 16 / Desconexión en línea de interbloqueo HT)",
  "subsystem": "Subsistema técnico específico de Elekta (ej: Beam Steering & Dosimetry / Vacuum & Waveguide / Gantry Motion & Drive / MLC Agility Control / High Tension & RF)",
  "confidence": "alta" | "media" | "baja",
  "explanation": "Razonamiento técnico genuino y detallado sobre la falla específica: explica el mecanismo físico o electrónico documentado en los manuales, la función de las señales o componentes identificados, y cómo interactúan las anomalías reportadas para provocar el disparo de interbloqueo o inhibición de haz.",
  "differential_diagnoses": [
    {
      "hypothesis": "Hipótesis diagnóstica alternativa concreta (ej: Deriva en la calibración del detector de simetría de haz / Fuga dieléctrica incipiente o desgasificación en la guía de ondas / Desalineación del flag óptico del carruaje MLC / Pérdida de paquetes en el enlace de bus CAN del procesador de colimador)",
      "subsystem": "Subsistema relacionado",
      "likelihood": "alta" | "media" | "baja",
      "rationale": "Justificación técnica concreta explicando por qué esta hipótesis es plausible según los manuales, cómo reproduce los síntomas y qué la diferencia de la causa raíz principal."
    }
  ],
  "associated_boards": ["Lista de nombres exactos de tarjetas PCB, módulos o racks vinculados SIN prefijos como 'Tarjeta:' (ej: ['PCB 12D', 'DIE-RHA', 'PCB 12F'])"],
  "cables_and_connectors": ["Lista de conectores, arneses y terminales asociados SIN prefijos como 'Conector:' (ej: ['PL1', 'PL2', 'SK12'])"],
  "test_points_and_signals": ["Lista de señales, ITEMs o puntos de prueba citados explícitamente SIN prefijos como 'Señal:' (ej: ['ITEM 475', 'ITEM 471', 'D1 FORCE TERM', 'TP1'])"],
  "citation_ids": ["Lista de identificadores de evidencia EXACTAMENTE como aparecen entre corchetes en el bloque de evidencia (ej: 'C1', 'C3'). Incluye únicamente los bloques que realmente sustentan tu diagnóstico."],
  "action_steps": [
    "Pasos de verificación e intervención técnica específicos, variados y aplicables: incluye validaciones en software (Service Mode / CCP), comprobación de registros de diagnóstico, ajustes de calibración específicos, inspecciones mecánicas o de alineación de sensores, mediciones de presión/temperatura o pruebas de forma de onda, además de verificaciones eléctricas donde proceda."
  ],
  "safety_warning": "Advertencia de seguridad crítica si aplica (alta tensión HT, corte de haz de radiación, riesgo mecánico) o vacío si no aplica."
}

Reglas estrictas de precisión e ingeniería biomédica:
1. Razonamiento dinámico genuino: No uses esquemas rígidos ni repitas plantillas idénticas entre consultas diferentes. Los pasos de acción y la explicación deben derivarse directamente de la evidencia técnica concreta de los manuales.
2. Rigor con códigos y señales: Cada señal o ITEM numérico es único y específico (ej: ITEM 474 es diferente de ITEM 409 o ITEM 332). No mezcles ni confundas señales parecidas.
3. Nivel de detalle técnico alto: Evita respuestas genéricas o superficiales. Especifica nombres de PCBs, áreas de montaje, buses de comunicación o lazos de control según se describa en los manuales.
4. Fundamentación en los manuales: Basa cada deducción directamente en los bloques de evidencia suministrados.
5. Si el usuario ingresa descripciones en lenguaje natural, deduce el fenómeno físico y tradúcelo a la arquitectura Elekta.
6. Responde ÚNICAMENTE el objeto JSON sin bloques de código markdown ni texto adicional.
7. NUNCA inventes nombres de manual o números de página. En 'citation_ids' cita SOLO las etiquetas [C1], [C2], etc.
8. PROHIBICIÓN ABSOLUTA: CERO menciones de 'IA', 'AI' o 'Inteligencia Artificial' en cualquier campo.
9. PROHIBICIÓN DE TEXTO INTRODUCTORIO GENÉRICO: NUNCA inicies el campo 'explanation' con 'Contexto Operativo: En la arquitectura del acelerador lineal Elekta, las señales analizadas forman parte integral del Sistema General de Interbloqueos y Seguridad (Elekta LINAC).' ni frases prefabricadas similares. Comienza de inmediato con el análisis físico y electrónico concreto de los síntomas reportados.
10. PROHIBICIÓN DE PLANTILLAS DE PROBABILIDAD FIJA: NUNCA utilices en 'action_steps' etiquetas fijas como 'Paso 1 (Probabilidad 1 - ...)', 'Probabilidad 1', 'Probabilidad 2', etc. Los pasos de acción deben ser procedimientos directos, concretos y fundamentados en los manuales sin esquemas preenlatados.
11. PRIORIDAD EQUILIBRADA DE TODOS LOS MANUALES: Los 19 manuales técnicos de Elekta (dosimetry, corrective, planned, technical, vacuum, ht_rf, movement, power_supplies, ccp, communications, covers, accessory, catalogue, table, xvi, iview, item part, beam physics, diagrams) tienen la misma prioridad. El manual de diagramas (diagrams.pdf) suministra únicamente esquemas eléctricos y cableado; las deducciones de causa raíz, mecanismos físicos, tolerancias y procedimientos de intervención deben fundamentarse primordialmente en los manuales de mantenimiento correctivo, calibración, comunicaciones, física y procedimientos técnicos.
12. DIAGNÓSTICOS DIFERENCIALES DIVERSOS Y MULTIFACÉTICOS: Genera obligatoriamente entre 2 y 4 diagnósticos diferenciales con distintas perspectivas (electrónica/lógica, calibración/deriva de sensor, mecánica/sensores ópticos, vacío/fluidos o comunicaciones/bus RTU) para brindar un espectro completo de análisis al ingeniero en campo. Cada diagnóstico diferencial debe contener una hipótesis técnica concreta, subsistema, probabilidad ('alta', 'media' o 'baja') y justificación exhaustiva basada en los manuales.
13. PROHIBICIÓN DE PASOS PREENLATADOS DE MULTÍMETRO O CONECTORES: En 'action_steps', NUNCA repitas pasos genéricos idénticos como 'Medir con multímetro u osciloscopio los niveles lógicos...', 'Inspeccionar visual y térmicamente...', 'Comprobar la continuidad eléctrica, apriete de terminales y ausencia de bornes flojos...'. Cada paso debe ser un procedimiento técnico concreto derivado de los manuales: lectura de registros de interlock en Service Mode / CCP, tablas de calibración de umbrales, inspección de puentes (jumper links) o interruptores específicos, comprobación de estabilidad de rieles bajo carga, y procedimiento de reinicio seguro.
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


class DifferentialDiagnosis(BaseModel):
    hypothesis: str = Field(description="Descripción técnica de la causa raíz alternativa o hipótesis diagnóstica")
    subsystem: str = Field(default="", description="Subsistema de Elekta relacionado (ej: Dosimetría, Vacío, RF, Movimiento, Control/CCP, Fuentes)")
    likelihood: str = Field(default="media", description="Probabilidad estimada: alta, media, baja")
    rationale: str = Field(description="Mecanismo físico, desajuste, drift o justificación técnica según los manuales")


class GeminiDiagnosis(BaseModel):
    """Schema de salida estructurada exigido a Gemini vía response_schema.

    IMPORTANTE: 'citation_ids' reemplaza al antiguo 'manual_references' de
    cara al modelo. El modelo solo puede citar los IDs [C1], [C2]... que
    nosotros mismos generamos en gather_grounding_context() a partir de datos
    reales de search_engine.py. La conversión final de esos IDs a texto legible
    ('diagrams.pdf (Página 211)') la hace este servicio, no el modelo — así
    el número de página nunca depende de lo que Gemini decida escribir.
    """

    root_cause: str
    subsystem: str
    confidence: Confidence
    explanation: str
    differential_diagnoses: list[DifferentialDiagnosis] = Field(default_factory=list)
    associated_boards: list[str] = Field(default_factory=list)
    cables_and_connectors: list[str] = Field(default_factory=list)
    test_points_and_signals: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)
    safety_warning: str = ""


# Caché en memoria para acelerar consultas repetidas y soportar múltiples usuarios concurrentes
# Formato: cache_key -> (timestamp, data_dict, model_used)
_DIAG_CACHE: OrderedDict[tuple[str, ...], tuple[float, dict, str]] = OrderedDict()
_CACHE_TTL_SECONDS = 3600  # 1 hora de persistencia en memoria
_MAX_CACHE_ENTRIES = 300
_CACHE_LOCK = threading.Lock()


# Latencia controlada para evitar bloqueos HTTP 504 / 500 en Render y Gunicorn:
# 25 s por intento individual; 42 s de tiempo acumulado global antes de pasar al motor local.
DEFAULT_GEMINI_TIMEOUT_SECONDS: float = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "25.0"))
DEFAULT_GEMINI_TIMEOUT_MS: int = int(
    DEFAULT_GEMINI_TIMEOUT_SECONDS if DEFAULT_GEMINI_TIMEOUT_SECONDS >= 1000 else DEFAULT_GEMINI_TIMEOUT_SECONDS * 1000
)
DEFAULT_GEMINI_TIMEOUT: float = DEFAULT_GEMINI_TIMEOUT_MS / 1000.0
GLOBAL_WATERFALL_DEADLINE_SECONDS: float = float(os.environ.get("GEMINI_WATERFALL_DEADLINE", "42.0"))


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


def _sanitize_explanation(text: str) -> str:
    """Elimina introducciones genéricas y frases prefabricadas no deseadas del análisis."""
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
    return cleaned.strip()


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


def _sanitize_differential_diagnoses(diffs: object) -> list[dict[str, str]]:
    """Valida, limpia y normaliza la lista de diagnósticos diferenciales técnicos."""
    if not isinstance(diffs, list):
        return []
    cleaned_diffs: list[dict[str, str]] = []
    for item in diffs:
        if isinstance(item, dict):
            hypo = str(item.get("hypothesis", "")).strip()
            sub = str(item.get("subsystem", "")).strip()
            like = str(item.get("likelihood", "media")).strip().lower()
            if like not in {"alta", "media", "baja"}:
                like = "media"
            rat = str(item.get("rationale", "")).strip()
            if hypo:
                cleaned_diffs.append({
                    "hypothesis": hypo,
                    "subsystem": sub,
                    "likelihood": like,
                    "rationale": rat,
                })
        elif isinstance(item, str) and item.strip():
            cleaned_diffs.append({
                "hypothesis": item.strip(),
                "subsystem": "",
                "likelihood": "media",
                "rationale": "",
            })
    return cleaned_diffs


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
    max_per_manual = 2  # Capped at 2 to ensure at least 8 distinct manuals can be represented

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

    # 2. Búsqueda directa por cada síntoma individual a través de todos los manuales
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

    # 3. Búsqueda cruzada de las tarjetas identificadas en manuales de subsistemas y mantenimiento
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

    if any(k in sym_blob for k in ["dosimetr", "die-rha", "item 475", "item 471", "i475", "i471", "d1 force", "d1 reset", "chamber bias", "dose"]):
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
            if b not in all_boards and len(all_boards) < 5 and b not in INVALID_BOARDS:
                all_boards.append(b)
        for c in comp.get("cables", []):
            if c not in all_cables and len(all_cables) < 5:
                all_cables.append(c)
        for s in comp.get("items", []):
            if s not in all_signals and s not in all_boards and len(all_signals) < 6:
                all_signals.append(s)
        for tp in comp.get("tps", []):
            if tp not in all_tps and len(all_tps) < 5:
                all_tps.append(tp)

    # Si all_signals aún no tiene suficientes, incorporar puntos de prueba
    for tp in all_tps:
        if tp not in all_signals and len(all_signals) < 6:
            all_signals.append(tp)

    # 9. Formulación de Causa Raíz técnica precisa y no preenlatada
    primary_board = all_boards[0] if all_boards else "tarjetas de control del subsistema"
    signals_label = ", ".join(all_signals[:2]) if all_signals else "líneas de supervisión"
    if all_boards and all_signals:
        root_cause = f"Disparo en lazo de seguridad de {subsystem}, comprometiendo {primary_board} y señales {signals_label}"
    elif all_boards:
        root_cause = f"Condición de interbloqueo en {subsystem} asociada a {primary_board}"
    elif all_signals:
        root_cause = f"Falla de estado lógico o interrupción en líneas {signals_label} de {subsystem}"
    else:
        root_cause = f"Apertura en bucle de seguridad de interlocks en {subsystem}"

    # 10. Formulación de Explicación técnica y contextual dinámica
    secondary_boards = (", " + ", ".join(all_boards[1:3])) if len(all_boards) > 1 else ""
    signals_text = ", ".join(all_signals[:3]) if all_signals else ", ".join(symptoms[:2])
    manuals_text = ", ".join(manual_refs[:4]) if manual_refs else "el catálogo técnico de 19 manuales Elekta"

    explanation = (
        f"Análisis documental de {subsystem}: Las señales analizadas ({signals_text}) convergen en la supervisión "
        f"operativa de {primary_board}{secondary_boards}. La documentación técnica contrastada en {manuals_text} "
        f"evidencia que una discrepancia en el lazo de interbloqueo maestro, una deriva en los umbrales de calibración "
        f"o una pérdida de sincronismo en los registros de supervisión inhibe de manera preventiva la emisión de haz (RAD_ON) "
        f"o la habilitación de alta tensión (HT). El restablecimiento operativo requiere inspeccionar los bits de disparo en "
        f"Service Mode / CCP, contrastar las tolerancias en los manuales de mantenimiento y calibración, y verificar la integridad "
        f"dinámica de las señales y rieles de alimentación antes de rearmar la cadena de seguridad."
    )

    # 11. Diagnósticos diferenciales e hipótesis técnicas multifacéticas por dominio
    differential_diagnoses: list[dict[str, str]] = []

    if "dosimetr" in low_sub or "haz" in low_sub:
        differential_diagnoses.append({
            "hypothesis": f"Disparo de interbloqueo por condición de terminación forzada o fallo de reset en {primary_board}",
            "subsystem": subsystem,
            "likelihood": "alta",
            "rationale": f"La traza técnica en {manuals_text} vincula las líneas {signals_label} con el enclavamiento de dosis del cabezal (RHCA). Cualquier discrepancia de estado o fallo en la confirmación de puesta a cero mantiene activo el lazo de corte de haz.",
        })
        differential_diagnoses.append({
            "hypothesis": "Deriva en tensión de polarización de cámara de ionización (Chamber Bias HT) o ganancia V-F",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Una fluctuación o caída de la tensión de polarización (-400V a -600V DC) en la cámara de ionización altera la recolección de carga y genera lecturas anómalas de tasa de dosis, superando los umbrales de tolerancia programados.",
        })
        differential_diagnoses.append({
            "hypothesis": "Fallo de comunicación en bus ARCNET/CAN o ciclo de reinicio de watchdog en la RTU del cabezal (RHCA)",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "likelihood": "media",
            "rationale": f"La tarjeta {primary_board} transmite su estado digital al procesador central mediante la RTU del cabezal. Microcortes o desfase en los puentes de configuración o en la señal de reloj del watchdog local provocan un timeout en la trama de supervisión.",
        })
        differential_diagnoses.append({
            "hypothesis": "Rizado dinámico parásito o caída transitoria en rieles de alimentación continua (+24VDC, ±15VDC)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "likelihood": "baja",
            "rationale": "Filtrado insuficiente en las fuentes de alimentación auxiliares bajo demanda de carga que induce transiciones lógicas espurias en las entradas de interbloqueo.",
        })
    elif "vacío" in low_sub or "vacuum" in low_sub:
        differential_diagnoses.append({
            "hypothesis": "Apertura del presostato SW1 por degradación de vacío o corriente elevada en bomba iónica",
            "subsystem": subsystem,
            "likelihood": "alta",
            "rationale": f"Presión residual superior a 10^-7 Torr que dispara el presostato de protección SW1 documentado en {manuals_text} e inhibe la orden de modulación de alta tensión.",
        })
        differential_diagnoses.append({
            "hypothesis": "Fuga dieléctrica superficial en el aislador cerámico del pasamuros de alto vacío",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Contaminación o microfisuras en el aislador cerámico que generan corrientes de fuga parásitas interpretadas como pérdida de vacío.",
        })
        differential_diagnoses.append({
            "hypothesis": "Inestabilidad en la fuente de polarización de alta tensión de la bomba de iones (3 kV - 5 kV)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "likelihood": "media",
            "rationale": "Fluctuaciones en el convertidor de alta tensión de la bomba que alteran la proporcionalidad entre corriente telemétrica y presión real.",
        })
        differential_diagnoses.append({
            "hypothesis": "Resistencia de contacto en los terminales del lazo de seguridad de vacío",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "likelihood": "baja",
            "rationale": "Oxidación o fatiga mecánica en los contactos auxiliares del presostato que abren la cadena de seguridad general.",
        })
    elif "rf" in low_sub or "tensión" in low_sub:
        differential_diagnoses.append({
            "hypothesis": "Dispersión temporal o deformación en el pulso de disparo de rejilla del tiratrón",
            "subsystem": subsystem,
            "likelihood": "alta",
            "rationale": f"Jitter o amplitud insuficiente en los pulsos PRF según {manuals_text} que provoca descargas erráticas del modulador y activa el lazo de sobrecorriente.",
        })
        differential_diagnoses.append({
            "hypothesis": "Deriva en corriente de filamento de magnetrón o desajuste de sintonía en bucle AFC",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Variación térmica o desgaste de cátodo que desplaza la impedancia dinámica del generador de microondas y eleva la potencia reflejada hacia el circulador.",
        })
        differential_diagnoses.append({
            "hypothesis": "Microdescarga o conmutación del detector óptico de arco en la guía de ondas",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Degradación del dieléctrico de gas SF6 o destellos en la ventana cerámica de RF que activan de inmediato la inhibición de pulsos de modulación.",
        })
        differential_diagnoses.append({
            "hypothesis": "Ruido electromagnético acoplado durante la descarga de la línea formadora de pulsos (PFN)",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "likelihood": "baja",
            "rationale": "Retorno de masa imperfecto o apantallamiento deteriorado que inyecta transitorios en las líneas lógicas de interbloqueo.",
        })
    elif "movimiento" in low_sub or "colimad" in low_sub or "mesa" in low_sub:
        differential_diagnoses.append({
            "hypothesis": "Discrepancia de seguimiento entre potenciómetro analógico y encoder digital de posición",
            "subsystem": subsystem,
            "likelihood": "alta",
            "rationale": f"Desfase angular o lineal documentado en {manuals_text} que excede la ventana de tolerancia admisible, provocando bloqueo preventivo de eje.",
        })
        differential_diagnoses.append({
            "hypothesis": "Fricción mecánica, holgura en correas de transmisión o retardo en frenos electromagnéticos",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Resistencia dinámica que incrementa la demanda de corriente en los servocontroladores antes de alcanzar la coordenada deseada.",
        })
        differential_diagnoses.append({
            "hypothesis": "Falsa activación o microdesalineación en sensores de final de carrera o touchguard",
            "subsystem": subsystem,
            "likelihood": "media",
            "rationale": "Apertura intermitente de microinterruptores de colisión o bordes sensibles durante el recorrido del eje.",
        })
        differential_diagnoses.append({
            "hypothesis": "Retardo de paquetes o saturación de cola en el bus CAN de posicionamiento",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "likelihood": "baja",
            "rationale": "Latencia en la confirmación de coordenadas de posición hacia el procesador central dentro del tiempo de ciclo.",
        })
    else:
        differential_diagnoses.append({
            "hypothesis": f"Disparo de lazo de seguridad maestro en {primary_board}",
            "subsystem": subsystem,
            "likelihood": "alta",
            "rationale": f"La traza técnica en {manuals_text} vincula las señales {signals_label} con la apertura de la cadena de enclavamientos del acelerador lineal.",
        })
        differential_diagnoses.append({
            "hypothesis": "Deriva en tensiones de referencia o rizado dinámico excesivo en fuentes auxiliares (+24V, ±15V)",
            "subsystem": "Distribución de Potencia y Fuentes DC (Power Supplies & Contactors)",
            "likelihood": "media",
            "rationale": "Pérdida de regulación bajo demanda de carga que induce transiciones espurias en compuertas lógicas y comparadores de umbral.",
        })
        differential_diagnoses.append({
            "hypothesis": "Retardo de sincronización o timeout en el bus de supervisión digital (CAN/ARCNET)",
            "subsystem": "Procesador Central y Comunicaciones (CCP & Safety Bus)",
            "likelihood": "media",
            "rationale": "Pérdida de tramas de estado que impide al procesador central confirmar el cierre coordinado de los circuitos de seguridad.",
        })
        differential_diagnoses.append({
            "hypothesis": "Aumento de resistencia de contacto en bornes de relés de seguridad del lazo redundante",
            "subsystem": "Interconexión y Lazo de Seguridad Maestro",
            "likelihood": "baja",
            "rationale": "Envejecimiento de los contactos electromecánicos en la cadena redundante de enclavamientos maestros.",
        })

    # 12. Procedimiento de Inspección Paso a Paso específico, profundo y libre de plantillas rígidas
    action_steps: list[str] = []
    cables_label = ", ".join(all_cables[:3]) if all_cables else "conectores del subsistema"

    if "dosimetr" in low_sub or "haz" in low_sub:
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

    # 12. Advertencia de seguridad según el subsistema
    if "ht" in low_sub or "rf" in low_sub or "tensión" in low_sub:
        safety_warning = "ALTA TENSIÓN (HT): Peligro de descarga eléctrica mortal. Cortar interruptor principal, verificar descarga de banco de condensadores y colocar pértiga de tierra antes de manipular componentes."
    elif "dosimetr" in low_sub or "haz" in low_sub:
        safety_warning = "SEGURIDAD RADIOLÓGICA: No puentear lazos de canal de dosimetría. Toda intervención requiere verificación de calibración de tasa y simetría con electrómetro de referencia."
    elif "movimiento" in low_sub or "colimad" in low_sub or "gantry" in low_sub:
        safety_warning = "RIESGO MECÁNICO DE COLISIÓN: Bloquear mecánicamente el gantry o colimador y activar paradas de emergencia antes de intervenir embragues o motores de tracción."
    else:
        safety_warning = "Desenergizar el equipo y comprobar descarga de condensadores antes de intervenir tarjetas electrónicas."

    return {
        "root_cause": root_cause,
        "subsystem": subsystem,
        "confidence": "alta" if len(matched_docs) >= 2 else "media",
        "explanation": _sanitize_explanation(explanation),
        "differential_diagnoses": _sanitize_differential_diagnoses(differential_diagnoses),
        "associated_boards": all_boards[:4],
        "cables_and_connectors": all_cables[:4],
        "test_points_and_signals": all_signals[:6],
        "manual_references": manual_refs[:5],
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
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
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
                    raw_text = response.text or ""
                    data = extract_json_safely(raw_text)
                    degraded_parse = True

                try:
                    finish_reason = response.candidates[0].finish_reason
                except (AttributeError, IndexError, TypeError):
                    finish_reason = None
                truncated = str(finish_reason or "").upper() in {"MAX_TOKENS", "LENGTH"}

                data = _resolve_citations(data, citation_map)
                data["explanation"] = _sanitize_explanation(data.get("explanation", ""))
                data["action_steps"] = _sanitize_action_steps(data.get("action_steps", []))
                data["differential_diagnoses"] = _sanitize_differential_diagnoses(data.get("differential_diagnoses", []))

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
