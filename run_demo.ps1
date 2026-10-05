# One-command local demo for Windows PowerShell:  .\run_demo.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
python scripts\simulate_fleet.py --direct --reset --days 14
$api = Start-Process -PassThru -NoNewWindow python -ArgumentList "-m","uvicorn","app.main:app","--port","8000"
Set-Location "$root\frontend"
if (-not (Test-Path node_modules)) { npm install }
Write-Host "Dashboard: http://localhost:5173   API docs: http://localhost:8000/docs"
try { npm run dev } finally { Stop-Process -Id $api.Id }
