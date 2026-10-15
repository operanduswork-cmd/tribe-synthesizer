# TRIBE v2 tool: the only way to start Modal runs from this laptop.
# Checks the Modal account first (D4), then runs one step.
#
#   .\backend\tribe.ps1 check                  # account check only, no spend
#   .\backend\tribe.ps1 smoke                  # image + pins check (CPU, cents)
#   .\backend\tribe.ps1 weights                # one-time weight download (CPU)
#   .\backend\tribe.ps1 reel C:\path\reel.mp4 [-Label name] [-Gpu A10G|L40S|A100-80GB]
#   .\backend\tribe.ps1 reel https://www.instagram.com/reel/XXXX/   # public reels only, no login
#       (tries yt-dlp first; Instagram usually refuses that, so it falls back to Apify with
#        APIFY_TOKEN from .env, well under 1 cent per reel)
#   .\backend\tribe.ps1 rerun <job_id> -Precision bf16   # same normalised clip again (speed test)
#   -Precision: bf16 (default since 8 Oct 2026, D24) runs only the V-JEPA2 video model in bfloat16;
#   fp32 is upstream's full precision (COSTS-AND-TIMES 7d)
#
# Every run is logged in the ledger on the tribe-runs volume and refused past the
# monthly cap in Modal secret tribe-config (D12).
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("check", "smoke", "weights", "reel", "rerun")]
    [string]$Step,
    [Parameter(Position = 1)]
    [string]$VideoPath = "",
    [string]$Label = "",
    [ValidateSet("A10G", "L40S", "A100-80GB")]
    [string]$Gpu = "A10G",
    [ValidateSet("fp32", "bf16")]
    [string]$Precision = "bf16"
)
$ErrorActionPreference = "Stop"
# modal prints characters like U+2713; this laptop's cp1252 console crashes on them when output is piped.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$expected = $env:TRIBE_MODAL_PROFILE
if (-not $expected) { Write-Error "Set TRIBE_MODAL_PROFILE to the Modal profile you want to bill." }

if ($env:MODAL_TOKEN_ID -or $env:MODAL_TOKEN_SECRET) {
    Write-Error "MODAL_TOKEN_ID/MODAL_TOKEN_SECRET are set and would override the profile. Unset them first."
}
$active = (modal profile current).Trim()
if ($active -ne $expected) {
    Write-Error "Active Modal profile is '$active'. Run: modal profile activate $expected"
}
# Uses only the active profile's token (`modal profile list` would also sign in as another account).
$info = (modal token info | Out-String)
if ($info -notmatch 'Workspace:\s*(\S+)') {
    Write-Error "Could not read the Modal workspace from 'modal token info'."
}
if ($Matches[1] -ne $expected) {
    Write-Error "Profile $expected points at workspace '$($Matches[1])', expected '$expected'."
}
Write-Host "Modal account OK: profile and workspace are $expected"
if ($Step -eq "check") { exit 0 }

$app = Join-Path $PSScriptRoot "tribe_app.py"
$Gpu = "A10G", "L40S", "A100-80GB" | Where-Object { $_ -eq $Gpu }  # standard casing
$prevGpu = $env:TRIBE_GPU
$prevCpuOnly = $env:TRIBE_CPU_ONLY
$env:TRIBE_GPU = $Gpu
# smoke and weights never touch a GPU, so leave the GPU class out of the app
# (Modal refuses apps with GPU functions until the account has a payment method).
$env:TRIBE_CPU_ONLY = if ($Step -in @("reel", "rerun")) { "0" } else { "1" }
try {
    switch ($Step) {
        "smoke"   { modal run "${app}::smoke" }
        "weights" { modal run "${app}::download_weights" }
        "reel" {
            if (-not $VideoPath) { Write-Error "Give a video path: .\backend\tribe.ps1 reel C:\path\reel.mp4" }
            # A link is downloaded on this laptop (public only, never logged in); a path is used as is.
            $inputFlag = if ($VideoPath -match '^https?://') { "--url" } else { "--video-path" }
            # Windows PowerShell 5.1 drops empty arguments, so only pass --label when there is one.
            $runArgs = @("run", $app, $inputFlag, $VideoPath)
            if ($Label) { $runArgs += @("--label", $Label) }
            $runArgs += @("--precision", $Precision)
            modal @runArgs
        }
        "rerun" {
            if ($VideoPath -notmatch '^\d{8}-\d{6}-[0-9a-f]{8}$') { Write-Error "Give a job id: .\backend\tribe.ps1 rerun 20260101-000000-demo0000 -Precision bf16" }
            $runArgs = @("run", $app, "--rerun-job", $VideoPath, "--precision", $Precision)
            if ($Label) { $runArgs += @("--label", $Label) }
            modal @runArgs
        }
    }
    $code = $LASTEXITCODE
}
finally {
    if ($null -eq $prevGpu) { Remove-Item Env:TRIBE_GPU -ErrorAction SilentlyContinue } else { $env:TRIBE_GPU = $prevGpu }
    if ($null -eq $prevCpuOnly) { Remove-Item Env:TRIBE_CPU_ONLY -ErrorAction SilentlyContinue } else { $env:TRIBE_CPU_ONLY = $prevCpuOnly }
}
exit $code
