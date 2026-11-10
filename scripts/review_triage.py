"""Decide how deep the fresh-eyes review of a branch must be: quick or full. No AI runs here.

A diff is `full` when it touches a risk path (scripts, hooks, CI, the marketplace, the
vault rules, the client folders, the git attributes), when its added lines hold personal
data or a secret (the same scanner the vault uses, `scripts/patterns.py`), or when it
changes BIG lines or more. Anything else is `quick`. If git fails, the answer is `full`.

CLI: python scripts/review_triage.py [--base REF] [--repo PATH]
Prints `review: quick` or `review: full`, then one reason per line. Exit 2 if git fails.
"""
import argparse
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RISK = ("scripts/", ".githooks/", ".github/", "marketplace/plugins/", "marketplace/scripts/",
        "_ai/rules.md", "_ai/update.md", "_ai/setup.md", "CLAUDE.md", ".claude/settings.json",
        ".gitignore", ".gitattributes", "wiki/clients/")
BIG = 400
MAX_LISTED = 10


class GitError(RuntimeError):
    pass


def _is_risky(path):
    for entry in RISK:
        if path == entry or (entry.endswith("/") and path.startswith(entry)):
            return True
    return False


def _pii_hits(added, scan):
    """Reasons from the PII scan: a hit, or the scan itself failing."""
    if scan is None:
        import patterns  # noqa: E402
        scan = patterns.scan
    try:
        hits = scan(added)
    except Exception:
        return ["PII scan unavailable"]
    if hits:
        return ["personal data or a secret in added lines"]
    return []


def triage(paths, added, changed_lines, scan=None):
    """(`quick` or `full`, reasons). `full` when any check gives a reason."""
    reasons = []
    risky = [p for p in paths if _is_risky(p)]
    for path in risky[:MAX_LISTED]:
        reasons.append("touches " + path)
    if len(risky) > MAX_LISTED:
        reasons.append("and " + str(len(risky) - MAX_LISTED) + " more")
    reasons.extend(_pii_hits(added, scan))
    if changed_lines >= BIG:
        reasons.append("large diff: " + str(changed_lines) + " lines")
    if reasons:
        return "full", reasons
    return "quick", ["no risk paths, no personal data, " + str(changed_lines) + " lines"]


def _git(repo, *args):
    cmd = ["git", "-c", "core.quotepath=off", "-C", str(repo), "--no-pager", *args]
    done = subprocess.run(cmd, capture_output=True)
    if done.returncode:
        message = done.stderr.decode("utf-8", errors="replace").strip() or "exit " + str(done.returncode)
        raise GitError(message)
    return done.stdout.decode("utf-8", errors="replace")


def diff_facts(repo, base):
    """(paths, added_text, changed_lines) for the commits on the branch since base."""
    span = base + "...HEAD"
    names = _git(repo, "diff", "--name-status", "-M", "--no-color", span)
    paths = []
    for line in names.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        paths.extend(fields[1:])  # a rename or copy carries old and new paths
    patch = _git(repo, "diff", "-U0", "--no-color", span)
    added = []
    for line in patch.splitlines():
        if line.startswith("+++ b/") or line.startswith("+++ /dev/null"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    numstat = _git(repo, "diff", "--numstat", "-M", "--no-color", span)
    changed = 0
    for line in numstat.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0].isdigit() and fields[1].isdigit():
            changed += int(fields[0]) + int(fields[1])
    return paths, "\n".join(added), changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Say whether a branch needs a quick or full review.")
    ap.add_argument("--base", default="origin/main", metavar="REF")
    ap.add_argument("--repo", default=".", metavar="PATH")
    args = ap.parse_args(argv)
    try:
        paths, added, changed = diff_facts(args.repo, args.base)
    except GitError as err:
        print("review: full")
        print("git failed: " + str(err))
        return 2
    verdict, reasons = triage(paths, added, changed)
    print("review: " + verdict)
    for reason in reasons:
        print(reason)
    if _git(args.repo, "status", "--porcelain").strip():
        print("uncommitted changes not included")
    return 0


if __name__ == "__main__":
    sys.exit(main())
