"""Local git guards: the enforcement GitHub Free will not give this repo.

Branch protection and rulesets are unavailable on private repos on the Free plan
-- the API answers 403 "Upgrade to GitHub Pro" -- so nothing server-side can
refuse a push. `secret-scan.yml` and `branch-policy.yml` run AFTER the push, which
makes them detection, not prevention: by the time TruffleHog annotates a run the
credential is already on GitHub, and the only fix left is rotation.

This module is the prevention half. It runs on the machine, before the object
leaves it, and it is the gate for four rules the register records as unenforced
or post-hoc:

  R-30  secrets never in a note           was WARN, post-push   -> blocked at commit
  R-32  raw/ assets/ .confluence-private  was .gitignore only   -> also blocked on `git add -f`
  R-33  content-level exclusions          was BREACHED, no gate -> warns at commit
  R-34  main changes by PR                was "cannot block"    -> blocked at commit and push

Severity is deliberate. A credential is a hard block: the false-positive cost is
one `--no-verify`, the false-negative cost is a rotation and an audit. The R-33
body patterns (rates, tenant GUIDs, prospect lists) are heuristics over prose and
only warn. Blocking on those would train people to bypass the hook, which costs
more than the warning saves.

Bypass and its limits. `git commit --no-verify` skips pre-commit, so pre-push
re-runs the same content checks over every commit being pushed. Bypassing both is
possible and deliberate: this stops accidents, not a determined author. Set
VAULT_ALLOW_MAIN=1 for the one legitimate case, an administrative commit on main.

Modes:
  pre-commit            staged changes
  commit-msg <file>     the message about to be recorded
  pre-push              refs on stdin, in git's pre-push format
  range <base> <head>   an explicit commit range, for CI
"""
import os
import pathlib
import re
import subprocess
import sys

CI = os.environ.get("GITHUB_ACTIONS") == "true"
ALLOW_MAIN = os.environ.get("VAULT_ALLOW_MAIN") == "1"
PROTECTED = {"main"}
ZERO = "0" * 40

# Topic-branch prefixes from vault-git.md section Model, plus migrate/ which the
# obsidian-legacy migration is actively using and the note predates.
BRANCH_OK = re.compile(r"^(main|capture|(knowledge|client|internal|chore|migrate|feature|digest)/.+)$")

errors = warnings = 0


def err(m):
    global errors
    print(f"::error::{m}" if CI else f"  BLOCKED  {m}")
    errors += 1


def warn(m):
    global warnings
    print(f"::warning::{m}" if CI else f"  warning  {m}")
    warnings += 1


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          errors="replace").stdout


# ---- R-32: zones that are never committed ----------------------------------
# .gitignore already covers these, but `git add -f` walks straight past it, and
# that is exactly how a 40 GB assets/ tree or an NDA export gets in by accident.
# _ai/templates/presentation/assets/ is un-ignored on purpose (it is source, not
# migrated output), so the assets rule is anchored at the repo root.
BLOCKED_PATH = re.compile(r"^(raw|_local|assets|\.confluence-private)/|(^|/)\.confluence-private/")
NESTED_GIT = re.compile(r"(^|/)\.git/")


def check_paths(paths, where):
    for p in paths:
        if BLOCKED_PATH.search(p):
            err(f"R-32  {where}: `{p}` is in a never-committed zone. "
                f"If this was `git add -f`, unstage it: git rm --cached '{p}'")
        if NESTED_GIT.search(p):
            err(f"R-32  {where}: `{p}` is inside a nested git repo. "
                f"Never nest a repo in this vault.")


