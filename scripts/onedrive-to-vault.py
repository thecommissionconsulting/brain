#!/usr/bin/env python3
"""Migrate the company OneDrive share into the vault's raw/ staging area.

Documents are converted to Markdown with markitdown. Every other file is
recorded in the asset index and left where it is -- the library is 194 GB, so
copying it would duplicate the whole share onto the same disk for no gain.
Pass --copy-assets to copy them instead, if the space exists.

The source folder tree is mirrored exactly and nothing under the OneDrive root
is ever modified.

The [all] extra is required, not optional: bare markitdown ships without its
PDF/Office backends and every document would fall back to a verbatim copy.

    uv run --with "markitdown[all]" python scripts/onedrive-to-vault.py --dry-run --limit 20
    uv run --with "markitdown[all]" python scripts/onedrive-to-vault.py --subdir Admin
    uv run --with "markitdown[all]" python scripts/onedrive-to-vault.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import queue
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SOURCE_DEFAULT = Path(r"C:\Users\DaruBroodryk\Company Ltd\Shared - Documents")
DEST_DEFAULT = VAULT / "raw" / "onedrive"
MANIFEST_DEFAULT = VAULT / "_local" / "onedrive-migration.jsonl"
INDEX_DEFAULT = VAULT / "_local" / "onedrive-asset-index.jsonl"

CONVERT_TIMEOUT = 120   # seconds a single document gets before its worker is killed
WORKER_STARTUP = 300    # seconds to allow for the first markitdown import
PROGRESS_EVERY = 100

# markitdown loads a whole spreadsheet or CSV into a pandas DataFrame. A
# few-hundred-MB file turns into gigabytes of process memory and takes minutes
# to fail, which is what exhausted this machine on the first full run. Past
# this size the file is copied verbatim instead -- a giant CSV is already plain
# text, and its markdown table would be larger and no more readable.
MAX_CONVERT_MB = 50

# The converter process is reused for speed, but pandas, pdfminer and pillow
# all hold memory across calls. Recycling it on a fixed interval keeps the
# high-water mark bounded over a 50k-file run.
RECYCLE_EVERY = 250

# Extensions markitdown registers a real converter for. Legacy .doc/.ppt/.rtf
# are deliberately absent -- markitdown has no converter for them, so they
# travel as verbatim copies instead of failing thousands of times. .zip is
# absent too: markitdown would flatten an archive into prose, which is worse
# than keeping the archive intact for sorting.
DOC_EXTS = {
    "pdf", "docx", "pptx", "xlsx", "xlsm", "xls", "csv", "tsv",
    "html", "htm", "json", "xml", "txt", "epub", "msg", "ipynb",
}

NOISE_EXACT = {"thumbs.db", ".ds_store", "desktop.ini"}
NOISE_PREFIXES = ("~$", ".~lock.")
# OneDrive drops a GUID-named sentinel file at the root of a synced library.
GUID_SENTINEL = re.compile(
    r"^\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# --------------------------------------------------------------------------
# Pure helpers -- these are what tests/test_onedrive_to_vault.py exercises.
# --------------------------------------------------------------------------

def winpath(path: Path) -> str:
    """Return a string safe to hand to open()/shutil on deep Windows trees.

    The OneDrive share nests well past the legacy 260-character MAX_PATH, so
    every filesystem call goes through the extended-length prefix.
    """
    text = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\" + text
    return text


def split_name(name: str) -> tuple[str, str]:
    """Split a filename into (stem, lowercase extension without the dot)."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return name, ""
    return stem, ext.lower()


def is_noise(name: str) -> bool:
    lowered = name.lower()
    if lowered in NOISE_EXACT:
        return True
    if lowered.startswith(NOISE_PREFIXES):
        return True
    return bool(GUID_SENTINEL.match(name))


def markdown_name(stem: str, ext: str) -> str:
    """Name the Markdown output, keeping the source type in the filename.

    'Terms of Service' + 'pdf' -> 'Terms of Service pdf.md'

    The share holds same-named .docx and .pdf siblings in one folder; without
    the type in the name they would silently overwrite each other.
    """
    return f"{stem} {ext}.md" if ext else f"{stem}.md"


def sniff_ooxml(path: Path) -> str | None:
    """Identify an extensionless OOXML file by the parts inside its zip."""
    try:
        with zipfile.ZipFile(winpath(path)) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    for prefix, ext in (("word/", "docx"), ("xl/", "xlsx"), ("ppt/", "pptx")):
        if any(n.startswith(prefix) for n in names):
            return ext
    if any(n.startswith("EPUB/") or n == "mimetype" for n in names):
        return "epub"
    return None


