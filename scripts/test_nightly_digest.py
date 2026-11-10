"""Cases for nightly_digest.py, run from the repo root: python scripts/test_nightly_digest.py

Every case works in its own temporary folder: a bare remote, a wiki clone of it, fake
transcripts, and a PATH that holds only git, a fake claude (never run: the runner is a
fake) and, in some cases, a fake notify-me. The real claude, the real notify-me and the
real ~/wiki are never reached. git runs for real.
"""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nd = load("nightly_digest")
hg = load("hooks_guard")

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(50) +
          "want " + str(want)[:30].ljust(30) + " got " + str(got)[:30])


DAY = "2026-11-10"
UTC = dt.timezone.utc


# ---- pure rules ---------------------------------------------------------------

def pure_cases():
    print("day choice")
    case("yesterday in NZ at 00:30 on the 11th is the 10th",
         nd.nz_yesterday(dt.datetime(2026, 11, 10, 11, 30, tzinfo=UTC)), dt.date(2026, 11, 10))
    case("yesterday in NZ at 23:30 on the 10th is the 9th",
         nd.nz_yesterday(dt.datetime(2026, 11, 10, 10, 30, tzinfo=UTC)), dt.date(2026, 11, 9))

    tmp = tempfile.mkdtemp()
    wiki = pathlib.Path(tmp)
    done = wiki / "_local" / "digest"
    done.mkdir(parents=True)
    today = dt.date(2026, 11, 11)
    case("no marker: yesterday only",
         nd.days_to_process(wiki, today), [dt.date(2026, 11, 10)])
    (done / "2026-11-05.done").write_text("", encoding="utf-8")
    case("after a marker: every day up to yesterday, oldest first",
         nd.days_to_process(wiki, today), [dt.date(2026, 11, 6) + dt.timedelta(days=i) for i in range(5)])
    (done / "2026-11-05.done").unlink()
    (done / "2026-10-01.done").write_text("", encoding="utf-8")
    got = nd.days_to_process(wiki, today)
    case("a long gap is capped at seven days, oldest first",
         (len(got), got[0]), (7, dt.date(2026, 10, 2)))
    case("an explicit day is the only day", nd.days_to_process(wiki, today, dt.date(2026, 9, 1)),
         [dt.date(2026, 9, 1)])
    (done / "2026-10-01.done").unlink()
    (done / "2026-11-12.done").write_text("", encoding="utf-8")
    case("a marker after yesterday leaves nothing", nd.days_to_process(wiki, today), [])
    shutil.rmtree(tmp, ignore_errors=True)

    print("branch rule")
    case("digest/<day> is an allowed branch", bool(hg.BRANCH_OK.match("digest/" + DAY)), True)
    case("a plain name is still refused", bool(hg.BRANCH_OK.match("digest")), False)


# ---- fixtures -----------------------------------------------------------------

NOTE_FM = ("---\ntype: note\nstatus: active\nowner: Test\ncreated: 2026-11-01\n---\n\n")

GIT_ID = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
          "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}


def git(*args, cwd=None, env=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", check=check)


def isolated_git_env(base):
    """A git environment with no owner config, so no owner hook or setting leaks in."""
    empty = base / "gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update(GIT_ID)
    env.update({"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": str(base), "XDG_CONFIG_HOME": str(base / "xdg")})
    return env


def world(base, claude=True, notify=True):
    """A bare remote, a wiki clone of it on main, fake transcripts, and the run environment."""
    base = pathlib.Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    genv = isolated_git_env(base)
    remote = base / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), env=genv)
    wiki = base / "wiki"
    wiki.mkdir()
    git("init", "-q", "-b", "main", str(wiki), env=genv)
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / ".gitignore").write_text("_local/\n", encoding="utf-8")
    eng = wiki / "wiki" / "clients" / "alpha-co" / "engagements"
    eng.mkdir(parents=True)
    (wiki / "wiki" / "clients" / "alpha-co" / "alpha-co.md").write_text(NOTE_FM + "# Alpha Co\n", encoding="utf-8")
    (eng / "alpha-co-data.md").write_text(NOTE_FM + "# Data\n\n## Log\n", encoding="utf-8")
    git("add", "-A", cwd=wiki, env=genv)
    git("commit", "-q", "-m", "fixture", cwd=wiki, env=genv)
    git("remote", "add", "origin", str(remote), cwd=wiki, env=genv)
    git("push", "-q", "-u", "origin", "main", cwd=wiki, env=genv)

    bin_dir = base / "bin"
    bin_dir.mkdir()
    for tool in ("git",):
        found = shutil.which(tool)
        (bin_dir / tool).symlink_to(found)
    if claude:
        fake = bin_dir / "claude"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
    notify_log = base / "notify.log"
    if notify:
        fake = bin_dir / "notify-me"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"" + notify_log.as_posix() + "\"\n",
                        encoding="utf-8")
        fake.chmod(0o755)

    repos = base / "repos.json"
    repos.write_text("{}\n", encoding="utf-8")
    env = dict(genv)
    env.update({"PATH": str(bin_dir), "BRAIN_WIKI": str(wiki), "DAY_DIGEST_REPOS": str(repos),
                "VAULT_CLAUDE_HOME": str(base / "claude"), "TYPESAFE_API_KEY": "not-a-real-key"})
    projects = base / "projects"
    write_session(projects, "acme", "s1", "/elsewhere/alpha-co-work/wiki/wiki/clients/alpha-co")
    return {"base": base, "wiki": wiki, "remote": remote, "env": env, "projects": projects,
            "bin": bin_dir, "notify_log": notify_log, "genv": genv}


