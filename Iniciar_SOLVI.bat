@echo off
setlocal
title SOLVI — Linac Forensic Suite (Modo Local Offline)
cd /d "%~dp0"

echo ============================================================
echo  ⚡ SOLVI — Suite Tecnica y Forense para Aceleradores Elekta
echo     Modo de Escritorio Local 100%% Offline
echo ============================================================
echo.

:: 1. Buscar entorno virtual local
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0venv\Scripts\python.exe"
    goto :RUN
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    goto :RUN
)

:: 2. Buscar Python en el PATH del sistema
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=python"
    goto :RUN
)

echo [ERROR] No se encontro Python ni el entorno virtual venv.
echo Por favor ejecuta una vez el instalador o crea el entorno:
echo python -m venv venv
echo.
pause
exit /b 1

:RUN
echo [*] Iniciando SOLVI con: %PY_EXE%
"%PY_EXE%" "%~dp0scripts\desktop_app.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [AVISO] La aplicacion se cerro con codigo %ERRORLEVEL%.
    pause
)
