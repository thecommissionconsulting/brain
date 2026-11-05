# Launch the OneDrive migration as an independent OS process.
#
# The migration itself is light (~200 MB), but it runs for hours and this
# machine sits close to its memory ceiling, so a supervising watchdog tends to
# kill it long before it finishes. Detaching hands the process to the OS.
#
#   .\scripts\start-migration-detached.ps1      # start it
#   .\scripts\stop-migration.ps1                # stop it
#
# Progress goes to _local\migration.log; the manifest at
# _local\onedrive-migration.jsonl is written after every file, so the run is
# resumable no matter how it ends.

$vault = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $vault '_local\migration.pid'

# Refuse to start a second copy -- two writers on one manifest would interleave.
if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing) {
        $running = Get-Process -Id $existing -ErrorAction SilentlyContinue
        if ($running) {
            Write-Output "already running as PID $existing - stop it first"
            exit 1
        }
    }
}

$params = @{
    FilePath               = 'powershell'
    ArgumentList           = @('-NoProfile', '-File', (Join-Path $vault 'scripts\onedrive-to-vault.ps1')) + $args
    WorkingDirectory       = $vault
    WindowStyle            = 'Hidden'
    RedirectStandardOutput = (Join-Path $vault '_local\migration.log')
    RedirectStandardError  = (Join-Path $vault '_local\migration.err')
    PassThru               = $true
}

$proc = Start-Process @params
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii
Write-Output "detached migration started, PID $($proc.Id)"
Write-Output "progress: Get-Content '$vault\_local\migration.log' -Tail 5"
