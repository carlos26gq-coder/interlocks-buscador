"""SOLVI - API de búsqueda técnica, diagnóstico y apuntes."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import sys
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

try:
    if "unittest" not in sys.modules:
        from dotenv import load_dotenv
        load_dotenv()
except ImportError:
    pass

from ai_service import analyze_with_gemini
from report_service import generate_report_body_hybrid, generate_report_docx
from flask import (
    Flask,
    jsonify,
    make_response,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from httpx import HTTPError
from postgrest.exceptions import APIError
from search_engine import SearchEngine, normalize
from supabase import Client, create_client
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import redis as redis_lib
except ImportError:  # Redis es opcional en desarrollo; Render debe configurarlo para compartir caché.
    redis_lib = None

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_PATH = DATA_DIR / "all_manuals.json"
MAX_QUERY_LENGTH = 200
MAX_NOTE_TITLE = 200
MAX_NOTE_TEXT = 20_000
MAX_TAGS = 20
MAX_TAG_LENGTH = 50
NOTES_CACHE_SECONDS = 5
NOTES_CACHE_REDIS_URL = (os.environ.get("NOTES_CACHE_REDIS_URL") or os.environ.get("REDIS_URL", "")).strip()
MAX_NOTES_PAGE = 100
MAX_NOTES_SEARCH = 500

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB para cargas de carpetas y diagnósticos forenses
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI") or os.environ.get("REDIS_URL", "memory://"),
    swallow_errors=True,
)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        app.logger.exception("No se pudo inicializar Supabase")

with DATA_PATH.open("r", encoding="utf-8") as file:
    manuals = json.load(file)

search_engine = SearchEngine(manuals)
BUILD_TIME = str(int(time.time()))
_notes_cache = {"loaded_at": 0.0, "data": []}
_notes_lock = threading.Lock()
_notes_shared_cache = None


def _get_shared_cache():
    """Obtiene Redis una sola vez; sin URL se mantiene el fallback local de desarrollo."""
    global _notes_shared_cache
    if _notes_shared_cache is not None:
        return _notes_shared_cache
    if not NOTES_CACHE_REDIS_URL or redis_lib is None:
        return None
    try:
        _notes_shared_cache = redis_lib.Redis.from_url(
            NOTES_CACHE_REDIS_URL, decode_responses=True, socket_timeout=1
        )
        _notes_shared_cache.ping()
        return _notes_shared_cache
    except Exception as exc:
        app.logger.warning("Caché Redis de apuntes no disponible: %s", _sanitize_error_message(exc))
        _notes_shared_cache = None
        return None

app.logger.info(
    "SOLVI iniciado: %s páginas, %s manuales, Supabase=%s, R2=%s",
    len(search_engine.documents),
    len(search_engine.manuals),
    bool(supabase),
    bool(R2_PUBLIC_URL),
)
if not ADMIN_PASSWORD:
    app.logger.warning("ADMIN_PASSWORD no configurada: las funciones administrativas quedan deshabilitadas")


class ValidationError(ValueError):
    pass


def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "worker-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https://*; "
            "connect-src 'self' https://* blob:; "
            "object-src 'none'; "
            "base-uri 'self';"
        ),
    )
    return response


def _sanitize_error_message(text: object) -> str:
    """Enmascara posibles claves API o tokens en mensajes de error antes de registrarlos o emitirlos."""
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


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("El cuerpo debe ser un objeto JSON válido.")
    return data


def bounded_text(data: dict, key: str, maximum: int, *, required: bool = False) -> str:
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"'{key}' debe ser texto.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"'{key}' es obligatorio.")
    if len(value) > maximum:
        raise ValidationError(f"'{key}' supera el máximo de {maximum} caracteres.")
    return value


def validated_tags(data: dict) -> list[str]:
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise ValidationError("'tags' debe ser una lista.")
    if len(tags) > MAX_TAGS:
        raise ValidationError(f"Se permiten como máximo {MAX_TAGS} etiquetas.")
    clean = []
    for tag in tags:
        if not isinstance(tag, str):
            raise ValidationError("Cada etiqueta debe ser texto.")
        tag = tag.strip()
        if len(tag) > MAX_TAG_LENGTH:
            raise ValidationError(f"Cada etiqueta admite hasta {MAX_TAG_LENGTH} caracteres.")
        if tag and tag not in clean:
            clean.append(tag)
    return clean


def validated_uuid(value: object, *, generate: bool = False) -> str:
    if (value is None or value == "") and generate:
        return str(uuid.uuid4())
    if not isinstance(value, str):
        raise ValidationError("El identificador del apunte debe ser texto UUID.")
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("El identificador del apunte no es válido.") from exc


def strict_string_list(value: object, *, key: str, max_items: int, max_length: int, required: bool = False) -> list[str]:
    """Valida listas JSON sin convertir silenciosamente números/objetos a texto."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValidationError(f"'{key}' debe ser una lista de textos.")
    if len(value) > max_items:
        raise ValidationError(f"'{key}' admite como máximo {max_items} elementos.")
    clean = []
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(f"Cada elemento de '{key}' debe ser texto.")
        item = item.strip()
        if len(item) > max_length:
            raise ValidationError(f"Cada elemento de '{key}' admite hasta {max_length} caracteres.")
        if item:
            clean.append(item)
    if required and not clean:
        raise ValidationError(f"'{key}' requiere al menos un elemento.")
    return clean


def check_password(password: object) -> bool:
    if not ADMIN_PASSWORD or not isinstance(password, str):
        return False
    return secrets.compare_digest(password.strip(), ADMIN_PASSWORD)


def admin_password_from_header() -> str:
    return request.headers.get("X-Admin-Password", "").strip()


