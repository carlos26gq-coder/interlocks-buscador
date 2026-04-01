"""
api.py  — Interlocks Buscador Técnico  v3
+ Apuntes personales  + Subida de PDFs  + Supabase (opcional)
"""

from flask import Flask, request, jsonify, render_template, send_from_directory, make_response
from flask_cors import CORS
from pathlib import Path
import json, os, uuid, re
from action_extractor import extract_action

# ── PDF processing ──
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ── Supabase (opcional, solo si están las variables de entorno) ──
USE_SUPABASE = False
supabase     = None
try:
    from supabase import create_client
    _url = os.environ.get("SUPABASE_URL", "")
    _key = os.environ.get("SUPABASE_KEY", "")
    if _url and _key:
        supabase     = create_client(_url, _key)
        USE_SUPABASE = True
        print("✅ Supabase conectado")
except ImportError:
    pass

# ════════════════════════════════════════════════════════
#  FLASK
# ════════════════════════════════════════════════════════

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)
CORS(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "elekta2025")

BASE_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = BASE_DIR / "data"
PAGES_DIR  = DATA_DIR / "pages"
DATA_PATH  = DATA_DIR / "all_manuals.json"
NOTES_PATH = DATA_DIR / "notes.json"
UPLOAD_DIR = BASE_DIR / "manuals"
UPLOAD_DIR.mkdir(exist_ok=True)
PAGES_DIR.mkdir(exist_ok=True)

with open(DATA_PATH, "r", encoding="utf-8") as f:
    manuals = json.load(f)

# ════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════

def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]  = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ── Notas: Supabase o JSON local ──

def notes_load():
    if USE_SUPABASE:
        return supabase.table("notes").select("*").execute().data or []
    if NOTES_PATH.exists():
        with open(NOTES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def _notes_save(notes):
    with open(NOTES_PATH, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def notes_create(title, text, tags):
    note = {"id": str(uuid.uuid4()), "title": title.strip(),
            "text": text.strip(), "tags": [t.strip() for t in tags if t.strip()]}
    if USE_SUPABASE:
        supabase.table("notes").insert(note).execute()
    else:
        data = notes_load(); data.append(note); _notes_save(data)
    return note

def notes_update(nid, title, text, tags):
    upd = {"title": title.strip(), "text": text.strip(),
           "tags": [t.strip() for t in tags if t.strip()]}
    if USE_SUPABASE:
        supabase.table("notes").update(upd).eq("id", nid).execute()
    else:
        data = notes_load()
        for n in data:
            if n["id"] == nid: n.update(upd)
        _notes_save(data)
    return upd

def notes_delete(nid):
    if USE_SUPABASE:
        supabase.table("notes").delete().eq("id", nid).execute()
    else:
        _notes_save([n for n in notes_load() if n["id"] != nid])

# ── PDF ──

def pdf_to_pages(pdf_path, manual_name):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"manual": manual_name.lower().strip(),
                               "page": i, "text": text})
    return pages

def rebuild_index():
    global manuals
    all_pages = []
    for jf in sorted(PAGES_DIR.glob("*_pages.json")):
        with open(jf, "r", encoding="utf-8") as f:
            all_pages.extend(json.load(f))
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(all_pages, f, ensure_ascii=False, indent=2)
    manuals = all_pages
    return len(all_pages)

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
<script>(async()=>{const k=await caches.keys();
await Promise.all(k.map(c=>caches.delete(c)));
const r=await navigator.serviceWorker.getRegistrations();
await Promise.all(r.map(x=>x.unregister()));
window.location.replace('/?v='+Date.now());})();</script></body></html>"""
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
        return jsonify({"results": []})

    results = []

    # Manuales
    for page in manuals:
        if mfilter and mfilter != "apuntes" and page["manual"].lower() != mfilter:
            continue
        tl = page["text"].lower()
        if keyword not in tl:
            continue
        pos   = tl.find(keyword)
        ctx   = page["text"][max(0,pos-80):min(len(page["text"]),pos+120)]
        ctx   = ctx.replace("\n"," ").strip()
        results.append({
            "type":    "manual",
            "manual":  page["manual"],
            "page":    page["page"],
            "context": ctx,
            "action":  extract_action(page["text"], keyword)
                       or "Revisar sección completa del manual"
        })

    # Apuntes
    if not mfilter or mfilter == "apuntes":
        for note in notes_load():
            blob = (note["title"]+" "+note["text"]+" "+" ".join(note.get("tags",[]))).lower()
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

    return jsonify({"results": results})

# ════════════════════════════════════════════════════════
#  API — APUNTES
# ════════════════════════════════════════════════════════

@app.route("/notes", methods=["GET"])
def get_notes():
    return jsonify(notes_load())

@app.route("/notes", methods=["POST"])
def create_note():
    d = request.get_json(force=True)
    return jsonify(notes_create(d.get("title","Sin título"),
                                d.get("text",""), d.get("tags",[]))), 201

@app.route("/notes/<nid>", methods=["PUT"])
def update_note(nid):
    d = request.get_json(force=True)
    return jsonify(notes_update(nid, d.get("title",""),
                                d.get("text",""), d.get("tags",[])))

@app.route("/notes/<nid>", methods=["DELETE"])
def delete_note(nid):
    notes_delete(nid)
    return jsonify({"ok": True})

# ════════════════════════════════════════════════════════
#  API — ADMIN: subir PDF
# ════════════════════════════════════════════════════════

@app.route("/admin/upload", methods=["POST"])
def upload_pdf():
    if request.form.get("password","") != ADMIN_PASSWORD:
        return jsonify({"error": "Contraseña incorrecta"}), 403
    if not PDF_AVAILABLE:
        return jsonify({"error": "Instala pdfplumber: pip install pdfplumber --break-system-packages"}), 500
    file = request.files.get("pdf")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Sube un archivo PDF válido"}), 400

    manual_name = request.form.get("manual_name","").strip()
    if not manual_name:
        manual_name = Path(file.filename).stem.lower().replace(" ","_")

    safe = re.sub(r"[^\w\-]","_", manual_name)
    pdf_path = UPLOAD_DIR / f"{safe}.pdf"
    file.save(str(pdf_path))

    try:
        pages = pdf_to_pages(str(pdf_path), manual_name)
    except Exception as e:
        return jsonify({"error": f"Error procesando PDF: {e}"}), 500

    pages_path = PAGES_DIR / f"{safe}_pages.json"
    with open(pages_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    total = rebuild_index()
    return jsonify({"ok": True, "manual": manual_name,
                    "pages": len(pages), "total_pages": total})

@app.route("/admin/manuals")
def list_manuals():
    if request.args.get("password","") != ADMIN_PASSWORD:
        return jsonify({"error": "Contraseña incorrecta"}), 403
    counts = {}
    for p in manuals:
        counts[p["manual"]] = counts.get(p["manual"], 0) + 1
    return jsonify([{"manual":k,"pages":v} for k,v in sorted(counts.items())])

# ════════════════════════════════════════════════════════
#  RUN
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
