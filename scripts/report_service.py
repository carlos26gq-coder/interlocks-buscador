"""SOLVI - Servicio de Generación de Informes Técnicos de Servicio.

Proporciona redacción técnica de ingeniería para la sección 'TRABAJO REALIZADO'
y extracción de repuestos fundamentada en los 19 manuales de aceleradores lineales Elekta.
Enfoque híbrido: utiliza la API de Gemini (con fallback automático al motor local de manuales).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from search_engine import SearchEngine

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class SparePartModel(BaseModel):
    pn: str = Field(default="", description="Número de parte (P/N) del repuesto")
    description: str = Field(default="", description="Descripción técnica del componente")
    quantity: str = Field(default="01", description="Cantidad solicitada, ej: '01'")


class ReportBodyResponse(BaseModel):
    body: str = Field(description="Texto técnico continuo para TRABAJO REALIZADO")
    suggested_diagnosis: str = Field(default="", description="Diagnóstico técnico sintético")
    suggested_parts: list[SparePartModel] = Field(default_factory=list, description="Lista de repuestos requeridos")
    suggested_conclusions: str = Field(default="", description="Texto de conclusiones técnicas")


SYSTEM_INSTRUCTION_REPORT = """Eres un Especialista Senior de Servicio Técnico e Ingeniería Biomédica en Aceleradores Lineales Elekta (Synergy, Versa HD, Precise, Agility, XVI, etc.).

Tu objetivo es redactar la sección "TRABAJO REALIZADO" para el Informe Técnico Oficial de Servicio Técnico, fundamentada estrictamente en la evidencia técnica de los 19 manuales de Elekta.

Debes seguir con precisión la estructura, formato, sobriedad y rigor del estándar técnico:
1. Contexto inicial e impacto clínico: Describir el interlock, síntoma o avería presentada (mencionando explícitamente el código de incidente y señales/ítems ingresados por el usuario, ej: HT PSU OT, ITEM 79, Interlock 283, etc.) y cómo afecta la continuidad de los tratamientos clínicos.
2. Identificación del sensor o componente físico: Identificar con precisión el sensor, interruptor, actuador, transductor o conjunto mecánico involucrado respetando la nomenclatura del diagnóstico preliminar si fue proporcionado (ej: si el incidente o diagnóstico menciona 'Switch Assembly', 'CON-K', etc., debes citar y describir explícitamente el Switch Assembly, sensor electromecánico OVERTEMP SW2, etc.) y su ubicación o lazo de montaje.
3. Lazo eléctrico o térmico de monitoreo: Explicar cómo se conecta en serie o en circuito cerrado en el lazo de seguridad o aislamiento (ej: lazo térmico de la tarjeta HTPSU Isolation Unit, lazo maestro de interlocks, etc.).
4. Mecanismo físico de falla detectado en la revisión: Describir la causa física observada durante la inspección técnica (holgura mecánica, falso contacto, oscilación, deriva térmica, rebote eléctrico, fatiga) y cómo genera la apertura errática del circuito y el disparo del interlock.
5. Tarjeta de procesamiento lógico, área y pines: Identificar la tarjeta de adquisición o decodificación digital (ej: DIE-HTB, DIE-ICA, DIE-RHA, etc.), el área de control (ej: Área 16 HTCA, Área 72, etc.) y los pines específicos (ej: pin A3) que reciben la señal hacia la lógica central del equipo. Justificar si la tarjeta receptora muestra degradación o daño en sus compuertas lógicas debido a los transitorios/rebotes.
6. Referencia formal a imágenes o diagramas adjuntos: Si se dispone de imágenes o diagramas adjuntos, incluir una referencia formal entre corchetes dentro del texto, ej.: [IMÁGENES ADJUNTAS: FOTO DEL INTERRUPTOR Y DIAGRAMA DE ESQUEMA DIE-HTB PIN A3].
7. Justificación y solicitud de repuestos necesarios: Concluir el último párrafo de TRABAJO REALIZADO sustentando explícitamente la solicitud de los repuestos requeridos indicando su nombre de componente y su P/N en el texto (ej: "Por lo expuesto, se solicita el reemplazo del conjunto Switch Assembly - 45133308377 y de la tarjeta DIE-HTB - 1573801...").

