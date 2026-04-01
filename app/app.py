from flask import Flask, send_from_directory
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "scripts" / "static"),
    template_folder=str(BASE_DIR / "scripts" / "templates")
)

@app.route("/")
def index():
    return send_from_directory(BASE_DIR / "scripts" / "templates", "index.html")

@app.route("/data/<path:filename>")
def data_files(filename):
    return send_from_directory(BASE_DIR / "data", filename)

@app.route("/manifest.json")
def manifest():
    return send_from_directory(BASE_DIR, "manifest.json")

@app.route("/sw.js")
def sw():
    return send_from_directory(BASE_DIR, "sw.js")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)