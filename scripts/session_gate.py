"""Session-start gate: report which vault rules are red, right now.

`_ai/rules.md` says what the rules are; this says which are currently holding. It runs
on SessionStart (see `.claude/settings.json`) so a session opens knowing the live state
instead of discovering it in CI after a push.

Only the sub-second gates run here — `check_maps.py` (~0.8s, run from the wiki),
`check_schema_sync.py` (~0.5s) and `check_gates.py` (run from the brain) — plus the wiki's `index.md` byte
budget, read straight from `check_links.py` so the number is never duplicated. With no
wiki on this machine, the maps and budget lines are replaced by a setup hint. The content-walking lints (`check_frontmatter.py` 4.3s,
`check_links.py` 2.1s) stay in CI; they are too slow to pay for on every session.

Always exits 0. This informs, it never blocks a session.
"""
import ast
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

BRAIN = wiki_root.BRAIN
SCRIPTS = BRAIN / "scripts"


def budget(wiki):
    """(bytes, max) for the wiki's index.md, with the limit read from check_links.py."""
    index = wiki / "index.md"
    checker = SCRIPTS / "check_links.py"
    if not (index.exists() and checker.exists()):
        return None, None
    limit = None
    for node in ast.parse(checker.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "INDEX_MD_MAX_BYTES" for t in node.targets):
            limit = ast.literal_eval(node.value)
    return len(index.read_bytes()), limit


def gate(label, script, cwd, parts, red):
    path = SCRIPTS / script
    if not path.exists():
        parts.append(f"{label} MISSING")
        red.append((label, f"python \"{path.as_posix()}\""))
        return
    done = subprocess.run([sys.executable, str(path)], cwd=str(cwd),
                          capture_output=True, text=True)
    if done.returncode == 0:
        parts.append(f"{label} ok")
    else:
        parts.append(f"{label} FAIL")
        red.append((label, f"cd \"{cwd.as_posix()}\" && python \"{path.as_posix()}\""))


def main():
    wiki = wiki_root.wiki_root()
    parts, red, notes = [], [], []
    if wiki is None:
        notes.append("wiki: not configured (python " + BRAIN.as_posix()
                     + "/scripts/install_vault.py --wiki <path>)")
        gate("schema", "check_schema_sync.py", BRAIN, parts, red)
        gate("gates", "check_gates.py", BRAIN, parts, red)
    else:
        gate("maps", "check_maps.py", wiki, parts, red)
        gate("schema", "check_schema_sync.py", BRAIN, parts, red)
        gate("gates", "check_gates.py", BRAIN, parts, red)
        size, limit = budget(wiki)
        if size is not None and limit:
            over = size > limit
            parts.append(f"index.md {size}/{limit}" + (" OVER (R-10)" if over else ""))

    print("vault gates: " + " | ".join(parts))
    for note in notes:
        print(note)
    if red:
        print("Red: " + ", ".join(label for label, _ in red) + ".")
        for label, command in red:
            print(f"  {label}: run `{command}` for detail.")
    print("Rules: " + BRAIN.as_posix() + "/_ai/rules.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # this informs; it never blocks a session
        print(f"session_gate: skipped ({err})")
    sys.exit(0)