def require_admin(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not ADMIN_PASSWORD:
            return jsonify({"error": "Administración no configurada."}), 503
        if not check_password(admin_password_from_header()):
            return jsonify({"error": "Acceso administrativo denegado."}), 403
        return function(*args, **kwargs)

    return wrapped


def invalidate_notes_cache() -> None:
    with _notes_lock:
        _notes_cache["loaded_at"] = 0.0
        _notes_cache["data"] = []
    shared_cache = _get_shared_cache()
    if shared_cache is not None:
        try:
            keys = list(shared_cache.scan_iter(match="solvi:notes:*", count=100))
            if keys:
                shared_cache.delete(*keys)
        except Exception as exc:
            app.logger.debug("Invalidación de caché Redis omitida: %s", _sanitize_error_message(exc))


def notes_load(*, force: bool = False, limit: int | None = None, offset: int = 0) -> list[dict]:
    if not supabase:
        return []
    if limit is not None:
        limit = max(1, min(MAX_NOTES_PAGE, int(limit)))
        offset = max(0, int(offset))
    cache_key = f"solvi:notes:{offset}:{limit or 'all'}"
    shared_cache = _get_shared_cache()
    if shared_cache is not None and not force:
        try:
            cached_json = shared_cache.get(cache_key)
            if cached_json:
                cached_data = json.loads(cached_json)
                if isinstance(cached_data, list):
                    return cached_data
        except Exception as exc:
            app.logger.debug("Lectura de caché Redis omitida: %s", _sanitize_error_message(exc))
    now = time.monotonic()
    if limit is None:
        with _notes_lock:
            if not force and now - _notes_cache["loaded_at"] < NOTES_CACHE_SECONDS:
                return list(_notes_cache["data"])
    try:
        query = supabase.table("notes").select("*")
        try:
            query = query.order("created_at", desc=True)
        except (AttributeError, TypeError):
            # Compatibilidad con adaptadores/mocks antiguos; la migración crea el índice.
            pass
        if limit is not None:
            try:
                query = query.range(offset, offset + limit - 1)
            except (AttributeError, TypeError):
                pass
        response = query.execute()
        data = response.data if isinstance(response.data, list) else []
        if limit is None:
            with _notes_lock:
                _notes_cache["loaded_at"] = now
                _notes_cache["data"] = data
        if shared_cache is not None:
            try:
                shared_cache.setex(cache_key, NOTES_CACHE_SECONDS, json.dumps(data, ensure_ascii=False))
            except Exception as exc:
                app.logger.debug("Escritura de caché Redis omitida: %s", _sanitize_error_message(exc))
        return list(data)
    except Exception:
        app.logger.exception("Error al leer apuntes de Supabase")
        if limit is not None:
            return []
        with _notes_lock:
            return list(_notes_cache["data"])


def _note_by_id(note_id: str) -> dict | None:
    if not supabase:
        return None
    response = (
        supabase.table("notes")
        .select("*")
        .eq("id", note_id)
        .limit(1)
        .execute()
    )
    data = response.data if isinstance(response.data, list) else []
    return data[0] if data and isinstance(data[0], dict) else None


def _same_note_content(existing: dict, submitted: dict) -> bool:
    def _norm_text(v):
        return (v or '').strip()
    def _norm_tags(v):
        if isinstance(v, list):
            return sorted(str(t) for t in v)
        return []
    return (
        _norm_text(existing.get('title')) == _norm_text(submitted.get('title'))
        and _norm_text(existing.get('text')) == _norm_text(submitted.get('text'))
        and _norm_tags(existing.get('tags')) == _norm_tags(submitted.get('tags'))
    )


def note_search(query: str) -> list[dict]:
    normalized_query = normalize(query)
    results = []
    for note in notes_load(limit=MAX_NOTES_SEARCH, offset=0):
        tags = note.get("tags") if isinstance(note.get("tags"), list) else []
        searchable = normalize(
            f"{note.get('title', '')} {note.get('text', '')} {' '.join(map(str, tags))}"
        )
        if normalized_query not in searchable:
            continue
        full_text = str(note.get("text", ""))
        results.append({
            "type": "note",
            "id": str(note.get("id", "")),
            "manual": "apuntes",
            "page": str(note.get("title") or "Sin título"),
            "context": full_text[:300] + ("..." if len(full_text) > 300 else ""),
            "tags": tags,
        })
    return results


@app.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify({"ok": False, "error": "validation_error", "message": str(error)}), 400


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify({
        "ok": False,
        "error": "payload_too_large",
        "message": "La carpeta o archivo supera el límite de transferencia HTTP (máx. 1 GB). Te sugerimos usar la opción 'Analizar Ruta Local en Disco' para procesar carpetas de cualquier tamaño de forma instantánea sin límites de red."
    }), 413


@app.errorhandler(429)
def handle_rate_limit(error):
    return jsonify({
        "ok": False,
        "error": "rate_limit_exceeded",
        "message": "Demasiadas solicitudes simultáneas. Espera unos segundos e intenta de nuevo.",
    }), 429


@app.errorhandler(500)
def handle_server_error(error):
    app.logger.exception("Error interno del servidor no controlado")
    return jsonify({
        "ok": False,
        "error": "server_error",
        "message": "Ocurrió un inconveniente temporal en el servidor. Puedes reintentar o usar el diagnóstico local.",
    }), 500


@app.route("/")
def home():
    return no_cache(make_response(render_template("index.html", build_time=BUILD_TIME, r2_url=R2_PUBLIC_URL)))


@app.route("/reset")
def reset():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Actualizando SOLVI...</title>
<style>body{background:#0b0f1a;color:#e2e8f0;font-family:sans-serif;display:flex;flex-direction:column;
align-items:center;justify-content:center;min-height:100vh;gap:16px;text-align:center}.s{width:40px;height:40px;
border:3px solid #1e293b;border-top-color:#00d4ff;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}p{color:#64748b;font-size:.9rem}</style></head><body>
<div class="s"></div><h2>Actualizando datos offline...</h2><p>Serás redirigido automáticamente.</p>
<script>(async()=>{const keys=await caches.keys();await Promise.all(keys.filter(k=>k.startsWith('solvi-')).map(k=>caches.delete(k)));
const regs=await navigator.serviceWorker.getRegistrations();await Promise.all(regs.filter(r=>r.scope===location.origin+'/').map(r=>r.unregister()));
location.replace('/?nocache='+Date.now())})()</script></body></html>"""
    return no_cache(make_response(html))


@app.route("/manifest.json")
def manifest():
    return no_cache(send_from_directory(BASE_DIR, "manifest.json", mimetype="application/manifest+json"))


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(BASE_DIR, "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/data/<path:filename>")
def serve_data(filename):
    data_dir_resolved = DATA_DIR.resolve()
    target = (DATA_DIR / filename).resolve()
    if not target.is_relative_to(data_dir_resolved):
        return jsonify({"ok": False, "error": "not_found", "message": "Archivo no encontrado."}), 404
    if not target.is_file():
        return jsonify({"ok": False, "error": "not_found", "message": "Archivo no encontrado."}), 404
    return send_from_directory(DATA_DIR, filename)


@app.route("/version")
def version():
    return jsonify({"build": BUILD_TIME})


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "pages": len(search_engine.documents),
        "manuals": len(search_engine.manuals),
        "supabase": bool(supabase),
        "r2": bool(R2_PUBLIC_URL),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
    })


@app.route("/search")
@limiter.limit("1200 per hour; 120 per minute")
def search():
    query = request.args.get("q", "").strip()
    manual_filter = request.args.get("manual", "").strip().lower()
    if not query:
        return jsonify({"results": [], "total": 0, "offset": 0, "limit": 25, "has_more": False, "r2_url": R2_PUBLIC_URL})
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationError(f"La búsqueda admite hasta {MAX_QUERY_LENGTH} caracteres.")
    try:
        offset = min(100_000, max(0, int(request.args.get("offset", 0))))
        limit = min(50, max(1, int(request.args.get("limit", 25))))
    except (ValueError, TypeError) as exc:
        raise ValidationError("La paginación no es válida.") from exc

    manual_total = 0
    manual_results = []
    if manual_filter != "apuntes":
        manual_page = search_engine.search(query, manual_filter, offset=offset, limit=limit)
        manual_total = manual_page["total"]
        manual_results = manual_page["results"]

    notes = note_search(query) if not manual_filter or manual_filter == "apuntes" else []
    if manual_filter == "apuntes":
        results = notes[offset:offset + limit]
    else:
        results = list(manual_results)
        remaining = limit - len(results)
        if remaining > 0:
            note_offset = max(0, offset - manual_total)
            results.extend(notes[note_offset:note_offset + remaining])

    total = manual_total + len(notes)
    return jsonify({
        "results": results,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(results) < total,
        "r2_url": R2_PUBLIC_URL,
    })


@app.route("/diagnose", methods=["POST"])
@app.route("/api/diagnose", methods=["POST"])
@limiter.limit("300 per hour; 30 per minute")
def diagnose():
    data = json_body()
    # New format: {"symptoms": ["...", "...", ...]} — up to 5 free-form symptom strings
    symptoms_raw = data.get("symptoms")
    if symptoms_raw is not None:
        symptoms = strict_string_list(symptoms_raw, key="symptoms", max_items=5, max_length=300)
        result = search_engine.diagnose_symptoms(symptoms, limit=5)
    else:
        # Legacy named-fields format (backward compatibility)
        signals = {
            "interlock": bounded_text(data, "interlock", 100),
            "error": bounded_text(data, "error", 100),
            "message": bounded_text(data, "message", 300),
            "observations": bounded_text(data, "observations", 500),
        }
        result = search_engine.diagnose(signals, limit=5)
    result["r2_url"] = R2_PUBLIC_URL
    return jsonify(result)


@app.route("/diagnose/ai", methods=["POST"])
@app.route("/api/diagnose/ai", methods=["POST"])
@limiter.limit("300 per hour; 30 per minute")
def diagnose_ai():
    try:
        data = json_body()
        symptoms = strict_string_list(
            data.get("symptoms", []), key="symptoms", max_items=5, max_length=300, required=True
        )

        client_key_raw = data.get("api_key", "")
        model_raw = data.get("model", data.get("model_override", ""))
        if not isinstance(client_key_raw, str) or not isinstance(model_raw, str):
            raise ValidationError("api_key y model deben ser texto.")
        client_key = client_key_raw.strip()[:256]
        model_override = model_raw.strip()[:100]
        from ai_service import ALLOWED_GEMINI_MODELS
        if model_override and model_override not in ALLOWED_GEMINI_MODELS:
            raise ValidationError("Modelo de diagnóstico no permitido.")
        ai_result = analyze_with_gemini(symptoms, search_engine, api_key=client_key, model=model_override)

        if not ai_result.get("ok"):
            error_type = ai_result.get("error")
            if error_type in {"no_api_key", "invalid_api_key"}:
                status_code = 400
            elif error_type == "quota_exceeded":
                status_code = 429
            elif error_type == "timeout":
                status_code = 504
            else:
                status_code = 503
            if "message" in ai_result:
                ai_result["message"] = _sanitize_error_message(ai_result["message"])
            return jsonify(ai_result), status_code

        return jsonify(ai_result), 200
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        clean_err = _sanitize_error_message(exc)
        app.logger.error("Error en endpoint /diagnose/ai: %s", clean_err)
        try:
            symptoms_safe = symptoms if "symptoms" in locals() and isinstance(symptoms, list) and symptoms else ["Falla técnica general"]
            from ai_service import generate_local_failover_diagnosis
            failover_res = generate_local_failover_diagnosis(symptoms_safe, search_engine, reason="server_failover")
            return jsonify({
                "ok": True,
                "data": failover_res,
                "model_used": "Análisis Causal Basado en Catálogo Documental (Manuales Elekta)",
                "symptoms": symptoms_safe,
                "failover": True,
                "notice": "Diagnóstico estructurado a partir del corpus documental de los 19 manuales técnicos de Elekta.",
            }), 200
        except Exception:
            return jsonify({
                "ok": False,
                "error": "server_exception",
                "message": f"Inconveniente temporal en el servidor: {clean_err[:120]}",
            }), 503


@app.route("/reports/generate-body", methods=["POST"])
@app.route("/api/reports/generate-body", methods=["POST"])
@limiter.limit("120 per minute")
def reports_generate_body():
    try:
        data = json_body()
        incident = bounded_text(data, "incident", 1000, required=True)
        equipment = bounded_text(data, "equipment", 200) or "ACELERADOR LINEAL"
        brand = bounded_text(data, "brand", 200) or "ELEKTA"
        model = bounded_text(data, "model", 200) or "SYNERGY FULL"
        diagnosis = bounded_text(data, "diagnosis", 1000)
        image_descriptions_raw = data.get("image_descriptions")
        image_descriptions = None
        if isinstance(image_descriptions_raw, list):
            image_descriptions = [str(x).strip() for x in image_descriptions_raw if str(x).strip()][:10]

        client_key_raw = data.get("api_key", "")
        client_key = client_key_raw.strip()[:256] if isinstance(client_key_raw, str) else ""

        result = generate_report_body_hybrid(
            incident=incident,
            equipment=equipment,
            brand=brand,
            model=model,
            diagnosis=diagnosis,
            image_descriptions=image_descriptions,
            search_engine=search_engine,
            api_key=client_key,
        )
        return jsonify(result), 200
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        clean_err = _sanitize_error_message(exc)
        app.logger.error("Error en endpoint /reports/generate-body: %s", clean_err)
        return jsonify({
            "ok": False,
            "error": "server_error",
            "message": f"Error al generar la propuesta de informe: {clean_err[:120]}",
        }), 500


@app.route("/reports/export-docx", methods=["POST"])
@app.route("/api/reports/export-docx", methods=["POST"])
@limiter.limit("60 per minute")
def reports_export_docx():
    try:
        data = json_body()
        docx_bytes = generate_report_docx(data)

        report_number = str(data.get("number") or "INFORME_TECNICO").strip()
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", report_number) or "INFORME_TECNICO"
        filename = f"{clean_name}.docx"

        response = make_response(docx_bytes)
        response.headers["Content-Type"] = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        clean_err = _sanitize_error_message(exc)
        app.logger.error("Error en endpoint /reports/export-docx: %s", clean_err)
        return jsonify({
            "ok": False,
            "error": "server_error",
            "message": f"Error al generar el documento Word: {clean_err[:120]}",
        }), 500


@app.route("/notes", methods=["GET"])
@limiter.limit("120 per minute")
def get_notes():
    # Compatibilidad: sin parámetros se conserva la respuesta de lista usada por
    # clientes antiguos. Las llamadas paginadas reciben metadatos explícitos.
    page_raw = request.args.get("page")
    limit_raw = request.args.get("limit")
    if page_raw is None and limit_raw is None:
        return jsonify(notes_load()), 200
    try:
        page = int(page_raw or 1)
        limit = int(limit_raw or MAX_NOTES_PAGE)
    except (TypeError, ValueError) as exc:
        raise ValidationError("La paginación de apuntes no es válida.") from exc
    if page < 1 or limit < 1 or limit > MAX_NOTES_PAGE:
        raise ValidationError(f"La página debe ser >= 1 y el límite debe estar entre 1 y {MAX_NOTES_PAGE}.")
    offset = (page - 1) * limit
    notes = notes_load(limit=limit, offset=offset)
    return jsonify({
        "notes": notes,
        "page": page,
        "limit": limit,
        "offset": offset,
        "has_more": len(notes) == limit,
    }), 200


@app.route("/notes/batch", methods=["POST"])
@limiter.limit("50 per hour")
def create_notes_batch():
    if not supabase:
        return jsonify({"error": "Supabase no está conectado."}), 503
    data = json_body()
    notes_raw = data.get("notes", [])
    if not isinstance(notes_raw, list):
        raise ValidationError("'notes' debe ser una lista.")
    if len(notes_raw) > 50:
        raise ValidationError("No se pueden sincronizar más de 50 apuntes por lote.")
    
    valid_notes = []
    for note in notes_raw:
        if not isinstance(note, dict):
            raise ValidationError("Cada elemento de 'notes' debe ser un objeto JSON.")
        valid_notes.append({
            "id": validated_uuid(note.get("id"), generate=True),
            "title": bounded_text(note, "title", MAX_NOTE_TITLE, required=True),
            "text": bounded_text(note, "text", MAX_NOTE_TEXT),
            "tags": validated_tags(note),
        })
    
    if not valid_notes:
        return jsonify({"inserted": 0, "notes": []}), 200

    existing_ids = [n["id"] for n in valid_notes]
    existing_notes = {}
    try:
        resp = supabase.table("notes").select("id, title, text, tags").in_("id", existing_ids).execute()
        if isinstance(resp.data, list):
            existing_notes = {n["id"]: n for n in resp.data}
    except Exception as exc:
        app.logger.warning("No se pudo verificar IDs existentes en lote: %s", _sanitize_error_message(exc))

    to_insert = []
    for n in valid_notes:
        if n["id"] in existing_notes:
            if _same_note_content(existing_notes[n["id"]], n):
                continue
            else:
                return jsonify({
                    "ok": False,
                    "error": "note_id_conflict",
                    "message": "Conflicto de identificadores en el lote."
                }), 409
        to_insert.append(n)

    if not to_insert:
        return jsonify({"inserted": len(valid_notes), "notes": valid_notes}), 201

    try:
        response = supabase.table("notes").insert(to_insert).execute()
        invalidate_notes_cache()
        inserted_data = response.data if isinstance(response.data, list) else to_insert
        return jsonify({"inserted": len(inserted_data), "notes": inserted_data}), 201
    except Exception as exc:
        app.logger.error("Error al guardar lote de apuntes: %s", _sanitize_error_message(exc))
        return jsonify({"error": "No se pudo guardar el lote de apuntes."}), 502


@app.route("/notes", methods=["POST"])
# FIXME: rate-limit may block large offline sync batches
@limiter.limit("100 per hour")
def create_note():
    if not supabase:
        return jsonify({"error": "Supabase no está conectado."}), 503
    data = json_body()
    note_data = {
        "id": validated_uuid(data.get("id"), generate=True),
        "title": bounded_text(data, "title", MAX_NOTE_TITLE, required=True),
        "text": bounded_text(data, "text", MAX_NOTE_TEXT),
        "tags": validated_tags(data),
    }
    try:
        response = supabase.table("notes").insert(note_data).execute()
        invalidate_notes_cache()
        created = response.data[0] if isinstance(response.data, list) and response.data else note_data
        return jsonify(created), 201
    except (APIError, HTTPError) as insert_error:
        # Un reintento offline con el mismo UUID es idempotente, pero nunca debe
        # convertir POST en una actualización anónima de una nota existente.
        try:
            existing = _note_by_id(note_data["id"])
        except Exception as lookup_error:  # noqa: BLE001 - límite con SDK/transportes externos
            app.logger.warning(
                "No se pudo verificar el UUID tras fallar la inserción: %s",
                _sanitize_error_message(lookup_error),
            )
            existing = None

        if existing and _same_note_content(existing, note_data):
            return jsonify(existing), 200
        if existing:
            return jsonify({
                "ok": False,
                "error": "note_id_conflict",
                "message": "El identificador ya pertenece a otro apunte. Las actualizaciones requieren autorización administrativa.",
            }), 409

        app.logger.error("Error al crear un apunte: %s", _sanitize_error_message(insert_error))
        return jsonify({"error": "No se pudo guardar el apunte en la nube."}), 502
    except Exception as unexpected_error:  # noqa: BLE001 - el endpoint debe conservar respuesta JSON
        app.logger.error(
            "Error inesperado al crear un apunte: %s",
            _sanitize_error_message(unexpected_error),
        )
        return jsonify({"error": "No se pudo guardar el apunte en la nube."}), 502


@app.route("/notes/<nid>", methods=["PUT"])
@limiter.limit("30 per minute")
@require_admin
def update_note(nid):
    if not supabase:
        return jsonify({"error": "Supabase no está conectado."}), 503
    note_id = validated_uuid(nid)
    data = json_body()
    update_data = {
        "title": bounded_text(data, "title", MAX_NOTE_TITLE, required=True),
        "text": bounded_text(data, "text", MAX_NOTE_TEXT),
        "tags": validated_tags(data),
    }
    try:
        response = supabase.table("notes").update(update_data).eq("id", note_id).execute()
        invalidate_notes_cache()
        updated = response.data[0] if isinstance(response.data, list) and response.data else {"id": note_id, **update_data}
        return jsonify(updated), 200
    except Exception:
        app.logger.exception("Error al actualizar un apunte")
        return jsonify({"error": "No se pudo actualizar el apunte."}), 502


@app.route("/notes/<nid>", methods=["DELETE"])
@limiter.limit("30 per minute")
@require_admin
def delete_note(nid):
    if not supabase:
        return jsonify({"error": "Supabase no está conectado."}), 503
    note_id = validated_uuid(nid)
    try:
        supabase.table("notes").delete().eq("id", note_id).execute()
        invalidate_notes_cache()
        return jsonify({"ok": True, "id": note_id}), 200
    except Exception:
        app.logger.exception("Error al eliminar un apunte")
        return jsonify({"error": "No se pudo eliminar el apunte."}), 502


@app.route("/admin/check", methods=["POST"])
@limiter.limit("5 per minute")
def admin_check():
    if not ADMIN_PASSWORD:
        return jsonify({"error": "Administración no configurada."}), 503
    data = json_body()
    if check_password(data.get("password", "")):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Contraseña incorrecta."}), 403


@app.route("/admin/manuals")
@limiter.limit("30 per minute")
@require_admin
def list_manuals():
    return jsonify([
        {"manual": manual, "pages": len(document_ids)}
        for manual, document_ids in sorted(search_engine.manuals.items())
    ])


@app.route("/admin/config")
@limiter.limit("30 per minute")
@require_admin
def admin_config():
    return jsonify({
        "r2_configured": bool(R2_PUBLIC_URL),
        "r2_url": R2_PUBLIC_URL or "No configurada",
        "total_pages": len(search_engine.documents),
        "total_manuals": len(search_engine.manuals),
        "notes_count": len(notes_load()),
        "build": BUILD_TIME,
        "search_engine": "inverted-index-v1",
    })


@app.route("/openapi.json")
def openapi_spec():
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "SOLVI API - Linear Accelerator Technical Engineering",
            "version": "2.1.0",
            "description": "API técnica para búsqueda documental, diagnóstico causal y referencias trazables de manuales para aceleradores lineales Elekta. Las correlaciones del índice no certifican cableado físico.",
        },
        "paths": {
            "/search": {
                "get": {
                    "summary": "Búsqueda exacta en manuales técnicos",
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "manual", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 25}},
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
                    ],
                    "responses": {"200": {"description": "Resultados de búsqueda"}},
                }
            },
            "/diagnose": {
                "post": {
                    "summary": "Diagnóstico relacional de síntomas",
                    "responses": {"200": {"description": "Convergencia de síntomas en manuales"}},
                }
            },
            "/diagnose/ai": {
                "post": {
                    "summary": "Diagnóstico causal avanzado asistido por LLM",
                    "responses": {"200": {"description": "Causa raíz técnica, puntos TP y citas deterministas"}},
                }
            },
            "/notes": {
                "get": {
                    "summary": "Obtener apuntes de campo",
                    "parameters": [
                        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": MAX_NOTES_PAGE, "default": MAX_NOTES_PAGE}},
                    ],
                    "responses": {"200": {"description": "Página de apuntes con has_more"}},
                },
                "post": {"summary": "Crear apunte de campo"},
            },
            "/notes/batch": {
                "post": {
                    "summary": "Sincronizar apuntes pendientes de forma idempotente",
                    "responses": {
                        "200": {"description": "Apuntes aceptados o ya existentes"},
                        "400": {"description": "Límite o tipos inválidos", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ValidationErrorResponse"}}}},
                    },
                }
            },
            "/health": {
                "get": {"summary": "Estado del servidor y servicios conectados"},
            },
            "/logs/parse": {
                "post": {
                    "summary": "Analizador Cronológico de Archivos de Registro",
                    "responses": {"200": {"description": "Resultados del parseo de logs"}},
                }
            },
            "/reports/generate-body": {
                "post": {
                    "summary": "Redacción técnica de cuerpo de informe y extracción de repuestos",
                    "responses": {"200": {"description": "Cuerpo técnico generado y repuestos asociados"}},
                }
            },
        },
        "components": {
            "schemas": {
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "example": False},
                        "error": {"type": "string", "example": "server_error"},
                        "message": {"type": "string", "example": "Descripción del error técnico."}
                    },
                    "required": ["ok", "error"]
                },
                "ValidationErrorResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "example": False},
                        "error": {"type": "string", "example": "validation_error"},
                        "message": {"type": "string", "example": "Parámetro o unidad incompatible."}
                    },
                    "required": ["ok", "error", "message"]
                }
            }
        },
    }
    return jsonify(spec)


@app.route("/logs/parse", methods=["POST"])
@limiter.limit("600 per hour")
def logs_parse():
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        if not text:
            raise ValidationError("Debe enviar texto de registro (log text).")
            
        from log_parser_service import parse_log_text
        result = parse_log_text(text)
        return jsonify(result), 200
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /logs/parse")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


# --------------------------------------------------------------------------
# LINACLOG SUITE: Dedicated endpoints for Elekta linac multi-format logs
# --------------------------------------------------------------------------
LINACLOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "linaclog"))
_LAST_LINAC_DIR: str = LINACLOG_DIR
_LAST_LINAC_ANALYSIS: Optional[Dict[str, Any]] = None


def _normalize_name_token(name: str) -> str:
    return re.sub(r'[\s_\-\.\+]+', '', name).lower()


def _extract_sdd_zip_if_needed(zip_path: str) -> Optional[str]:
    """
    Checks if a zip file contains Elekta Linac logs and returns an extracted cache directory.
    If an already-extracted directory with logs exists alongside the zip (e.g. 'LOGS'), returns it immediately.
    """
    import zipfile
    import hashlib
    import tempfile
    if not (os.path.isfile(zip_path) and (zip_path.lower().endswith(".zip") or zipfile.is_zipfile(zip_path))):
        return None

    # Check for adjacent already-extracted 'LOGS' folder
    parent_dir = os.path.dirname(zip_path)
    log_patterns = ("*.trf", "rt-udp*.log", "*Manifest*.txt", "*AUDIT*.TXT", "LOG[0-9]*", "OPT*.xml")
    logs_sibling = os.path.join(parent_dir, "LOGS")
    if os.path.isdir(logs_sibling):
        import glob
        if any(any(os.path.isfile(f) for f in glob.glob(os.path.join(logs_sibling, pat))) for pat in log_patterns):
            return logs_sibling

    try:
        st = os.stat(zip_path)
        cache_key = hashlib.sha256(f"{zip_path}_{st.st_size}_{st.st_mtime}".encode()).hexdigest()[:16]
        cache_dir = os.path.join(tempfile.gettempdir(), f"solvi_sdd_{cache_key}")
        if os.path.isdir(cache_dir) and len(os.listdir(cache_dir)) > 0:
            return cache_dir

        os.makedirs(cache_dir, exist_ok=True)
        log_exts = (".trf", ".log", ".txt", ".xml", ".dat")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir() or member.filename.startswith("__MACOSX"):
                    continue
                name = os.path.basename(member.filename)
                if not name:
                    continue
                low = name.lower()
                if (
                    low.endswith(log_exts)
                    or low.startswith("log")
                    or low.startswith("elekta")
                    or low.startswith("rt-udp")
                    or "manifest" in low
                    or "audit" in low
                ):
                    target_file = os.path.join(cache_dir, name)
                    with zf.open(member) as source, open(target_file, "wb") as target:
                        target.write(source.read())
        return cache_dir if os.path.isdir(cache_dir) and len(os.listdir(cache_dir)) > 0 else None
    except Exception:
        return None


def _find_linac_log_subdir(folder: str) -> str:
    """
    If a folder does not directly contain linac logs, checks if an immediate subfolder
    (such as 'LOGS', 'logs', 'SDD+...', etc.) or zip file contains the logs and returns it.
    """
    import zipfile
    if not folder:
        return folder

    # 1. Direct zip file check
    if os.path.isfile(folder) and (folder.lower().endswith(".zip") or zipfile.is_zipfile(folder)):
        extracted = _extract_sdd_zip_if_needed(folder)
        if extracted:
            return extracted
        return folder

    if not os.path.isdir(folder):
        # Check if folder + '.zip' exists
        if os.path.isfile(folder + ".zip"):
            extracted = _extract_sdd_zip_if_needed(folder + ".zip")
            if extracted:
                return extracted
        return folder

    # 2. Check if folder directly has log files
    log_signatures = {".trf", ".log", ".txt", ".xml"}
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.is_file():
                    name_low = entry.name.lower()
                    if (
                        name_low.endswith(".trf")
                        or (name_low.startswith("rt-udp") and name_low.endswith(".log"))
                        or ((name_low.startswith("audit") or "audit_trail" in name_low) and name_low.endswith(".txt"))
                        or (name_low == "rtdmanifest.txt" or name_low == "rtdregistry.txt")
                        or (name_low.startswith("elekta.ccp") and name_low.endswith(".log"))
                        or (name_low.startswith("opt") and name_low.endswith(".xml"))
                    ):
                        return folder
    except Exception:
        pass

    # 3. Check subdirectories (prioritize LOGS, logs, SDD+)
    try:
        subdirs = []
        with os.scandir(folder) as it:
            for entry in it:
                if entry.is_dir():
                    subdirs.append(entry.path)
                elif entry.is_file() and entry.name.lower().endswith(".zip"):
                    zip_res = _extract_sdd_zip_if_needed(entry.path)
                    if zip_res:
                        return zip_res

        subdirs.sort(key=lambda x: (0 if os.path.basename(x).upper() in ("LOGS", "LOG") else (1 if os.path.basename(x).upper().startswith("SDD") else 2)))
        for sub in subdirs:
            try:
                with os.scandir(sub) as it:
                    for entry in it:
                        if entry.is_file():
                            name_low = entry.name.lower()
                            if (
                                name_low.endswith(".trf")
                                or (name_low.startswith("rt-udp") and name_low.endswith(".log"))
                                or ((name_low.startswith("audit") or "audit_trail" in name_low) and name_low.endswith(".txt"))
                                or (name_low == "rtdmanifest.txt" or name_low == "rtdregistry.txt")
                                or (name_low.startswith("elekta.ccp") and name_low.endswith(".log"))
                                or (name_low.startswith("opt") and name_low.endswith(".xml"))
                            ):
                                return sub
            except Exception:
                pass
    except Exception:
        pass

    return folder


def _resolve_fuzzy_segments(base_dir: str, parts: List[str]) -> Optional[str]:
    """Walks directory hierarchy matching segments with case, space, punctuation, and zip tolerance."""
    current = base_dir
    for i, part in enumerate(parts):
        if not part:
            continue
        direct = os.path.join(current, part)
        if os.path.exists(direct):
            if os.path.isdir(direct):
                current = direct
                continue
            elif os.path.isfile(direct) and i == len(parts) - 1:
                return _find_linac_log_subdir(direct)

        target_norm = _normalize_name_token(part)
        matched = False
        try:
            if os.path.isdir(current):
                with os.scandir(current) as it:
                    for entry in it:
                        entry_norm = _normalize_name_token(entry.name)
                        # Check exact token match or without .zip extension
                        if entry_norm == target_norm or entry_norm.replace("zip", "") == target_norm:
                            if entry.is_dir():
                                current = entry.path
                                matched = True
                                break
                            elif entry.is_file() and i == len(parts) - 1:
                                return _find_linac_log_subdir(entry.path)
        except Exception:
            pass
        if not matched:
            return None
    return current if (os.path.exists(current)) else None


def resolve_folder_path(raw_path: str) -> Optional[str]:
    """
    Intelligently resolves a user-entered folder path string into an existing absolute directory path.
    Handles:
      - Trailing and leading whitespace, single/double quotes, and backticks.
      - URL prefixes like file:/// or file://.
      - Paths missing Windows drive letters (e.g., 'Users\\CGutierrez\\Desktop\\AL5LOGS\\LOGS' -> 'C:\\Users\\...').
      - Variations with spaces vs no spaces (e.g., 'AL5 LOGS' vs 'AL5LOGS').
      - Forward and backward slash variations.
      - SDD zip files (e.g. 'AL5LOGS\\SDD+ELEKTA5+...zip' or pointing directly to .zip).
      - Tilde user expansion (~/Desktop/...).
      - Relative paths to User home, Desktop, current working directory, or project root.
      - Subfolder auto-detection (e.g., pointing to 'AL5LOGS' auto-resolves to 'AL5LOGS\\LOGS').
    Returns:
      Canonical absolute path to the directory containing logs if it exists, otherwise None.
    """
    if not raw_path:
        return None

    cleaned = str(raw_path).strip().strip('"\'`\u201c\u201d').strip()
    if not cleaned:
        return None

    # Handle file:// or file:/// URL prefixes
    if cleaned.lower().startswith("file:///"):
        cleaned = cleaned[8:]
        if os.name == "nt" and len(cleaned) > 2 and cleaned[0] == "/" and cleaned[2] == ":":
            cleaned = cleaned[1:]
    elif cleaned.lower().startswith("file://"):
        cleaned = cleaned[7:]

    # Expand ~
    expanded = os.path.expanduser(cleaned)

    # 1. Standard direct check (directory or file/zip)
    norm = os.path.abspath(os.path.normpath(expanded))
    if os.path.exists(norm):
        return _find_linac_log_subdir(norm)
    if os.path.exists(norm + ".zip"):
        return _find_linac_log_subdir(norm + ".zip")

    stripped = cleaned.lstrip(r"\/")
    parts = [p for p in re.split(r'[\\/]+', stripped) if p]

    # 2. Windows drive resolution (e.g. user entered 'Users\...\Desktop\...' or '\Users\...')
    if os.name == "nt" or "\\" in cleaned or "/" in cleaned:
        sys_drive = os.environ.get("SystemDrive", "C:").rstrip(":")
        cwd_drive = os.path.splitdrive(os.getcwd())[0].rstrip(":")
        preferred_drives = [d for d in [sys_drive, cwd_drive, "C", "D", "E"] if d]
        seen_drives = set()
        ordered_drives = []
        for d in preferred_drives:
            if d.upper() not in seen_drives:
                seen_drives.add(d.upper())
                ordered_drives.append(d.upper())

        for letter in ordered_drives:
            cand = os.path.abspath(os.path.normpath(f"{letter}:\\{stripped}"))
            if os.path.exists(cand):
                return _find_linac_log_subdir(cand)
            if os.path.exists(cand + ".zip"):
                return _find_linac_log_subdir(cand + ".zip")
            fuz = _resolve_fuzzy_segments(f"{letter}:\\", parts)
            if fuz and os.path.exists(fuz):
                return _find_linac_log_subdir(fuz)

    # 3. User Home and Desktop relative resolution
    user_home = os.path.expanduser("~")
    desktop_dir = os.path.join(user_home, "Desktop")
    downloads_dir = os.path.join(user_home, "Downloads")
    documents_dir = os.path.join(user_home, "Documents")
    candidates_roots = [
        desktop_dir,
        user_home,
        downloads_dir,
        documents_dir,
        str(BASE_DIR),
        os.path.dirname(str(BASE_DIR)),
        LINACLOG_DIR,
    ]
    if _LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR):
        candidates_roots.insert(0, _LAST_LINAC_DIR)

    for root in candidates_roots:
        if not os.path.exists(root):
            continue
        cand_norm = os.path.abspath(os.path.normpath(os.path.join(root, stripped)))
        if os.path.exists(cand_norm):
            return _find_linac_log_subdir(cand_norm)
        if os.path.exists(cand_norm + ".zip"):
            return _find_linac_log_subdir(cand_norm + ".zip")
        fuz = _resolve_fuzzy_segments(root, parts)
        if fuz and os.path.exists(fuz):
            return _find_linac_log_subdir(fuz)

    return None


def discover_local_linac_folders() -> List[Dict[str, Any]]:
    """Discovers local directories and SDD archives on the host containing Elekta linac logs (ultra-fast scan)."""
    discovered = []
    seen = set()

    search_roots = [
        LINACLOG_DIR,
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        str(BASE_DIR),
    ]
    if _LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR):
        search_roots.insert(0, _LAST_LINAC_DIR)

    ignored_dir_names = {".git", "venv", ".venv", "node_modules", "__pycache__", "scripts", "static", "templates", "data", "tests"}

    def _check_and_add_folder(path: str, label: str):
        canonical = os.path.abspath(os.path.normpath(path))
        if canonical in seen or not os.path.isdir(canonical):
            return
        base_name = os.path.basename(canonical).lower()
        if base_name in ignored_dir_names or base_name.startswith("."):
            return

        trf_count = 0
        has_critical_signature = False
        total_logs = 0

        try:
            with os.scandir(canonical) as it:
                for entry in it:
                    if entry.is_file():
                        name_low = entry.name.lower()
                        if name_low.endswith(".trf"):
                            trf_count += 1
                            total_logs += 1
                        elif name_low.startswith("rt-udp") and name_low.endswith(".log"):
                            has_critical_signature = True
                            total_logs += 1
                        elif (name_low.startswith("audit") or "audit_trail" in name_low) and name_low.endswith(".txt"):
                            has_critical_signature = True
                            total_logs += 1
                        elif name_low == "rtdmanifest.txt" or name_low == "rtdregistry.txt":
                            has_critical_signature = True
                            total_logs += 1
                        elif name_low.startswith("elekta.ccp") and name_low.endswith(".log"):
                            has_critical_signature = True
                            total_logs += 1
                        elif name_low.startswith("opt") and name_low.endswith(".xml"):
                            has_critical_signature = True
                            total_logs += 1
                        elif name_low.startswith("log") and (not "." in name_low or name_low.split(".")[-1].isdigit()):
                            total_logs += 1
        except Exception:
            return

        if trf_count >= 2 or has_critical_signature or (total_logs >= 20 and trf_count >= 1):
            seen.add(canonical)
            discovered.append({
                "path": canonical,
                "label": label,
                "file_count_estimate": total_logs
            })

    for root in search_roots:
        if not os.path.exists(root):
            continue
        if os.path.isdir(root):
            _check_and_add_folder(root, os.path.basename(root) or root)
            try:
                with os.scandir(root) as it:
                    for sub in it:
                        if sub.is_dir() and sub.name.lower() not in ignored_dir_names and not sub.name.startswith("."):
                            _check_and_add_folder(sub.path, f"{os.path.basename(root)}/{sub.name}")
                            try:
                                with os.scandir(sub.path) as it2:
                                    for sub2 in it2:
                                        if sub2.is_dir() and sub2.name.lower() not in ignored_dir_names and not sub2.name.startswith("."):
                                            _check_and_add_folder(sub2.path, f"{os.path.basename(root)}/{sub.name}/{sub2.name}")
                            except Exception:
                                pass
            except Exception:
                pass

    discovered.sort(key=lambda x: x.get("file_count_estimate", 0), reverse=True)
    return discovered[:6]


@app.route("/api/linaclog/suggested-folders", methods=["GET"])
@limiter.limit("600 per hour")
def linaclog_suggested_folders():
    """Discovers available linac log directories on the local machine for 1-click selection."""
    try:
        suggestions = discover_local_linac_folders()
        return jsonify({"ok": True, "folders": suggestions}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/profile", methods=["GET"])
@limiter.limit("600 per hour")
def linaclog_profile():
    """Returns linac hardware identification, software version, and beam hours."""
    try:
        from log_engine import RTDManifestParser
        active_dir = _LAST_LINAC_DIR if (_LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR)) else LINACLOG_DIR
        manifest_path = os.path.join(active_dir, "RTDManifest.txt")
        if not os.path.exists(manifest_path) and active_dir != LINACLOG_DIR:
            manifest_path = os.path.join(LINACLOG_DIR, "RTDManifest.txt")

        if os.path.exists(manifest_path):
            parser = RTDManifestParser()
            res = parser.parse_file(manifest_path)
            return jsonify({"ok": True, "data": res.to_dict()}), 200
        return jsonify({"ok": False, "error": "Manifest file not found"}), 404
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/profile")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/files", methods=["GET"])
@limiter.limit("600 per hour")
def linaclog_files():
    """Lists categorized available log files in linaclog directory."""
    try:
        folder_param = request.args.get("folder")
        active_dir = LINACLOG_DIR
        if folder_param:
            resolved = resolve_folder_path(folder_param)
            if resolved and os.path.isdir(resolved):
                active_dir = resolved
        elif _LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR):
            active_dir = _LAST_LINAC_DIR

        if not os.path.exists(active_dir):
            return jsonify({"ok": True, "files": {}, "total": 0}), 200

        import glob
        categories = {
            "trf_treatment": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "*.trf"))[:25]],
            "rt_udp_telemetry": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "rt-udp.*.log"))],
            "audit_trail": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "*AUDIT*.TXT"))],
            "ccp_supervisor": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "Elekta.CCP*.log"))[:15]],
            "controller_log": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "LOG*")) if not os.path.splitext(f)[1]][:20],
            "optical_calibration": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "OPT*.xml"))],
            "rtd_manifest": [os.path.basename(f) for f in glob.glob(os.path.join(active_dir, "RTDManifest.txt"))],
        }
        total_count = sum(len(v) for v in categories.values())
        return jsonify({"ok": True, "categories": categories, "sampled_total": total_count, "folder": active_dir}), 200
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/files")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/parse", methods=["POST"])
@limiter.limit("600 per hour")
def linaclog_parse():
    """Parses an uploaded log file or an existing file from the linaclog directory."""
    try:
        from log_engine import parse_linac_log

        # 1. Check if a file was uploaded
        if "file" in request.files:
            file_obj = request.files["file"]
            if not file_obj.filename:
                raise ValidationError("Archivo adjunto sin nombre.")
            data = file_obj.read()
            max_rec = request.form.get("max_records", type=int) or 100
            res = parse_linac_log(data, filename=file_obj.filename, max_records=max_rec)
            return jsonify({"ok": res.success, "result": res.to_dict()}), 200

        # 2. Check JSON payload with file_name
        req_json = request.get_json(silent=True) or {}
        file_name = req_json.get("file_name", "")
        max_rec = req_json.get("max_records", 100)

        if not file_name:
            raise ValidationError("Debe proporcionar 'file_name' o subir un archivo en el campo 'file'.")

        clean_name = os.path.basename(file_name)
        active_dir = _LAST_LINAC_DIR if (_LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR)) else LINACLOG_DIR
        target_path = os.path.abspath(os.path.join(active_dir, clean_name))

        if not target_path.startswith(active_dir) and not target_path.startswith(LINACLOG_DIR):
            raise ValidationError("Acceso a ruta de archivo denegado (path traversal detectado).")

        if not os.path.exists(target_path):
            alt_path = os.path.abspath(os.path.join(LINACLOG_DIR, clean_name))
            if os.path.exists(alt_path):
                target_path = alt_path
            else:
                return jsonify({"ok": False, "error": f"Archivo no encontrado: {clean_name}"}), 404

        res = parse_linac_log(target_path, max_records=max_rec)
        return jsonify({"ok": res.success, "result": res.to_dict()}), 200

    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/parse")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/analyze-folder", methods=["GET", "POST"])
@limiter.limit("60 per minute")
def linaclog_analyze_folder():
    """Performs full forensic correlation and aggregation over a Linac log folder."""
    global _LAST_LINAC_ANALYSIS, _LAST_LINAC_DIR
    try:
        from log_engine import LinacFolderAnalyzer
        target_dir = _LAST_LINAC_DIR if (_LAST_LINAC_DIR and os.path.exists(_LAST_LINAC_DIR)) else LINACLOG_DIR
        max_audit = 5000
        max_trf = 200

        if request.method == "POST":
            req_json = request.get_json(silent=True) or {}
            custom_path = req_json.get("folder_path")
            if custom_path:
                resolved = resolve_folder_path(custom_path)
                if not resolved or not os.path.isdir(resolved):
                    if os.name != "nt" and (":\\" in custom_path or custom_path.startswith("Users") or "\\" in custom_path):
                        raise ValidationError(
                            f"La ruta '{custom_path}' pertenece al disco de tu computadora local, mientras que esta sesión se ejecuta en la nube (Render). "
                            "Por favor pulsa el botón '📂 Seleccionar Carpeta de Logs' para analizar tu carpeta al instante."
                        )
                    suggestions = [f["path"] for f in discover_local_linac_folders()][:3]
                    hint = f" Carpetas sugeridas encontradas en el equipo: {', '.join(suggestions)}" if suggestions else ""
                    raise ValidationError(f"Directorio no válido o inexistente: {custom_path}.{hint}")
                target_dir = resolved
                _LAST_LINAC_DIR = resolved
            max_audit = int(req_json.get("max_audit_records", 5000))
            max_trf = int(req_json.get("max_trf_records", 200))

        if not os.path.exists(target_dir):
            return jsonify({"ok": False, "error": f"Directorio linaclog no encontrado en {target_dir}"}), 404

        analyzer = LinacFolderAnalyzer(target_dir)
        result = analyzer.analyze(max_audit_records=max_audit, max_trf_records=max_trf)
        _LAST_LINAC_ANALYSIS = result
        _LAST_LINAC_DIR = analyzer.folder_path

        return jsonify({
            "ok": True,
            "data": result,
            "resolved_path": analyzer.folder_path
        }), 200
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/analyze-folder")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/upload-chunk", methods=["POST"])
@limiter.limit("1000 per hour")
def linaclog_upload_chunk():
    """Receives a batch/chunk of files for an ongoing upload session to prevent HTTP 413."""
    import tempfile
    import re
    try:
        session_id = request.form.get("session_id", "").strip()
        if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            raise ValidationError("ID de sesión de carga inválido o no provisto.")
        
        session_dir = os.path.join(tempfile.gettempdir(), f"solvi_session_{session_id}")
        os.makedirs(session_dir, exist_ok=True)

        uploaded_files = request.files.getlist("files") or request.files.getlist("files[]")
        if not uploaded_files:
            raise ValidationError("No se recibieron archivos en este lote de carga.")

        saved_count = 0
        for f in uploaded_files:
            if not f.filename:
                continue
            base_fname = os.path.basename(f.filename)
            if not base_fname:
                continue
            dest_path = os.path.join(session_dir, base_fname)
            f.save(dest_path)
            saved_count += 1

        return jsonify({
            "ok": True,
            "session_id": session_id,
            "files_saved": saved_count
        }), 200
    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/upload-chunk")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500


@app.route("/api/linaclog/finalize-upload", methods=["POST"])
@limiter.limit("60 per hour")
def linaclog_finalize_upload():
    """Finalizes an upload session, correlates all files, and returns executive dashboard data."""
    global _LAST_LINAC_ANALYSIS
    import tempfile
    import shutil
    import re
    from log_engine import LinacFolderAnalyzer

    req_json = request.get_json(silent=True) or {}
    session_id = str(req_json.get("session_id", "")).strip()
    if not session_id or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
        return jsonify({"ok": False, "error": "validation_error", "message": "ID de sesión inválido"}), 400

    session_dir = os.path.join(tempfile.gettempdir(), f"solvi_session_{session_id}")
    if not os.path.exists(session_dir) or not os.path.isdir(session_dir):
        return jsonify({"ok": False, "error": "not_found", "message": "Sesión de carga expirada o inexistente"}), 404

    try:
        max_audit = int(req_json.get("max_audit_records", 5000))
        max_trf = int(req_json.get("max_trf_records", 200))

        analyzer = LinacFolderAnalyzer(session_dir)
        result = analyzer.analyze(max_audit_records=max_audit, max_trf_records=max_trf)
        _LAST_LINAC_ANALYSIS = result

        saved_files_count = len(os.listdir(session_dir))
        return jsonify({
            "ok": True,
            "data": result,
            "files_processed": saved_files_count
        }), 200
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/finalize-upload")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500
    finally:
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass


@app.route("/api/linaclog/upload-folder", methods=["POST"])
@limiter.limit("60 per hour")
def linaclog_upload_folder():
    """Receives multiple files uploaded from a browser directory selector and analyzes them."""
    global _LAST_LINAC_ANALYSIS
    import tempfile
    import shutil
    from log_engine import LinacFolderAnalyzer

    temp_dir = tempfile.mkdtemp(prefix="solvi_linac_upload_")
    try:
        uploaded_files = request.files.getlist("files") or request.files.getlist("files[]")
        if not uploaded_files:
            raise ValidationError("No se recibieron archivos en la carga de carpeta.")

        saved_count = 0
        for f in uploaded_files:
            if not f.filename:
                continue
            base_fname = os.path.basename(f.filename)
            if not base_fname:
                continue
            dest_path = os.path.join(temp_dir, base_fname)
            f.save(dest_path)
            saved_count += 1

        if saved_count == 0:
            raise ValidationError("No se pudieron guardar archivos válidos de la carpeta.")

        max_audit = request.form.get("max_audit_records", type=int) or 5000
        max_trf = request.form.get("max_trf_records", type=int) or 200

        analyzer = LinacFolderAnalyzer(temp_dir)
        result = analyzer.analyze(max_audit_records=max_audit, max_trf_records=max_trf)
        _LAST_LINAC_ANALYSIS = result

        return jsonify({"ok": True, "data": result, "files_processed": saved_count}), 200

    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/upload-folder")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@app.route("/api/linaclog/upload-zip", methods=["POST"])
@limiter.limit("60 per hour")
def linaclog_upload_zip():
    """Receives a single SDD zip archive, extracts linac logs, and performs full forensic analysis."""
    global _LAST_LINAC_ANALYSIS
    import tempfile
    import shutil
    import zipfile
    from log_engine import LinacFolderAnalyzer

    if "file" not in request.files and "zip" not in request.files:
        return jsonify({"ok": False, "error": "validation_error", "message": "No se recibió ningún archivo .zip."}), 400

    zip_file = request.files.get("file") or request.files.get("zip")
    if not zip_file or not zip_file.filename:
        return jsonify({"ok": False, "error": "validation_error", "message": "Archivo .zip inválido."}), 400

    temp_dir = tempfile.mkdtemp(prefix="solvi_linac_zip_upload_")
    try:
        zip_temp_path = os.path.join(temp_dir, "upload.zip")
        zip_file.save(zip_temp_path)

        if not zipfile.is_zipfile(zip_temp_path):
            raise ValidationError("El archivo subido no es un archivo .zip válido.")

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        log_exts = (".trf", ".log", ".txt", ".xml", ".dat")
        saved_count = 0
        with zipfile.ZipFile(zip_temp_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir() or member.filename.startswith("__MACOSX"):
                    continue
                name = os.path.basename(member.filename)
                if not name:
                    continue
                low = name.lower()
                if (
                    low.endswith(log_exts)
                    or low.startswith("log")
                    or low.startswith("elekta")
                    or low.startswith("rt-udp")
                    or "manifest" in low
                    or "audit" in low
                ):
                    target_file = os.path.join(extract_dir, name)
                    with zf.open(member) as source, open(target_file, "wb") as target:
                        target.write(source.read())
                    saved_count += 1

        if saved_count == 0:
            raise ValidationError("El archivo .zip no contiene registros compatibles de Linac Elekta.")

        max_audit = request.form.get("max_audit_records", type=int) or 5000
        max_trf = request.form.get("max_trf_records", type=int) or 200

        analyzer = LinacFolderAnalyzer(extract_dir)
        result = analyzer.analyze(max_audit_records=max_audit, max_trf_records=max_trf)
        _LAST_LINAC_ANALYSIS = result

        return jsonify({"ok": True, "data": result, "files_processed": saved_count}), 200

    except ValidationError as val_err:
        return jsonify({"ok": False, "error": "validation_error", "message": str(val_err)}), 400
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/upload-zip")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@app.route("/api/linaclog/export-excel", methods=["GET", "POST"])
@limiter.limit("120 per hour")
def linaclog_export_excel():
    """Generates and downloads a multi-sheet Excel audit report (.xlsx)."""
    global _LAST_LINAC_ANALYSIS
    import io
    import datetime
    from log_engine import LinacExcelExporter, LinacFolderAnalyzer

    try:
        if not LinacExcelExporter.is_available():
            return jsonify({
                "ok": False,
                "error": "openpyxl no está disponible en el servidor. Instale openpyxl para exportar en Excel."
            }), 503

        data_to_export = None
        if request.method == "POST":
            req_json = request.get_json(silent=True) or {}
            data_to_export = req_json.get("analysis_data")

        if not data_to_export:
            data_to_export = _LAST_LINAC_ANALYSIS

        if not data_to_export:
            if os.path.exists(LINACLOG_DIR):
                analyzer = LinacFolderAnalyzer(LINACLOG_DIR)
                data_to_export = analyzer.analyze()
                _LAST_LINAC_ANALYSIS = data_to_export
            else:
                return jsonify({
                    "ok": False,
                    "error": "No hay análisis de Linac previo ni carpeta linaclog disponible para exportar."
                }), 404

        excel_buffer = io.BytesIO()
        LinacExcelExporter.export(data_to_export, output=excel_buffer)
        excel_buffer.seek(0)

        linac_id = str(data_to_export.get("profile", {}).get("linac_id") or "4574")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Auditoria_Linac_{linac_id}_{timestamp}.xlsx"

        return send_file(
            excel_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        app.logger.exception("Error en /api/linaclog/export-excel")
        return jsonify({"ok": False, "error": _sanitize_error_message(exc)}), 500




if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug_requested = os.environ.get("FLASK_DEBUG") == "1"
    is_loopback = host in ("127.0.0.1", "localhost", "::1")
    # P1-6: Prevenir que debug=True se ejecute si el host está expuesto fuera de loopback
    debug_mode = debug_requested and is_loopback
    if debug_requested and not is_loopback:
        app.logger.warning("FLASK_DEBUG deshabilitado por seguridad: el host '%s' no es loopback.", host)
    app.run(host=host, port=port, debug=debug_mode)
