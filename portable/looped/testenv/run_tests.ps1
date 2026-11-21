<#
.SYNOPSIS
Runs the Looped Mode scenarios in an isolated container project.

.DESCRIPTION
Everything runs in the compose project "looped-test": a throwaway Agent Zero,
a scripted stub model, and a driver, on a private network with no internet,
no published ports and no GPU. No real model is contacted.

The script never stops, restarts, removes or changes a container, network or
volume outside the "looped-test" project. It checks first and stops with a
report if anything it needs is already taken.

.PARAMETER WhatIf
Print the checks and every action that would be taken, then exit. Changes nothing.

.PARAMETER Only
Run only these scenarios (names from scenarios.py).

.PARAMETER Keep
Leave the test containers running afterwards, for inspection. Remove them
later with: run_tests.ps1 -Down

.PARAMETER Down
Only remove the test project's containers, network and run folder.

.PARAMETER Reuse
If the test containers are already running (from -Keep), reuse them instead of
starting fresh ones: only the plugin files are refreshed. Faster while debugging.

.PARAMETER SeedTokenizerFrom
Name of an existing container to copy Agent Zero's tokenizer cache from, once.
This is a read-only copy; that container is not changed. Needed because the
test network has no internet to download the tokenizer file.

.EXAMPLE
.\run_tests.ps1 -WhatIf
.EXAMPLE
.\run_tests.ps1 -Only 01_agree,02_tiebreak
#>
param(
    [switch]$WhatIf,
    [string[]]$Only = @(),
    [switch]$Keep,
    [switch]$Down,
    [switch]$Reuse,
    [string]$SeedTokenizerFrom = ''
)

$ErrorActionPreference = 'Continue'
$Project = 'looped-test'
$Network = 'looped-test-net'
$Names = @('looped-test-a0', 'looped-test-llm', 'looped-test-driver')
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Compose = Join-Path $Here 'docker-compose.yml'
$RunDir = Join-Path $Here '.run'
$Package = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Here))) 'plugins\looped'
$Image = if ($env:LOOPED_TEST_IMAGE) { $env:LOOPED_TEST_IMAGE } else { 'agent0ai/agent-zero:latest' }

function Write-Step([string]$Text) { Write-Host "  - $Text" }
function Stop-WithReport([string]$Text) {
    Write-Host ""
    Write-Host "STOPPED: $Text" -ForegroundColor Red
    Write-Host "Nothing was started or changed."
    exit 2
}

# The only place that changes Docker state. It is always scoped to the test project.
function Invoke-TestCompose {
    $arguments = @('compose', '-p', $Project, '-f', $Compose) + $args
    & docker @arguments | Out-Host
    return $LASTEXITCODE
}

function Get-OtherContainers {
    # Every container except this project's, as "id name image state" lines.
    $lines = & docker ps -a --no-trunc --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.State}}'
    return @($lines | Where-Object { $_ -and (($_ -split '\|')[1] -notlike 'looped-test-*') } | Sort-Object)
}

function Get-GpuProcesses {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return @('nvidia-smi not available') }
    return @(& nvidia-smi --query-compute-apps=pid,name --format=csv,noheader 2>$null | Sort-Object)
}

function Remove-RunFolder {
    if (-not (Test-Path $RunDir)) { return }
    $resolved = (Resolve-Path $RunDir).Path
    if (-not $resolved.StartsWith((Resolve-Path $Here).Path, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-WithReport "run folder resolves outside the test project: $resolved"
    }
    $usr = Join-Path $resolved 'usr'
    if (Test-Path $usr) { Remove-Item -LiteralPath $usr -Recurse -Force -Confirm:$false }
}

Write-Host "Looped Mode isolated tests (project '$Project')"
Write-Host ""
Write-Host "Preflight (read-only):"

& docker version --format '{{.Server.Version}}' *> $null
if ($LASTEXITCODE -ne 0) { Stop-WithReport 'Docker is not running or not reachable.' }
Write-Step 'Docker is reachable'

if ($Down) {
    Write-Host ""
    Write-Host "Removing the '$Project' project only:"
    if ($WhatIf) {
        Write-Step "would run: docker compose -p $Project down --volumes --remove-orphans"
        Write-Step "would delete: $RunDir\usr"
        exit 0
    }
    Invoke-TestCompose --profile run down --volumes --remove-orphans | Out-Null
    Remove-RunFolder
    Write-Host "Done."
    exit 0
}

& docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithReport "image '$Image' is not available locally. This script never pulls images."
}
Write-Step "image '$Image' is local (no pull needed)"