def write_session(projects, folder, sid, cwd, day_ts="2026-11-10T01:00:00Z"):
    path = projects / folder / (sid + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "user", "timestamp": day_ts, "sessionId": sid, "cwd": cwd,
         "message": {"role": "user", "content": "Work on the data model"}},
        {"type": "assistant", "timestamp": day_ts.replace("01:00", "01:05"), "sessionId": sid,
         "cwd": cwd, "message": {"role": "assistant", "content": [
             {"type": "tool_use", "name": "Edit", "input": {"file_path": cwd + "/a.md"}}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class Fake:
    """Stands in for claude: records each call, optionally acts in the wiki, returns a code."""

    def __init__(self, action=None, rc=0, raises=None):
        self.calls, self.action, self.rc, self.raises = [], action, rc, raises

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.action:
            self.action(pathlib.Path(kw["cwd"]))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.rc, "", "")


def timesheet(wiki, day=DAY):
    path = wiki / "wiki" / "internal" / "timesheets" / (day + "-timesheet.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NOTE_FM + "# Timesheet " + day + "\n\n## Hours\n", encoding="utf-8")


def log_line(wiki, day=DAY):
    path = wiki / "wiki" / "clients" / "alpha-co" / "engagements" / "alpha-co-data.md"
    path.write_text(path.read_text(encoding="utf-8") + "- " + day + " worked on the model.\n",
                    encoding="utf-8")


def both(wiki):
    timesheet(wiki)
    log_line(wiki)


def remote_log(world_, branch="main"):
    out = git("-C", str(world_["remote"]), "log", "--format=%s", branch, check=False)
    return out.stdout.splitlines()


def local_branch(world_, name):
    return git("-C", str(world_["wiki"]), "branch", "--list", name, check=False).stdout.strip()


def notified(world_):
    path = world_["notify_log"]
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def run_with(world_, fake, day=dt.date(2026, 11, 10), projects=None, today=None):
    return nd.run(day=day, env=world_["env"], runner=fake,
                  projects=projects or world_["projects"], today=today)


def done_marker(world_, day=DAY):
    return (world_["wiki"] / "_local" / "digest" / (day + ".done")).exists()


def report_of(world_, day=DAY):
    return world_["wiki"] / "_local" / "digest" / (day + "-report.md")


# ---- the run ------------------------------------------------------------------

def run_cases():
    print("before Claude")
    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        (w["wiki"] / "_local" / "digest").mkdir(parents=True)
        (w["wiki"] / "_local" / "digest" / (DAY + ".done")).write_text("", encoding="utf-8")
        fake = Fake()
        case("a day already done is skipped (exit 0)", run_with(w, fake), 0)
        case("the skipped day never calls claude", len(fake.calls), 0)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        lock = w["wiki"] / "_local" / "digest" / ".lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("1 now\n", encoding="utf-8")
        fake = Fake()
        case("a fresh lock: another run holds it (exit 0)", run_with(w, fake), 0)
        case("a held lock calls nothing", len(fake.calls), 0)
        old = time.time() - 3 * 3600
        os.utime(lock, (old, old))
        fake = Fake(action=both)
        case("a stale lock (over 2 hours) is taken over", run_with(w, fake), 0)
        case("the stale-lock run calls claude once", len(fake.calls), 1)
        case("the lock is released at the end", lock.exists(), False)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        (w["wiki"] / "stray.md").write_text("x\n", encoding="utf-8")
        fake = Fake()
        case("a dirty wiki stops the run (exit 1)", run_with(w, fake), 1)
        case("a dirty wiki calls nothing", len(fake.calls), 0)
        (w["wiki"] / "stray.md").unlink()

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        git("checkout", "-q", "-b", "other", cwd=w["wiki"], env=w["genv"])
        fake = Fake()
        case("not on main stops the run (exit 1)", run_with(w, fake), 1)
        git("checkout", "-q", "main", cwd=w["wiki"], env=w["genv"])

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        git("remote", "set-url", "origin", str(w["base"] / "gone.git"), cwd=w["wiki"], env=w["genv"])
        fake = Fake()
        case("a failed pull stops before claude (exit 1)", run_with(w, fake), 1)
        case("a failed pull calls nothing", len(fake.calls), 0)
        case("a failed pull is reported", "pull" in report_of(w).read_text(encoding="utf-8"), True)
        case("a failed pull notifies", "pull" in notified(w), True)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp, claude=False)
        fake = Fake()
        case("claude missing on PATH exits 1", run_with(w, fake), 1)
        case("claude missing calls nothing", len(fake.calls), 0)

    print("the Claude run")
    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        fake = Fake(action=both)
        code = run_with(w, fake)
        case("success with changes exits 0", code, 0)
        argv, kw = fake.calls[0]
        case("claude is called once", len(fake.calls), 1)
        case("argv: -p then the marked prompt",
             argv[1] == "-p" and argv[2].startswith("[nightly-digest] "), True)
        case("argv: the fixed flags follow the prompt",
             argv[3:], ["--permission-mode", "dontAsk", "--permission-prompts", "none",
                        "--setting-sources", "project,local", "--no-session-persistence",
                        "--tools", "Read,Write,Edit,MultiEdit,Glob,Grep,Bash",
                        "--allowedTools",
                        "Read(./**),Glob,Grep,Edit(./wiki/**),Write(./wiki/**),MultiEdit(./wiki/**),"
                        "Edit(./index.md),Bash(python scripts/new_note.py:*)",
                        "--disallowedTools",
                        "Edit(./.githooks/**),Write(./.githooks/**),Edit(./.claude/**),Write(./.claude/**)",
                        "--append-system-prompt", nd.UNATTENDED])
        case("the run is in the wiki", pathlib.Path(kw["cwd"]), w["wiki"])
        case("the run has a 45 minute timeout", kw["timeout"], 45 * 60)
        case("the run's environment has no TYPESAFE_API_KEY", "TYPESAFE_API_KEY" in kw["env"], False)
        case("the prompt names the fact file", str(w["wiki"] / "_local" / "digest" / (DAY + ".json"))
             in argv[2], True)
        case("the prompt has no unfilled placeholder", "{json_path}" in argv[2] or "{day}" in argv[2], False)
        case("success pushes one commit to main", remote_log(w)[0], "Nightly digest " + DAY)
        case("success writes the done marker", done_marker(w), True)
        case("success writes the fact file", (w["wiki"] / "_local" / "digest" / (DAY + ".json")).is_file(), True)
        case("success writes a report", report_of(w).is_file(), True)
        case("success notifies that it was pushed", "pushed" in notified(w), True)
        case("success leaves no digest branch", local_branch(w, "digest/" + DAY), "")

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        projects = w["base"] / "other-projects"
        write_session(projects, "other", "s2", "/home/x/private-notes", "2026-11-10T02:00:00Z")
        def only_timesheet(cwd):
            timesheet(cwd)
        fake = Fake(action=only_timesheet)
        case("a day with no client sessions still exits 0", run_with(w, fake, projects=projects), 0)
        changed = git("show", "--name-only", "--format=", "main", cwd=w["remote"], check=False).stdout
        case("a no-client day commits only the timesheet",
             [l for l in changed.splitlines() if l], ["wiki/internal/timesheets/" + DAY + "-timesheet.md"])

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        timesheet(w["wiki"])
        git("add", "-A", cwd=w["wiki"], env=w["genv"])
        git("commit", "-q", "-m", "timesheet", cwd=w["wiki"], env=w["genv"])
        git("push", "-q", "origin", "main", cwd=w["wiki"], env=w["genv"])
        before = len(remote_log(w))
        fake = Fake()
        case("no change exits 0", run_with(w, fake), 0)
        case("no change pushes nothing", len(remote_log(w)), before)
        case("no change writes the done marker", done_marker(w), True)

    print("when the checks or Claude fail")
    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        def dup(cwd):
            both(cwd)
            (cwd / "wiki" / "clients" / "alpha-co" / "meetings").mkdir(parents=True)
            (cwd / "wiki" / "clients" / "alpha-co" / "meetings" / "alpha-co.md").write_text(
                NOTE_FM + "# Duplicate\n", encoding="utf-8")
        fake = Fake(action=dup)
        case("a link check failure exits 1", run_with(w, fake), 1)
        case("the failed work is parked on digest/<day>", local_branch(w, "digest/" + DAY) != "", True)
        case("nothing is pushed when checks fail", remote_log(w), ["fixture"])
        case("main is back to the remote", git("rev-parse", "main", cwd=w["wiki"], env=w["genv"]).stdout ==
             git("rev-parse", "origin/main", cwd=w["wiki"], env=w["genv"]).stdout, True)
        case("no done marker on a failed day", done_marker(w), False)
        case("a failed run notifies it was NOT pushed", "NOT pushed" in notified(w), True)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        fake = Fake(action=both, rc=1)
        case("claude exiting non-zero exits 1", run_with(w, fake), 1)
        case("claude failure parks the work", local_branch(w, "digest/" + DAY) != "", True)
        case("claude failure pushes nothing", remote_log(w), ["fixture"])

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        fake = Fake(action=both, raises=subprocess.TimeoutExpired(["claude"], 2700))  # acts, then times out
        case("a claude timeout exits 1", run_with(w, fake), 1)
        case("a claude timeout parks the work", local_branch(w, "digest/" + DAY) != "", True)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        def outside(cwd):
            both(cwd)
            (cwd / "scripts").mkdir()
            (cwd / "scripts" / "evil.py").write_text("print(1)\n", encoding="utf-8")
        fake = Fake(action=outside)
        case("a change outside the allowed paths exits 1", run_with(w, fake), 1)
        case("a change outside the allowed paths is not pushed", remote_log(w), ["fixture"])
        wiki_dir = w["wiki"] if isinstance(w, dict) else w.wiki
        head = subprocess.run(["git", "-C", str(wiki_dir), "symbolic-ref", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(wiki_dir), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        parked = subprocess.run(["git", "-C", str(wiki_dir), "show", "--name-only", "--format=",
                                 "digest/" + DAY], capture_output=True, text=True).stdout
        case("after parking, the wiki is back on main", head, "main")
        case("after parking, main is clean", dirty, "")
        case("the parked branch holds the stray file", "scripts/evil.py" in parked, True)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        fake = Fake(action=lambda cwd: log_line(cwd))
        case("a missing timesheet exits 1 even when claude exits 0", run_with(w, fake), 1)
        case("a missing timesheet is not pushed", remote_log(w), ["fixture"])

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp, notify=False)
        fake = Fake(action=lambda cwd: both(cwd), rc=1)
        case("no notify-me on PATH does not stop the run", run_with(w, fake), 1)
        case("the report still exists without notify-me", report_of(w).is_file(), True)

    with tempfile.TemporaryDirectory() as tmp:
        w = world(tmp)
        fake = Fake(action=both, rc=1)
        code = nd.run(env=w["env"], runner=fake, projects=w["projects"], today=dt.date(2026, 11, 11))
        case("with no marker, a day that fails exits 1", code, 1)
        w2 = world(pathlib.Path(tmp) / "second")
        (w2["wiki"] / "_local" / "digest").mkdir(parents=True)
        for d in ("2026-11-07",):
            (w2["wiki"] / "_local" / "digest" / (d + ".done")).write_text("", encoding="utf-8")
        fake = Fake(action=both, rc=1)
        code = nd.run(env=w2["env"], runner=fake, projects=w2["projects"], today=dt.date(2026, 11, 11))
        case("a failed day stops the batch (one claude call)", len(fake.calls), 1)
        case("a failed batch exits 1", code, 1)


def main():
    pure_cases()
    run_cases()
    print("\ntest_nightly_digest: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
