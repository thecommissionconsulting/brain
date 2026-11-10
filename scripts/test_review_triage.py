"""Cases for review_triage.py, run from the repo root: python scripts/test_review_triage.py

The pure cases call triage() directly. The git cases build throwaway repositories in the
temp directory and never read the real repo or the wiki. Names in the added text are
invented; the email is assembled from pieces so no source line holds one.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("review_triage", ROOT / "scripts" / "review_triage.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(50) +
          "want " + str(want)[:40].ljust(40) + " got " + str(got)[:40])


def boom(text):
    raise RuntimeError("scanner missing (forced for the test)")


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    done = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)
    if done.returncode:
        raise RuntimeError(done.stderr.strip())
    return done.stdout.strip()


def new_repo(base):
    repo = pathlib.Path(base) / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "docs").mkdir()
    (repo / "docs" / "readme.md").write_text("start\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    return repo, git(repo, "rev-parse", "HEAD")


def run_cli(args, cwd):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "review_triage.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=str(cwd))


def main():
    print("pure triage")
    verdict, reasons = rt.triage(["docs/notes.md"], "a plain note line", 3, scan=lambda t: [])
    case("a doc-only change is quick", verdict, "quick")
    case("quick carries one reason", len(reasons), 1)
    verdict, reasons = rt.triage(["scripts/x.py"], "", 1, scan=lambda t: [])
    case("a change under scripts/ is full", verdict, "full")
    case("the risky path is named", "touches scripts/x.py" in reasons, True)
    verdict, _ = rt.triage([".claude/settings.json"], "", 1, scan=lambda t: [])
    case("settings.json is full", verdict, "full")
    verdict, _ = rt.triage([".claude/settings.local.json"], "", 1, scan=lambda t: [])
    case("settings.local.json alone is quick", verdict, "quick")
    verdict, _ = rt.triage(["wiki/clients/alpha-co/x.md"], "", 1, scan=lambda t: [])
    case("a client folder path is full", verdict, "full")
    verdict, _ = rt.triage(["scriptsx/y.py"], "", 1, scan=lambda t: [])
    case("a prefix that is not a folder is quick", verdict, "quick")
    verdict, _ = rt.triage(["_ai/rules.md"], "", 1, scan=lambda t: [])
    case("rules.md is full", verdict, "full")

    print("personal data and size")
    fake_mail = "contact jane.doe" + "@" + "example" + ".org"
    verdict, reasons = rt.triage(["docs/notes.md"], fake_mail, 1)
    case("a fake email in added lines is full", verdict, "full")
    case("the reason names personal data", "personal data or a secret in added lines" in reasons, True)
    verdict, _ = rt.triage(["docs/notes.md"], "", 400, scan=lambda t: [])
    case("400 changed lines is full", verdict, "full")
    verdict, _ = rt.triage(["docs/notes.md"], "", 399, scan=lambda t: [])
    case("399 changed lines is quick", verdict, "quick")
    verdict, reasons = rt.triage(["docs/notes.md"], "", 400, scan=lambda t: [])
    case("the large-diff reason is given", reasons, ["large diff: 400 lines"])
    verdict, reasons = rt.triage(["docs/notes.md"], "x", 1, scan=boom)
    case("a scan error is full", verdict, "full")
    case("a scan error gives the scan reason", reasons, ["PII scan unavailable"])
    many = ["scripts/f%02d.py" % i for i in range(11)]
    verdict, reasons = rt.triage(many, "", 1, scan=lambda t: [])
    case("more than ten risky paths list ten", len([r for r in reasons if r.startswith("touches")]), 10)
    case("the rest are counted", reasons[-1], "and 1 more")

    print("git facts")
    with tempfile.TemporaryDirectory() as tmp:
        repo, _ = new_repo(tmp)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "a.py").write_text("print('a')\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add script")
        first = git(repo, "rev-parse", "HEAD")
        git(repo, "mv", "scripts/a.py", "docs/a.py")
        git(repo, "commit", "-q", "-m", "move script out")
        paths, _, _ = rt.diff_facts(repo, first)
        case("a rename out of scripts/ names the old path", "scripts/a.py" in paths, True)
        case("a rename out of scripts/ names the new path", "docs/a.py" in paths, True)
        verdict, _ = rt.triage(paths, "", 2, scan=lambda t: [])
        case("a rename out of scripts/ is full", verdict, "full")

        (repo / "docs" / "note.md").write_text("line one\nline two\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "note")
        paths, added, changed = rt.diff_facts(repo, first)
        case("added text has no +++ header", "+++" in added, False)
        case("added text keeps the added lines", "line two" in added, True)
        case("changed lines are added plus removed", changed >= 2, True)

        proc = run_cli(["--base", "no-such-ref", "--repo", str(repo)], tmp)
        case("a git failure exits 2", proc.returncode, 2)
        case("a git failure prints review: full", "review: full" in proc.stdout, True)
        case("a git failure gives the git reason", "git failed:" in proc.stdout, True)

        (repo / "docs" / "dirty.md").write_text("not committed\n", encoding="utf-8")
        proc = run_cli(["--base", first, "--repo", str(repo)], tmp)
        case("the CLI exits 0 on a good base", proc.returncode, 0)
        case("uncommitted changes are reported", "uncommitted changes not included" in proc.stdout, True)

    print(f"\ntest_review_triage: {RAN[0] - FAILS[0]} passed, {FAILS[0]} failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
