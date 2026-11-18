"""Vault lint: every content note carries valid frontmatter. Run from repo root.

Ported from obsidian-legacy with the changes vault-restructure-design.md §7 asks
for: `archive/` dropped (replaced by `status: archived`) and `confluence/`
swapped for `raw/`. The master index here is index.md, per the owner's ruling
of 2026-09-11 on the index.md / old master-note conflict between the two design docs.

Enforces R-07 (frontmatter parses, type is a registry value, required fields are present).
"""
import pathlib
import re
import sys

import yaml

ALLOWED_TYPES = {"client", "engagement", "meeting", "playbook", "tool",
                 "snowflake-assessment", "people", "note", "knowledge",
                 "instruction"}
# Keep in step with _ai/rules.md §Schema. check_schema_sync.py enforces that.
REQUIRED = {"engagement": ["status", "client_id", "owner", "created"],
            "client": ["client_id", "status", "owner", "created"],
            "meeting": ["client_id", "owner", "created"],
            "knowledge": ["status", "owner", "created"],
            "playbook": ["status", "owner", "created"],
            "tool": ["status", "owner", "created"]}
SKIP_PREFIX = ("_ai/", "_local/", ".obsidian/", ".claude/", ".agents/",
               "raw/", ".confluence-private/", "scripts/", "assets/",
               ".superpowers/", "marketplace/")
EXEMPT = {"README.md", "index.md", "CLAUDE.md"}


def emit(path, msg):
    print(f"::error::{path}: {msg}")


errors = 0
checked = 0
for p in pathlib.Path(".").rglob("*.md"):
    rp = p.as_posix()
    if rp.startswith(SKIP_PREFIX) or p.name in EXEMPT or "/README" in rp:
        continue
    checked += 1
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        emit(rp, "no frontmatter")
        errors += 1
        continue
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        emit(rp, f"broken YAML ({e})")
        errors += 1
        continue
    t = fm.get("type")
    if t not in ALLOWED_TYPES:
        emit(rp, f"type '{t}' not in registry")
        errors += 1
    for field in REQUIRED.get(t, []):
        if not fm.get(field):
            emit(rp, f"type '{t}' missing required '{field}'")
            errors += 1

print(f"\ncheck_frontmatter: {checked:,} notes checked, {errors} error(s).")
sys.exit(1 if errors else 0)
