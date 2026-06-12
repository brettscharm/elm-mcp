<#
  ELM MCP - one-command installer for Windows (PowerShell).

  Run this in PowerShell:

    irm https://raw.githubusercontent.com/brettscharm/elm-mcp/main/install.ps1 | iex

  It clones the repo to %USERPROFILE%\.elm-mcp, runs setup.py to wire up
  your AI host (IBM Bob, Claude Code, Cursor, VS Code, Windsurf), prompts
  for your ELM credentials, and installs the 5 custom Bob modes. Re-running
  it later updates the clone in place and re-runs setup. Idempotent.

  This is the Windows counterpart to install.sh (Mac/Linux). The core
  setup.py is identical and cross-platform - this script just handles the
  clone + Python detection the PowerShell way.

  NOT an official IBM product. Personal passion project. Use at your own risk.
#>

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/brettscharm/elm-mcp.git"
$InstallDir = if ($env:ELM_MCP_DIR) { $env:ELM_MCP_DIR } else { Join-Path $HOME ".elm-mcp" }

function Write-StepLine($msg) { Write-Host "`n$msg" -ForegroundColor White }
function Write-OkLine($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-FailLine($msg) { Write-Host "  FAIL  $msg" -ForegroundColor Red; exit 1 }

Write-Host "ELM MCP installer (Windows)" -ForegroundColor White
Write-Host "Personal passion project - not an official IBM product. Use at your own risk." -ForegroundColor DarkGray

# -- Prerequisites --------------------------------------------
Write-StepLine "[1/4] Checking prerequisites"

# git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-FailLine "git is not installed. Get it from https://git-scm.com/download/win and re-run."
}
Write-OkLine "git: $((git --version) 2>&1)"

# Python - try the 'py' launcher first (most reliable on Windows), then
# python / python3. Each candidate is an exe + an explicit args array, so
# there's no fragile string-splitting.
$PyCandidates = @(
    [pscustomobject]@{ Exe = "py";      PreArgs = @("-3") },
    [pscustomobject]@{ Exe = "python";  PreArgs = @() },
    [pscustomobject]@{ Exe = "python3"; PreArgs = @() }
)
$Py = $null
foreach ($c in $PyCandidates) {
    if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
        try {
            $probe = & $c.Exe @($c.PreArgs) -c "import sys; print(1 if sys.version_info >= (3,9) else 0)" 2>$null
            if ("$probe".Trim() -eq "1") { $Py = $c; break }
        } catch { }
    }
}
if (-not $Py) {
    Write-FailLine "Python 3.9+ is required. Install from https://www.python.org/downloads/windows/ (check 'Add Python to PATH'), then re-run."
}
$PyVer = (& $Py.Exe @($Py.PreArgs) --version 2>&1)
$PyDisplay = (@($Py.Exe) + $Py.PreArgs) -join " "
Write-OkLine "python: $PyVer  (using '$PyDisplay')"

# -- Clone or update ------------------------------------------
Write-StepLine "[2/4] Clone or update the repo at $InstallDir"
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-OkLine "Existing clone found - pulling latest"
    git -C $InstallDir fetch --quiet origin
    git -C $InstallDir reset --hard --quiet origin/main
    Write-OkLine "Updated: $((git -C $InstallDir rev-parse --short HEAD) 2>&1)"
} elseif (Test-Path $InstallDir) {
    Write-FailLine "$InstallDir exists but isn't a git checkout. Move/delete it and re-run."
} else {
    git clone --quiet $RepoUrl $InstallDir
    Write-OkLine "Cloned: $((git -C $InstallDir rev-parse --short HEAD) 2>&1)"
}

# -- Run setup.py ---------------------------------------------
Write-StepLine "[3/4] Running setup.py (deps + AI host config + modes + smoke test)"
Push-Location $InstallDir
try {
    # PowerShell runs interactively here - Python's input()/getpass() read
    # from the real console directly, so credential prompts just work.
    # No /dev/tty dance needed (that's a Unix-only concern).
    & $Py.Exe @($Py.PreArgs) setup.py
    $setupExit = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($setupExit -ne 0) {
    Write-FailLine "setup.py exited with code $setupExit. Run it again from $InstallDir to see the error."
}

# -- Done -----------------------------------------------------
Write-StepLine "[4/4] Done"
$PyExe = (Get-Command $Py.Exe).Source
$ServerPath = Join-Path $InstallDir "doors_mcp_server.py"
$PyExeJson = $PyExe -replace '\\', '\\'
$ServerJson = $ServerPath -replace '\\', '\\'

Write-Host ""
Write-Host "  + ELM MCP installed at: $InstallDir" -ForegroundColor Green
Write-Host "  + Configs written to every AI host detected (incl. ~\.bob)." -ForegroundColor Green
Write-Host "  + Modes installed: Concierge, Plan, Push, Impact Analyst, Compliance Auditor." -ForegroundColor Green
Write-Host "  + Now: fully quit and reopen your AI assistant, then say:" -ForegroundColor Green
Write-Host "      'Connect to ELM and list my projects'" -ForegroundColor White
Write-Host ""
Write-Host "If your AI doesn't see the MCP server after restart, add it manually." -ForegroundColor White
Write-Host "Config file locations on Windows (create if missing):"
Write-Host "  - IBM Bob:     %USERPROFILE%\.bob\settings\mcp_settings.json"
Write-Host "  - Claude Code: %USERPROFILE%\.claude.json"
Write-Host "  - Cursor:      %USERPROFILE%\.cursor\mcp.json"
Write-Host ""
Write-Host "JSON to paste (top-level 'mcpServers' key):"
Write-Host ""
$jsonConfig = @"
{
  "mcpServers": {
    "elm-mcp": {
      "command": "$PyExeJson",
      "args": ["$ServerJson"]
    }
  }
}
"@
Write-Host $jsonConfig -ForegroundColor DarkGray
Write-Host ""
Write-Host "  To update later: re-run this same command, or:" -ForegroundColor DarkGray
Write-Host "    cd `"$InstallDir`"; git pull; $PyDisplay setup.py" -ForegroundColor DarkGray
Write-Host "  Or just talk to your AI: 'update yourself'." -ForegroundColor DarkGray
Write-Host ""
