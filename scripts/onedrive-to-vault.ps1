# Thin wrapper so the migration is always launched with the markitdown extras.
# Bare markitdown has no PDF/Office backends and would silently copy everything
# across instead of converting it.
#
# Flags are passed straight through to the Python script, so they take its
# double-dash form:
#
#   .\scripts\onedrive-to-vault.ps1 --dry-run --limit 20
#   .\scripts\onedrive-to-vault.ps1 --subdir Admin
#   .\scripts\onedrive-to-vault.ps1

$script = Join-Path $PSScriptRoot 'onedrive-to-vault.py'
uv run --python 3.12 --with 'markitdown[all]' python $script @args
exit $LASTEXITCODE
