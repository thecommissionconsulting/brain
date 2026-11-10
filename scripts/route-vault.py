#!/usr/bin/env python3
"""Route migrated OneDrive files out of raw/ into their place in the vault.

Four destinations:

    .confluence-private/  personal and HR records -- gitignored, never committed
    wiki/                 markdown knowledge, kebab-cased to match the vault
    scripts/              genuine company code, excluding vendored package trees
    assets/               everything else, mirrored -- gitignored, large binaries

Nothing is dropped and nothing in OneDrive is touched. A file with no matching
rule stays in raw/ and is reported, so the mapping can be extended rather than
guessed at.

    .\\scripts\\route-vault.ps1                # dry run, prints the plan
    .\\scripts\\route-vault.ps1 --apply        # perform the moves
    .\\scripts\\route-vault.ps1 --undo         # put the last run back
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

VAULT = wiki_root.wiki_root() or wiki_root.MISSING
RAW_DEFAULT = VAULT / "raw" / "onedrive"
MANIFEST_DEFAULT = VAULT / "_local" / "vault-routing.jsonl"

# Personal and HR material. Matched before anything else and applied to every
# file type, so a passport scan never leaks into assets/ on its way past.
PRIVATE_RULES = [
    ("Admin/ASB Checks", ".confluence-private/asb-checks"),
    ("Admin/Employees", ".confluence-private/employees"),
    # Holds a generic process PDF alongside named individuals' employment
    # agreements and visa applications. Routed private on the safer reading;
    # promote the process doc to wiki/company/people/ by hand if wanted.
    ("Admin/Accredited Employee Visa", ".confluence-private/visa"),
]

# Markdown destinations. Longest prefix wins, so a nested rule can override a
# broader one regardless of the order written here.
WIKI_RULES = [
    ("Admin/Asset Registry", "wiki/company/ops/asset-registry"),
    ("Admin/Computers", "wiki/company/ops/asset-registry"),
    ("Admin/Admin Set up Instructions", "wiki/company/ops/instructions-user-guides"),
    ("Admin/Cathedral House", "wiki/company/ops"),
    ("Admin/Electricity", "wiki/company/ops"),
    # Catch-all for loose Admin paperwork. Safe as a broad rule because the
    # private rules are matched first and longer prefixes above win.
    ("Admin", "wiki/company/ops"),

    # Client engagement material -- SOWs, signed contracts, proposals. Routed
    # public by explicit decision, alongside the Confluence-era client tree.
    ("Customers", "wiki/clients/client-documentation"),

    ("Services", "wiki/internal/playbooks/services-team"),
    ("Marketing", "wiki/company/sales/marketing"),
    ("Partners", "wiki/company/sales/partners"),
    ("Account Setup", "wiki/company/ops"),
]

ASSETS_ROOT = "assets"

CODE_EXTS = {
    "sql", "py", "r", "rmd", "sh", "ps1", "js", "ts", "cpp", "c", "h", "hpp",
    "bat", "cmd", "pl", "rb", "java", "scala", "vba",
}

# Vendored dependency trees. Code inside one is somebody else's, not a company
# script, so it travels to assets/ with the rest of the machine leftovers.
PACKAGE_MARKERS = (
    "win-library", "site-packages", "node_modules", "/r/library/",
    ".venv", "vendor/", "packages/", "__pycache__",
)

# Type markers the migration appended for collision safety in raw/. They are
# noise in a wiki filename and come off unless two files actually collide.
TYPE_MARKERS = {
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "xlsm", "csv", "tsv",
    "html", "htm", "json", "xml", "txt", "epub", "msg", "ipynb",
}


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def winpath(path: Path) -> str:
    text = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\" + text
    return text


def kebab(text: str) -> str:
    """Lowercase hyphenated form matching the vault's existing wiki filenames."""
    text = text.replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-").lower()


def strip_type_marker(stem: str) -> tuple[str, str]:
    """Split 'Card Audit xlsx' into ('Card Audit', 'xlsx').

    Returns the stem unchanged and an empty marker when the last word is not
    one of the extensions the migration appends.
    """
    head, sep, last = stem.rpartition(" ")
    if sep and last.lower() in TYPE_MARKERS:
        return head, last.lower()
    return stem, ""


def wiki_filename(name: str, keep_type: bool = False) -> str:
    """Kebab-case a migrated markdown filename for the wiki."""
    stem = name[:-3] if name.lower().endswith(".md") else name
    base, marker = strip_type_marker(stem)
    if keep_type and marker:
        base = f"{base} {marker}"
    return kebab(base) + ".md"


def is_vendored(rel_posix: str) -> bool:
    lowered = "/" + rel_posix.lower()
    return any(marker in lowered for marker in PACKAGE_MARKERS)


def match_rule(rel_posix: str, rules) -> tuple[str, str] | None:
    """Longest matching prefix rule, or None."""
    best = None
    for prefix, dest in rules:
        if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, dest)
    return best


def plan_destination(rel: Path) -> tuple[str, Path] | None:
    """Decide where one raw/ file belongs.

    Returns (bucket, destination relative to the vault root), or None when no
    rule applies and the file should stay in raw/.
    """
    rel_posix = rel.as_posix()
    name = rel.name

    private = match_rule(rel_posix, PRIVATE_RULES)
    if private:
        prefix, dest = private
        remainder = rel_posix[len(prefix):].lstrip("/")
        return "private", Path(dest) / remainder

    is_markdown = name.lower().endswith(".md")

    if is_markdown:
        wiki = match_rule(rel_posix, WIKI_RULES)
        if not wiki:
            return None
        prefix, dest = wiki
        remainder = PurePosixParts(rel_posix[len(prefix):].lstrip("/"))
        target = Path(dest)
        for part in remainder.dirs:
            target = target / kebab(part)
        return "wiki", target / wiki_filename(name)

    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext in CODE_EXTS and not is_vendored(rel_posix):
        return "scripts", Path("scripts") / rel

    return "assets", Path(ASSETS_ROOT) / rel


