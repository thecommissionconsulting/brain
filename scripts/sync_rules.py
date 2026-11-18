"""Copy named text blocks from _ai/rules.md into other files, and check that they match.

A block is the text between two marker lines in a file:
    <!-- block:{name}:start -->
    body
    <!-- block:{name}:end -->
A file that names a block must hold exactly one start and one end marker for it. A
repeated marker, or a start with no end, counts as missing markers. write() never adds
markers.

Targets are listed in TARGETS as (where, relpath, block names). where is "brain", "wiki"
or "home"; home is the .claude folder (VAULT_CLAUDE_HOME, else ~/.claude).

CLI: python scripts/sync_rules.py --check | --write [--no-home]
--check prints ::error:: lines for problems and plain lines for notes, and exits 1 on any
problem. CI uses --check --no-home. --write rewrites drifted blocks, then runs the check.

Enforces R-19: session text is written once, in _ai/rules.md; every copy matches.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BRAIN = Path(__file__).resolve().parent.parent
MARK = "<!-- block:{name}:{edge} -->"
MARK_RE = re.compile(r"<!-- block:([A-Za-z0-9_-]+):(start|end) -->")
RULES = "_ai/rules.md"
TARGETS = (
    ("brain", "CLAUDE.md", ("brain-guardrails", "response-contract", "build-flow-brain")),
    ("brain", "_ai/claude-setup.md", ("global-guardrails", "response-contract", "build-flow-global")),
    ("wiki", "CLAUDE.md", ("wiki-guardrails",)),
    ("home", "CLAUDE.md", ("global-guardrails", "response-contract", "build-flow-global")),
)
WHERES = ("brain", "wiki", "home")


def claude_dir():
    value = os.environ.get("VAULT_CLAUDE_HOME")
    if value:
        return Path(value)
    return Path.home() / ".claude"


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _markers(text):
    """Map each block name to its start and end marker matches, in file order."""
    found = {}
    for m in MARK_RE.finditer(text):
        starts, ends = found.setdefault(m.group(1), ([], []))
        (starts if m.group(2) == "start" else ends).append(m)
    return found


def _span(text, name):
    """(body_start, body_end) for a block with exactly one start and one end, else None."""
    found = _markers(text).get(name)
    if found is None:
        return None
    starts, ends = found
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].end():
        return None
    return starts[0].end(), ends[0].start()


def blocks(text):
    """Map each well-formed block name to its body (LF endings, surrounding newlines removed)."""
    text = text.replace("\r\n", "\n")
    out = {}
    for name in _markers(text):
        span = _span(text, name)
        if span is not None:
            out[name] = text[span[0]:span[1]].strip("\n")
    return out


def replace(text, name, body):
    """Return text with the block's body swapped for body, or None if its markers are missing."""
    span = _span(text, name)
    if span is None:
        return None
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = body.replace("\r\n", "\n").strip("\n").replace("\n", nl)
    return text[:span[0]] + nl + lines + nl + text[span[1]:]


def _source(brain):
    path = Path(brain) / RULES
    if not path.is_file():
        return {}
    return blocks(_read(path))


def _roots(brain, wiki, home):
    return {"brain": brain, "wiki": wiki, "home": home}


def check(brain, wiki, home):
    """Return (problems, notes). Labels are where:relpath."""
    problems, notes = [], []
    source = _source(brain)
    roots = _roots(brain, wiki, home)
    for where, rel, names in TARGETS:
        label = "%s:%s" % (where, rel)
        root = roots[where]
        if root is None:
            notes.append("skipped (no %s): %s" % (where, label))
            continue
        path = Path(root) / rel
        if not path.is_file():
            notes.append("skipped (absent): %s" % label)
            continue
        found = blocks(_read(path))
        for name in names:
            if name not in source:
                problem = "unknown block: %s" % name
            elif name not in found:
                problem = "missing markers: %s %s" % (label, name)
            elif found[name] != source[name]:
                problem = "drift: %s %s" % (label, name)
            else:
                continue
            if problem not in problems:
                problems.append(problem)
    return problems, notes


def write(brain, wiki, home, wheres=WHERES):
    """Rewrite drifted blocks in the targets whose where is in wheres. Return changed labels.

    A file with a missing-markers block is left as it is; check() reports it.
    """
    source = _source(brain)
    roots = _roots(brain, wiki, home)
    changed = []
    for where, rel, names in TARGETS:
        if where not in wheres or roots[where] is None:
            continue
        path = Path(roots[where]) / rel
        if not path.is_file():
            continue
        text = _read(path)
        found = blocks(text)
        if any(name in source and name not in found for name in names):
            continue
        new = text
        for name in names:
            if name not in source or found[name] == source[name]:
                continue
            new = replace(new, name, source[name])
            if new is None:
                break
        if new is None or new == text:
            continue
        _write(path, new)
        changed.append("%s:%s" % (where, rel))
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync and check the session-text blocks (R-19).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report drift; exit 1 on a problem")
    mode.add_argument("--write", action="store_true", help="rewrite drifted blocks, then check")
    parser.add_argument("--no-home", action="store_true", help="skip the .claude folder")
    args = parser.parse_args(argv)

    wiki = wiki_root.wiki_root()
    home = None if args.no_home else claude_dir()
    if args.write:
        for label in write(BRAIN, wiki, home):
            print("wrote: " + label)
    problems, notes = check(BRAIN, wiki, home)
    for problem in problems:
        print("::error::" + problem)
    for note in notes:
        print(note)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
