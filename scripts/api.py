"""SOLVI - API de búsqueda técnica, diagnóstico y apuntes."""

from __future__ import annotations

from functools import wraps
import json
import os
from pathlib import Path
import secrets
import time
import uuid

from flask import Flask, jsonify, make_response, render_template, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import Client, create_client
from werkzeug.middleware.proxy_fix import ProxyFix

from search_engine import SearchEngine, normalize


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_PATH = DATA_DIR / "all_manuals.json"
MAX_QUERY_LENGTH = 200
MAX_NOTE_TITLE = 200
MAX_NOTE_TEXT = 20_000
MAX_TAGS = 20
MAX_TAG_LENGTH = 50
NOTES_CACHE_SECONDS = 30

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
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
    return response


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
    if not value and generate:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("El identificador del apunte no es válido.") from exc


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
    _notes_cache["loaded_at"] = 0.0
    _notes_cache["data"] = []


def notes_load(*, force: bool = False) -> list[dict]:
    if not supabase:
        return []
    now = time.monotonic()
    if not force and now - _notes_cache["loaded_at"] < NOTES_CACHE_SECONDS:
        return list(_notes_cache["data"])
    try:
        response = supabase.table("notes").select("*").execute()
        data = response.data if isinstance(response.data, list) else []
        _notes_cache["loaded_at"] = now
        _notes_cache["data"] = data
        return list(data)
    except Exception:
        app.logger.exception("Error al leer apuntes de Supabase")
        return list(_notes_cache["data"])


def note_search(query: str) -> list[dict]:
    normalized_query = normalize(query)
    results = []
    for note in notes_load():
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
    return jsonify({"error": str(error)}), 400


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify({"error": "La solicitud supera el tamaño permitido."}), 413


@app.errorhandler(429)
def handle_rate_limit(error):
    return jsonify({"error": "Demasiadas solicitudes. Intenta nuevamente en unos minutos."}), 429


@app.route("/")
def home():
    return no_cache(make_response(render_template("index.html", build_time=BUILD_TIME)))


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
    })


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    manual_filter = request.args.get("manual", "").strip().lower()
    if not query:
        return jsonify({"results": [], "total": 0, "offset": 0, "limit": 25, "has_more": False, "r2_url": R2_PUBLIC_URL})
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationError(f"La búsqueda admite hasta {MAX_QUERY_LENGTH} caracteres.")
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(50, max(1, int(request.args.get("limit", 25))))
    except ValueError as exc:
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
@limiter.limit("60 per hour")
def diagnose():
    data = json_body()
    signals = {
        "interlock": bounded_text(data, "interlock", 100),
        "error": bounded_text(data, "error", 100),
        "message": bounded_text(data, "message", 300),
        "observations": bounded_text(data, "observations", 500),
    }
    result = search_engine.diagnose(signals, limit=6)
    result["r2_url"] = R2_PUBLIC_URL
    return jsonify(result)


@app.route("/notes", methods=["GET"])
def get_notes():
    return jsonify(notes_load()), 200


@app.route("/notes", methods=["POST"])
@limiter.limit("30 per hour")
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
    except Exception:
        app.logger.exception("Error al crear un apunte")
        return jsonify({"error": "No se pudo guardar el apunte en la nube."}), 502


@app.route("/notes/<nid>", methods=["PUT"])
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
@require_admin
def list_manuals():
    return jsonify([
        {"manual": manual, "pages": len(document_ids)}
        for manual, document_ids in sorted(search_engine.manuals.items())
    ])


@app.route("/admin/config")
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
