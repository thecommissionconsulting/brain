---
type: instruction
status: review
owner: Daru Broodryk
created: 2026-10-01
---

# new-machine

> **Answers:** How do I get Git, Python and Claude Code installed and on PATH on a new machine?

Run it in an ordinary PowerShell window, not as administrator. Everything installs for
the current user only (`--scope user`), so there is no UAC prompt.

```powershell
Set-Location C:\

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Add-UserPath([string]$dir) {
    if (-not (Test-Path $dir)) { return }
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($user -split ';') -notcontains $dir) {
        [Environment]::SetEnvironmentVariable('Path', "$dir;$user", 'User')
    }
    Update-SessionPath
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'winget not found. Install "App Installer" from the Microsoft Store, then rerun.'
}

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    winget install --id Git.Git -e --source winget --scope user --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    Add-UserPath "$env:LOCALAPPDATA\Programs\Git\cmd"
}

# Python. Being on PATH is not enough: the Microsoft Store alias answers to
# "python" and only prints a message, so check that it actually runs Python 3.
$pyWorks = $false
try { $pyWorks = ((& python -c "import sys; print(sys.version_info[0])" 2>$null) -eq '3') } catch {}
if (-not $pyWorks) {
    winget install --id Python.Python.3.12 -e --source winget --scope user --accept-package-agreements --accept-source-agreements
    Add-UserPath "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
    Add-UserPath "$env:LOCALAPPDATA\Programs\Python\Python312"
}

# Claude Code
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
    Add-UserPath "$env:USERPROFILE\.local\bin"
}

Update-SessionPath
foreach ($tool in 'git', 'python', 'claude') {
    if (Get-Command $tool -ErrorAction SilentlyContinue) {
        & $tool --version
    } else {
        Write-Error "$tool is still not on PATH. Open a new PowerShell window and rerun."
    }
}
```
