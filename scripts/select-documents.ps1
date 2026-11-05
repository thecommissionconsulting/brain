# Wrapper for the document selector. Flags pass through to the Python script.
#
#   .\scripts\select-documents.ps1              # write the include list
#   .\scripts\select-documents.ps1 --show sow   # inspect one class

$script = Join-Path $PSScriptRoot 'select-documents.py'
uv run --python 3.12 python $script @args
exit $LASTEXITCODE