def sniff_extension(path: Path) -> str | None:
    """Guess a convertible extension for a file that has none."""
    try:
        with open(winpath(path), "rb") as handle:
            head = handle.read(8)
    except OSError:
        return None
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return sniff_ooxml(path)
    # A leading OLE2 signature could be doc, xls or ppt and we cannot tell
    # which cheaply. It falls through to a verbatim copy.
    return None


def index_row(src: Path, rel: Path, ext: str, kind: str) -> dict:
    """One line of the asset index: what the file is and where it still lives.

    The vault records the file's existence and location rather than a copy of
    it. OneDrive remains the store.

    The path is stored relative to the shared library root, with forward
    slashes -- never an absolute path. Everyone syncs the same library to a
    different local root ("C:/Users/<someone>/Company Ltd/Shared -
    Documents", a Mac path, or the SharePoint web view), so an absolute path
    would resolve only on the machine that wrote it. Joining this path to a
    reader's own library root resolves the same file anywhere.
    """
    try:
        stat = src.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = None, None
    return {
        "path": rel.as_posix(),
        "ext": ext,
        "kind": kind,
        "bytes": size,
        "modified": (
            datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")
            if mtime else None
        ),
    }


def classify(path: Path) -> tuple[str, str]:
    """Return (action, effective_extension) for one source file.

    action is one of: 'skip', 'convert', 'copy'.
    """
    name = path.name
    if is_noise(name):
        return "skip", ""
    _, ext = split_name(name)
    if ext in DOC_EXTS:
        return "convert", ext
    if not ext:
        sniffed = sniff_extension(path)
        if sniffed:
            return "convert", sniffed
    return "copy", ext


# --------------------------------------------------------------------------
# Conversion worker -- one long-lived process, killed and replaced on timeout.
# --------------------------------------------------------------------------

def _worker_loop(job_q, res_q) -> None:
    # pdfminer logs a paragraph per encrypted PDF and openpyxl warns on every
    # unparseable header. Across 52k files that buries the progress output.
    import logging
    import warnings

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")

    try:
        from markitdown import MarkItDown
    except Exception as exc:  # noqa: BLE001 - reported to the parent verbatim
        res_q.put(("fatal", f"markitdown import failed: {exc}"))
        return
    converter = MarkItDown(enable_plugins=False)
    res_q.put(("ready", ""))
    while True:
        job = job_q.get()
        if job is None:
            return
        try:
            result = converter.convert(job)
            res_q.put(("ok", result.text_content or ""))
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            res_q.put(("err", f"{type(exc).__name__}: {exc}"))


class ConverterPool:
    """A persistent markitdown process with a hard per-file timeout.

    markitdown is imported once and reused across ~20k documents; spawning a
    process per file would add hours of pure overhead. A file that hangs the
    worker gets it terminated and a fresh one started in its place.
    """

    def __init__(self, timeout: int = CONVERT_TIMEOUT, recycle_every: int = RECYCLE_EVERY) -> None:
        self.timeout = timeout
        self.recycle_every = recycle_every
        self.proc = None
        self.job_q = None
        self.res_q = None
        self.restarts = 0
        self.recycles = 0
        self.since_start = 0

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        self.job_q = ctx.Queue()
        self.res_q = ctx.Queue()
        self.proc = ctx.Process(
            target=_worker_loop, args=(self.job_q, self.res_q), daemon=True
        )
        self.proc.start()
        kind, payload = self.res_q.get(timeout=WORKER_STARTUP)
        if kind != "ready":
            raise RuntimeError(payload)
        self.since_start = 0

    def convert(self, staged: Path) -> tuple[str | None, str | None]:
        """Return (markdown, error). Exactly one is None."""
        if self.proc is not None and self.since_start >= self.recycle_every:
            self.stop()
            self.recycles += 1
        if self.proc is None or not self.proc.is_alive():
            self._start()
        self.since_start += 1
        self.job_q.put(winpath(staged))
        try:
            kind, payload = self.res_q.get(timeout=self.timeout)
        except queue.Empty:
            self.stop(kill=True)
            self.restarts += 1
            return None, f"timeout after {self.timeout}s"
        if kind == "ok":
            return payload, None
        return None, payload

    def stop(self, kill: bool = False) -> None:
        if self.proc is None:
            return
        try:
            if kill:
                self.proc.terminate()
            else:
                self.job_q.put(None)
            self.proc.join(timeout=10)
            if self.proc.is_alive():
                self.proc.kill()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
        finally:
            self.proc = None
            self.job_q = None
            self.res_q = None


