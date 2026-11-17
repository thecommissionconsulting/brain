"""Check that every HARD rule in the register has a gate file that exists and names the rule.

`_ai/rules.md` lists each rule with its gate in the "Enforced by" column. A HARD rule is
only as strong as that gate, so this checks, without AI and without network, that the
gate file exists and that a Python gate's source names the rule id (R-xx).

Rules:
- A HARD row with no gate file named is an error.
- A gate file that is named but does not exist is an error.
- A .py gate that does not contain the rule id is an error.
- A gate marked "(wiki)" lives in the wiki repo: a missing file there is a warning, not an error.

Bare names resolve in this order: scripts/, .githooks/, .github/workflows/, then the repo root.

CLI: python scripts/check_gates.py (run from the brain root). Prints ::error:: and ::warning::
lines and a summary. Exit 1 if there is any error.
python scripts/check_gates.py --counts prints the live totals (HARD, WARN, MANUAL, retired) and exits 0.

Enforces R-62: every HARD rule names a gate file that exists, and a .py gate names its rule id.

Warns on R-68: each guarded gate file (GUARDED) has an Edit and a Write entry in
permissions.ask of .claude/settings.json, so Claude asks before editing it. The warning never
fails the run. Bash writes are not caught.
"""
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROW = re.compile(r"^\| R-\d+ \|")
TOKEN = re.compile(r"`([^`]+)`")
GATE_SUFFIXES = (".py", ".yml", ".yaml", ".sh")
GATE_NAMES = (".gitignore", ".gitattributes")
SEARCH = ("scripts", ".githooks", ".github/workflows")
GUARDED = (
    "_ai/rules.md",
    "scripts/hooks_guard.py",
    "scripts/pii_gate.py",
    "scripts/patterns.py",
    "scripts/jev_client.py",
    "scripts/check_gates.py",
    "scripts/sync_rules.py",
    "scripts/wiki_edit_gate.py",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".githooks/**",
)
ASK_RULE = re.compile(r"^(Edit|Write)\((.*)\)$")


def rows(text):
    """Each register row as {"id", "level", "gate", "status"}. The register's columns are fixed."""
    out = []
    for line in text.splitlines():
        if not ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().split("|")[1:-1]]
        out.append({
            "id": cells[0] if len(cells) > 0 else "",
            "gate": cells[4] if len(cells) > 4 else "",
            "level": cells[5] if len(cells) > 5 else "",
            "status": cells[6] if len(cells) > 6 else "",
        })
    return out


def gate_files(gate):
    """Every backticked token in the gate cell that looks like a gate file."""
    found = []
    for token in TOKEN.findall(gate):
        if " " in token or "(" in token:
            continue
        if token.endswith(GATE_SUFFIXES) or token in GATE_NAMES:
            found.append(token)
        elif token.startswith(".githooks/") and len(token) > len(".githooks/"):
            found.append(token)
    return found


def resolve(token, root):
    """The file a gate token names, or None. A path is tried as given, then the search folders."""
    root = pathlib.Path(root)
    candidates = [root / token] + [root / folder / token for folder in SEARCH]
    for path in candidates:
        if path.is_file():
            return path
    return None


def ask_rules(root):
    """The (tool, path) pairs of Edit and Write entries in permissions.ask of the project settings.

    One leading "./" or "/" is removed from each path, since a project rule anchors a path
    starting with a single "/" to the project root. A missing or unreadable settings file gives none.
    """
    settings = pathlib.Path(root) / ".claude" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    permissions = data.get("permissions") if isinstance(data, dict) else None
    asks = permissions.get("ask") if isinstance(permissions, dict) else None
    if not isinstance(asks, list):
        return set()
    found = set()
    for entry in asks:
        match = ASK_RULE.match(entry.strip()) if isinstance(entry, str) else None
        if not match:
            continue
        path = match.group(2)
        if path.startswith("./"):
            path = path[2:]
        elif path.startswith("/"):
            path = path[1:]
        found.add((match.group(1), path))
    return found


def missing_ask_rules(root):
    """Each GUARDED path that lacks an Edit entry or a Write entry in permissions.ask."""
    found = ask_rules(root)
    return [path for path in GUARDED
            if ("Edit", path) not in found or ("Write", path) not in found]


def check(root):
    """(errors, warnings) for the HARD rows of the register under root."""
    root = pathlib.Path(root)
    rules = root / "_ai" / "rules.md"
    if not rules.is_file():
        return ["rules.md: not found at " + str(rules)], []
    errors, warnings = [], []
    for row in rows(rules.read_text(encoding="utf-8")):
        if "HARD" not in row["level"]:
            continue
        rid, gate = row["id"], row["gate"]
        tokens = gate_files(gate)
        if not tokens:
            if "(wiki)" in gate:
                warnings.append(rid + ": gate is in the wiki repo; not checked here")
            else:
                errors.append(rid + ": no gate file named")
            continue
        for token in tokens:
            path = resolve(token, root)
            if path is None:
                if "(wiki)" in gate:
                    warnings.append(rid + ": gate " + token + " is in the wiki repo; not checked here")
                else:
                    errors.append(rid + ": gate file " + token + " not found")
                continue
            if path.suffix == ".py":
                text = path.read_text(encoding="utf-8", errors="replace")
                if not re.search(r"\b" + re.escape(rid) + r"\b", text):
                    shown = path.relative_to(root).as_posix()
                    errors.append(rid + ": " + shown + " does not name " + rid)
    return errors, warnings


def hard_count(root):
    rules = pathlib.Path(root) / "_ai" / "rules.md"
    if not rules.is_file():
        return 0
    return sum(1 for row in rows(rules.read_text(encoding="utf-8")) if "HARD" in row["level"])


def level_counts(root):
    """Live totals of the register: HARD, WARN and MANUAL rows, plus retired rows.

    A retired row counts only as retired. The level is the first word of the Level cell,
    with the ** marks removed, so "**HARD** (local)" counts as HARD.
    """
    counts = {"HARD": 0, "WARN": 0, "MANUAL": 0, "retired": 0}
    rules = pathlib.Path(root) / "_ai" / "rules.md"
    if not rules.is_file():
        return counts
    for row in rows(rules.read_text(encoding="utf-8")):
        if row["status"] == "retired":
            counts["retired"] += 1
            continue
        words = row["level"].replace("*", "").split()
        level = words[0] if words else ""
        if level in counts:
            counts[level] += 1
    return counts


def main():
    root = pathlib.Path.cwd()
    if "--counts" in sys.argv[1:]:
        counts = level_counts(root)
        print("HARD " + str(counts["HARD"]) + ", WARN " + str(counts["WARN"]) + ", MANUAL "
              + str(counts["MANUAL"]) + ", retired " + str(counts["retired"]))
        return 0
    errors, warnings = check(root)
    for message in errors:
        print("::error::" + message)
    for message in warnings:
        print("::warning::" + message)
    for path in missing_ask_rules(root):
        print("::warning::" + path + ": no Edit and Write entry in permissions.ask (R-68)")
    print("check_gates: " + str(hard_count(root)) + " HARD rule(s), " + str(len(errors))
          + " error(s), " + str(len(warnings)) + " warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
