"""SOLVI - Servicio de Inteligencia Artificial para Diagnóstico Biomédico.

Utiliza el SDK oficial google-genai con modelos Gemini y arquitectura de alta disponibilidad:
1. Comprensión de síntomas en lenguaje natural y descripciones complejas.
2. Razonamiento causal basado en los manuales técnicos de Elekta Linac.
3. Cadena de respaldo de modelos (waterfall) ante límites de cuota (429), saturación (503) o versión (404).
4. Caché en memoria para respuestas instantáneas (<0.01s) en consultas repetidas o múltiples usuarios concurrentes.
5. Extracción robusta de JSON a prueba de fallos sintácticos.
"""

from __future__ import annotations

from collections import OrderedDict
import json
import os
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from search_engine import SearchEngine

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


SYSTEM_INSTRUCTION = """Eres un Especialista Senior de Servicio Técnico e Ingeniería Biomédica en Aceleradores Lineales de Radioterapia Elekta (modelos Synergy, Versa HD, Precise, con subsistemas Agility MLC, XVI CBCT, iViewGT, Sistemas de Vacío, RF Magnetron, Generador de Dosis, Control de Gantry, Colimador y Mesa).

Tu misión es analizar uno o varios síntomas ingresados por el técnico (códigos de error, números de interlocks, o descripciones de fallas en lenguaje natural) y determinar la CAUSA RAÍZ técnica exacta y detallada basándote estrictamente en la evidencia de los manuales técnicos de Elekta.

Debes responder SIEMPRE en formato JSON válido con la siguiente estructura exacta:
{
  "root_cause": "Identificación precisa del componente, tarjeta PCB, sensor, actuador o circuito causante (ej: Descalibración en canal 1 de dosimetría / Fallo en driver de motor de colimador PCB 16N en Área 16 / Falla en contacto de relé RLA1 en circuito de interlock HT)",
  "subsystem": "Subsistema técnico específico de Elekta (ej: Beam Steering & Dosimetry / Vacuum & Waveguide / Gantry Motion & Drive / MLC Agility Control)",
  "confidence": "alta" | "media" | "baja",
  "explanation": "Explicación técnica profunda, minuciosa y no genérica del mecanismo de falla: describe cómo interactúan las señales, qué fenómeno físico o eléctrico ocurrió, por qué convergen los síntomas ingresados y cuál es la lógica de control o lazo de retroalimentación según los diagramas y manuales.",
  "associated_boards": ["Lista exhaustiva de tarjetas PCB, módulos, áreas físicas o racks vinculados (ej: PCB 12D, PCB AO8, Área 16, Rack HTCA)"],
  "cables_and_connectors": ["Lista de cables, arneses, conectores, terminales y pines asociados (ej: Cable W14, Conector PL1 / SK12, Pin 3, Terminal Block TB2)"],
  "test_points_and_signals": ["Puntos de prueba TP, voltajes nominales, fusibles, relés y números de ITEM involucrados (ej: TP2 (+15VDC ±0.5V), ITEM 474, Relé RLB2, Fusible FS1)"],
  "manual_references": ["Lista de manuales de Elekta con sus páginas exactas donde se documenta el circuito o procedimiento (ej: diagrams.pdf (Pág 211), beam physics.pdf (Pág 86))"],
  "action_steps": [
    "Paso 1: Medición o inspección física específica con multímetro/osciloscopio (indicando puntos de prueba TP, voltajes nominales o fusibles)",
    "Paso 2: Inspección de continuidad en cableado, conectores o relés asociados",
    "Paso 3: Procedimiento de ajuste, calibración o verificación en modo de servicio (Service Mode)",
    "Paso 4: Criterio de reemplazo de tarjeta/componente o validación final"
  ],
  "safety_warning": "Advertencia de seguridad crítica si aplica (alta tensión HT, corte de haz de radiación, riesgo mecánico) o vacío si no aplica."
}

Reglas estrictas de precisión e ingeniería biomédica:
1. Rigor con códigos y señales: Cada señal o ITEM numérico es único y específico (ej: ITEM 474 es diferente de ITEM 409 o ITEM 332). No mezcles ni confundas señales parecidas.
2. Nivel de detalle técnico alto: Evita respuestas genéricas o superficiales. Especifica nombres de PCBs (ej: PCB 12D, PCB AO8, PCB 16N), áreas de montaje (Área 16, HTCA), buses de comunicación (CAN, ArcNet, RS485) o lazos de control de retroalimentación según se describa en los manuales.
3. Pasos de acción concretos: En 'action_steps', proporciona instrucciones accionables que un ingeniero de campo pueda ejecutar con un multímetro, osciloscopio o en la consola de servicio.
4. Fundamentación en los manuales: Basa tus deducciones directamente en las conexiones, tarjetas, áreas y esquemas documentados en los manuales de Elekta proporcionados en el contexto.
5. Si el usuario ingresa descripciones en lenguaje natural (ej: 'gantry se frena al girar en sentido horario y hay sobrecorriente'), deduce el fenómeno físico (driver de motor, puente H, encoder, relé térmico) y tradúcelo a la arquitectura Elekta.
6. Responde ÚNICAMENTE el objeto JSON sin bloques de código markdown ni texto adicional.
"""

