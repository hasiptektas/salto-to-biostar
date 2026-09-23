$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyInstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path -LiteralPath $pyInstaller)) {
    throw "PyInstaller bulunamadı. Önce: .\.venv\Scripts\python.exe -m pip install pyinstaller"
}

& $pyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name SaltoBioStar `
    --paths (Join-Path $projectRoot "src") `
    --collect-all keyring `
    (Join-Path $projectRoot "src\app.py")

Write-Host "EXE hazır: $projectRoot\dist\SaltoBioStar\SaltoBioStar.exe"
