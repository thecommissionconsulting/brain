# Wrapper for the asset-copy reclaim. Flags pass through to the Python script.
#
#   .\scripts\reclaim-asset-copies.ps1            # dry run
#   .\scripts\reclaim-asset-copies.ps1 --apply    # index and delete

$script = Join-Path $PSScriptRoot 'reclaim-asset-copies.py'
uv run --python 3.12 python $script @args
exit $LASTEXITCODE
