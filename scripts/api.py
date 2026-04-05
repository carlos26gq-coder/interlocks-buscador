"""
api.py — Interlocks Buscador Técnico v6
- Contraseña admin robusta
- Notas en data/notes.json (sin Supabase)
- PDFs en Cloudflare R2 (URL pública configurable)
- Sin dependencias opcionales que puedan fallar
"""

from flask import Flask, request, jsonify, render_template, send_from_directory, make_response
from flask_cors import CORS
from pathlib import Path
import json, os, uuid
from action_extractor import extract_action

# ════════════════════════════════════════════════════════
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ── Contraseña admin ──
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "elekta2025").strip()

# ── URL base de Cloudflare R2 (ej: https://pub-xxx.r2.dev) ──
# Sin barra al final. Si no está configurada, el botón PDF no aparece.
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")

# ── Paths ──
BASE_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = BASE_DIR / "data"
PAGES_DIR  = DATA_DIR / "pages"
DATA_PATH  = DATA_DIR / "all_manuals.json"
NOTES_PATH = DATA_DIR / "notes.json"

# Cargar índice de manuales
with open(DATA_PATH, "r", encoding="utf-8") as f:
    manuals = json.load(f)

print(f"✅ {len(manuals)} páginas cargadas")
print(f"🔑 Admin password: {'env' if os.environ.get('ADMIN_PASSWORD') else 'default'}")
print(f"☁️  R2 URL: {R2_PUBLIC_URL or 'no configurada'}")

# ════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════

def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]  = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

def check_pw(pw):
    return pw.strip() == ADMIN_PASSWORD

