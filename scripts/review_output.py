"""Stop gate: no session ends with an untriaged artifact in raw/output/.

R-48 sends every generated artifact -- a report, an export, an extract -- to
`raw/output/`, which is gitignored. That keeps generated text out of the repo and
out of the grep route, and it also means an artifact left there is invisible: no
lint sees it, no CI run mentions it, and the next session starts with no idea it
exists. This gate closes that gap by making the decision happen while the person
who asked for the artifact is still in the conversation.

It runs on Stop (see `.claude/settings.json`), so it fires when a turn ends
rather than when the session does. Claude Code's SessionEnd hook runs after the
conversation is over and can neither ask a question nor file a note, so a review
scheduled there would have no one to review with.

Fires at most once per session. The marker is written BEFORE the block is
emitted, so a crash between the two costs a review rather than looping, and
`stop_hook_active` is honoured as a second stop. A gate that can trap a session
in its own review is worse than no gate.

The ledger at `_local/output-triage.json` records the files the person chose to
leave in place, keyed by size and mtime. Editing an artifact makes it untriaged
again, which is the point: the decision was about the old content.

Modes:

  --gate      Stop-hook mode. Reads the hook JSON on stdin, prints the block
              JSON on stdout when there is something to review.
  --list      Print the untriaged artifacts. Safe to run by hand at any time.
  --keep P..  Record "leave it in raw/output/" for one or more paths.

Fail-open by design, like `pii_gate.py`. If this script errors, the turn ends
normally. A gate that hangs the session gets switched off, and a gate that is
switched off protects nothing.
"""
import json
import pathlib
import sys
import time

SCRIPT = pathlib.Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
ROOT_ARG = ""  # set by --root, repeated in the gate message so the command finds the same folder
OUTPUT = ROOT / "raw" / "output"
STATE = ROOT / "_local"
LEDGER = STATE / "output-triage.json"
MARKERS = STATE / "output-triage"
MARKER_KEEP = 20

REVIEW = """Untriaged artifacts are sitting in raw/output/ (R-49). Before this
session ends, review them with the user:

  {base} --list

Show one table covering every artifact: path, size, when it was written, what it
is, and a proposed destination under wiki/ with a `type:` for the ones worth
keeping. The user approves or amends the whole list in one message -- do not walk
them through the files one at a time.

Then act on their decisions:

  promote  convert to a note from _ai/templates/ with an `Answers:` block, put it
           at the approved path, and update index.md. Ask before `git mv` or any
           git operation.
  keep     {base} --keep <path>   (silences it until the
           file changes)
  delete   remove it, once the user has said so for that specific file.

If they would rather not do this now, say so plainly and stop. This gate fires
once per session and will not ask again."""


def use_root(root, custom=True):
    """Point the state at another folder (--root). The default is this script's own vault."""
    global ROOT, ROOT_ARG, OUTPUT, STATE, LEDGER, MARKERS
    ROOT = root
    ROOT_ARG = f' --root "{root.as_posix()}"' if custom else ""
    OUTPUT = ROOT / "raw" / "output"
    STATE = ROOT / "_local"
    LEDGER = STATE / "output-triage.json"
    MARKERS = STATE / "output-triage"


def ledger():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stamp(path):
    """(size, mtime) rounded to the second -- the identity of one artifact version."""
    info = path.stat()
    return [info.st_size, int(info.st_mtime)]


def untriaged():
    """Artifacts in raw/output/ whose current version nobody has ruled on."""
    if not OUTPUT.is_dir():
        return []
    decided = ledger()
    out = []
    for path in sorted(OUTPUT.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            now = stamp(path)
        except OSError:
            continue
        if decided.get(rel) == now:
            continue
        out.append((rel, now))
    return out


def keep(paths):
    decided = ledger()
    for raw in paths:
        path = pathlib.Path(raw)
        path = path if path.is_absolute() else ROOT / raw
        path = path.resolve()
        if not path.is_file():
            print(f"not a file, skipped: {raw}")
            continue
        decided[path.relative_to(ROOT).as_posix()] = stamp(path)
    STATE.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(decided, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"triage ledger: {len(decided)} file(s) marked keep")


def show():
    pending = untriaged()
    if not pending:
        print("raw/output: nothing awaiting triage")
        return
    print(f"raw/output: {len(pending)} file(s) awaiting triage")
    for rel, (size, mtime) in pending:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        print(f"  {when}  {size:>9,} B  {rel}")


def mark(session):
    """Record that this session has been asked. Written before the block is emitted."""
    MARKERS.mkdir(parents=True, exist_ok=True)
    (MARKERS / f"{session}.done").write_text(str(int(time.time())), encoding="utf-8")
    old = sorted(MARKERS.glob("*.done"), key=lambda p: p.stat().st_mtime)[:-MARKER_KEEP]
    for path in old:
        try:
            path.unlink()
        except OSError:
            pass


def gate():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    if event.get("stop_hook_active"):
        return
    session = "".join(c for c in str(event.get("session_id", "unknown"))
                      if c.isalnum() or c in "-_")[:64] or "unknown"
    if (MARKERS / f"{session}.done").exists():
        return
    pending = untriaged()
    if not pending:
        return
    mark(session)
    listing = "\n".join(f"  {rel}" for rel, _ in pending[:20])
    if len(pending) > 20:
        listing += f"\n  ... and {len(pending) - 20} more"
    base = f'python "{SCRIPT.as_posix()}"{ROOT_ARG}'
    text = REVIEW.format(base=base)
    print(json.dumps({"decision": "block", "reason": f"{text}\n\n{listing}"}))


def main(argv):
    argv = list(argv)
    if "--root" in argv:
        # Parsed before --keep, so --keep never takes --root's value as a path.
        i = argv.index("--root")
        if i + 1 >= len(argv):
            print("review_output: --root needs a folder", file=sys.stderr)
            return 2
        use_root(pathlib.Path(argv[i + 1]).expanduser().resolve())
        del argv[i:i + 2]
    if "--gate" in argv:
        try:
            gate()
        except Exception as err:                      # fail open, never trap a session
            print(f"review_output: gate skipped ({err})", file=sys.stderr)
        return 0
    if "--keep" in argv:
        keep(argv[argv.index("--keep") + 1:])
        return 0
    show()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
