#!/usr/bin/env python3
"""Collapse the imported client tree to one folder per client.

Routing mirrored OneDrive, which produced 937 folders under wiki/clients/ at up
to eleven levels. vault-restructure-design.md §2 rules two levels maximum
before a note, so each client becomes a single folder and the engagement path
moves into frontmatter, where §9 says the system of record already lives.

    wiki/clients/client-documentation/aa-life/202504-tableau-cloud/sow/x.md
    -> wiki/clients/aa-life/x.md          engagement: 202504-tableau-cloud/sow

Only notes this import created are moved. Confluence-era client notes are left
alone: the design's §10 lists client folder contents as not changing.

    .\\scripts\\flatten-clients.ps1              # dry run
    .\\scripts\\flatten-clients.ps1 --apply      # move
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
CLIENTS = VAULT / "wiki" / "clients"
IMPORTED_ROOT = CLIENTS / "client-documentation"
ROUTING_DEFAULT = VAULT / "_local" / "vault-routing.jsonl"
MAPPING_DEFAULT = VAULT / "_local" / "client-flatten.jsonl"
RAW_MARKER = "raw/onedrive/"


def library_relative(src: str) -> str:
    normalised = src.replace("\\", "/")
    _, _, tail = normalised.partition(RAW_MARKER)
    return tail or normalised


def slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-").lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routing", type=Path, default=ROUTING_DEFAULT)
    parser.add_argument("--mapping", type=Path, default=MAPPING_DEFAULT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # dst path -> library-relative source, for notes this import produced.
    origin: dict[str, str] = {}
    if args.routing.exists():
        for line in args.routing.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("dst"):
                origin[str(Path(record["dst"])).lower()] = library_relative(record["src"])

    if not IMPORTED_ROOT.is_dir():
        print(f"nothing to flatten: {IMPORTED_ROOT} does not exist", file=sys.stderr)
        return 2

    moves: list[dict] = []
    taken: set[str] = set()
    untouched = 0
    per_client: Counter = Counter()

    for dirpath, dirnames, filenames in os.walk(IMPORTED_ROOT):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.lower().endswith(".md"):
                continue
            path = Path(dirpath) / name
            source = origin.get(str(path).lower())
            if source is None:
                untouched += 1          # Confluence-era note, leave in place
                continue

            rel = path.relative_to(IMPORTED_ROOT)
            parts = rel.parts
            if len(parts) < 2:
                untouched += 1          # already directly under the bucket
                continue

            client = parts[0]
            engagement = "/".join(parts[1:-1])
            target = CLIENTS / client / name

            # Flattening collapses distinct folders onto one namespace, so a
            # collision here is expected. Qualify with the engagement slug
            # before falling back to a counter.
            if str(target).lower() in taken or target.exists():
                qualifier = slug(engagement.split("/")[0]) if engagement else "doc"
                target = CLIENTS / client / f"{qualifier}-{name}"
                counter = 2
                while str(target).lower() in taken or target.exists():
                    target = CLIENTS / client / f"{qualifier}-{counter}-{name}"
                    counter += 1
            taken.add(str(target).lower())

            per_client[client] += 1
            moves.append({
                "from": str(path),
                "to": str(target),
                "client": client,
                "engagement": engagement,
                "source": source,
            })

    print(f"clients            {len(per_client):,}")
    print(f"notes to flatten   {len(moves):,}")
    print(f"left in place      {untouched:,}  (Confluence-era)")
    print("\nlargest clients")
    for client, count in per_client.most_common(6):
        print(f"  {count:>5,}  {client[:70]}")
    print("\nexamples")
    for move in moves[:3]:
        print(f"  {Path(move['from']).relative_to(CLIENTS)}")
        print(f"    -> {Path(move['to']).relative_to(CLIENTS)}   engagement: {move['engagement'][:50]}")

    if args.apply:
        args.mapping.parent.mkdir(parents=True, exist_ok=True)
        with open(args.mapping, "w", encoding="utf-8", newline="\n") as handle:
            for move in moves:
                os.makedirs(Path(move["to"]).parent, exist_ok=True)
                shutil.move(move["from"], move["to"])
                handle.write(json.dumps(move, ensure_ascii=False) + "\n")

        for dirpath, dirnames, filenames in os.walk(IMPORTED_ROOT, topdown=False):
            if not dirnames and not filenames and Path(dirpath) != IMPORTED_ROOT:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass
        print(f"\nmoved {len(moves):,} notes; mapping written to {args.mapping}")
    elif moves:
        print("\nrerun with --apply to move them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
