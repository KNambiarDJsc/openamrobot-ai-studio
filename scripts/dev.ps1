# Start the API (port 8000) and the web app (port 3000). Ctrl+C stops both.
# Reads .env if present; environment variables already set take precedence.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -match '^\s*([A-Z_]+)=(.*)$' } | ForEach-Object {
    $k, $v = $Matches[1], $Matches[2]
    if (-not [Environment]::GetEnvironmentVariable($k)) { [Environment]::SetEnvironmentVariable($k, $v) }
  }
}
$api = Start-Process -FilePath .\.venv\Scripts\python.exe -NoNewWindow -PassThru `
  -ArgumentList "-m","uvicorn","studio_api.app:create_app","--factory","--host","127.0.0.1","--port","8000"
try {
  Push-Location apps/web
  npx next dev -H 127.0.0.1 -p 3000
} finally {
  Pop-Location
  Stop-Process -Id $api.Id -ErrorAction SilentlyContinue
}