# --------------------------------------------------------------------------
# Manifest -- append-only JSONL so a 52k-file run can stop and resume.
# --------------------------------------------------------------------------

DONE_STATES = {"ok", "fallback", "skipped"}


def load_done(manifest: Path) -> set[str]:
    """Source paths already finished. Failures are absent, so reruns retry them."""
    if not manifest.exists():
        return set()
    done: set[str] = set()
    with open(winpath(manifest), "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line from an interrupted run
            if record.get("status") in DONE_STATES:
                done.add(record["src"])
            else:
                done.discard(record["src"])
    return done


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--dest", type=Path, default=DEST_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--subdir", default="", help="Limit the run to one folder under --source")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N files (0 = no limit)")
    parser.add_argument("--timeout", type=int, default=CONVERT_TIMEOUT)
    parser.add_argument("--max-convert-mb", type=int, default=MAX_CONVERT_MB,
                        help="Files larger than this are copied, not converted")
    parser.add_argument("--recycle-every", type=int, default=RECYCLE_EVERY,
                        help="Restart the converter process after this many documents")
    parser.add_argument("--index", type=Path, default=INDEX_DEFAULT)
    parser.add_argument("--include-list", type=Path,
                        help="Only process paths listed in this file, one library-relative "
                             "path per line. Produced by select-documents.py.")
    parser.add_argument("--copy-assets", action="store_true",
                        help="Copy non-documents into raw/ instead of indexing them. "
                             "Needs free space equal to the whole source tree.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions, write nothing")
    parser.add_argument("--force", action="store_true", help="Redo files the manifest marks done")
    args = parser.parse_args()

    root = args.source / args.subdir if args.subdir else args.source
    if not root.is_dir():
        print(f"source not found: {root}", file=sys.stderr)
        return 2

    include = None
    if args.include_list:
        include = {
            line.strip().replace("\\", "/")
            for line in args.include_list.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        print(f"include list: {len(include):,} paths selected for conversion")

    done = set() if (args.force or args.dry_run) else load_done(args.manifest)
    if done:
        print(f"manifest: {len(done):,} files already done, resuming")

    pool = ConverterPool(args.timeout, args.recycle_every)
    stage_dir = Path(tempfile.mkdtemp(prefix="onedrive-stage-"))
    manifest_handle = None
    if not args.dry_run:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest_handle = open(winpath(args.manifest), "a", encoding="utf-8")

        # Every index path is relative to the shared library root. Record which
        # library that is, so a reader on any machine knows what to join them
        # to -- their own sync root, or the SharePoint web view.
        meta_path = args.index.with_suffix(".meta.json")
        args.index.parent.mkdir(parents=True, exist_ok=True)
        with open(winpath(meta_path), "w", encoding="utf-8") as meta_handle:
            json.dump({
                "library": "/".join(args.source.parts[-2:]),
                "resolve": "join each entry's `path` to your own local copy of this library",
                "note": "paths are relative and use forward slashes; they resolve on any machine",
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, meta_handle, indent=2)
            meta_handle.write("\n")

    counts = {"converted": 0, "copied": 0, "indexed": 0, "skipped": 0,
              "failed": 0, "resumed": 0, "oversize": 0}
    index_rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    seen = 0
    missing_deps = 0
    started = time.time()

    try:
        for src in walk_files(root):
            rel = src.relative_to(args.source)
            if include is not None and rel.as_posix() not in include:
                continue
            key = str(src)
            if key in done:
                counts["resumed"] += 1
                continue

            seen += 1
            if args.limit and seen > args.limit:
                break

            action, ext = classify(src)
            if action == "convert":
                try:
                    if src.stat().st_size > args.max_convert_mb * 1024 * 1024:
                        action = "copy"
                        counts["oversize"] += 1
                except OSError:
                    pass
            stem, _ = split_name(src.name)
            out_dir = args.dest / rel.parent
            status, error, out_path = "ok", None, None
            begin = time.time()

            if action == "skip":
                status = "skipped"
                counts["skipped"] += 1
            elif action == "convert":
                out_path = out_dir / markdown_name(stem, ext)
                if args.dry_run:
                    print(f"CONVERT {rel}  ->  {out_path.relative_to(args.dest)}")
                    counts["converted"] += 1
                else:
                    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]
                    staged = stage_dir / f"{digest}.{ext}"
                    try:
                        shutil.copy2(winpath(src), winpath(staged))
                        markdown, error = pool.convert(staged)
                    except OSError as exc:
                        markdown, error = None, f"stage failed: {exc}"
                    finally:
                        staged.unlink(missing_ok=True)

                    if markdown is None:
                        if error and "MissingDependencyException" in error:
                            missing_deps += 1
                        # Conversion failed. Nothing is lost -- OneDrive still
                        # holds the original -- so record it in the index and
                        # move on rather than duplicating the file.
                        out_path = None
                        status = "fallback"
                        index_rows.append(index_row(src, rel, ext, "unconverted"))
                        counts["indexed"] += 1
                        failures.append((str(rel), error or "unknown"))
                    else:
                        os.makedirs(winpath(out_dir), exist_ok=True)
                        with open(winpath(out_path), "w", encoding="utf-8", newline="\n") as handle:
                            handle.write(markdown)
                        counts["converted"] += 1
            elif args.copy_assets:
                out_path = out_dir / src.name
                if args.dry_run:
                    print(f"COPY    {rel}")
                    counts["copied"] += 1
                else:
                    try:
                        os.makedirs(winpath(out_dir), exist_ok=True)
                        shutil.copy2(winpath(src), winpath(out_path))
                        counts["copied"] += 1
                    except OSError as exc:
                        status, error = "failed", str(exc)
                        counts["failed"] += 1
                        failures.append((str(rel), str(exc)))
            else:
                # Default path. OneDrive already stores, syncs and versions this
                # file; copying it would duplicate 194 GB onto the same disk for
                # no gain. Record where it lives instead.
                action = "index"
                if args.dry_run:
                    print(f"INDEX   {rel}")
                else:
                    index_rows.append(index_row(src, rel, ext, "asset"))
                counts["indexed"] += 1

            if manifest_handle is not None:
                manifest_handle.write(json.dumps({
                    "src": key,
                    "rel": str(rel),
                    "action": action,
                    "status": status,
                    "out": str(out_path) if out_path else None,
                    "ms": int((time.time() - begin) * 1000),
                    "error": error,
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
                manifest_handle.flush()

            # Bare markitdown converts nothing. Catch that in the first handful
            # of documents rather than after copying 52,000 files.
            if missing_deps >= 5 and counts["converted"] == 0:
                print(
                    "\nABORTING: the first 5 documents all failed with "
                    "MissingDependencyException.\nmarkitdown is installed without "
                    'its format backends. Rerun with --with "markitdown[all]".',
                    file=sys.stderr,
                )
                return 3

            if index_rows and not args.dry_run:
                args.index.parent.mkdir(parents=True, exist_ok=True)
                with open(winpath(args.index), "a", encoding="utf-8") as index_handle:
                    for row in index_rows:
                        index_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                index_rows.clear()

            if seen % PROGRESS_EVERY == 0:
                rate = seen / max(time.time() - started, 0.001)
                print(f"  {seen:,} files | {counts['converted']:,} converted "
                      f"{counts['indexed']:,} indexed {counts['failed']:,} failed "
                      f"| {rate:.1f}/s", flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted -- manifest is current, rerun to resume", file=sys.stderr)
    finally:
        pool.stop()
        if manifest_handle is not None:
            manifest_handle.close()
        shutil.rmtree(stage_dir, ignore_errors=True)

    elapsed = time.time() - started
    print(f"\n{'DRY RUN ' if args.dry_run else ''}done in {elapsed / 60:.1f} min")
    print(f"  converted {counts['converted']:,}")
    print(f"  indexed   {counts['indexed']:,}   (left in OneDrive, recorded in the index)")
    if counts["copied"]:
        print(f"  copied    {counts['copied']:,}")
    print(f"  skipped   {counts['skipped']:,}")
    print(f"  failed    {counts['failed']:,}")
    if counts["resumed"]:
        print(f"  resumed   {counts['resumed']:,} already done")
    if counts["oversize"]:
        print(f"  oversize  {counts['oversize']:,} copied instead of converted "
              f"(over {args.max_convert_mb} MB)")
    if pool.restarts:
        print(f"  worker restarts after timeout: {pool.restarts}")
    if pool.recycles:
        print(f"  worker recycles to cap memory:  {pool.recycles}")
    if failures:
        print(f"\nfirst {min(len(failures), 10)} of {len(failures)} problems:")
        for rel, err in failures[:10]:
            print(f"  {rel}: {err[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
