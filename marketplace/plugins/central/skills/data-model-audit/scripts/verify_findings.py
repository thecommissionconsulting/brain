"""Check every finding's citation before it is reported. No judgement here: only text.

Input: the auditor's findings, JSON:
  [{"id": "F1", "check": "SET-01", "verdict": "CONFIRMED" | "PLAUSIBLE",
    "where": "path/to/file.sql:123", "evidence": ["token", ...],
    "also": [{"where": "doc.md:12", "evidence": ["store_key"]}],   # the other side, if any
    "candidate_status": "candidate" | "not_checkable" | "judgement"}]

A finding fails when a cited file or line does not exist, when a token is not within --window
lines of the cited line, when it has no evidence tokens at all, or when a candidate the
mechanical pass marked not_checkable comes back CONFIRMED. Failed findings are dropped from
the report, not softened.

    python3 verify_findings.py findings.json [--root .] [--window 3]
"""

import argparse
import json
import sys
from pathlib import Path


def check_cite(where: str, tokens: list[str], root: Path, window: int) -> str:
    if ":" not in where:
        return f"no line number in {where!r}"
    path, _, line = where.rpartition(":")
    f = Path(path) if Path(path).is_absolute() else root / path
    if not f.exists():
        return f"file not found: {path}"
    try:
        n = int(line)
    except ValueError:
        return f"bad line number in {where!r}"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    if not 1 <= n <= len(lines):
        return f"{path} has {len(lines)} lines, cited {n}"
    text = "\n".join(lines[max(0, n - 1 - window):n + window]).lower()
    missing = [t for t in tokens if t.lower() not in text]
    return f"not within {window} lines of {where}: {missing}" if missing else ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("findings", type=Path)
    ap.add_argument("--root", type=Path, default=Path("."), help="relative paths resolve from here")
    ap.add_argument("--window", type=int, default=3)
    args = ap.parse_args()

    failed = 0
    for f in json.loads(args.findings.read_text()):
        problems = []
        if not f.get("evidence"):
            problems.append("no evidence tokens")
        if f.get("candidate_status") == "not_checkable" and f.get("verdict") == "CONFIRMED":
            problems.append("not_checkable cannot be CONFIRMED from the text")
        for cite in [{"where": f.get("where", ""), "evidence": f.get("evidence", [])}] + f.get("also", []):
            p = check_cite(cite["where"], cite.get("evidence", []), args.root, args.window)
            if p:
                problems.append(p)
        status = "FAIL" if problems else "ok"
        failed += bool(problems)
        print(f"{status:4} {f.get('id', '?'):5} {f.get('check', ''):9} {f.get('where', '')}"
              + ("\n       " + "\n       ".join(problems) if problems else ""))
    print(f"{failed} of the findings failed verification" if failed else "every citation checks out")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
