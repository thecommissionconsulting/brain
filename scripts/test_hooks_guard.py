"""Cases for the pre-merge-commit guard, run from the repo root: python scripts/test_hooks_guard.py

Each case builds a small git repo in a temporary directory, copies .githooks/ and
scripts/hooks_guard.py into it, and points that repo's core.hooksPath at the copy. The
real repo's hooksPath and the real _local/ are never read or written.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(40) +
          "want " + str(want)[:20].ljust(20) + " got " + str(got)[:20])


def env_without_allow(**extra):
    env = {k: v for k, v in os.environ.items() if k != "VAULT_ALLOW_MAIN"}
    env["GIT_MERGE_AUTOEDIT"] = "no"
    env.update(extra)
    return env


def git(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, env=env or env_without_allow(),
                          capture_output=True, text=True)


def make_repo(current):
    """main and a side branch get their commits before hooks are installed.

    `current` is the branch checked out for the merge. The side branch is merged into it.
    """
    repo = pathlib.Path(tempfile.mkdtemp(prefix="hooks-guard-"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "setup main")

    git(repo, "switch", "-q", "-c", "side")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "setup side")

    git(repo, "switch", "-q", "main")
    git(repo, "switch", "-q", "-c", "internal/x")
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "c.txt")
    git(repo, "commit", "-q", "-m", "setup internal/x")
    git(repo, "switch", "-q", current)

    shutil.copytree(ROOT / ".githooks", repo / ".githooks")
    (repo / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "hooks_guard.py", repo / "scripts" / "hooks_guard.py")
    git(repo, "config", "core.hooksPath", str(repo / ".githooks"))
    return repo


def merge_side(repo, env=None):
    return git(repo, "merge", "--no-ff", "-q", "-m", "merge side", "side", env=env)


def bypass_log_lines(repo):
    log = repo / "_local" / "main-bypass.log"
    if not log.exists():
        return -1
    return len(log.read_text().splitlines())


def run_cases():
    # merge_into_main_refused: a merge commit on main is refused.
    repo = make_repo("main")
    r = merge_side(repo)
    case("merge_into_main_refused", r.returncode != 0, True)
    shutil.rmtree(repo, ignore_errors=True)

    # merge_on_topic_ok: the same merge on a topic branch goes through.
    repo = make_repo("internal/x")
    r = merge_side(repo)
    case("merge_on_topic_ok", r.returncode, 0)
    shutil.rmtree(repo, ignore_errors=True)

    # bypass_logged: VAULT_ALLOW_MAIN=1 lets the merge through and writes one log line.
    repo = make_repo("main")
    r = merge_side(repo, env=env_without_allow(VAULT_ALLOW_MAIN="1"))
    case("bypass_logged merge exit", r.returncode, 0)
    case("bypass_logged log lines", bypass_log_lines(repo), 1)
    shutil.rmtree(repo, ignore_errors=True)


def main():
    print("hooks_guard pre-merge-commit")
    run_cases()
    print(f"\n{RAN[0] - FAILS[0]}/{RAN[0]} ok")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
