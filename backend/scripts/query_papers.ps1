# Smoke test: ingest two papers, send a comparative /chat question, assert paper_qa
# routes and cites >= 2 distinct paper_content rows via [chunk:N] markers.
# Requires a real LLM key (GEMINI_API_KEY or equivalent) in backend/.env.
# Usage: .\scripts\query_papers.ps1
$ErrorActionPreference = "Stop"

# ── 1. Load backend/.env ──────────────────────────────────────────────────────
$backendDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$envFile = Join-Path $backendDir ".env"
if (-not (Test-Path $envFile)) {
    throw "Missing $envFile. Copy backend/.env.example to backend/.env and fill in your API key."
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

# ── Real-flow guard ───────────────────────────────────────────────────────────
$paperQaModel = if ($env:PAPERHUB_PAPER_QA_MODEL) { $env:PAPERHUB_PAPER_QA_MODEL } else { "gemini/gemini-2.5-pro" }
$needsKey = @{
    "gemini"    = "GEMINI_API_KEY"
    "openai"    = "OPENAI_API_KEY"
    "anthropic" = "ANTHROPIC_API_KEY"
}
$provider = ($paperQaModel -split "/", 2)[0]
$keyName  = $needsKey[$provider]
if ($keyName -and -not (Get-Item -Path "env:$keyName" -ErrorAction SilentlyContinue).Value) {
    throw "Model '$paperQaModel' requires env var '$keyName'. Set it in backend/.env."
}

# ── 2. Isolated workspace ─────────────────────────────────────────────────────
$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace\smoke-query"
if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

# Clear any lingering mock vars.
Remove-Item Env:PAPERHUB_ROUTER_MOCK   -ErrorAction SilentlyContinue
Remove-Item Env:PAPERHUB_CHITCHAT_MOCK -ErrorAction SilentlyContinue

# ── 3. Pre-flight: port 8768 must be free ─────────────────────────────────────
$portInUse = $false
try {
    $tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8768)
    $tcp.Start(); $tcp.Stop()
} catch { $portInUse = $true }
if ($portInUse) {
    throw "Port 8768 already in use. Kill the orphan process and retry."
}

