param(
  [string]$Port = "5000"
)

Write-Host "[local] Creating venv (.venv) if missing..."
if (!(Test-Path .venv)) {
  py -3 -m venv .venv
}

Write-Host "[local] Activating venv..."
& .\.venv\Scripts\Activate.ps1

Write-Host "[local] Upgrading pip and installing requirements..."
python -m pip install -U pip
python -m pip install -r requirements.txt

Write-Host "[local] Starting Flask on port $Port..."
$env:FLASK_APP = "app.py"
Start-Job -ScriptBlock { flask run } | Out-Null
Start-Sleep -Seconds 3

Write-Host "[local] Smoke tests..."
try {
  Invoke-RestMethod "http://127.0.0.1:5000/health/notion" | ConvertTo-Json -Depth 4 | Write-Host
  Invoke-RestMethod "http://127.0.0.1:5000/get-masterindex" | ConvertTo-Json -Depth 4 | Write-Host
} catch {
  Write-Host "[local] Smoke test failed: $_" -ForegroundColor Yellow
}

Write-Host "[local] To stop Flask: Get-Job | Remove-Job -Force"

