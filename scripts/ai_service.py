"""SOLVI - Servicio de Inteligencia Artificial para Diagnóstico Biomédico.

Utiliza el SDK oficial google-genai con modelos Gemini 2.5 Flash para:
1. Comprender síntomas en lenguaje natural y descriptivo.
2. Realizar razonamiento causal profundo basado en la arquitectura de Aceleradores Elekta.
3. Deducir la causa raíz, subsistema, tarjetas (PCBs), y procedimientos de inspección paso a paso.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from search_engine import SearchEngine

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


SYSTEM_INSTRUCTION = """Eres un Especialista Senior de Servicio Técnico e Ingeniería Biomédica en Aceleradores Lineales de Radioterapia Elekta (modelos Synergy, Versa HD, Precise, con subsistemas Agility MLC, XVI CBCT, iViewGT, Sistemas de Vacío, RF/Klystron, Generador de Dosis, Control de Gantry, Colimador y Mesa).

Tu misión es analizar uno o varios síntomas ingresados por el técnico (que pueden ser códigos de error, números de interlocks, o descripciones de fallas en lenguaje natural) y determinar la CAUSA RAÍZ más probable basándote en la arquitectura técnica de Elekta.

Debes responder SIEMPRE en formato JSON válido con la siguiente estructura exacta:
{
  "root_cause": "Nombre conciso de la causa raíz y componente/tarjeta principal (ej: Tarjeta AO8 en Área 16 / Falla en sensor de posición de Gantry)",
  "subsystem": "Nombre del subsistema de la máquina (ej: Beam Centering / Gantry Motion / Vacuum Control)",
  "confidence": "alta" | "media" | "baja",
  "explanation": "Explicación técnica detallada y comprensible de por qué se relacionan estos síntomas, qué fenómeno físico o eléctrico ocurrió y por qué ese componente es el factor común.",
  "associated_boards": ["Lista de tarjetas PCB, módulos o áreas vinculadas (ej: AO8, PCB 16V, Área 16)"],
  "manual_references": ["Lista de manuales de Elekta donde se documenta esto (ej: diagrams.pdf, beam physics.pdf)"],
  "action_steps": [
    "Paso 1 de verificación práctica para el técnico con valores o componentes específicos",
    "Paso 2...",
    "Paso 3..."
  ],
  "safety_warning": "Advertencia de seguridad crítica si aplica (alta tensión HT, corte de haz, riesgo mecánico) o vacío si no aplica."
}

Reglas estrictas:
1. Si el usuario ingresa descripciones en lenguaje natural (ej: 'gantry se frena al girar en sentido horario y hay sobrecorriente'), deduce el fenómeno físico (driver de motor, puente H, encoder, relé térmico) y tradúcelo a la arquitectura Elekta.
2. Si se proporciona contexto de los manuales, prioriza las tarjetas (PCBs), señales (ITEMs), áreas y conectores mencionados en ellos.
3. Sé preciso, profesional y directo. No inventes códigos inexistentes si no tienes certeza.
4. Responde ÚNICAMENTE el objeto JSON sin bloques de código markdown ni texto adicional.
"""


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
        words = [w for w in cleaned.split() if len(w) >= 3 and w not in stop_words]
        keywords.extend(words)
    return list(dict.fromkeys(keywords))[:12]


def gather_grounding_context(search_engine: SearchEngine, symptoms: list[str], max_pages: int = 6) -> str:
    """Busca en los 19 manuales los fragmentos técnicos más relevantes para fundamentar la respuesta."""
    contexts = []
    seen_pages = set()

    # 1. Intentar diagnóstico relacional con el motor
    diag_res = search_engine.diagnose_symptoms(symptoms, limit=max_pages)
    for r in diag_res.get("results", []):
        key = (r["manual"], r["page"])
        if key not in seen_pages:
            seen_pages.add(key)
            comp = r.get("associated_component", "")
            comp_str = f" [Componente: {comp}]" if comp else ""
            contexts.append(f"--- Manual: {r['manual']} (Página {r['page']}){comp_str} ---\n{r['context']}")

    # 2. Si faltan contextos, buscar por palabras clave individuales
    if len(contexts) < 3:
        kws = extract_keywords_for_retrieval(symptoms)
        for kw in kws:
            s_res = search_engine.search(kw, limit=3)
            for r in s_res.get("results", []):
                key = (r["manual"], r["page"])
                if key not in seen_pages and len(contexts) < max_pages:
                    seen_pages.add(key)
                    contexts.append(f"--- Manual: {r['manual']} (Página {r['page']}) ---\n{r['context']}")

    return "\n\n".join(contexts) if contexts else "No se encontraron páginas directas con los términos exactos."


def analyze_with_gemini(
    symptoms: list[str],
    search_engine: SearchEngine,
    api_key: str = "",
    model: str = "",
) -> dict:
    """Ejecuta el análisis inteligente con la API de Gemini."""
    if not GENAI_AVAILABLE:
        return {
            "ok": False,
            "error": "sdk_missing",
            "message": "La biblioteca google-genai no está instalada en el servidor.",
        }

    key = api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return {
            "ok": False,
            "error": "no_api_key",
            "message": "Se requiere una clave de API de Gemini. Configúrala como variable GEMINI_API_KEY o ingrésala en la app.",
        }

    # Modelo configurable: por defecto gemini-2.5-flash, o gemini-2.5-pro / gemini-3.7-flash
    active_model = model.strip() or os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"

    # Recopilar evidencia técnica de los 19 manuales
    grounding_docs = gather_grounding_context(search_engine, symptoms)

    symptoms_text = "\n".join(f"- Síntoma/Señal {i+1}: {s}" for i, s in enumerate(symptoms))

    prompt = f"""EVIDENCIA EXTRAÍDA DE LOS MANUALES TÉCNICOS DE ELEKTA:
{grounding_docs}

SÍNTOMAS / SEÑALES INGRESADOS POR EL TÉCNICO:
{symptoms_text}

Realiza el diagnóstico de causa raíz y responde en el formato JSON solicitado:"""

    try:
        client = genai.Client(api_key=key)

        response = client.models.generate_content(
            model=active_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text or ""
        # Limpieza de posibles delimitadores markdown
        cleaned_json = re.sub(r"^```json\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json).strip()

        data = json.loads(cleaned_json)
        return {
            "ok": True,
            "data": data,
            "symptoms": symptoms,
        }

    except Exception as exc:
        err_msg = str(exc)
        if "API_KEY_INVALID" in err_msg or "400" in err_msg and "API key" in err_msg:
            return {
                "ok": False,
                "error": "invalid_api_key",
                "message": "La clave de API de Gemini ingresada no es válida.",
            }
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            return {
                "ok": False,
                "error": "quota_exceeded",
                "message": "Límite de consultas de Gemini alcanzado. Intenta de nuevo en unos momentos.",
            }
        return {
            "ok": False,
            "error": "api_error",
            "message": f"Error al consultar Gemini API: {err_msg[:160]}",
        }