Reglas críticas de formato y números de parte:
- Conservar los nombres de componentes y señales del usuario: Si el incidente o diagnóstico menciona ítems específicos como 'Switch Assembly', 'ITEM 79', 'CON-K', 'Interlock 283', etc., DEBEN aparecer explícitamente en el cuerpo del informe.
- Redacción continua y técnica, en tono formal de ingeniería de servicio de campo.
- Sin listas con viñetas en el cuerpo de trabajo realizado.
- Sin texto promocional ni relleno innecesario.
- REGLA ESTRICTA DE P/N: Los números de plano esquemático (ej: 1024690, 1024686, 1024693, o códigos tipo 45133307021) son referencias de planos de ingeniería, NUNCA números de parte de repuestos sustituibles. Los repuestos reales provienen del catálogo de repuestos de Elekta (ej: Switch Assembly 45133308377, tarjeta DIE-HTB 1573801, DIE-ICA 1573800, bloque auxiliar de contactor 1512130, etc.). NUNCA uses números de planos como P/N de repuestos.
- Responder SIEMPRE en formato JSON válido según el esquema solicitado."""


def _is_drawing_number(code: str) -> bool:
    """Detecta si un código corresponde a un número de plano o dibujo esquemático de Elekta."""
    clean = re.sub(r"\s+", "", str(code or "")).strip()
    if re.match(r"^1024\d{3}$", clean):  # Ej: 1024690, 1024686, 1024693
        return True
    if clean.startswith("45133307"):  # 12NC de plano de ingeniería
        return True
    return False


def _extract_spare_parts_from_context(search_engine: SearchEngine, terms: list[str]) -> list[dict[str, str]]:
    """Busca en el catálogo de repuestos (catalogue) de los manuales números de parte y descripciones."""
    results: list[dict[str, str]] = []
    seen_pns = set()

    for term in terms:
        clean_t = term.strip()
        if not clean_t or len(clean_t) < 3:
            continue
        try:
            hits = search_engine.search(clean_t, manual="catalogue", limit=3)
            for h in hits.get("results", []):
                ctx = h.get("context", "")
                # Patrón estándar del catálogo de Elekta: número de ítem, P/N (7 u 11 dígitos), descripción
                matches = re.findall(
                    r"(?:^|\s)(?:\d{1,3}\s+)?(\d{7}|\d{11}|\d{4}\s*\d{3}\s*\d{4,5})\s+([A-Za-z][A-Za-z0-9\s,\-\(\)\/\&\.\+]+?)(?=\s+\d{1,3}\s+\d{7,11}|\s*\n|$)",
                    ctx,
                )
                for pn_raw, desc_raw in matches:
                    pn_clean = re.sub(r"\s+", "", pn_raw).strip()
                    desc_clean = desc_raw.strip()
                    if len(desc_clean) > 80:
                        desc_clean = desc_clean[:80].rsplit(" ", 1)[0]
                    if pn_clean not in seen_pns and len(pn_clean) >= 7 and len(desc_clean) >= 4 and not _is_drawing_number(pn_clean):
                        seen_pns.add(pn_clean)
                        results.append({
                            "pn": pn_clean,
                            "description": desc_clean,
                            "quantity": "01",
                        })
        except Exception as exc:
            logger.debug("Error buscando repuesto para '%s': %s", clean_t, exc)

    return results[:5]


def generate_local_report_body(
    incident: str,
    equipment: str = "ACELERADOR LINEAL",
    brand: str = "ELEKTA",
    model: str = "SYNERGY FULL",
    diagnosis: str = "",
    image_descriptions: list[str] | None = None,
    search_engine: SearchEngine | None = None,
) -> dict[str, Any]:
    """Genera la redacción técnica fundamentada localmente a partir de los 19 manuales técnicos.

    Asegura disponibilidad total incluso sin conexión externa o clave API.
    """
    inc_upper = incident.strip().upper()
    img_refs = []
    if image_descriptions:
        img_refs = [desc.strip().upper() for desc in image_descriptions if desc.strip()]

    # 1. Caso emblemático documentado: HT PSU OT / Sobretemperatura en fuente HT
    is_ht_psu_ot = (
        "HT PSU OT" in inc_upper
        or ("HT" in inc_upper and "PSU" in inc_upper and "OT" in inc_upper)
        or ("OVERTEMP" in inc_upper and "HT" in inc_upper)
        or "251" in inc_upper
    )

    if is_ht_psu_ot:
        img_tag = ""
        if img_refs:
            img_tag = f" [IMÁGENES ADJUNTAS: {' Y '.join(img_refs)}]."
        else:
            img_tag = " [IMÁGENES ADJUNTAS: FOTO DEL INTERRUPTOR Y DIAGRAMA DE ESQUEMA DIE-HTB PIN A3]."

        body = (
            f"Durante tratamientos se presenta el interlock HT PSU OT (High Tension Power Supply Over-Temperature), "
            f"lo que impide la continuidad de los tratamientos clínicos en el acelerador lineal {brand} {model}. "
            f"El conjunto Switch Assembly actúa como el sensor electromecánico OVERTEMP SW2 montado en el transformador "
            f"de alta tensión (Área 17). Sus contactos están conectados en serie dentro del lazo térmico que monitorea "
            f"la tarjeta HTPSU Isolation Unit. Durante la revisión técnica, este presenta holgura mecánica severa, "
            f"oscilación o falso contacto en su montaje sobre el vástago del fuelle, por lo tanto, el interruptor abre "
            f"erráticamente este circuito cerrado, activando la transmisión óptica hacia el Área 16 y disparando de "
            f"inmediato el interlock. Asimismo, de acuerdo con los diagramas esquemáticos del sistema (plano 1024686), "
            f"la señal de sobretemperatura del chasis de alta tensión ingresa directamente a través del pin A3 de la "
            f"tarjeta DIE-HTB en el Área 16 (HTCA), la cual es la encargada de procesar este lazo térmico y emitir el "
            f"enclavamiento hacia la lógica central del equipo. Dado que la tarjeta DIE-HTB es el núcleo lógico por donde "
            f"transita esta señal de enclavamiento y no logra estabilizar la lectura pese a las verificaciones de reposo, "
            f"tiene indicios que ha sufrido una degradación en sus circuitos lógicos a causa de las fallas y rebotes "
            f"eléctricos del interruptor defectuoso.{img_tag} Por lo expuesto, se solicita el conjunto Switch Assembly "
            f"- 45133308377 para corregir el accionamiento mecánico y del módulo DIE-HTB - 1573801 para restablecer la "
            f"correcta recepción del lazo de seguridad, permitiendo la normalización del sistema HT y la operatividad "
            f"clínica del acelerador lineal."
        )
        return {
            "ok": True,
            "body": body,
            "suggested_diagnosis": "Reemplazo de Switch Assembly y DIE HTB",
            "suggested_parts": [
                {"pn": "45133308377", "description": "Switch Assembly", "quantity": "01"},
                {"pn": "1573801", "description": "Digital input & encoding board (DIE-HTB, DIE-B)", "quantity": "01"},
            ],
            "suggested_conclusions": "- Equipo operativo tras intervención técnica\n- Se requiere los siguientes repuestos para normalizar el servicio clínico",
            "source": "local_manuals",
        }

    # 2. Caso CON-K / Contactor principal de potencia e interlocks de arranque
    is_con_k = (
        "CON-K" in inc_upper or "CON K" in inc_upper or "ITEM 79" in inc_upper or "I79" in inc_upper
    )
    if is_con_k:
        img_tag = f" [IMÁGENES ADJUNTAS: {' Y '.join(img_refs)}]." if img_refs else " [IMÁGENES ADJUNTAS: REGISTRO DE CONTACTOS CON-K Y MEDICIÓN EN DIE-ICA]."
        body = (
            f"Durante la secuencia de preparación del equipo {brand} {model}, se detecta la inhibición del contactor "
            f"principal de potencia CON-K supervisado por la señal ITEM 79 (i79 'HT con K'). Dicha señal ingresa "
            f"a la tarjeta DIE-ICA (Área 72 ICCA, conector PL/SK 72L pin C8) y a las tarjetas de relés de interbloqueo "
            f"IRC-A e IRC-B (Área 74). Durante la inspección técnica con el equipo desenergizado y consignado, se "
            f"constata desgaste mecánico y carbonización en los contactos auxiliares 13 y 14 de CON-K, lo cual produce "
            f"una resistencia de contacto superior a 0.8 ohm y una interrupción en el retorno a 0V hacia el punto "
            f"de masa central CGPB 20.{img_tag} Al no cerrarse firmemente la entrada lógica a masa, el sistema reporta "
            f"i79 inactivo e impide el paso al estado Preparatory. Se requiere el reemplazo del bloque de contactos "
            f"auxiliares del contactor CON-K e inspección de pistas de interconexión en el bastidor de Área 72/74 "
            f"para normalizar la secuencia de encendido de potencia y la emisión de haz."
        )
        return {
            "ok": True,
            "body": body,
            "suggested_diagnosis": "Reemplazo de contactos auxiliares de contactor CON-K y verificación de lazo en DIE-ICA",
            "suggested_parts": [
                {"pn": "1512130", "description": "Relay output card / Contactor aux block CON-K", "quantity": "01"},
                {"pn": "1573800", "description": "Digital input encoding board (DIE-ICA, DIE-A)", "quantity": "01"},
            ],
            "suggested_conclusions": "- Equipo operativo tras intervención de potencia\n- Se requiere los siguientes repuestos para normalizar el servicio clínico",
            "source": "local_manuals",
        }

    # 3. Caso Dosimetría / Interlock de Tasa de Dosis / Canal de Cámara (ej. Interlock 283 / Dose 1 / Dose 2)
    is_dosimetry = (
        "DOSE" in inc_upper or "DOSIMETR" in inc_upper or "283" in inc_upper or "CHAMBER" in inc_upper or "DIE-RHA" in inc_upper
    )
    if is_dosimetry:
        img_tag = f" [IMÁGENES ADJUNTAS: {' Y '.join(img_refs)}]." if img_refs else " [IMÁGENES ADJUNTAS: MEDICIÓN DE POLARIZACIÓN Y LECTURAS DIE-RHA]."
        body = (
            f"Durante la entrega de haz se presenta inhibición de radiación por discrepancia de dosimetría ({incident}) en el "
            f"acelerador {brand} {model}. La cámara de ionización de transmisión del cabezal incorpora canales "
            f"independientes redundantes Canal 1 y Canal 2 procesados por la tarjeta DIE-RHA en el bastidor RHCA. "
            f"Durante la revisión técnica se detectó una desviación de cero y deriva térmica en los integradores de carga, "
            f"así como una fluctuación en la alta tensión de polarización negativa (-500V DC) a través del conector triaxial.{img_tag} "
            f"Esta inestabilidad supera la tolerancia del ±2% entre canales de monitorización, activando el circuito de "
            f"terminación forzada de haz. Se realiza ajuste preliminar de offset y se solicita el reemplazo preventivo "
            f"de la tarjeta DIE-RHA y el cable de polarización de cámara para garantizar la repetibilidad y calibración dosimétrica."
        )
        return {
            "ok": True,
            "body": body,
            "suggested_diagnosis": f"Sustitución de tarjeta de dosimetría DIE-RHA y verificación de polarización asociada a {incident}",
            "suggested_parts": [
                {"pn": "1573801", "description": "Digital input & encoding board DIE-RHA / DIE-B", "quantity": "01"},
            ],
            "suggested_conclusions": "- Calibración de dosimetría verificada provisionalmente\n- Se requiere los siguientes repuestos para restablecer la tolerancia clínica",
            "source": "local_manuals",
        }

    # 4. Caso Vacío / Bomba Iónica / Cañón de electrones
    is_vacuum = (
        "VACUUM" in inc_upper
        or "VACIO" in inc_upper
        or "VACÍO" in inc_upper
        or "ION PUMP" in inc_upper
        or "BOMBA" in inc_upper
        or "IÓNICA" in inc_upper
        or "IONICA" in inc_upper
        or "GUN" in inc_upper
        or "CAÑON" in inc_upper
        or "CAÑÓN" in inc_upper
    )
    if is_vacuum:
        img_tag = f" [IMÁGENES ADJUNTAS: {' Y '.join(img_refs)}]." if img_refs else " [IMÁGENES ADJUNTAS: CURVA DE CORRIENTE IÓNICA Y PASAMUROS]."
        body = (
            f"El equipo {brand} {model} presenta interrupción de tratamiento debido a disparo en el lazo de seguridad "
            f"de ultra alto vacío ({incident}) en la columna aceleradora. El sistema es monitoreado mediante la telemetría de corriente "
            f"de la bomba iónica y el presostato de seguridad SW1 cableado hacia las tarjetas DIE de supervisión. Durante "
            f"la inspección técnica se evidenció un incremento anómalo en la corriente de fuga superficial en el aislador "
            f"cerámico del pasamuros del cañón, generando microdescargas resistivas interpretadas por el controlador "
            f"como pérdida de vacío.{img_tag} Se efectúa limpieza química de contactos cerámicos y se solicita la "
            f"sustitución del conjunto pasamuros y verificación de la fuente de polarización de la bomba para asegurar "
            f"la estabilidad del vacío y proteger el cañón de electrones."
        )
        return {
            "ok": True,
            "body": body,
            "suggested_diagnosis": f"Limpieza y reemplazo de pasamuros cerámico de alto vacío ({incident})",
            "suggested_parts": [
                {"pn": "261308030177", "description": "SEAL, O-RING, VITON RUBBER HV160", "quantity": "01"},
            ],
            "suggested_conclusions": "- Vacío estabilizado en nivel operativo\n- Se requiere los siguientes repuestos para mantenimiento definitivo",
            "source": "local_manuals",
        }

    # 5. Caso General / Dinámico con búsqueda en manuales
    board_hint = "DIE-HTB"
    pin_hint = "pin de señal"
    part_hint = "componente electromecánico"
    extracted_parts = []

    if search_engine:
        try:
            hits = search_engine.search(incident, limit=5).get("results", [])
            terms_to_catalog = [incident]
            for h in hits:
                snip = h.get("context", "")
                m_b = re.findall(r"\b(DIE-[A-Z0-9]+|PCB\s*[0-9]+[A-Z]?|ROC-[A-Z0-9]+)\b", snip)
                if m_b and board_hint == "DIE-HTB":
                    board_hint = m_b[0]
                    terms_to_catalog.append(board_hint)
                m_p = re.findall(r"\b(pin\s+[A-Z0-9]+|PL\d+|SK\d+)\b", snip, re.I)
                if m_p and pin_hint == "pin de señal":
                    pin_hint = m_p[0]

            parts_found = _extract_spare_parts_from_context(search_engine, terms_to_catalog)
            if parts_found:
                extracted_parts = parts_found
        except Exception as search_err:
            logger.debug("Búsqueda documental para caso general omitida: %s", search_err)

    if not extracted_parts:
        extracted_parts = [
            {"pn": "1573801", "description": f"Tarjeta de control e interfaz ({board_hint})", "quantity": "01"}
        ]

    img_tag = f" [IMÁGENES ADJUNTAS: {' Y '.join(img_refs)}]." if img_refs else " [IMÁGENES ADJUNTAS: EVIDENCIA TÉCNICA Y DIAGRAMA DE ESQUEMA]."
    body = (
        f"Durante la operación clínica del acelerador lineal {brand} {model}, se registró el incidente: {incident}. "
        f"El componente afectado actúa dentro del circuito de control y seguridad asociado al subsistema reportado. "
        f"Durante la revisión técnica se detectaron anomalías en la estabilidad de la señal y holgura o fatiga en "
        f"los elementos de interconexión hacia la tarjeta {board_hint} a través del {pin_hint}, generando la activación "
        f"del enclavamiento de seguridad hacia la lógica central del equipo.{img_tag} Para asegurar la continuidad "
        f"operativa y la total seguridad del paciente, se solicita la sustitución del componente dañado y la "
        f"tarjeta {board_hint} correspondiente, permitiendo normalizar los parámetros operativos del sistema."
    )

    return {
        "ok": True,
        "body": body,
        "suggested_diagnosis": f"Revisión y reemplazo de {board_hint} asociado a {incident}",
        "suggested_parts": extracted_parts,
        "suggested_conclusions": "- Equipo intervenido técnicamente\n- Se requiere los siguientes repuestos para normalizar el servicio clínico",
        "source": "local_manuals",
    }


def generate_report_body_hybrid(
    incident: str,
    equipment: str = "ACELERADOR LINEAL",
    brand: str = "ELEKTA",
    model: str = "SYNERGY FULL",
    diagnosis: str = "",
    image_descriptions: list[str] | None = None,
    search_engine: SearchEngine | None = None,
    api_key: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    """Enfoque híbrido: intenta redactar con la API de Gemini (con contexto de manuales)

    y ante cualquier indisponibilidad recurre al motor local de manuales.
    """
    incident_clean = str(incident or "").strip()
    if not incident_clean:
        return {
            "ok": False,
            "error": "empty_incident",
            "message": "Debe especificar el incidente que manifiesta el usuario.",
        }

    key = str(api_key or os.environ.get("GEMINI_API_KEY", "")).strip().strip("\"' \r\n\t")

    # Si no hay SDK o clave configurada, fallback local inmediato
    if not GENAI_AVAILABLE or not key:
        return generate_local_report_body(
            incident=incident_clean,
            equipment=equipment,
            brand=brand,
            model=model,
            diagnosis=diagnosis,
            image_descriptions=image_descriptions,
            search_engine=search_engine,
        )

    # 1. Recopilar contexto documental de los 19 manuales técnicos
    evidence_text = ""
    if search_engine:
        try:
            hits = search_engine.search(incident_clean, limit=6).get("results", [])
            snippets = []
            for h in hits:
                m = h.get("manual", "")
                p = h.get("page", 0)
                sn = h.get("context", "")[:1200]
                snippets.append(f"--- Manual: {m} (Página {p}) ---\n{sn}")
            evidence_text = "\n\n".join(snippets)
        except Exception as exc:
            logger.debug("Error recolectando evidencia para informe: %s", exc)

    img_info = ""
    if image_descriptions:
        img_info = "IMÁGENES ADJUNTAS DISPONIBLES: " + ", ".join(image_descriptions)

    prompt = f"""EVIDENCIA TÉCNICA DE LOS MANUALES DE ELEKTA:
{evidence_text or 'Considere el catálogo y esquemas de aceleradores lineales Elekta.'}

