"""
Crea un acceso directo en el Escritorio de Windows para SOLVI.
"""

import os
import sys
from pathlib import Path


def create_desktop_shortcut():
    root = Path(__file__).resolve().parent.parent
    target_bat = root / "Iniciar_SOLVI.bat"
    icon_path = root / "scripts" / "static" / "favicon.ico"
    desktop_dir = Path(os.path.expanduser("~/Desktop"))

    shortcut_path = desktop_dir / "SOLVI — Linac Forensic Suite.lnk"

    # Script en VBScript para crear el archivo .lnk oficial de Windows
    vbs_script = f"""
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_bat}"
oLink.WorkingDirectory = "{root}"
oLink.Description = "SOLVI — Suite Técnica y Forense para Aceleradores Elekta"
oLink.IconLocation = "{icon_path}, 0"
oLink.WindowStyle = 1
oLink.Save
"""
    vbs_path = root / "scripts" / "_temp_create_shortcut.vbs"
    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_script)

        os.system(f'cscript //nologo "{vbs_path}"')
        print(f"[OK] Acceso directo creado en: {shortcut_path}")
    except Exception as exc:
        print(f"[ERROR] No se pudo crear acceso directo: {exc}")
    finally:
        if vbs_path.exists():
            try:
                vbs_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    create_desktop_shortcut()
