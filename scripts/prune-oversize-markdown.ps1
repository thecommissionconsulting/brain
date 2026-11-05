# Wrapper for the oversize-markdown prune. Flags pass through to the script.
#
#   .\scripts\prune-oversize-markdown.ps1            # dry run
#   .\scripts\prune-oversize-markdown.ps1 --apply    # prune

$script = Join-Path $PSScriptRoot 'prune-oversize-markdown.py'
uv run --python 3.12 python $script @args
exit $LASTEXITCODE