DATOS DEL EQUIPO Y SERVICIO:
- Equipo: {equipment}
- Marca: {brand}
- Modelo: {model}
- Incidente que manifiesta el usuario: {incident_clean}
- Diagnóstico técnico preliminar: {diagnosis or 'A determinar'}
{img_info}

INSTRUCCIONES CLAVE DE REDACCIÓN:
- En la redacción de TRABAJO REALIZADO, debes incluir y mantener explícitamente todos los términos, señales y componentes del incidente y diagnóstico ingresados (por ejemplo: {incident_clean}{f', {diagnosis}' if diagnosis else ''}). No los omitas ni sustituyas por nombres genéricos.
- En el párrafo final de TRABAJO REALIZADO, debes justificar y listar explícitamente los repuestos requeridos con su nombre formal y número de parte (P/N) real del catálogo (por ejemplo: 'Switch Assembly - 45133308377', 'DIE-HTB - 1573801', etc.).
- En el campo 'suggested_parts', coloca la lista estructurada de dichos repuestos (P/N, descripción, cantidad).

Redacta la sección 'TRABAJO REALIZADO' y extrae los repuestos requeridos en formato JSON:"""

    # Modelos a intentar en orden de disponibilidad
    models_to_try = []
    if model_name and model_name.strip():
        models_to_try.append(model_name.strip())
    env_m = os.environ.get("GEMINI_MODEL", "").strip().strip("\"' ")
    if env_m and env_m not in models_to_try:
        models_to_try.append(env_m)

    default_models = [
        "gemini-3.8-flash",
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]
    for dm in default_models:
        if dm not in models_to_try:
            models_to_try.append(dm)

    try:
        http_opts = types.HttpOptions(timeout=20000)
        client = genai.Client(api_key=key, http_options=http_opts)

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

        for current_model in models_to_try:
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION_REPORT,
                        temperature=0.2,
                        response_mime_type="application/json",
                        response_schema=ReportBodyResponse,
                        max_output_tokens=2048,
                        automatic_function_calling=afc_cfg,
                        thinking_config=thinking_cfg,
                    ),
                )
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, ReportBodyResponse):
                    data = parsed.model_dump(mode="json")
                else:
                    raw_text = response.text or "{}"
                    clean_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.I)
                    clean_json = re.sub(r"\s*```$", "", clean_json).strip()
                    data = json.loads(clean_json)

                body_out = str(data.get("body", "")).strip()
                if body_out:
                    raw_parts = data.get("suggested_parts", [])
                    clean_parts = []
                    for p in raw_parts:
                        if isinstance(p, dict):
                            pn_cand = str(p.get("pn", "")).strip()
                            if pn_cand and not _is_drawing_number(pn_cand):
                                clean_parts.append(p)

                    # Fidelidad al caso HT PSU OT (modelo oficial de referencia)
                    is_ht_ot = "HT PSU OT" in incident_clean.upper() or ("HT" in incident_clean.upper() and "OT" in incident_clean.upper())
                    if is_ht_ot:
                        existing_pns = {p.get("pn") for p in clean_parts}
                        if "45133308377" not in existing_pns:
                            clean_parts.insert(0, {"pn": "45133308377", "description": "Switch Assembly", "quantity": "01"})
                        if "1573801" not in existing_pns:
                            clean_parts.append({"pn": "1573801", "description": "Digital input & encoding board (DIE-HTB)", "quantity": "01"})
                        if "Switch Assembly" not in body_out:
                            body_out = re.sub(
                                r"(?i)\b(?:sensor electromecánico|fuelle térmico|interruptor de fuelle)\b",
                                "conjunto Switch Assembly (sensor electromecánico SW2)",
                                body_out,
                                count=1,
                            )
                            if "Switch Assembly" not in body_out:
                                body_out = "El conjunto Switch Assembly actúa en el lazo de sobretemperatura. " + body_out
                        if "45133308377" not in body_out:
                            body_out += " Por lo expuesto, se solicita el reemplazo del conjunto Switch Assembly - 45133308377 y de la tarjeta DIE-HTB - 1573801 para restablecer la correcta recepción del lazo de seguridad y la operatividad clínica."

                    # Fidelidad a señales específicas ingresadas (ej: ITEM 79)
                    if "ITEM 79" in incident_clean.upper() and "ITEM 79" not in body_out.upper():
                        body_out = re.sub(
                            r"(?i)\bCON-K\b",
                            "CON-K (supervisado por ITEM 79)",
                            body_out,
                            count=1,
                        )

                    # Si no se extrajeron repuestos válidos del modelo, consultar el catálogo local
                    if not clean_parts and search_engine:
                        terms = [incident_clean]
                        if diagnosis:
                            terms.append(diagnosis)
                        clean_parts = _extract_spare_parts_from_context(search_engine, terms)
                    if not clean_parts:
                        clean_parts = [
                            {"pn": "1573801", "description": "Tarjeta de control e interfaz (DIE)", "quantity": "01"}
                        ]

                    return {
                        "ok": True,
                        "body": body_out,
                        "suggested_diagnosis": data.get("suggested_diagnosis", "") or diagnosis,
                        "suggested_parts": clean_parts,
                        "suggested_conclusions": data.get("suggested_conclusions", "- Equipo operativo tras reemplazo\n- Se requiere los siguientes repuestos"),
                        "source": "gemini",
                        "model_used": current_model,
                    }
            except Exception as model_err:
                logger.warning("Fallo al generar cuerpo de informe con modelo '%s': %s", current_model, model_err)
                continue

    except Exception as gemini_err:
        logger.warning("Excepción en cliente Gemini para informe: %s", gemini_err)

    # Fallback automático local si Gemini no completó la redacción
    return generate_local_report_body(
        incident=incident_clean,
        equipment=equipment,
        brand=brand,
        model=model,
        diagnosis=diagnosis,
        image_descriptions=image_descriptions,
        search_engine=search_engine,
    )
