# Wrapper for the vault router. Flags pass straight through to the Python
# script, so they take its double-dash form.
#
#   .\scripts\route-vault.ps1              # dry run, prints the plan
#   .\scripts\route-vault.ps1 --apply      # perform the moves
#   .\scripts\route-vault.ps1 --undo       # put the last run back

$script = Join-Path $PSScriptRoot 'route-vault.py'
uv run --python 3.12 python $script @args
exit $LASTEXITCODE
