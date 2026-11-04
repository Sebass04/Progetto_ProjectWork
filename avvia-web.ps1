param([switch]$Install)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'

Push-Location -LiteralPath $projectDirectory
try {
    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Impossibile creare l'ambiente Python. Installa Python 3.11 o successivo." }
        $Install = $true
    }

    $dependenciesMissing = [bool]$Install
    if (-not $dependenciesMissing) {
        try {
            & $pythonExecutable -c "import importlib.util, sys; sys.exit(any(importlib.util.find_spec(name) is None for name in ('fastapi', 'uvicorn', 'langgraph', 'langchain_ollama', 'langchain_chroma', 'pypdf')))"
            $dependenciesMissing = $LASTEXITCODE -ne 0
        } catch { $dependenciesMissing = $true }
    }
    if ($dependenciesMissing) {
        & $pythonExecutable -m pip install -r requirements-web.txt
        if ($LASTEXITCODE -ne 0) { throw 'Installazione delle dipendenze Python non riuscita.' }
    }

    if ($Install -or -not (Test-Path -LiteralPath (Join-Path $projectDirectory 'frontend\dist\index.html'))) {
        Push-Location -LiteralPath (Join-Path $projectDirectory 'frontend')
        try {
            if ($Install -or -not (Test-Path -LiteralPath 'node_modules')) {
                npm.cmd ci --no-audit --no-fund
                if ($LASTEXITCODE -ne 0) { throw 'Installazione delle dipendenze frontend non riuscita.' }
            }
            npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Compilazione del frontend non riuscita.' }
        } finally { Pop-Location }
    }

    Write-Host ''
    Write-Host 'Salus Levante è disponibile su http://127.0.0.1:8000' -ForegroundColor Green
    Write-Host 'Lascia aperto questo terminale. Premi Ctrl+C per chiudere.'
    Write-Host ''
    & $pythonExecutable -m uvicorn api:app --host 127.0.0.1 --port 8000
} finally { Pop-Location }
