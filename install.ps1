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

# IMPORTANT - why the whole script body lives inside this `& { ... }` block:
#
# The documented install path is `irm ... | iex`, which runs this script's
# text directly in YOUR live PowerShell session - there is no script-file
# boundary. In that context a bare `exit` terminates the host process, so
# the window closes instantly and you never get to read the error. (That's
# the "it just closes out right away" bug.)
#
# Wrapping everything in `& { ... }` + try/catch and using `throw` instead of
# `exit` fixes that: on failure the catch prints the reason and the window
# STAYS OPEN. The block also gives the script its own scope, so it doesn't
# leave $ErrorActionPreference="Stop" (or any temp variable) behind in your
# session after it runs.
& {
    $ErrorActionPreference = "Stop"

    $RepoUrl = "https://github.com/brettscharm/elm-mcp.git"
    $InstallDir = if ($env:ELM_MCP_DIR) { $env:ELM_MCP_DIR } else { Join-Path $HOME ".elm-mcp" }

    function Write-StepLine($msg) { Write-Host "`n$msg" -ForegroundColor White }
    function Write-OkLine($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
    # Fail throws (caught below) instead of `exit`, so an `iex` session is
    # never killed and the user actually sees what went wrong.
    function Fail($msg) { throw $msg }

    try {
        Write-Host "ELM MCP installer (Windows)" -ForegroundColor White
        Write-Host "Personal passion project - not an official IBM product. Use at your own risk." -ForegroundColor DarkGray

        # -- Prerequisites --------------------------------------------
        Write-StepLine "[1/4] Checking prerequisites"

        # git
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Fail "git is not installed. Get it from https://git-scm.com/download/win and re-run."
        }
        Write-OkLine "git: $((git --version) 2>&1)"

        # Python - try the 'py' launcher first (most reliable on Windows), then
        # python / python3. Each candidate is an exe + an explicit args array, so
        # there's no fragile string-splitting.
        # The MCP SDK (`mcp`) has NO build for Python < 3.10, so we require 3.10+
        # and prefer an explicit newer interpreter (the `py` launcher can target
        # a specific version) before falling back to a bare python/python3.
        $PyCandidates = @(
            [pscustomobject]@{ Exe = "py";      PreArgs = @("-3.13") },
            [pscustomobject]@{ Exe = "py";      PreArgs = @("-3.12") },
            [pscustomobject]@{ Exe = "py";      PreArgs = @("-3.11") },
            [pscustomobject]@{ Exe = "py";      PreArgs = @("-3.10") },
            [pscustomobject]@{ Exe = "py";      PreArgs = @("-3") },
            [pscustomobject]@{ Exe = "python";  PreArgs = @() },
            [pscustomobject]@{ Exe = "python3"; PreArgs = @() }
        )
        $Py = $null
        foreach ($c in $PyCandidates) {
            if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
                try {
                    $probe = & $c.Exe @($c.PreArgs) -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2>$null
                    if ("$probe".Trim() -eq "1") { $Py = $c; break }
                } catch { }
            }
        }
        if (-not $Py) {
            # Give a genuinely useful message - distinguish "no Python at all"
            # from "Python present but too old", since the fix differs.
            $anyPy = $false
            foreach ($e in @("py", "python", "python3")) {
                if (Get-Command $e -ErrorAction SilentlyContinue) { $anyPy = $true; break }
            }
            if ($anyPy) {
                $foundVer = ""
                foreach ($e in @("py", "python", "python3")) {
                    if (Get-Command $e -ErrorAction SilentlyContinue) {
                        $foundVer = (& $e --version 2>&1); break
                    }
                }
                Fail @"
Python 3.10+ is required, but the Python on your PATH is too old ($foundVer).
The MCP SDK has no build for Python < 3.10, so the install can't succeed on it.
Fix: install Python 3.12 from https://www.python.org/downloads/windows/
     (check 'Add Python to PATH' in the installer), then paste this command again.
"@
            } else {
                Fail @"
Python 3.10+ is required, but no Python was found on your PATH.
Install Python 3.12 from https://www.python.org/downloads/windows/
(check 'Add Python to PATH' in the installer), then paste this command again.
"@
            }
        }
        $PyVer = (& $Py.Exe @($Py.PreArgs) --version 2>&1)
        $PyDisplay = (@($Py.Exe) + $Py.PreArgs) -join " "
        Write-OkLine "python: $PyVer  (using '$PyDisplay')"

        # -- Clone or update ------------------------------------------
        Write-StepLine "[2/4] Clone or update the repo at $InstallDir"
        if (Test-Path (Join-Path $InstallDir ".git")) {
            Write-OkLine "Existing clone found - pulling latest"
            git -C $InstallDir fetch --quiet origin
            if ($LASTEXITCODE -ne 0) { Fail "git fetch failed for $InstallDir. Check your network/proxy and re-run." }
            git -C $InstallDir reset --hard --quiet origin/main
            if ($LASTEXITCODE -ne 0) { Fail "git reset failed for $InstallDir." }
            Write-OkLine "Updated: $((git -C $InstallDir rev-parse --short HEAD) 2>&1)"
        } elseif (Test-Path $InstallDir) {
            Fail "$InstallDir exists but isn't a git checkout. Move/delete it and re-run."
        } else {
            git clone --quiet $RepoUrl $InstallDir
            if ($LASTEXITCODE -ne 0) { Fail "git clone failed. Check your network/proxy, then re-run." }
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
            Fail "setup.py exited with code $setupExit. Run it again from $InstallDir to see the full error: $PyDisplay setup.py"
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
    }
    catch {
        # Reached on any Fail/throw above. Because we're inside `& { }` and not
        # calling `exit`, the window STAYS OPEN so the user can read this.
        Write-Host ""
        Write-Host "  FAIL  Install did not complete." -ForegroundColor Red
        Write-Host ""
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        Write-Host ""
        Write-Host "(Your PowerShell window stayed open on purpose so you can read the error above.)" -ForegroundColor DarkGray
        Write-Host "Fix the issue, then paste the same command again to retry." -ForegroundColor DarkGray
        Write-Host ""
        # Signal failure to any caller that checks, without killing an iex session.
        $global:LASTEXITCODE = 1
    }
}
