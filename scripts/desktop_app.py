"""
SOLVI Desktop Application Launcher
Permite ejecutar SOLVI como una aplicación de escritorio nativa 100% offline en Windows.
Inicia el motor Flask en segundo plano y abre la interfaz en modo ventana independiente (Chrome/Edge App Mode).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

PORT = int(os.environ.get("PORT", 5000))
HOST = "127.0.0.1"
BASE_URL = f"http://{HOST}:{PORT}"


def is_server_running(host: str = HOST, port: int = PORT) -> bool:
    """Verifica si el servidor SOLVI ya está activo y respondiendo en el puerto."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_local_server():
    """Inicia el servidor Flask de SOLVI en un hilo daemon."""
    from api import app

    # Desactivar logs ruidosos de werkzeug en consola
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def find_browser_app_executable() -> tuple[str | None, str]:
    """Busca Microsoft Edge o Google Chrome en rutas estándar de Windows para ejecutar en modo --app."""
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    for p in edge_paths:
        if os.path.isfile(p):
            return p, "msedge"

    for p in chrome_paths:
        if os.path.isfile(p):
            return p, "chrome"

    return None, "default"


def launch_desktop_ui():
    """Abre la ventana de aplicación de escritorio."""
    exe_path, browser_name = find_browser_app_executable()

    if exe_path:
        app_arg = f"--app={BASE_URL}"
        # Parámetros optimizados para rendimiento nativo de escritorio
        cmd = [
            exe_path,
            app_arg,
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-name=SOLVI Linac Forensic Suite",
        ]
        try:
            return subprocess.Popen(cmd)
        except Exception as exc:
            print(f"[Aviso] No se pudo iniciar {browser_name} en modo app: {exc}. Abriendo navegador predeterminado...")

    # Fallback al navegador web estándar
    webbrowser.open(BASE_URL)
    return None


def main():
    print("=" * 60)
    print(" ⚡ SOLVI — Suite Técnica y Forense para Aceleradores Elekta")
    print("    Modo de Escritorio Local 100% Offline")
    print("=" * 60)

    if not is_server_running():
        print(f"[*] Iniciando servidor técnico en {BASE_URL}...")
        server_thread = threading.Thread(target=start_local_server, daemon=True)
        server_thread.start()

        # Esperar hasta que el servidor responda
        max_wait = 20
        started = False
        for _ in range(max_wait * 10):
            if is_server_running():
                started = True
                break
            time.sleep(0.1)

        if not started:
            print(f"[ERROR] El servidor no pudo iniciar en {BASE_URL}. Verifica que el puerto {PORT} esté libre.")
            sys.exit(1)
        print("[OK] Motor de diagnóstico y búsqueda local iniciado exitosamente.")
    else:
        print(f"[OK] Servidor local ya activo en {BASE_URL}.")

    print("[*] Abriendo ventana de aplicación SOLVI...")
    proc = launch_desktop_ui()

    print("\n[+] SOLVI está listo para usar.")
    print("    - Lectura instantánea en disco SSD (0s de subida).")
    print("    - 100% offline (sin necesidad de internet en el búnker).")
    print("    - Para cerrar el programa, cierra esta ventana o presiona Ctrl+C.\n")

    try:
        if proc:
            proc.wait()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Cerrando SOLVI Desktop...")
        sys.exit(0)


if __name__ == "__main__":
    main()