if (-not (Test-Path (Join-Path $Package 'plugin.yaml'))) {
    Stop-WithReport "assembled plugin not found at $Package. Run: python portable/looped/assemble.py"
}
Write-Step "assembled plugin found at $Package"

$TokenizerCache = Join-Path $Here 'seed\tiktoken-cache'
if ($SeedTokenizerFrom) {
    # A read-only copy out of an existing container; that container is not changed.
    if ($WhatIf) {
        Write-Step "would copy the tokenizer cache out of '$SeedTokenizerFrom' (read-only) to $TokenizerCache"
    } else {
        New-Item -ItemType Directory -Force -Path $TokenizerCache | Out-Null
        & docker cp "${SeedTokenizerFrom}:/tmp/data-gym-cache/." $TokenizerCache
        if ($LASTEXITCODE -ne 0) { Stop-WithReport "could not copy the tokenizer cache from '$SeedTokenizerFrom'." }
    }
}
if (-not $WhatIf -or -not $SeedTokenizerFrom) {
    if (-not (Test-Path $TokenizerCache) -or -not (Get-ChildItem -LiteralPath $TokenizerCache -File -ErrorAction SilentlyContinue)) {
        Stop-WithReport ("the tokenizer cache is missing at $TokenizerCache. Agent Zero downloads it on first use, " +
            "but the test network has no internet. Copy it once from a container that has run before: " +
            ".\run_tests.ps1 -SeedTokenizerFrom <container name>  (a read-only copy).")
    }
    Write-Step 'tokenizer cache is present (the test network has no internet)'
}

foreach ($name in $Names) {
    $owner =& docker ps -a --filter "name=^/$name$" --format '{{.Label \"com.docker.compose.project\"}}'
    if ($owner -and ($owner -ne $Project)) {
        Stop-WithReport "a container named '$name' already exists and belongs to '$owner', not to this test project."
    }
    $exists = & docker ps -a --filter "name=^/$name$" --format '{{.Names}}'
    if ($exists -and -not $owner) {
        Stop-WithReport "a container named '$name' already exists and was not created by this test project."
    }
}
Write-Step "container names $($Names -join ', ') are free or belong to this project"

$networkOwner = & docker network ls --filter "name=^$Network$" --format '{{.Label \"com.docker.compose.project\"}}'
$networkExists = & docker network ls --filter "name=^$Network$" --format '{{.Name}}'
if ($networkExists -and ($networkOwner -ne $Project)) {
    Stop-WithReport "a network named '$Network' already exists and does not belong to this test project."
}
Write-Step "network '$Network' is free or belongs to this project"

$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
if ($os) {
    $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    if ($freeGb -lt 6) {
        Stop-WithReport "only $freeGb GB of memory is free; the test Agent Zero may use up to 8 GB. Free some memory and run again."
    }
    Write-Step "$freeGb GB of memory is free (the test containers are capped at 9 GB in total)"
}

$before = Get-OtherContainers
$gpuBefore = Get-GpuProcesses
Write-Step "$($before.Count) other container(s) on this machine will be left untouched:"
foreach ($line in $before) {
    $parts = $line -split '\|'
    Write-Host "      $($parts[1])  [$($parts[3])]  $($parts[2])"
}

Write-Host ""
Write-Host "Plan:"
Write-Step "create $RunDir\usr with the plugin, a stub-model preset, and memory/infection-check switched off"
Write-Step "start looped-test-llm (stub model) and looped-test-a0 (Agent Zero) on the private network '$Network'"
Write-Step "no host ports, no internet, no GPU, no real model; CPU and memory are capped"
if ($Only.Count -gt 0) { Write-Step "run scenarios: $($Only -join ', ')" } else { Write-Step 'run all scenarios in scenarios.py' }
if ($Keep) { Write-Step 'leave the test containers running (-Keep)' }
else { Write-Step "remove the '$Project' containers, network and $RunDir\usr; keep $RunDir\results" }
Write-Step 'compare the other containers and GPU processes before and after'

if ($WhatIf) {
    Write-Host ""
    Write-Host "Dry run only: nothing was started or changed."
    exit 0
}

