#!/usr/bin/env python3
"""Audit the vault against the approved exclusions and remove what breaches them.

Every routed file is traced back to its OneDrive source through the routing
manifest. A file whose source sits in a hard-excluded zone is deleted; its
original is untouched in the library, so nothing is lost by removing the
converted copy.

Files matching a sensitive filename pattern inside an approved zone are
reported and left alone, per the owner's decision of 2026-09-11.

    .\\scripts\\enforce-exclusions.ps1              # audit only
    .\\scripts\\enforce-exclusions.ps1 --apply      # delete the breaches
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

VAULT = wiki_root.wiki_root() or wiki_root.MISSING
SCRIPTS = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("exclusions", SCRIPTS / "exclusions.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

ROUTING_DEFAULT = VAULT / "_local" / "vault-routing.jsonl"
RAW_MARKER = "raw/onedrive/"


def library_relative(src: str) -> str:
    """Recover the library-relative path from a raw/ staging path."""
    normalised = src.replace("\\", "/")
    _, _, tail = normalised.partition(RAW_MARKER)
    return tail or normalised


def main() -> int:
    wiki_root.require_wiki(VAULT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routing", type=Path, default=ROUTING_DEFAULT)
    parser.add_argument("--apply", action="store_true", help="Delete breaches (default is audit)")
    args = parser.parse_args()

    if not args.routing.exists():
        print(f"no routing manifest at {args.routing}", file=sys.stderr)
        return 2

    breaches: list[tuple[Path, str, str]] = []
    flagged: list[tuple[Path, str]] = []
    by_zone: Counter = Counter()
    by_bucket: Counter = Counter()

    for line in args.routing.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        rel = library_relative(record.get("src", ""))
        dst = Path(record.get("dst", ""))
        zone = ex.blocked(rel)
        if zone:
            breaches.append((dst, rel, zone))
            by_zone[zone] += 1
            by_bucket[record.get("bucket", "?")] += 1
        else:
            term = ex.flagged(rel)
            if term:
                flagged.append((dst, rel))

    present = [(dst, rel, zone) for dst, rel, zone in breaches if dst.exists()]

    print("breaches of the hard-excluded zones")
    for zone, count in by_zone.most_common():
        print(f"  {zone:<32}{count:>6,}")
    print(f"  {'still on disk':<32}{len(present):>6,}")
    print(f"  {'by destination':<32}{dict(by_bucket)}")

    print(f"\nflagged but retained (owner decision 2026-09-11): {len(flagged):,}")
    for _, rel in flagged[:5]:
        term = ex.flagged(rel)
        print(f"  [{term}] {rel[:88]}")
    if len(flagged) > 5:
        print(f"  ... and {len(flagged) - 5:,} more")

    if args.apply:
        removed = 0
        for dst, _, _ in present:
            try:
                os.remove(dst)
                removed += 1
            except OSError as exc:
                print(f"  could not delete {dst}: {exc}", file=sys.stderr)

        # Clear the directory skeleton the deletions leave behind.
        for root in (VAULT / "wiki", VAULT / ".confluence-private"):
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root, topdown=False):
                if not dirnames and not filenames and Path(dirpath) != root:
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
        print(f"\nremoved {removed:,} files")
    elif present:
        print("\nrerun with --apply to remove them")

    return 0


if __name__ == "__main__":
    sys.exit(main())
