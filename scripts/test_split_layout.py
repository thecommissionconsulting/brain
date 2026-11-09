"""Layout checks for the brain/wiki split, run from the repo root: python scripts/test_split_layout.py

The knowledge base lives in the wiki repo now. These cases fail if a moved file is
still tracked by the brain, if the brain still carries the wiki's deny rules, or if a
brain markdown file still uses the old [[retrieval]] link. Reads git and files only.
"""
import fnmatch
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

MOVED_EXACT = ["index.md", "_ai/retrieval.md", "_ai/pii-denylist.txt"]
MOVED_GLOB = ["_ai/templates/*"]


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def is_moved(path):
    if path in MOVED_EXACT:
        return True
    return any(fnmatch.fnmatch(path, pat) for pat in MOVED_GLOB)


def case(name, ok, detail, fails):
    fails[1] += 1
    if not ok:
        fails[0] += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok or not detail else f"  ({detail})"))


def main():
    fails = [0, 0]  # [failed, total]

    files = tracked()
    leftover = sorted(p for p in files if is_moved(p))
    case("no moved wiki file is tracked by the brain", not leftover, ", ".join(leftover), fails)

    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    deny = settings.get("permissions", {}).get("deny", [])
    case("brain .claude/settings.json has no permissions.deny", not deny, f"{len(deny)} entries", fails)

    stale = []
    for p in files:
        if p.endswith(".md") and not p.startswith("marketplace/") and not p.startswith("raw/"):
            text = (ROOT / p).read_text(encoding="utf-8", errors="replace")
            if "[[retrieval]]" in text:
                stale.append(p)
    case("no brain markdown file uses [[retrieval]]", not stale, ", ".join(stale), fails)

    print(f"\n{fails[1] - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
