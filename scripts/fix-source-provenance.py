#!/usr/bin/env python3
"""Repoint `source:` at the original library document, not the staged markdown.

The routing manifest records where a note came from inside raw/, which is the
converted markdown. vault-restructure-design.md §2 wants provenance that
survives raw/ being wiped, so `source:` has to name the document in the
SharePoint library instead.

The migration manifests hold both halves: `rel` is the library document, `out`
is the markdown it produced. Joining them gives the correct value.

    .\\scripts\\fix-source-provenance.ps1              # dry run
    .\\scripts\\fix-source-provenance.ps1 --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
WIKI = VAULT / "wiki"
MIGRATION_MANIFESTS = (
    VAULT / "_local" / "curated-migration.jsonl",
    VAULT / "_local" / "onedrive-migration.jsonl",
)
RAW_MARKER = "raw/onedrive/"
SOURCE_LINE = re.compile(r'^source: ".*"$', re.M)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # staged markdown path (library-relative) -> original library document
    original: dict[str, str] = {}
    for manifest in MIGRATION_MANIFESTS:
        if not manifest.exists():
            continue
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            out, rel = record.get("out"), record.get("rel")
            if not out or not rel:
                continue
            staged = out.replace("\\", "/")
            _, _, tail = staged.partition(RAW_MARKER)
            if tail:
                original[tail] = rel.replace("\\", "/")

    fixed = unmatched = untouched = 0
    samples: list[tuple[str, str]] = []

    for path in sorted(WIKI.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(r'^source: "(.*)"$', text, re.M)
        if not match:
            untouched += 1
            continue
        current = match.group(1)
        target = original.get(current)
        if not target:
            unmatched += 1
            continue
        if len(samples) < 3:
            samples.append((current, target))
        if args.apply:
            path.write_text(
                text.replace(f'source: "{current}"', f'source: "{target}"', 1),
                encoding="utf-8", newline="\n")
        fixed += 1

    print(f"{'' if args.apply else 'DRY RUN '}source provenance")
    print(f"  repointed   {fixed:,}")
    print(f"  no match    {unmatched:,}")
    print(f"  no source   {untouched:,}")
    for before, after in samples:
        print(f"\n  {before[:92]}")
        print(f"    -> {after[:92]}")
    if not args.apply and fixed:
        print("\nrerun with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
