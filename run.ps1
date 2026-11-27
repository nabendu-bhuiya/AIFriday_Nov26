# Starts TrialLens locally: FastAPI backend (port 8000) + React UI (port 5173)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$root\.env")) { Write-Host "Missing .env - copy .env.example to .env and add your LLM key." -ForegroundColor Yellow }
if (-not (Test-Path "$root\frontend\node_modules")) { Push-Location "$root\frontend"; npm install; Pop-Location }
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; python -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\frontend'; npm run dev"
Start-Sleep -Seconds 6
Start-Process 'http://localhost:5173'
