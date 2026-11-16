"""PreToolUse gate: keep the vault's personal data out of the prompt.

The commit guards in `hooks_guard.py` control what leaves the repo. This controls
what enters the model's context, which is a different boundary and needs a
different answer: once a file is read, it is in the prompt and nothing downstream
can take it back. So the check has to sit in front of the read.

Scope, measured rather than assumed. A whole-vault scan on 2026-09-17 found 997
of 3,483 notes carrying at least one contact address or the phrase "billable
rate". Denying 29% of the vault would make it useless, and most of those are a
single client contact named in an engagement note -- ordinary consulting record
keeping, not a case for a read gate. Only 2 notes hold bulk personal data at 10+ distinct
external addresses. That is what this blocks, plus the graduate-programme
`candidates/` subtree, which is job-applicant CVs and evaluations: personal data
of private individuals who never agreed to be in a consulting vault.

Two rules, so a new file is covered before anyone remembers to list it:

  static   paths and prefixes in _ai/pii-denylist.txt, reviewed like any other file
  dynamic  any note with DISTINCT_EXTERNAL_LIMIT or more distinct non-example.nz
           addresses, computed at read time

What this does NOT stop, stated plainly: a broad Grep across wiki/ can still
return a matching line from a denied file, because a PreToolUse hook chooses
allow or deny for the whole call and cannot filter results. It also cannot help
with anything pasted into the prompt by hand. Those need the content moved out of
the vault, which is the real fix and a bigger job than a hook.

Fail-open by design. If this script itself errors, the tool call proceeds: a
crashed gate that silently bricks every read would get switched off within the
hour, and a gate that is switched off protects nothing.

Enforces R-66: `pii_gate.py` keeps bulk personal data from reads out of the prompt.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

DISTINCT_EXTERNAL_LIMIT = 10
INTERNAL_DOMAIN = "@example.nz"

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
PATH_TOOLS = {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit"}
SEARCH_TOOLS = {"Grep", "Glob"}

# Shell verbs that put file CONTENT on stdout. A command that merely mentions a
# path (writing the denylist, moving the file, git-adding it) is not a read.
# Deliberately excludes python/node/perl/awk/sed: an inline script that writes
# config naming a denied path is indistinguishable from one that reads it, and
# blocking the first makes the gate impossible to configure. Someone scripting
# their way around this is outside the threat model -- like the commit guards,
# this stops accidents, not intent.
# The verb must be in COMMAND POSITION -- start of a line, or just after a pipe
# or separator. Matching it anywhere after whitespace flagged the words "more",
# "less" and "type" in ordinary prose, which blocked a commit whose message
# happened to contain both "10 or more" and a denied filename.
READS_A_FILE = re.compile(
    r"(?:^|[|;&`(]|&&|\|\|)\s*\(?\s*"
    r"(cat|bat|head|tail|less|more|nl|strings|xxd|od|"
    r"grep|rg|ag|ack|Get-Content|gc|Select-String)\b",
    re.MULTILINE)


def load_denylist():
    """Entries from the wiki's denylist. No wiki on this machine: an empty list."""
    root = wiki_root.wiki_root()
    if root is None:
        return []
    denylist = root / "_ai" / "pii-denylist.txt"
    if not denylist.exists():
        return []
    out = []
    for line in denylist.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.rstrip("/"))
    return out


def rel(p):
    """Wiki-relative, forward-slash. Anything outside the wiki is not ours to judge."""
    root = wiki_root.wiki_root()
    if root is None:
        return None
    try:
        return pathlib.Path(p).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def denied_by_list(path, denylist):
    r = rel(path)
    if r is None:
        return None
    for entry in denylist:
        if r == entry or r.startswith(entry + "/"):
            return entry
    return None


def bulk_personal_data(path):
    """Distinct external addresses in the file, or 0 if it cannot be read."""
    try:
        p = pathlib.Path(path)
        if not p.is_file() or p.suffix.lower() not in (".md", ".txt", ".csv", ".json"):
            return 0
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len({a.lower() for a in EMAIL.findall(text)
                if not a.lower().endswith(INTERNAL_DOMAIN)})


def deny(reason):
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(0)


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    denylist = load_denylist()

    targets = []
    if tool in PATH_TOOLS:
        targets = [ti.get("file_path") or ti.get("notebook_path")]
    elif tool in SEARCH_TOOLS:
        targets = [ti.get("path")]
    elif tool == "Bash":
        # A shell line cannot be parsed reliably, so the test is: does this
        # command READ, and does it name a denied path? Both halves are needed.
        # Matching a bare path mention blocks writing the denylist itself, and a
        # bare basename makes an ordinary word like "candidates" un-typeable --
        # a gate that fires on its own configuration gets switched off.
        # A determined rewrite (a glob, a shell variable) still gets through.
        cmd = ti.get("command") or ""
        if not READS_A_FILE.search(cmd):
            return
        for entry in denylist:
            base = entry.rsplit("/", 1)[-1]
            named = entry in cmd or ("." in base and base in cmd)
            if named:
                deny(f"Blocked: that command reads `{entry}`, which is on the vault's "
                     f"PII denylist (_ai/pii-denylist.txt). It would put personal data "
                     f"into the prompt. Ask the user directly if you need a detail from it.")
        return

    for t in filter(None, targets):
        hit = denied_by_list(t, denylist)
        if hit:
            deny(f"Blocked by _ai/pii-denylist.txt (`{hit}`). This holds personal data "
                 f"about identifiable people, and reading it would put that data into the "
                 f"prompt. If you genuinely need it, the user must hand you the specific "
                 f"detail themselves.")
        if tool == "Read":
            n = bulk_personal_data(t)
            if n >= DISTINCT_EXTERNAL_LIMIT:
                deny(f"Blocked: `{rel(t) or t}` contains {n} distinct external email "
                     f"addresses, at or over the bulk-personal-data limit of "
                     f"{DISTINCT_EXTERNAL_LIMIT}. A contact or applicant list belongs in "
                     f"the CRM or the HR system, not in a prompt. Add it to "
                     f"_ai/pii-denylist.txt if it should be permanently off limits.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail open -- see the module docstring.
        pass
