param(
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $projectRoot

function Find-Python312 {
    if ($env:SOLVI_PYTHON312 -and (Test-Path -LiteralPath $env:SOLVI_PYTHON312)) {
        return (Resolve-Path -LiteralPath $env:SOLVI_PYTHON312).Path
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidate = (& $launcher.Source -3.12 -c "import sys; print(sys.executable)").Trim()
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $python = Get-Command python3.12 -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "No se encontró Python 3.12. Instálalo o define SOLVI_PYTHON312 con la ruta absoluta."
}

$python312 = Find-Python312
& $python312 --version
if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $python312 -m venv $VenvPath
}
$venvPython = Join-Path $VenvPath "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --requirement requirements-dev.txt
& $venvPython -m pip check
Write-Host "Bootstrap SOLVI listo en $((Resolve-Path $VenvPath).Path)"