# ── Notas en JSON local (data/notes.json) ──
def notes_load():
    if NOTES_PATH.exists():
        with open(NOTES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def notes_save(notes):
    with open(NOTES_PATH, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def note_create(title, text, tags):
    note = {
        "id":    str(uuid.uuid4()),
        "title": title.strip(),
        "text":  text.strip(),
        "tags":  [t.strip() for t in tags if t.strip()]
    }
    notes = notes_load()
    notes.append(note)
    notes_save(notes)
    return note

def note_update(nid, title, text, tags):
    notes = notes_load()
    for n in notes:
        if n["id"] == nid:
            n["title"] = title.strip()
            n["text"]  = text.strip()
            n["tags"]  = [t.strip() for t in tags if t.strip()]
    notes_save(notes)

def note_delete(nid):
    notes_save([n for n in notes_load() if n["id"] != nid])

# ════════════════════════════════════════════════════════
#  FRONTEND
# ════════════════════════════════════════════════════════

@app.route("/")
def home():
    return no_cache(make_response(render_template("index.html")))

@app.route("/reset")
def reset():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Limpiando caché...</title>
<style>body{background:#0b0f1a;color:#e2e8f0;font-family:sans-serif;display:flex;
flex-direction:column;align-items:center;justify-content:center;min-height:100vh;
gap:16px;text-align:center}.s{width:40px;height:40px;border:3px solid #1e293b;
border-top-color:#00d4ff;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}p{color:#64748b;font-size:.9rem}
</style></head><body><div class="s"></div><h2>⚡ Limpiando caché...</h2>
<p>Serás redirigido automáticamente.</p>
<script>(async()=>{
const k=await caches.keys();await Promise.all(k.map(c=>caches.delete(c)));
const r=await navigator.serviceWorker.getRegistrations();
await Promise.all(r.map(x=>x.unregister()));
window.location.replace('/?nocache='+Date.now());
})();</script></body></html>"""
    return no_cache(make_response(html))

@app.route("/manifest.json")
def manifest():
    return no_cache(send_from_directory(BASE_DIR, "manifest.json",
                                        mimetype="application/manifest+json"))

@app.route("/sw.js")
def service_worker():
    r = send_from_directory(BASE_DIR, "sw.js", mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    return r

@app.route("/data/<path:filename>")
def serve_data(filename):
    return send_from_directory(DATA_DIR, filename)

# ════════════════════════════════════════════════════════
#  API — BÚSQUEDA
# ════════════════════════════════════════════════════════

@app.route("/search")
def search():
    keyword = request.args.get("q", "").lower().strip()
    mfilter = request.args.get("manual", "").lower().strip()
    if not keyword:
        return jsonify({"results": [], "r2_url": R2_PUBLIC_URL})

    results = []

    # Buscar en manuales
    for page in manuals:
        if mfilter and mfilter != "apuntes" and page["manual"].lower() != mfilter:
            continue
        tl = page["text"].lower()
        if keyword not in tl:
            continue
        pos = tl.find(keyword)
        ctx = page["text"][max(0, pos-80):min(len(page["text"]), pos+120)]
        ctx = ctx.replace("\n", " ").strip()
        results.append({
            "type":    "manual",
            "manual":  page["manual"],
            "page":    page["page"],
            "context": ctx,
            "action":  extract_action(page["text"], keyword)
                       or "Revisar sección completa del manual"
        })

    # Buscar en apuntes
    if not mfilter or mfilter == "apuntes":
        for note in notes_load():
            blob = (note["title"] + " " + note["text"] + " " +
                    " ".join(note.get("tags", []))).lower()
            if keyword in blob:
                results.append({
                    "type":    "note",
                    "id":      note["id"],
                    "manual":  "apuntes",
                    "page":    note["title"],
                    "context": note["text"][:220],
                    "action":  "Apunte personal",
                    "tags":    note.get("tags", [])
                })

    return jsonify({"results": results, "r2_url": R2_PUBLIC_URL})

# ════════════════════════════════════════════════════════
#  API — NOTAS
# ════════════════════════════════════════════════════════

@app.route("/notes", methods=["GET"])
def get_notes():
    return jsonify(notes_load())

@app.route("/notes", methods=["POST"])
def create_note():
    d = request.get_json(force=True)
    return jsonify(note_create(
        d.get("title", "Sin título"),
        d.get("text", ""),
        d.get("tags", [])
    )), 201

@app.route("/notes/<nid>", methods=["PUT"])
def update_note(nid):
    d = request.get_json(force=True)
    note_update(nid, d.get("title",""), d.get("text",""), d.get("tags",[]))
    return jsonify({"ok": True})

@app.route("/notes/<nid>", methods=["DELETE"])
def delete_note(nid):
    note_delete(nid)
    return jsonify({"ok": True})

# ════════════════════════════════════════════════════════
#  API — ADMIN
# ════════════════════════════════════════════════════════

@app.route("/admin/check", methods=["POST"])
def admin_check():
    d  = request.get_json(force=True)
    pw = d.get("password", "").strip()
    if check_pw(pw):
        return jsonify({"ok": True, "r2_configured": bool(R2_PUBLIC_URL)})
    return jsonify({"ok": False}), 403

@app.route("/admin/manuals")
def list_manuals():
    pw = request.args.get("password", "").strip()
    if not check_pw(pw):
        return jsonify({"error": "Contraseña incorrecta"}), 403
    counts = {}
    for p in manuals:
        counts[p["manual"]] = counts.get(p["manual"], 0) + 1
    return jsonify([{"manual": k, "pages": v} for k, v in sorted(counts.items())])

@app.route("/admin/config")
def admin_config():
    """Devuelve configuración no sensible para mostrar en Admin."""
    pw = request.args.get("password", "").strip()
    if not check_pw(pw):
        return jsonify({"error": "Contraseña incorrecta"}), 403
    return jsonify({
        "r2_configured": bool(R2_PUBLIC_URL),
        "r2_url":        R2_PUBLIC_URL or "No configurada",
        "total_pages":   len(manuals),
        "total_manuals": len(set(p["manual"] for p in manuals)),
        "notes_count":   len(notes_load()),
    })

# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