class PurePosixParts:
    """Split 'a/b/file.md' into its directory parts."""

    def __init__(self, rel_posix: str) -> None:
        parts = [p for p in rel_posix.split("/") if p]
        self.dirs = parts[:-1] if parts else []


def unique_destination(target: Path, name_with_type: str | None, taken: set) -> Path:
    """Resolve a collision by reinstating the type marker, then numbering."""
    if str(target).lower() not in taken and not target.exists():
        return target
    if name_with_type:
        retyped = target.parent / name_with_type
        if str(retyped).lower() not in taken and not retyped.exists():
            return retyped
        target = retyped
    stem, dot, ext = target.name.rpartition(".")
    counter = 2
    while True:
        candidate = target.parent / f"{stem}-{counter}{dot}{ext}"
        if str(candidate).lower() not in taken and not candidate.exists():
            return candidate
        counter += 1


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def undo(manifest: Path) -> int:
    if not manifest.exists():
        print(f"no routing manifest at {manifest}", file=sys.stderr)
        return 2
    records = []
    with open(winpath(manifest), "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    restored = missing = 0
    for record in reversed(records):
        dst, src = Path(record["dst"]), Path(record["src"])
        if not dst.exists():
            missing += 1
            continue
        os.makedirs(winpath(src.parent), exist_ok=True)
        shutil.move(winpath(dst), winpath(src))
        restored += 1
    print(f"restored {restored:,} files to raw/ ({missing:,} already gone)")
    manifest.unlink(missing_ok=True)
    return 0


def main() -> int:
    wiki_root.require_wiki(VAULT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--apply", action="store_true", help="Perform the moves (default is a dry run)")
    parser.add_argument("--undo", action="store_true", help="Reverse the last routing run")
    args = parser.parse_args()

    if args.undo:
        return undo(args.manifest)

    if not args.raw.is_dir():
        print(f"nothing to route: {args.raw} does not exist", file=sys.stderr)
        return 2

    counts = {"private": 0, "wiki": 0, "scripts": 0, "assets": 0, "unrouted": 0}
    bytes_moved = {"private": 0, "wiki": 0, "scripts": 0, "assets": 0}
    unrouted: dict[str, int] = {}
    taken: set = set()
    moves: list[tuple[Path, Path, str]] = []

    for dirpath, dirnames, filenames in os.walk(args.raw):
        dirnames.sort()
        for name in sorted(filenames):
            src = Path(dirpath) / name
            rel = src.relative_to(args.raw)
            decision = plan_destination(rel)

            if decision is None:
                counts["unrouted"] += 1
                folder = "/".join(rel.parts[:2])
                unrouted[folder] = unrouted.get(folder, 0) + 1
                continue

            bucket, dest_rel = decision
            target = VAULT / dest_rel
            retyped = None
            if bucket == "wiki":
                retyped = wiki_filename(name, keep_type=True)
            target = unique_destination(target, retyped, taken)
            taken.add(str(target).lower())

            counts[bucket] += 1
            try:
                bytes_moved[bucket] += src.stat().st_size
            except OSError:
                pass
            moves.append((src, target, bucket))

    if not args.apply:
        by_bucket: dict[str, list] = {}
        for src, target, bucket in moves:
            by_bucket.setdefault(bucket, []).append((src, target))
        for bucket in ("private", "wiki", "scripts", "assets"):
            sample = by_bucket.get(bucket, [])
            if not sample:
                continue
            print(f"\n--- {bucket}: {len(sample):,} files ---")
            for src, target in sample[:6]:
                print(f"  {src.relative_to(args.raw)}")
                print(f"    -> {target.relative_to(VAULT)}")
            if len(sample) > 6:
                print(f"  ... and {len(sample) - 6:,} more")
    else:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(winpath(args.manifest), "a", encoding="utf-8") as handle:
            for src, target, bucket in moves:
                os.makedirs(winpath(target.parent), exist_ok=True)
                shutil.move(winpath(src), winpath(target))
                handle.write(json.dumps({
                    "src": str(src),
                    "dst": str(target),
                    "bucket": bucket,
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
        # Clear the empty directory skeleton the moves left behind.
        for dirpath, dirnames, filenames in os.walk(args.raw, topdown=False):
            if not dirnames and not filenames and Path(dirpath) != args.raw:
                try:
                    os.rmdir(winpath(Path(dirpath)))
                except OSError:
                    pass

    print(f"\n{'' if args.apply else 'DRY RUN '}summary")
    for bucket in ("private", "wiki", "scripts", "assets"):
        size = bytes_moved[bucket] / 1024 / 1024
        print(f"  {bucket:<9} {counts[bucket]:>7,} files  {size:>9.1f} MB")
    print(f"  {'unrouted':<9} {counts['unrouted']:>7,} files  (left in raw/)")

    if unrouted:
        print("\nno rule for these folders -- add one and rerun:")
        for folder, count in sorted(unrouted.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:>6,}  {folder}")

    if not args.apply and moves:
        print("\nrerun with --apply to perform these moves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