# ── 4. Boot uvicorn ───────────────────────────────────────────────────────────
$server = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backendDir `
    uv -ArgumentList @("run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8768")

try {
    # ── 5. Wait for /health (30 s) ────────────────────────────────────────────
    $healthy = $false
    for ($i = 0; $i -lt 150; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8768/health -ErrorAction Stop | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    if (-not $healthy) { throw "Server did not become healthy within 30 s." }
    Write-Host "Server up on :8768."

    # ── 6. Pre-create chat_sessions row 3 ─────────────────────────────────────
    $dbPath = Join-Path $env:PAPERHUB_WORKSPACE "paperhub.db"
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-Path $dbPath) { break }
        Start-Sleep -Milliseconds 200
    }
    & uv run --project $backendDir python -c @'
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (3, 'smoke-query')")
conn.commit()
conn.close()
'@ $dbPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to pre-create chat_sessions row." }

    # ── 7. Ingest two distinct papers into session 3 ──────────────────────────
    Write-Host "Ingesting paper 1: 1706.03762 (Attention Is All You Need)..."
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8768/papers" `
        -ContentType "application/json" `
        -Body (@{ session_id = 3; arxiv_id = "1706.03762" } | ConvertTo-Json -Compress) | Out-Null

    Write-Host "Ingesting paper 2: 2104.09864 (RoFormer)..."
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8768/papers" `
        -ContentType "application/json" `
        -Body (@{ session_id = 3; arxiv_id = "2104.09864" } | ConvertTo-Json -Compress) | Out-Null

    Write-Host "Both papers ingested. Sending comparative chat query..."

    # ── 8. POST /chat and capture SSE stream ──────────────────────────────────
    $body = @{ session_id = 3; user_message = "Compare the positional encoding methods used in these two papers" } |
        ConvertTo-Json -Compress
    $tmpBody = Join-Path $env:TEMP "smoke_query_body.json"
    [System.IO.File]::WriteAllText($tmpBody, $body)

    # Use curl.exe for SSE — Invoke-RestMethod buffers the whole response.
    $sseRaw = & curl.exe -N -s -X POST http://127.0.0.1:8768/chat `
        -H "Content-Type: application/json" `
        --data-binary "@$tmpBody"
    if ($LASTEXITCODE -ne 0) { throw "curl.exe failed with exit code $LASTEXITCODE." }

    Write-Host "`n--- Raw SSE (truncated) ---"
    Write-Host ($sseRaw | Select-Object -First 30 | Out-String)

    # ── 9. Parse SSE — extract final event content ────────────────────────────
    # SSE format: lines of "event: <type>" and "data: <json>", blank-line separated.
    $final = $null
    $currentEvent = $null
    foreach ($line in ($sseRaw -split "`n")) {
        $line = $line.TrimEnd("`r")
        if ($line.StartsWith("event:")) {
            $currentEvent = $line.Substring(6).Trim()
        } elseif ($line.StartsWith("data:") -and $currentEvent -eq "final") {
            $dataJson = $line.Substring(5).Trim()
            try {
                $obj = $dataJson | ConvertFrom-Json
                $final = $obj.content
            } catch {
                # Not valid JSON on this data line; keep scanning.
            }
        } elseif ($line -eq "") {
            $currentEvent = $null
        }
    }

    if (-not $final) {
        throw "ASSERTION: No 'final' SSE event found in response. Raw output:`n$sseRaw"
    }
    Write-Host "`n--- Final content (first 500 chars) ---"
    Write-Host $final.Substring(0, [Math]::Min(500, $final.Length))

    # ── 10. Assert v2.10 paper_qa trace shape ─────────────────────────────────
    # The agentic hierarchical pipeline (Plan C v2.10) emits these tool_step
    # events: paper_qa:resolve (always), paper_qa:subagent (one per enabled
    # paper, in parallel), paper_qa:finalize (always). The old map-reduce
    # path emitted paper_qa:map + paper_qa:synthesize — those names should
    # NEVER appear in a v2.10 trace.
    $traceToolNames = @()
    $currentEvent = $null
    foreach ($line in ($sseRaw -split "`n")) {
        $line = $line.TrimEnd("`r")
        if ($line.StartsWith("event:")) {
            $currentEvent = $line.Substring(6).Trim()
        } elseif ($line.StartsWith("data:") -and $currentEvent -eq "tool_step") {
            try {
                $obj = $line.Substring(5).Trim() | ConvertFrom-Json
                if ($obj.record -and $obj.record.tool) {
                    $traceToolNames += $obj.record.tool
                }
            } catch {
                # Not a parseable tool_step payload; skip.
            }
        } elseif ($line -eq "") {
            $currentEvent = $null
        }
    }

    foreach ($expected in @("paper_qa:resolve", "paper_qa:subagent", "paper_qa:finalize")) {
        if ($traceToolNames -notcontains $expected) {
            throw "ASSERTION (v2.10): expected tool_step '$expected' missing from trace. Saw: $($traceToolNames -join ', ')"
        }
    }
    $subagentCount = ($traceToolNames | Where-Object { $_ -eq "paper_qa:subagent" }).Count
    if ($subagentCount -lt 2) {
        throw "ASSERTION (v2.10): expected >= 2 'paper_qa:subagent' steps (one per enabled paper), got $subagentCount"
    }
    foreach ($legacy in @("paper_qa:map", "paper_qa:synthesize", "paper_qa:single")) {
        if ($traceToolNames -contains $legacy) {
            throw "ASSERTION (v2.10): legacy map-reduce tool_step '$legacy' present in trace — v2.10 should NOT emit this"
        }
    }
    Write-Host "v2.10 trace OK — resolve + $subagentCount subagent + finalize, no legacy map-reduce steps"

    # ── 11. Assert >= 2 [chunk:N] markers spanning >= 2 distinct papers ───────
    $chunkIds = [regex]::Matches($final, '\[chunk:(\d+)\]') | ForEach-Object { [int]$_.Groups[1].Value }
    if ($chunkIds.Count -lt 2) {
        throw "ASSERTION: expected >= 2 [chunk:N] markers, got $($chunkIds.Count). Final content:`n$final"
    }
    $inList = ($chunkIds | ForEach-Object { $_ }) -join ","
    $db = $dbPath

    $paperIdsRaw = & uv run --project $backendDir python -c @'
import sqlite3, sys
db, ids = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(db)
rows = conn.execute(f"SELECT DISTINCT paper_content_id FROM chunks WHERE id IN ({ids})").fetchall()
for r in rows:
    print(r[0])
conn.close()
'@ $db $inList
    if ($LASTEXITCODE -ne 0) { throw "SQLite query for distinct paper_content_ids failed." }

    $paperIds = @($paperIdsRaw | Where-Object { $_ -ne "" } | Sort-Object -Unique)
    if ($paperIds.Count -lt 2) {
        throw "ASSERTION I-8 #3: citations span < 2 distinct paper_content rows (found: $($paperIds -join ', '))"
    }

    Write-Host "paper_qa OK — $($chunkIds.Count) chunk citations across $($paperIds.Count) papers (ids: $($paperIds -join ', '))"
    Write-Host "PASS: query_papers smoke test complete."

} finally {
    & taskkill.exe /F /T /PID $server.Id 2>&1 | Out-Null
    if (Test-Path $env:PAPERHUB_WORKSPACE) {
        Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE -ErrorAction SilentlyContinue
    }
}
