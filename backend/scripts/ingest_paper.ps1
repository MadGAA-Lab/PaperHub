# Smoke test: POST /papers twice for the same arxiv_id; assert cache_hit on second call.
# No LLM needed — only hits the arxiv API + local ingest pipeline.
# Usage: .\scripts\ingest_paper.ps1 [arxiv_id]    (default: 1706.03762 — Vaswani transformer)
$ErrorActionPreference = "Stop"

# ── 1. Load backend/.env ──────────────────────────────────────────────────────
$backendDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$envFile = Join-Path $backendDir ".env"
if (-not (Test-Path $envFile)) {
    throw "Missing $envFile. Copy backend/.env.example to backend/.env (no API key required for this script)."
}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if (($val.StartsWith('"') -and $val.EndsWith('"')) -or
        ($val.StartsWith("'") -and $val.EndsWith("'"))) {
        $val = $val.Substring(1, $val.Length - 2)
    }
    if ($val -ne "") { Set-Item -Path "env:$key" -Value $val }
}

# ── 2. Isolated workspace ─────────────────────────────────────────────────────
$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace\smoke-ingest"
if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

# ── 3. Pre-flight: port 8767 must be free ─────────────────────────────────────
$portInUse = $false
try {
    $tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8767)
    $tcp.Start(); $tcp.Stop()
} catch { $portInUse = $true }
if ($portInUse) {
    throw "Port 8767 already in use. Kill the orphan process and retry."
}

# ── 4. Boot uvicorn ───────────────────────────────────────────────────────────
$server = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backendDir `
    uv -ArgumentList @("run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8767")

try {
    # ── 5. Wait for /health (30 s) ────────────────────────────────────────────
    $healthy = $false
    for ($i = 0; $i -lt 150; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8767/health -ErrorAction Stop | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    if (-not $healthy) { throw "Server did not become healthy within 30 s." }
    Write-Host "Server up on :8767."

    # ── 6. Pre-create chat_sessions rows 1 and 2 ──────────────────────────────
    $dbPath = Join-Path $env:PAPERHUB_WORKSPACE "paperhub.db"
    # Wait briefly for the lifespan migration to finish writing the DB.
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-Path $dbPath) { break }
        Start-Sleep -Milliseconds 200
    }
    & uv run --project $backendDir python -c @'
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (1, 'smoke-1')")
conn.execute("INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (2, 'smoke-2')")
conn.commit()
conn.close()
'@ $dbPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to pre-create chat_sessions rows." }

    # ── 7. Assertions ─────────────────────────────────────────────────────────
    $arxivId = if ($args.Count -gt 0) { $args[0] } else { "1706.03762" }
    Write-Host "Testing ingest of arxiv_id=$arxivId ..."

    # First ingest — must be a cache miss.
    $first = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8767/papers" `
        -ContentType "application/json" `
        -Body (@{ session_id = 1; arxiv_id = $arxivId } | ConvertTo-Json -Compress)
    if ($first.cache_hit) {
        throw "ASSERTION: first ingest must be cache_miss, got cache_hit=true"
    }
    Write-Host "first ingest OK — paper_content_id=$($first.paper_content_id), title=$($first.title)"

    # Second ingest — must be a cache hit and complete in < 500 ms.
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $second = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8767/papers" `
        -ContentType "application/json" `
        -Body (@{ session_id = 2; arxiv_id = $arxivId } | ConvertTo-Json -Compress)
    $sw.Stop()
    if (-not $second.cache_hit) {
        throw "ASSERTION: second ingest must be cache_hit=true"
    }
    if ($second.paper_content_id -ne $first.paper_content_id) {
        throw "ASSERTION: same paper_content_id expected; got $($second.paper_content_id) vs $($first.paper_content_id)"
    }
    if ($sw.Elapsed.TotalMilliseconds -ge 500) {
        throw "ASSERTION I-8 #2: second ingest took $([int]$sw.Elapsed.TotalMilliseconds)ms (>= 500ms threshold)"
    }
    Write-Host "second ingest OK — cache_hit=true, $([int]$sw.Elapsed.TotalMilliseconds)ms (< 500ms threshold)"
    Write-Host "PASS: ingest_paper smoke test complete."

} finally {
    # Kill the entire uvicorn process tree.
    & taskkill.exe /F /T /PID $server.Id 2>&1 | Out-Null
    # Clean up isolated workspace.
    if (Test-Path $env:PAPERHUB_WORKSPACE) {
        Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE -ErrorAction SilentlyContinue
    }
}