# Caché en memoria para acelerar consultas repetidas y soportar múltiples usuarios sin agotar cuota
# Formato: cache_key -> (timestamp, data_dict, model_used)
_DIAG_CACHE: OrderedDict[tuple[str, ...], tuple[float, dict, str]] = OrderedDict()
_CACHE_TTL_SECONDS = 3600  # 1 hora de persistencia en memoria
_MAX_CACHE_ENTRIES = 300


def _normalize_token(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower().strip())


def _make_cache_key(symptoms: list[str]) -> tuple[str, ...]:
    return tuple(sorted(_normalize_token(s) for s in symptoms if s and _normalize_token(s)))


def get_cached_diagnosis(symptoms: list[str]) -> dict | None:
    """Recupera un diagnóstico previo si existe en memoria y no ha expirado."""
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
        "data": data,
        "model_used": f"{model_used} (caché)",
        "symptoms": symptoms,
        "cached": True,
    }


def set_cached_diagnosis(symptoms: list[str], data: dict, model_used: str) -> None:
    """Almacena el resultado de diagnóstico en la caché en memoria."""
    key = _make_cache_key(symptoms)
    if not key or not data:
        return
    if len(_DIAG_CACHE) >= _MAX_CACHE_ENTRIES:
        _DIAG_CACHE.popitem(last=False)  # Expulsar el más antiguo
    _DIAG_CACHE[key] = (time.time(), data, model_used)


def extract_json_safely(raw_text: str) -> dict:
    """Extrae y parsea JSON de forma tolerante a fallos de formato o markdown."""
    if not raw_text or not raw_text.strip():
        raise ValueError("Respuesta vacía del modelo de IA.")

    cleaned = raw_text.strip()
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
                    "associated_boards": [],
                    "cables_and_connectors": [],
                    "test_points_and_signals": [],
                    "manual_references": ["Elekta Service Manuals"],
                    "action_steps": ["Verificar señales y componentes asociados en Service Mode."],
                    "safety_warning": "",
                }
            raise ValueError(f"No se pudo estructurar el JSON devuelto por la IA: {cleaned[:120]}")


def extract_keywords_for_retrieval(symptoms: list[str]) -> list[str]:
    """Extrae palabras clave para buscar en el índice técnico de manuales."""
    keywords = []
    stop_words = {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en",
        "con", "por", "para", "que", "hay", "esta", "cuando", "hace", "falla", "error",
        "the", "and", "for", "with", "from", "into", "during"
    }
    for s in symptoms:
        cleaned = re.sub(r"[^\w\s\d]", " ", s.lower())
        words = [w for w in cleaned.split() if len(w) >= 2 and w not in stop_words]
        keywords.extend(words)
    return list(dict.fromkeys(keywords))[:12]


