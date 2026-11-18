"""Session-start gate: report which vault rules are red, right now.

`_ai/rules.md` says what the rules are; this says which are currently holding. It runs
on SessionStart (see `.claude/settings.local.json`, written by install_vault.py by absolute path) so a session opens knowing the live state
instead of discovering it in CI after a push.

Only the sub-second gates run here — `check_maps.py` (~0.8s, run from the wiki),
`check_schema_sync.py` (~0.5s), `check_gates.py` and `sync_rules.py --check` (run from the
brain) — plus the wiki's `index.md` byte budget, read straight from `check_links.py` so the
number is never duplicated. With no wiki on this machine, the maps and budget lines are
replaced by a setup hint. The content-walking lints (`check_frontmatter.py` 4.3s,
`check_links.py` 2.1s) stay in CI; they are too slow to pay for on every session.

It also reports the median time of today's and yesterday's Jev calls from the decision
log (§Limits), and marks it OVER above 4 s. It counts the Jev PII entries not yet reviewed
(R-15), with the command that lists them.

Always exits 0. This informs, it never blocks a session.
"""
import ast
import datetime
import json
import pathlib
import statistics
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

BRAIN = wiki_root.BRAIN
SCRIPTS = BRAIN / "scripts"
JEV_LOG = BRAIN / "_local" / "jev-log"
JEV_LIMIT_MS = 4000  # §Limits: a per-prompt hook finishes within 4 s in total


def budget(wiki):
    """(bytes, max) for the wiki's index.md, with the limit read from check_links.py."""
    index = wiki / "index.md"
    checker = SCRIPTS / "check_links.py"
    if not (index.exists() and checker.exists()):
        return None, None
    limit = None
    for node in ast.parse(checker.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "INDEX_MD_MAX_BYTES" for t in node.targets):
            limit = ast.literal_eval(node.value)
    return len(index.read_bytes()), limit


def jev_median(log_dir):
    """Median ms over the Jev decision records for today and yesterday (UTC), or None.

    Reads the files jev_client writes, named YYYY-MM-DD.jsonl; skips lines with no ms.
    """
    today = datetime.datetime.now(datetime.timezone.utc).date()
    names = {(today - datetime.timedelta(days=back)).isoformat() + ".jsonl" for back in (0, 1)}
    times = []
    for name in names:
        path = pathlib.Path(log_dir) / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ms = json.loads(line).get("ms")
            except (ValueError, AttributeError):
                continue
            if isinstance(ms, int) and not isinstance(ms, bool):
                times.append(ms)
    if not times:
        return None
    return int(statistics.median(times))


def jev_part(ms):
    """The session-line part for a median, or None when there is no median."""
    if ms is None:
        return None
    if ms > JEV_LIMIT_MS:
        return f"jev OVER {ms} ms (limit 4 s)"
    return f"jev {ms} ms"


def pii_part(count):
    """The session-line part for new Jev PII entries (R-15), or None when there are none."""
    if count > 0:
        return f"pii {count} new (R-15): python scripts/jev_pii.py --list"
    return None


def gate(label, script, cwd, parts, red, args=()):
    path = SCRIPTS / script
    tail = "".join(" " + arg for arg in args)
    if not path.exists():
        parts.append(f"{label} MISSING")
        red.append((label, f"python \"{path.as_posix()}\"{tail}"))
        return
    done = subprocess.run([sys.executable, str(path), *args], cwd=str(cwd),
                          capture_output=True, text=True)
    if done.returncode == 0:
        parts.append(f"{label} ok")
    else:
        parts.append(f"{label} FAIL")
        red.append((label, f"cd \"{cwd.as_posix()}\" && python \"{path.as_posix()}\"{tail}"))


def main():
    wiki = wiki_root.wiki_root()
    parts, red, notes = [], [], []
    if wiki is None:
        notes.append("wiki: not configured (python " + BRAIN.as_posix()
                     + "/scripts/install_vault.py --wiki <path>)")
        gate("schema", "check_schema_sync.py", BRAIN, parts, red)
        gate("gates", "check_gates.py", BRAIN, parts, red)
        gate("sync", "sync_rules.py", BRAIN, parts, red, args=("--check",))
    else:
        gate("maps", "check_maps.py", wiki, parts, red)
        gate("schema", "check_schema_sync.py", BRAIN, parts, red)
        gate("gates", "check_gates.py", BRAIN, parts, red)
        gate("sync", "sync_rules.py", BRAIN, parts, red, args=("--check",))
        size, limit = budget(wiki)
        if size is not None and limit:
            over = size > limit
            parts.append(f"index.md {size}/{limit}" + (" OVER (R-06)" if over else ""))

    jev = jev_part(jev_median(JEV_LOG))
    if jev is not None:
        parts.append(jev)

    try:
        import jev_pii
        pii = pii_part(len(jev_pii.new_entries()))
    except Exception:  # the PII count is optional; a failure adds no part
        pii = None
    if pii is not None:
        parts.append(pii)

    print("vault gates: " + " | ".join(parts))
    for note in notes:
        print(note)
    if red:
        print("Red: " + ", ".join(label for label, _ in red) + ".")
        for label, command in red:
            print(f"  {label}: run `{command}` for detail.")
    print("Rules: " + BRAIN.as_posix() + "/_ai/rules.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # this informs; it never blocks a session
        print(f"session_gate: skipped ({err})")
    sys.exit(0)
