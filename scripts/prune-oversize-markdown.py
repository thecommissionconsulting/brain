#!/usr/bin/env python3
"""Drop converted markdown that is a data dump rather than a document.

A handful of spreadsheets -- hourly telemetry, audit logs, RFP compliance
matrices -- convert into markdown tables of tens of megabytes. They were
selected because their filenames carry words like "audit" and "health check",
but nobody will read a 22 MB table in a wiki.

Each pruned file's source is recorded in the asset index and stays in OneDrive,
so it remains findable. Nothing is deleted from the library.

    .\\scripts\\prune-oversize-markdown.ps1                 # dry run
    .\\scripts\\prune-oversize-markdown.ps1 --apply         # prune
    .\\scripts\\prune-oversize-markdown.ps1 --max-kb 500    # different threshold
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

VAULT = wiki_root.wiki_root() or wiki_root.MISSING

_spec = importlib.util.spec_from_file_location(
    "onedrive_to_vault", Path(__file__).resolve().parent / "onedrive-to-vault.py"
)
otv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(otv)

RAW_DEFAULT = VAULT / "raw" / "onedrive"
MANIFEST_DEFAULT = VAULT / "_local" / "curated-migration.jsonl"
INDEX_DEFAULT = otv.INDEX_DEFAULT
MAX_KB = 1024


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.1f} {unit}"
        size /= 1024


def main() -> int:
    wiki_root.require_wiki(VAULT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--index", type=Path, default=INDEX_DEFAULT)
    parser.add_argument("--source", type=Path, default=otv.SOURCE_DEFAULT)
    parser.add_argument("--max-kb", type=int, default=MAX_KB,
                        help="Markdown larger than this is pruned (default 1024)")
    parser.add_argument("--apply", action="store_true", help="Delete (default is a dry run)")
    args = parser.parse_args()

    # Map each written markdown file back to the source it came from.
    origin: dict[str, str] = {}
    if args.manifest.exists():
        for line in args.manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("out"):
                origin[str(Path(record["out"])).lower()] = record["rel"]

    limit = args.max_kb * 1024
    victims: list[tuple[Path, str, int]] = []
    kept_bytes = 0

    for dirpath, dirnames, filenames in os.walk(args.raw):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.lower().endswith(".md"):
                continue
            path = Path(dirpath) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= limit:
                kept_bytes += size
                continue
            rel = origin.get(str(path).lower())
            victims.append((path, rel or "", size))

    victims.sort(key=lambda row: -row[2])
    freed = sum(row[2] for row in victims)

    print(f"threshold {args.max_kb:,} KB\n")
    for path, rel, size in victims[:25]:
        shown = rel or str(path.relative_to(args.raw))
        print(f"  {human(size):>10}  {shown[:96]}")
    if len(victims) > 25:
        print(f"  ... and {len(victims) - 25:,} more")

    if args.apply:
        rows = []
        unmapped = 0
        for path, rel, _ in victims:
            if rel:
                source = args.source / rel
                _, ext = otv.split_name(Path(rel).name)
                rows.append(otv.index_row(source, Path(rel), ext, "data-export"))
            else:
                unmapped += 1
            try:
                os.remove(otv.winpath(path))
            except OSError as exc:
                print(f"  could not delete {path}: {exc}", file=sys.stderr)

        if rows:
            args.index.parent.mkdir(parents=True, exist_ok=True)
            with open(otv.winpath(args.index), "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        for dirpath, dirnames, filenames in os.walk(args.raw, topdown=False):
            if not dirnames and not filenames and Path(dirpath) != args.raw:
                try:
                    os.rmdir(otv.winpath(Path(dirpath)))
                except OSError:
                    pass
        if unmapped:
            print(f"\n  {unmapped} pruned file(s) had no manifest entry and were not indexed")

    print(f"\n{'' if args.apply else 'DRY RUN '}summary")
    print(f"  pruned    {len(victims):,} files   {human(freed)}")
    print(f"  remaining {human(kept_bytes)} of markdown")
    if not args.apply and victims:
        print("\nrerun with --apply to prune")
    return 0


if __name__ == "__main__":
    sys.exit(main())
