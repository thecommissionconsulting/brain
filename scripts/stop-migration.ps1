# Stop a detached migration and clean up its worker processes.
#
# Safe to run at any time: the manifest is flushed after every file, so
# restarting picks up exactly where this left off.

$vault = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $vault '_local\migration.pid'

if (-not (Test-Path $pidFile)) {
    Write-Output 'no migration.pid - nothing recorded as running'
    exit 0
}

$parentPid = Get-Content $pidFile -ErrorAction SilentlyContinue
$stopped = 0

# Kill descendants first so a converter worker is never orphaned holding memory.
$descendants = Get-CimInstance Win32_Process |
    Where-Object { $_.ParentProcessId -eq $parentPid -or $_.CommandLine -match 'onedrive-to-vault' }

foreach ($proc in $descendants) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        $stopped++
    } catch { }
}

try {
    Stop-Process -Id $parentPid -Force -ErrorAction Stop
    $stopped++
} catch { }

Remove-Item $pidFile -ErrorAction SilentlyContinue

# markitdown workers are spawned via multiprocessing and can outlive the parent.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'onedrive-to-vault|multiprocessing-fork' } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $stopped++ } catch { }
    }

Write-Output "stopped $stopped process(es); rerun start-migration-detached.ps1 to resume"
