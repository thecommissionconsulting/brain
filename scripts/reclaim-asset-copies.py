#!/usr/bin/env python3
"""Replace verbatim asset copies with index entries and reclaim the disk.

Earlier runs copied every non-document out of OneDrive into raw/ (and, for the
Admin pilot, into assets/). At 194 GB of source that was never going to fit.
This turns each of those copies into a line in the asset index and deletes it.

Markdown stays exactly where it is -- it is the converted output and has no
copy in OneDrive to fall back on.

A copy is deleted ONLY once its OneDrive original is confirmed present. If the
original has gone, the copy is the last instance and is kept.

    .\\scripts\\reclaim-asset-copies.ps1              # dry run, shows the total
    .\\scripts\\reclaim-asset-copies.ps1 --apply      # index and delete
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent

# The migration script owns the index format; load it rather than restate it.
_spec = importlib.util.spec_from_file_location(
    "onedrive_to_vault", Path(__file__).resolve().parent / "onedrive-to-vault.py"
)
otv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(otv)

SOURCE_DEFAULT = otv.SOURCE_DEFAULT
RAW_DEFAULT = VAULT / "raw" / "onedrive"
ASSETS_DEFAULT = VAULT / "assets"
INDEX_DEFAULT = otv.INDEX_DEFAULT


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024


def reclaimable(root: Path, source: Path, strip: Path):
    """Yield (copy_path, rel_to_library, size) for every non-markdown copy.

    `strip` is the directory the mirrored structure starts from, so the
    remainder is the file's path within the OneDrive library.
    """
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.lower().endswith(".md"):
                continue  # converted output, not a copy
            path = Path(dirpath) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            yield path, path.relative_to(strip), size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--assets", type=Path, default=ASSETS_DEFAULT)
    parser.add_argument("--index", type=Path, default=INDEX_DEFAULT)
    parser.add_argument("--apply", action="store_true", help="Index and delete (default is a dry run)")
    args = parser.parse_args()

    targets = [(args.raw, args.raw), (args.assets, args.assets)]

    indexed = deleted = kept = 0
    freed = 0
    orphans: list[str] = []
    index_rows: list[dict] = []

    for root, strip in targets:
        for copy_path, rel, size in reclaimable(root, args.source, strip):
            original = args.source / rel
            if not original.exists():
                # The copy is the only instance left. Leave it alone.
                kept += 1
                if len(orphans) < 20:
                    orphans.append(str(rel))
                continue

            _, ext = otv.split_name(copy_path.name)
            index_rows.append(otv.index_row(original, rel, ext, "asset"))
            indexed += 1
            freed += size

            if args.apply:
                try:
                    os.remove(otv.winpath(copy_path))
                    deleted += 1
                except OSError as exc:
                    print(f"  could not delete {rel}: {exc}", file=sys.stderr)

    if args.apply and index_rows:
        args.index.parent.mkdir(parents=True, exist_ok=True)
        with open(otv.winpath(args.index), "a", encoding="utf-8") as handle:
            for row in index_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        # Drop the directory skeleton the deletions left behind.
        for root, _ in targets:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root, topdown=False):
                if not dirnames and not filenames and Path(dirpath) != root:
                    try:
                        os.rmdir(otv.winpath(Path(dirpath)))
                    except OSError:
                        pass

    print(f"\n{'' if args.apply else 'DRY RUN '}reclaim summary")
    print(f"  indexed   {indexed:,} copies")
    if args.apply:
        print(f"  deleted   {deleted:,} copies")
    print(f"  space     {human(freed)} {'reclaimed' if args.apply else 'reclaimable'}")
    if kept:
        print(f"  kept      {kept:,} copies whose OneDrive original is missing")
        for rel in orphans:
            print(f"              {rel}")
    if not args.apply and indexed:
        print("\nrerun with --apply to index these and delete the copies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
