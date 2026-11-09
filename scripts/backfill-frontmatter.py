#!/usr/bin/env python3
"""Give every note the frontmatter the vault lint requires.

No note in the vault carries frontmatter, so `check_frontmatter.py` would fail
on all 3,152. The field registry is _ai/rules.md §Schema; the provenance
requirement is vault-restructure-design.md §2, which asks for `source:` on
migrated notes so origin survives raw/ being wiped.

Type is derived from location, which is the only honest signal available:

    wiki/clients/<client>/       note      + client, client_id
    wiki/internal/knowledge-base knowledge
    wiki/internal/playbooks      playbook
    wiki/internal/products       tool
    wiki/company/people          people
    everything else              note

Status is `review` for every backfilled note. Nobody has verified these, and
the review cadence exists to move them on. Claiming `active` would be a lie the
vault then carries.

    .\\scripts\\backfill-frontmatter.ps1              # dry run
    .\\scripts\\backfill-frontmatter.ps1 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

VAULT = wiki_root.wiki_root() or wiki_root.MISSING
WIKI = VAULT / "wiki"
FLATTEN_MAP = VAULT / "_local" / "client-flatten.jsonl"
ROUTING = VAULT / "_local" / "vault-routing.jsonl"
RAW_MARKER = "raw/onedrive/"
OWNER = "Daru Broodryk"


def derive_type(rel: Path) -> str:
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "clients":
        return "note"
    joined = "/".join(parts)
    if joined.startswith("internal/knowledge-base"):
        return "knowledge"
    if joined.startswith("internal/playbooks"):
        return "playbook"
    if joined.startswith("internal/products"):
        return "tool"
    if joined.startswith("company/people"):
        return "people"
    return "note"


def client_of(rel: Path) -> str | None:
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "clients" and parts[1] != "client-documentation":
        return parts[1]
    if len(parts) >= 3 and parts[0] == "clients" and parts[1] == "client-documentation":
        return parts[2] if len(parts) > 3 else None
    return None


def yaml_escape(value: str) -> str:
    return value.replace('"', '\\"')


def main() -> int:
    wiki_root.require_wiki(VAULT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # Provenance: flattened notes know their library path; so do routed ones.
    source_of: dict[str, str] = {}
    engagement_of: dict[str, str] = {}
    if FLATTEN_MAP.exists():
        for line in FLATTEN_MAP.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_of[str(Path(record["to"])).lower()] = record["source"]
            if record.get("engagement"):
                engagement_of[str(Path(record["to"])).lower()] = record["engagement"]
    if ROUTING.exists():
        for line in ROUTING.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(Path(record.get("dst", ""))).lower()
            if key and key not in source_of:
                src = record.get("src", "").replace("\\", "/")
                _, _, tail = src.partition(RAW_MARKER)
                if tail:
                    source_of[key] = tail

    types: Counter = Counter()
    written = skipped = 0

    for path in sorted(WIKI.rglob("*.md")):
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if body.startswith("---"):
            skipped += 1
            continue

        rel = path.relative_to(WIKI)
        note_type = derive_type(rel)
        types[note_type] += 1
        key = str(path).lower()

        try:
            created = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
        except OSError:
            created = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = ["---", f"type: {note_type}", "status: review", f"owner: {OWNER}",
                 f"created: {created}"]
        client = client_of(rel)
        if client:
            lines.append(f'client: "[[{client}]]"')
            lines.append(f"client_id: {client}")
        if key in engagement_of:
            lines.append(f'engagement: "{yaml_escape(engagement_of[key])}"')
        if key in source_of:
            lines.append(f'source: "{yaml_escape(source_of[key])}"')
        lines.append("---")
        lines.append("")

        if args.apply:
            path.write_text("\n".join(lines) + body, encoding="utf-8", newline="\n")
        written += 1

    print(f"{'' if args.apply else 'DRY RUN '}frontmatter backfill")
    print(f"  notes needing frontmatter {written:,}")
    print(f"  already had it            {skipped:,}")
    print(f"  with source provenance    {sum(1 for k in source_of):,} known")
    print("\n  by derived type")
    for note_type, count in types.most_common():
        print(f"    {note_type:<12}{count:>7,}")
    if not args.apply:
        print("\nrerun with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