$usr = Join-Path $RunDir 'usr'
$running = & docker ps --filter "name=^/looped-test-a0$" --filter "label=com.docker.compose.project=$Project" --format '{{.Names}}'
$reusing = $Reuse -and $running
Write-Host ""
if ($reusing) {
    Write-Host "Reusing the running test containers (-Reuse); refreshing the plugin files..."
    Copy-Item -Path (Join-Path $Package '*') -Destination (Join-Path $usr 'plugins\looped') -Recurse -Force
} else {
Write-Host "Preparing the run folder..."
Invoke-TestCompose --profile run down --volumes --remove-orphans *> $null
Remove-RunFolder
New-Item -ItemType Directory -Force -Path (Join-Path $usr 'plugins') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RunDir 'results') | Out-Null
Copy-Item -Path $Package -Destination (Join-Path $usr 'plugins\looped') -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $usr 'plugins\_model_config') | Out-Null
Copy-Item -Path (Join-Path $Here 'seed\presets.yaml') -Destination (Join-Path $usr 'plugins\_model_config\presets.yaml') -Force
foreach ($plugin in @('_memory', '_infection_check')) {
    $folder = Join-Path $usr "plugins\$plugin"
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Set-Content -LiteralPath (Join-Path $folder '.toggle-0') -Value '' -Encoding ascii
}
}
$oldResults = Join-Path $RunDir 'results\results.json'
if (Test-Path $oldResults) { Remove-Item -LiteralPath $oldResults -Force -Confirm:$false }

$env:LOOPED_TEST_ONLY = ($Only -join ',')
Write-Host "Starting the test containers..."
$code = Invoke-TestCompose up -d looped-test-llm looped-test-a0
if ($code -ne 0) {
    Invoke-TestCompose --profile run down --volumes --remove-orphans *> $null
    Stop-WithReport 'the test containers did not start; the test project was removed again.'
}

Write-Host "Running the scenarios (Agent Zero's first start takes a few minutes)..."
$code = Invoke-TestCompose --profile run run --rm looped-test-driver
$result = $code

if ($result -ne 0) {
    Write-Host ""
    Write-Host "Last Agent Zero log lines:"
    & docker logs --tail 40 looped-test-a0
}

if ($Keep) {
    Write-Host ""
    Write-Host "Test containers left running (-Keep). Remove them with: .\run_tests.ps1 -Down"
} else {
    Write-Host ""
    Write-Host "Removing the test project..."
    Invoke-TestCompose --profile run down --volumes --remove-orphans *> $null
    Remove-RunFolder
}

Write-Host ""
Write-Host "Isolation check:"
$after = Get-OtherContainers
$gpuAfter = Get-GpuProcesses
$missing = @($before | Where-Object { $after -notcontains $_ })
$appeared = @($after | Where-Object { $before -notcontains $_ })
if ($missing.Count -gt 0) {
    Write-Host "  Containers that existed before the run changed or are gone:" -ForegroundColor Yellow
    foreach ($line in $missing) { $parts = $line -split '\|'; Write-Host "      $($parts[1])  [$($parts[3])]" }
    Write-Host "  (This script only acts on '$Project'; something else on the machine changed them.)"
} else {
    Write-Step "all $($before.Count) container(s) that existed before the run are unchanged"
}
if ($appeared.Count -gt 0) {
    Write-Step "$($appeared.Count) unrelated container(s) were started or changed by something else during the run:"
    foreach ($line in $appeared) { $parts = $line -split '\|'; Write-Host "      $($parts[1])  [$($parts[3])]" }
}
$gpuDiff = Compare-Object -ReferenceObject $gpuBefore -DifferenceObject $gpuAfter
if ($gpuDiff) {
    # Informational: the test containers are given no GPU, so any difference
    # comes from other programs on the machine starting or stopping.
    Write-Step 'the test containers have no GPU access; GPU processes of other programs changed during the run:'
    foreach ($item in $gpuDiff) {
        $what = if ($item.SideIndicator -eq '=>') { 'started' } else { 'ended' }
        Write-Host "      $what`: $($item.InputObject)"
    }
} else {
    Write-Step 'GPU processes are unchanged (the test containers have no GPU access)'
}
if (-not $Keep) {
    $left = & docker ps -a --filter "label=com.docker.compose.project=$Project" --format '{{.Names}}'
    if ($left) { Write-Host "  Left behind: $left" -ForegroundColor Yellow } else { Write-Step "no '$Project' container remains" }
}

$resultsFile = Join-Path $RunDir 'results\results.json'
Write-Host ""
if (Test-Path $resultsFile) { Write-Host "Results: $resultsFile" }
if ($result -eq 0) { Write-Host "All scenarios passed." -ForegroundColor Green }
else { Write-Host "Scenarios failed or did not run (exit code $result)." -ForegroundColor Red }
exit $result
