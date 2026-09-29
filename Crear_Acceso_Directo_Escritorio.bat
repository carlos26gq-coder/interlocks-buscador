@echo off
setlocal
cd /d "%~dp0"

echo Creando acceso directo de SOLVI en tu Escritorio...

if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0scripts\crear_acceso_directo.py"
) else (
    python "%~dp0scripts\crear_acceso_directo.py"
)

echo.
echo Listo! Ya puedes abrir SOLVI directamente desde tu Escritorio con 1 clic.
echo.
pause
