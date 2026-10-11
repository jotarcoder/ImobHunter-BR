$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[1/5] Checking Python..." -ForegroundColor Cyan
$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($PythonCommand) {
    & py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'; print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or newer was not found through the py launcher. Install Python 3.11+ and retry."
    }
    $Python = "py"
    $PythonArgs = @("-3")
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python 3.11+ is required. Install it from https://www.python.org/downloads/windows/"
    }
    & python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'; print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "The installed Python is older than 3.11."
    }
    $Python = "python"
    $PythonArgs = @()
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[2/5] Creating local virtual environment..." -ForegroundColor Cyan
    & $Python @PythonArgs -m venv ".venv"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
} else {
    Write-Host "[2/5] Reusing existing .venv..." -ForegroundColor Cyan
}

Write-Host "[3/5] Installing project test dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $VenvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

Write-Host "[4/5] Compiling Python modules..." -ForegroundColor Cyan
& $VenvPython -m compileall -q imobhunter tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation check failed." }

Write-Host "[5/5] Running tests and lint..." -ForegroundColor Cyan
& $VenvPython -m pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Do not publish; fix the reported failures first." }
& $VenvPython -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff reported issues. Do not publish until they are fixed." }

Write-Host "PASS: local compile, tests, and lint completed successfully." -ForegroundColor Green
Write-Host "This validates local Python checks only; it does not validate installers or cloud deployments."
