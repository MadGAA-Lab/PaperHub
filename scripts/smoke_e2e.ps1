# End-to-end smoke: boot backend (mocked LLM) + Vite, verify chitchat SSE round-trip, tear down.
# Exit 0 on success, non-zero on any failed assertion.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

$expectedFinal = "Hi from PaperHub! (e2e smoke)"
$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace_smoke_e2e"
$env:PAPERHUB_ROUTER_MOCK = '{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"e2e smoke"}'
$env:PAPERHUB_CHITCHAT_MOCK = $expectedFinal

if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

# Free ports 8000 and 5173 if anything is already listening on them.
function Kill-Port([int]$port) {
    $pids = (netstat -ano | Select-String ":$port\s") |
        ForEach-Object { ($_ -split '\s+')[-1] } |
        Where-Object { $_ -match '^\d+$' } |
        Select-Object -Unique
    foreach ($p in $pids) {
        Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
    }
}
Kill-Port 8000
Kill-Port 5173
Start-Sleep -Milliseconds 300   # let OS reclaim sockets

Push-Location $backendDir
$backend = Start-Process -PassThru -NoNewWindow uv -ArgumentList @(
    "run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8000"
)
Pop-Location

Push-Location $frontendDir
$npmCmd = if ($IsWindows -or $env:OS -eq "Windows_NT") { "npm.cmd" } else { "npm" }
# Pass --port 5173 so Vite doesn't silently pick an alternate port.
$frontend = Start-Process -PassThru -NoNewWindow $npmCmd -ArgumentList @("run", "dev", "--", "--port", "5173")
Pop-Location

$exitCode = 1
try {
    # Wait for backend /health
    $backendReady = $false
    for ($i = 0; $i -lt 50; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8000/health -ErrorAction Stop | Out-Null
            $backendReady = $true
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $backendReady) { throw "Backend did not come up on :8000" }

    # Wait for Vite root (Vite listens on localhost which may resolve to [::1] on Windows)
    $frontendReady = $false
    for ($i = 0; $i -lt 50; $i++) {
        try {
            (Invoke-WebRequest http://localhost:5173 -UseBasicParsing -ErrorAction Stop).StatusCode | Out-Null
            $frontendReady = $true
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $frontendReady) { throw "Frontend did not come up on :5173" }

    Write-Host "Both servers up. Posting /chat..."

    # Issue the chat request through curl and capture SSE
    $tmpBody = Join-Path $env:TEMP "smoke_e2e_body.json"
    [System.IO.File]::WriteAllText($tmpBody, '{"user_message":"hello"}')
    $sseRaw = & curl.exe -N -s -X POST http://127.0.0.1:8000/chat `
        -H "Content-Type: application/json" `
        --data-binary "@$tmpBody"

    # Parse expected events
    $eventCounts = @{}
    foreach ($line in $sseRaw -split "`r?`n") {
        if ($line -match "^event:\s*(.+)$") {
            $name = $matches[1].Trim()
            if ($eventCounts.ContainsKey($name)) {
                $eventCounts[$name] = $eventCounts[$name] + 1
            } else {
                $eventCounts[$name] = 1
            }
        }
    }

    Write-Host "Events received: $(($eventCounts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', ')"

    if (-not $eventCounts.ContainsKey("routing_decision")) {
        throw "Missing routing_decision event"
    }
    if (-not $eventCounts.ContainsKey("tool_step") -or $eventCounts["tool_step"] -lt 2) {
        throw "Expected >=2 tool_step events, got $($eventCounts['tool_step'])"
    }
    if (-not $eventCounts.ContainsKey("token") -or $eventCounts["token"] -lt 1) {
        throw "Expected >=1 token event"
    }
    if (-not $eventCounts.ContainsKey("final")) {
        throw "Missing final event"
    }

    # Verify final content
    $finalLine = ($sseRaw -split "`r?`n") | Where-Object { $_ -match '^data:.*"content":"' } | Select-Object -Last 1
    if (-not ($finalLine -match [regex]::Escape($expectedFinal))) {
        throw "Final content does not contain expected string '$expectedFinal'. Got: $finalLine"
    }

    Write-Host "All assertions passed." -ForegroundColor Green
    $exitCode = 0
} catch {
    Write-Host "SMOKE FAILED: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    & taskkill.exe /F /T /PID $backend.Id 2>&1 | Out-Null
    & taskkill.exe /F /T /PID $frontend.Id 2>&1 | Out-Null
}

exit $exitCode
