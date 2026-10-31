# Sick - self-improving coding agent. Idempotent Windows installer.
#
#   .\install.ps1              local dev install: uv sync + sick.cmd on PATH
#   .\install.ps1 -Global      global install: uv tool install (works anywhere)
#   .\install.ps1 -WithVideo   also install the Remotion skills for /visual
#   .\install.ps1 -Uninstall   remove the shim / global tool
#
# Or via install.bat. Requires PowerShell 5.1+ (ships with Windows).
param(
    [switch]$Global,
    [switch]$Uninstall,
    [switch]$WithVideo
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Log($msg) { Write-Host "[sick] $msg" -ForegroundColor Blue }

# The `nooa` git dependency carries Git-LFS example artifacts that installs
# don't need; skipping the smudge keeps clones working without git-lfs.
if (-not $env:GIT_LFS_SKIP_SMUDGE) { $env:GIT_LFS_SKIP_SMUDGE = "1" }

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    Log "uv not found - installing via the official installer"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # make uv visible in this session without a terminal restart
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installed but not on PATH - restart your terminal and re-run install.ps1"
    }
}

$BinDir = Join-Path $env:USERPROFILE ".local\bin"
$Shim = Join-Path $BinDir "sick.cmd"

if ($Uninstall) {
    if (Test-Path $Shim) {
        Remove-Item $Shim -Force
        Log "removed shim $Shim"
    }
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv tool uninstall sick 2>$null | Out-Null
        Log "removed global uv tool 'sick' (if it was installed)"
    }
    Log "uninstalled. (checkout and $env:USERPROFILE\.sick data left untouched)"
    return
}

Ensure-Uv

# Only download a Python when none is available (keeps re-runs offline-safe).
$found = uv python find 3.13 2>$null
if (-not $found) {
    Log "installing Python 3.13 via uv"
    uv python install 3.13
}

if ($Global) {
    Log "installing sick globally via uv tool (isolated env, works from any directory)"
    uv tool install --force --from $Root sick
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed (exit $LASTEXITCODE) - check network access to PyPI/GitHub" }
    if (Get-Command sick -ErrorAction SilentlyContinue) {
        sick --version
    } else {
        Log "WARNING: sick not on PATH yet - restart your terminal (uv tool bin: $BinDir)"
    }
} else {
    Log "syncing dependencies"
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE) - check network access to PyPI/GitHub" }

    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $Root ".env.example") $envFile
        # best-effort: restrict .env to the current user (POSIX 600 equivalent)
        try {
            icacls $envFile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
        } catch {
            Log "note: could not restrict .env permissions - keep it private"
        }
        Log "created .env - or just run ``sick`` and the first-run wizard will ask for your key"
    } else {
        Log ".env already exists - leaving it untouched"
    }

    # Global `sick` command: a tiny launcher in %USERPROFILE%\.local\bin that
    # forwards to this checkout's bin\sick.cmd (no symlink/admin rights needed).
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $launcher = "@echo off`r`ncall `"$Root\bin\sick.cmd`" %*`r`n"
    Set-Content -Path $Shim -Value $launcher -Encoding Ascii
    Log "installed $Shim -> $Root\bin\sick.cmd"

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$BinDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$BinDir;$userPath", "User")
        $env:Path = "$BinDir;$env:Path"
        Log "added $BinDir to your user PATH (new terminals pick it up automatically)"
    }
}

if ($WithVideo) {
    Log "installing remotion skills (requires Node.js)"
    npx skills add remotion-dev/skills@remotion-create -g -y
    npx skills add remotion-dev/skills@remotion-best-practices -g -y
}

Log "running preflight"
$venvSick = Join-Path $Root ".venv\Scripts\sick.exe"
if (Test-Path $venvSick) {
    & $venvSick --preflight
    if ($LASTEXITCODE -ne 0) { Log "preflight found issues - see the report above" }
} elseif (Get-Command sick -ErrorAction SilentlyContinue) {
    sick --preflight
    if ($LASTEXITCODE -ne 0) { Log "preflight found issues - see the report above" }
} else {
    Log "skipping preflight (no sick binary yet - restart terminal first)"
}

Log "done. Run: sick"
