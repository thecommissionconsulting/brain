"""Session-start gate: report which vault rules are red, right now. Run from repo root.

`_ai/rules.md` says what the rules are; this says which are currently holding. It runs
on SessionStart (see `.claude/settings.json`) so a session opens knowing the live state
instead of discovering it in CI after a push.

Only the sub-second gates run here — `check_maps.py` (~0.8s) and `check_schema_sync.py`
(~0.5s) — plus the `index.md` budget, read straight from `check_links.py` so the number
is never duplicated. The content-walking lints (`check_frontmatter.py` 4.3s,
`check_links.py` 2.1s) stay in CI; they are too slow to pay for on every session.

Always exits 0. This informs, it never blocks a session.
"""
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATES = (("maps", "check_maps.py"), ("schema", "check_schema_sync.py"))


def budget():
    """(lines, max) for index.md, with the limit read from check_links.py."""
    index = ROOT / "index.md"
    checker = ROOT / "scripts" / "check_links.py"
    if not (index.exists() and checker.exists()):
        return None, None
    limit = None
    for node in ast.parse(checker.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "INDEX_MD_MAX_LINES" for t in node.targets):
            limit = ast.literal_eval(node.value)
    lines = len(index.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines, limit


parts, red = [], []
for label, script in GATES:
    path = ROOT / "scripts" / script
    if not path.exists():
        parts.append(f"{label} MISSING")
        red.append(label)
        continue
    done = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                          capture_output=True, text=True)
    if done.returncode == 0:
        parts.append(f"{label} ok")
    else:
        parts.append(f"{label} FAIL")
        red.append(label)

lines, limit = budget()
if lines and limit:
    over = lines > limit
    parts.append(f"index.md {lines}/{limit}" + (" OVER (R-10)" if over else ""))

print("vault gates: " + " | ".join(parts))
if red:
    print(f"Red: {', '.join(red)}. Run `python scripts/check_{red[0]}.py` for detail.")
print("Rules and model contract: _ai/rules.md")
sys.exit(0)