# ---- R-30: credentials ------------------------------------------------------
# Every pattern needs an actual value, so a note that merely discusses API keys
# (rules.md and setup.md both do) will not match. Escape hatch for a documented
# example: append  # pragma: allowlist secret  to the line.
SECRETS = [
    ("AWS access key id",     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*\S{40}")),
    ("GitHub token",          re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token",           re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("OpenAI key",            re.compile(r"\bsk-(proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("Anthropic key",         re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key",        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block",     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("service-account json",  re.compile(r'"private_key_id"\s*:')),
    ("JWT",                   re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")),
    ("password assignment",   re.compile(r"(?i)\b(password|passwd|pwd|secret|token)\s*[=:]\s*"
                                         r"['\"][^'\"\s]{8,}['\"]")),
    ("credentials in a URL",  re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]+@")),
]

# ---- R-33: content-level exclusions, the register's one breached rule -------
# Heuristics over prose. Warn only -- see the module docstring on severity.
SENSITIVE = [
    ("charge-out or billable rate", re.compile(r"(?i)\b(billable|charge[\s-]?out|hourly)\s+rate\b")),
    ("tenant or subscription GUID", re.compile(r"(?i)\b(tenant|subscription)[_\s-]?id\s*[=:]\s*"
                                               r"\{?[0-9a-f]{8}-[0-9a-f]{4}")),
    ("NZ IRD number",               re.compile(r"(?i)\bIRD\s*(number|no\.?)?\s*[:#]?\s*"
                                               r"\d{2,3}-?\d{3}-?\d{3}\b")),
    ("NZ bank account number",      re.compile(r"\b\d{2}-\d{4}-\d{7}-\d{2,3}\b")),
]
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
ALLOWLIST = re.compile(r"pragma:\s*allowlist secret")


def scan_added_lines(diff_text, where):
    """Only added lines. Re-flagging what is already in history is noise."""
    path = "?"
    emails_per_file = {}
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if ALLOWLIST.search(body):
            continue
        for name, pat in SECRETS:
            if pat.search(body):
                err(f"R-30  {where}: possible {name} added in `{path}`. Credentials live in "
                    f"the tool's own config, never in this repo. If it is a documented "
                    f"example, append  # pragma: allowlist secret")
        for name, pat in SENSITIVE:
            if pat.search(body):
                warn(f"R-33  {where}: {name} in `{path}`. Check this belongs in the vault and "
                     f"not in the per-client repo.")
        found = EMAIL.findall(body)
        if found:
            emails_per_file.setdefault(path, set()).update(found)

    # A prospect list looks like many distinct external addresses in one file.
    for path, addrs in emails_per_file.items():
        external = {a for a in addrs if not a.lower().endswith("@example.nz")}
        if len(external) >= 10:
            warn(f"R-33  {where}: {len(external)} distinct external email addresses added in "
                 f"`{path}`. A prospect or contact list belongs in the CRM, not the vault.")


# ---- modes ------------------------------------------------------------------
def current_branch():
    # symbolic-ref, not rev-parse: before the first commit `rev-parse
    # --abbrev-ref HEAD` answers "HEAD", which would skip the main guard.
    return (git("symbolic-ref", "--quiet", "--short", "HEAD").strip()
            or git("rev-parse", "--abbrev-ref", "HEAD").strip())


def mode_pre_commit():
    branch = current_branch()
    if branch in PROTECTED and not ALLOW_MAIN:
        err(f"R-34  `{branch}` changes go through a PR. Move this to a topic branch:\n"
            f"             git switch -c knowledge/<what>\n"
            f"           An administrative commit on main needs VAULT_ALLOW_MAIN=1.")
    if not BRANCH_OK.match(branch):
        warn(f"R-37  branch `{branch}` is not a recognised topic branch. Expected knowledge/..., "
             f"client/..., internal/..., chore/... or migrate/... (vault-git.md section Model).")
    check_paths([p for p in git("diff", "--cached", "--name-only",
                                "--diff-filter=ACMR").splitlines() if p], "staged")
    scan_added_lines(git("diff", "--cached", "-U0", "--no-color"), "staged")


def mode_commit_msg(path):
    msg = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    if re.search(r"^vault backup:", msg, re.M) and current_branch() in PROTECTED:
        err("R-35  Obsidian `vault backup:` commits never land on main. Use the `capture` branch.")


def mode_range(base, head):
    where = f"{base[:9]}..{head[:9]}"
    check_paths([p for p in git("diff", "--name-only", "--diff-filter=ACMR",
                                base, head).splitlines() if p], where)
    scan_added_lines(git("diff", "-U0", "--no-color", base, head), where)


def mode_pre_push():
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, remote_ref, remote_sha = parts
        target = remote_ref.rsplit("/", 1)[-1]

        if local_sha == ZERO:
            if target in PROTECTED and not ALLOW_MAIN:
                err(f"R-34  refusing to delete remote `{target}`.")
            continue

        if target in PROTECTED and not ALLOW_MAIN:
            err(f"R-34  refusing to push straight to `{target}`. Push the topic branch and "
                f"open a PR.\n           An administrative push needs VAULT_ALLOW_MAIN=1.")
            # A force-push additionally rewrites what others have already pulled.
            if remote_sha != ZERO and subprocess.run(
                    ["git", "merge-base", "--is-ancestor", remote_sha, local_sha],
                    capture_output=True).returncode != 0:
                err(f"R-34  `{target}` would be force-pushed -- this rewrites published history.")

        # Re-scan content: pre-commit may have been skipped with --no-verify.
        if remote_sha != ZERO:
            mode_range(remote_sha, local_sha)
        else:
            base = git("merge-base", local_sha, "origin/main").strip()
            if not base:
                base = (git("rev-list", "--max-parents=0", local_sha).split() or [local_sha])[0]
            mode_range(base, local_sha)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    mode = args[0]
    if mode == "pre-commit":
        mode_pre_commit()
    elif mode == "commit-msg":
        mode_commit_msg(args[1])
    elif mode == "pre-push":
        mode_pre_push()
    elif mode == "range":
        mode_range(args[1], args[2])
    else:
        print(f"unknown mode: {mode}")
        return 2

    if errors:
        print(f"\n{errors} blocked, {warnings} warning(s). Nothing was committed or pushed.")
        if not CI:
            print("These guards exist because GitHub Free cannot protect this branch server-side.")
        return 1
    if warnings:
        print(f"{warnings} warning(s) -- not blocking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
