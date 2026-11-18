"""Vault lint: the documented schema matches the enforced one. Run from repo root.

`_ai/rules.md` states the frontmatter contract for humans and for Claude.
`scripts/check_frontmatter.py` enforces it. Until now the two were kept in step by
a code comment asking someone to remember ("Keep in step with ... _ai/conventions.md",
a note that no longer exists).
This makes the drift fail CI instead.

Reads the checker with `ast` rather than importing it — importing would run the lint
and call sys.exit. Nothing here executes vault code.

Enforces R-11: the schema table in _ai/rules.md matches the checker.
"""
import ast
import pathlib
import re
import sys

CHECKER = pathlib.Path("scripts/check_frontmatter.py")
DOC = pathlib.Path("_ai/rules.md")
START, END = "<!-- schema-table:start -->", "<!-- schema-table:end -->"

errors = 0


def err(m):
    global errors
    print(f"::error::{m}")
    errors += 1


def literals(path, names):
    """Top-level literal assignments from a module, without executing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found[target.id] = ast.literal_eval(node.value)
    return found


def documented(path):
    """{type: {required fields}} parsed from the marked table in the doc."""
    text = path.read_text(encoding="utf-8")
    block = re.search(re.escape(START) + r"(.*?)" + re.escape(END), text, re.S)
    if not block:
        err(f"{path}: no schema table between {START} and {END}.")
        return None
    rows = {}
    for line in block.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0].startswith("---") or cells[0] == "`type:`":
            continue
        name = cells[0].strip("`")
        fields = {f.strip().strip("`") for f in cells[1].split(",")}
        rows[name] = set() if cells[1].strip() in {"—", "-", ""} else fields
    return rows


for path in (CHECKER, DOC):
    if not path.exists():
        print(f"::error::{path} is missing — cannot compare schema.")
        sys.exit(1)

code = literals(CHECKER, {"ALLOWED_TYPES", "REQUIRED"})
missing_names = {"ALLOWED_TYPES", "REQUIRED"} - set(code)
if missing_names:
    print(f"::error::{CHECKER}: could not read {', '.join(sorted(missing_names))}.")
    sys.exit(1)

allowed = set(code["ALLOWED_TYPES"])
required = {t: set(f) for t, f in code["REQUIRED"].items()}
doc = documented(DOC)
if doc is None:
    sys.exit(1)

# 1) The two type registries agree.
for t in sorted(allowed - set(doc)):
    err(f"type '{t}' is in ALLOWED_TYPES but not in the {DOC} schema table — document it.")
for t in sorted(set(doc) - allowed):
    err(f"{DOC} documents type '{t}', which is not in ALLOWED_TYPES — remove it or add it to the code.")

# 2) Required fields agree, for every type in both.
for t in sorted(allowed & set(doc)):
    want, have = required.get(t, set()), doc[t]
    for f in sorted(want - have):
        err(f"type '{t}': code requires '{f}', the {DOC} table does not list it.")
    for f in sorted(have - want):
        err(f"type '{t}': {DOC} lists '{f}' as required, the code does not enforce it.")

print(f"\ncheck_schema_sync: {len(allowed)} types compared, {errors} drift error(s).")
sys.exit(1 if errors else 0)