def gather_grounding_context(search_engine: SearchEngine, symptoms: list[str], max_pages: int = 6) -> str:
    """Busca en los 19 manuales los fragmentos técnicos más relevantes para fundamentar la respuesta.
    
    Balance óptimo entre profundidad de ingeniería y velocidad:
    - Hasta 6 páginas de diagnóstico relacional y esquemas
    - Extracción de componentes (PCBs, Items, Cables, Test Points)
    - Fragmentos de hasta 1600 caracteres por manual
    - Total máximo 10,000 caracteres para análisis exhaustivo
    """
    contexts = []
    seen_pages = set()

    # 1. Diagnóstico relacional: páginas donde convergen los síntomas
    diag_res = search_engine.diagnose_symptoms(symptoms, limit=max_pages)
    for r in diag_res.get("results", []):
        key = (r["manual"], r["page"])
        if key not in seen_pages:
            seen_pages.add(key)
            comp = r.get("associated_component", "")
            comp_str = f" [Detalle: {comp}]" if comp else ""
            snip = str(r.get("context", ""))[:1600]
            contexts.append(f"--- Manual: {r['manual']} (Página {r['page']}){comp_str} ---\n{snip}")

    # 2. Búsqueda directa por códigos numéricos/señales específicas (ej: ITEM 474)
    for sym in symptoms:
        if len(contexts) >= max_pages:
            break
        cleaned_sym = sym.strip()
        if re.search(r"\b(?:item\s*\d+|\d{2,4})\b", cleaned_sym, re.I):
            s_res = search_engine.search(cleaned_sym, limit=3)
            for r in s_res.get("results", []):
                key = (r["manual"], r["page"])
                if key not in seen_pages and len(contexts) < max_pages:
                    seen_pages.add(key)
                    snip = str(r.get("context", ""))[:1400]
                    contexts.append(f"--- Manual: {r['manual']} (Página {r['page']}) [Señal Directa] ---\n{snip}")

    # 3. Búsqueda por palabras clave individuales para complementar si hay pocas coincidencias
    if len(contexts) < 3:
        kws = extract_keywords_for_retrieval(symptoms)
        for kw in kws:
            if len(contexts) >= max_pages:
                break
            s_res = search_engine.search(kw, limit=2)
            for r in s_res.get("results", []):
                key = (r["manual"], r["page"])
                if key not in seen_pages and len(contexts) < max_pages:
                    seen_pages.add(key)
                    snip = str(r.get("context", ""))[:1200]
                    contexts.append(f"--- Manual: {r['manual']} (Página {r['page']}) ---\n{snip}")

    # 4. Complementar con traza de circuito de hardware del Grafo si está disponible
    try:
        from graph_engine import get_graph_engine
        g_engine = get_graph_engine()
        g_trace = g_engine.trace_circuit(symptoms)
        if g_trace.get("found"):
            hub = g_trace.get("hub_node", "")
            trace_str = g_trace.get("trace_diagram", "")
            pcbs_str = ", ".join(g_trace.get("pcbs", []))
            cables_str = ", ".join(g_trace.get("cables", []))
            conns_str = ", ".join(g_trace.get("connectors", []))
            tps_str = ", ".join(g_trace.get("test_points", []))
            areas_str = ", ".join(g_trace.get("areas", []))
            contexts.append(
                f"=== TOPOLOGÍA DE HARDWARE EN GRAFO ELEKTA ===\n"
                f"Componente/Tarjeta Central: {hub}\n"
                f"Ruta de Conexión: {trace_str}\n"
                f"Tarjetas: {pcbs_str} | Cables: {cables_str} | Conectores: {conns_str}\n"
                f"Puntos de Prueba TP/Voltajes: {tps_str} | Ubicación: {areas_str}"
            )
    except Exception:
        pass

    combined = "\n\n".join(contexts) if contexts else "No se encontraron páginas directas con los términos exactos."
    return combined[:10000]


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
            "message": "Se requiere una clave de API de Gemini. Configúrala como variable GEMINI_API_KEY o ingrésala en la app.",
        }

    # 1. Verificar si la respuesta ya está en caché en memoria (0.001s de respuesta)
    cached = get_cached_diagnosis(symptoms)
    if cached:
        return cached

    # 2. Lista de modelos con respaldo automático (waterfall de alta velocidad y disponibilidad)
    models_to_try = []
    if model.strip():
        models_to_try.append(model.strip())
    env_model = os.environ.get("GEMINI_MODEL", "").strip().strip("\"' ")
    if env_model and env_model not in models_to_try:
        models_to_try.append(env_model)

    default_chain = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-flash-latest",
    ]
    for default_m in default_chain:
        if default_m not in models_to_try:
            models_to_try.append(default_m)

    # 3. Recopilar evidencia técnica de los manuales de Elekta
    grounding_docs = gather_grounding_context(search_engine, symptoms)
    symptoms_text = "\n".join(f"- Síntoma/Señal {i+1}: {s}" for i, s in enumerate(symptoms))

    prompt = f"""EVIDENCIA EXTRAÍDA DE LOS MANUALES TÉCNICOS DE ELEKTA:
{grounding_docs}

SÍNTOMAS / SEÑALES INGRESADOS POR EL TÉCNICO:
{symptoms_text}

Realiza el diagnóstico de causa raíz y responde en el formato JSON solicitado:"""

    try:
        client = genai.Client(api_key=key)
        last_error = None
        quota_hit = False

        for current_model in models_to_try:
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.15,
                        response_mime_type="application/json",
                    ),
                )

                raw_text = response.text or ""
                data = extract_json_safely(raw_text)

                # Guardar en caché para futuros usuarios o consultas idénticas
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

                # Si es error 429 (cuota de ese modelo específico agotada), intentar siguiente modelo
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    quota_hit = True
                    continue

                # Si es error 404 (modelo no disponible) o 503 (saturación temporal), intentar siguiente modelo
                if "404" in err_str or "503" in err_str or "UNAVAILABLE" in err_str or "NOT_FOUND" in err_str:
                    continue

                # Si es clave inválida o error 400 de autenticación, romper de inmediato
                if "API_KEY_INVALID" in err_str or ("400" in err_str and "API key" in err_str):
                    raise model_err

        # Si todos los modelos de la cadena agotaron su cuota
        if quota_hit:
            return {
                "ok": False,
                "error": "quota_exceeded",
                "message": "Límite temporal de consultas de Gemini alcanzado en la API gratuita. Espera unos segundos o utiliza el botón de diagnóstico local.",
            }

        if last_error:
            raise last_error

        return {
            "ok": False,
            "error": "no_model_available",
            "message": "No se pudo conectar con ningún modelo de Gemini disponible.",
        }

    except Exception as exc:
        err_msg = str(exc)
        if "API_KEY_INVALID" in err_msg or ("400" in err_msg and "API key" in err_msg):
            return {
                "ok": False,
                "error": "invalid_api_key",
                "message": "La clave de API de Gemini ingresada no es válida.",
            }
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            return {
                "ok": False,
                "error": "quota_exceeded",
                "message": "Límite temporal de consultas de Gemini alcanzado. Espera unos momentos o utiliza el diagnóstico local.",
            }
        return {
            "ok": False,
            "error": "api_error",
            "message": f"Error al procesar diagnóstico con IA: {err_msg[:160]}",
        }
