"""The nightly digest: turn the day's Claude Code transcripts into wiki notes and push them.

Run at midnight (Pacific/Auckland) by the timer install_vault.py --nightly writes. It
handles the day that just ended, and any earlier day still unhandled (at most seven,
oldest first), so a machine that was off is caught up on the next run.

For each day: the fact file is built by day_digest.py (no AI). Claude then runs headless
in the wiki with the fixed prompt in nightly_digest_prompt.md and narrow tools. The wiki
checks run. Only when they pass, Claude succeeds, the timesheet exists and every change is
under wiki/, index.md or _ai/client-names.json is the work committed and pushed to main.
Otherwise the work is parked on a local branch digest/<day>, nothing is pushed, and the
report and notify-me say why. A day is marked done (_local/digest/<day>.done) only after a
push or when nothing changed.

Every step is logged to <wiki>/_local/digest/<day>-report.md. Nothing goes to any service
except the local claude run. The claude run is the only Claude call; the tests inject a
fake runner for it.

CLI: python scripts/nightly_digest.py [--day YYYY-MM-DD] [--projects PATH]
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
BRAIN = HERE.parent
sys.path.insert(0, str(HERE))
import day_digest  # noqa: E402
import wiki_root  # noqa: E402

PROMPT_FILE = HERE / "nightly_digest_prompt.md"
DIGEST_MARKER = day_digest.DIGEST_MARKER
UNATTENDED = ("This is the unattended nightly digest, pre-approved by the owner under rule R-24. "
              "No one will answer questions. Do not ask, do not wait for a go, do not plan, do not "
              "invoke skills. Do the steps in the prompt now, then stop. Leave every `status:` "
              "field unchanged.")
TOOLS = "Read,Write,Edit,MultiEdit,Glob,Grep,Bash"
ALLOWED = ("Read(./**),Glob,Grep,Edit(./wiki/**),Write(./wiki/**),MultiEdit(./wiki/**),"
           "Edit(./index.md),Bash(python scripts/new_note.py:*)")
DISALLOWED = "Edit(./.githooks/**),Write(./.githooks/**),Edit(./.claude/**),Write(./.claude/**)"
CLAUDE_TIMEOUT = 45 * 60
LOCK_STALE = 2 * 3600
MAX_DAYS = 7
IGNORED = "_local/"
CLIENT_NAMES = "_ai/client-names.json"
NOTIFY = "notify-me"
DONE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.done$")


def nz_yesterday(now=None):
    """Yesterday's date in Pacific/Auckland, for an aware UTC instant (default now)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(day_digest.nz_tz()).date() - dt.timedelta(days=1)


def done_dir(wiki):
    return wiki / "_local" / "digest"


def done_days(wiki):
    folder = done_dir(wiki)
    if not folder.is_dir():
        return set()
    found = set()
    for path in folder.iterdir():
        m = DONE_RE.match(path.name)
        if m:
            try:
                found.add(dt.date.fromisoformat(m.group(1)))
            except ValueError:
                pass
    return found


def days_to_process(wiki, today, explicit=None):
    """The days this run handles, oldest first. today is the New Zealand date."""
    if explicit is not None:
        return [explicit]
    yesterday = today - dt.timedelta(days=1)
    done = done_days(wiki)
    if not done:
        return [yesterday]
    day = max(done) + dt.timedelta(days=1)
    out = []
    while day <= yesterday and len(out) < MAX_DAYS:
        out.append(day)
        day += dt.timedelta(days=1)
    return out


class Report:
    """The step log for one day. Written on every step, so a crash keeps what happened."""

    def __init__(self, path, day):
        self.path, self.day, self.lines = pathlib.Path(path), day, []

    def add(self, step, text):
        self.lines.append("- " + step + ": " + text)
        print("  " + step + ": " + text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "# Nightly digest " + str(self.day) + "\n\n" + "\n".join(self.lines) + "\n"
        self.path.write_text(body, encoding="utf-8", newline="\n")


def take_lock(wiki):
    """The lock path if this run took it, else None (another run holds a fresh one)."""
    path = done_dir(wiki) / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if time.time() - path.stat().st_mtime < LOCK_STALE:
            return None
        path.unlink()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, (str(os.getpid()) + " " + dt.datetime.now().isoformat() + "\n").encode("utf-8"))
    os.close(fd)
    return path


def git(wiki, env, *args):
    return subprocess.run(["git", "-C", str(wiki), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def changes(wiki, env):
    """(code, path) for every change outside _local/, or None if git cannot say."""
    res = git(wiki, env, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if res.returncode != 0:
        return None
    entries = res.stdout.split("\0")
    out, i = [], 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            i += 1  # the old name of a rename or copy follows as its own entry
        if not path.startswith(IGNORED):
            out.append((code, path))
    return out


def outside(paths):
    return [p for _, p in paths
            if not (p.startswith("wiki/") or p in ("index.md", CLIENT_NAMES))]


def tail(text, limit=1500):
    text = (text or "").strip()
    return text[-limit:] if text else ""


def preflight(wiki, env, report):
    """Stop unless the wiki is on main, clean, and pulls fast-forward. Returns "" when ready, else why."""
    branch = git(wiki, env, "symbolic-ref", "--short", "HEAD").stdout.strip()
    if branch != "main":
        why = "not on main (on " + (branch or "a detached HEAD") + ")"
    else:
        dirty = changes(wiki, env)
        if dirty is None:
            why = "git status failed"
        elif dirty:
            why = "uncommitted changes (" + ", ".join(p for _, p in dirty[:5]) + ")"
        else:
            pull = git(wiki, env, "pull", "--ff-only")
            if pull.returncode != 0:
                why = "pull failed (" + tail(pull.stderr or pull.stdout, 300) + ")"
            else:
                report.add("pull", "fast-forward ok")
                return ""
    report.add("preflight", why + "; nothing done")
    return why


def claude_argv(claude, prompt):
    return [claude, "-p", prompt, "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--setting-sources", "project,local", "--no-session-persistence",
            "--tools", TOOLS, "--allowedTools", ALLOWED, "--disallowedTools", DISALLOWED,
            "--append-system-prompt", UNATTENDED]


def build_prompt(day, json_path):
    text = PROMPT_FILE.read_text(encoding="utf-8")
    text = (text.replace("{json_path}", json_path.as_posix())
            .replace("{day}", day.isoformat()).replace("{brain}", BRAIN.as_posix()))
    return DIGEST_MARKER + " " + text


def run_checks(wiki, env, report):
    """The wiki checks from the brain, run in the wiki. Returns True when the required ones pass."""
    import importlib.util
    ok = True
    checks = [("check_links.py", True), ("check_maps.py", False)]
    if importlib.util.find_spec("yaml") is not None:
        checks.append(("check_frontmatter.py", True))
    else:
        report.add("checks", "check_frontmatter skipped: PyYAML is not installed")
    for name, required in checks:
        res = subprocess.run([sys.executable, str(HERE / name)], cwd=str(wiki), env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        status = "pass" if res.returncode == 0 else ("FAIL" if required else "warn")
        report.add("check " + name, status + (("; " + tail(res.stdout + res.stderr, 400))
                                              if res.returncode else ""))
        if res.returncode != 0 and required:
            ok = False
    return ok


def park(wiki, env, day, why, report):
    """Keep the work on digest/<day>, leave main as the remote has it, push nothing."""
    branch = "digest/" + day.isoformat()
    pending = changes(wiki, env)
    if not pending:
        report.add("park", "no changes to park (" + why + ")")
        return
    steps = [("switch", ["switch", "-C", branch]),
             ("add", ["add", "-A"]),
             ("commit", ["commit", "-m", "Nightly digest " + day.isoformat() + " (parked: " + why + ")"])]
    for label, args in steps:
        res = git(wiki, env, *args)
        if res.returncode != 0 and not (label == "commit" and "nothing to commit" in (res.stdout or "")):
            report.add("park", label + " failed on " + branch + ": " + tail(res.stderr or res.stdout, 300))
            break
    back = git(wiki, env, "switch", "main")
    reset = git(wiki, env, "reset", "--hard", "origin/main")
    if back.returncode or reset.returncode:
        report.add("park", "could not return to main: " + tail(back.stderr + reset.stderr, 300))
        return
    report.add("park", "work parked on " + branch + ", not pushed (" + why + ")")


def process_day(day, wiki, env, runner, projects, repos, claude, report):
    """Handle one day. Returns a summary dict; ok is False when the day must stop the batch."""
    summary = {"day": day.isoformat(), "ok": False, "pushed": False, "created": 0, "updated": 0}
    if (done_dir(wiki) / (day.isoformat() + ".done")).exists():
        report.add("skip", "already done")
        summary["ok"] = True
        return summary

    facts = day_digest.extract(day, day_digest.nz_tz(), projects, wiki, repos)
    json_path = done_dir(wiki) / (day.isoformat() + ".json")
    json_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    report.add("facts", str(len(facts["sessions"])) + " session(s), clients " +
               json.dumps(facts["clients"], sort_keys=True) + ", other " +
               json.dumps(facts["other"], sort_keys=True))

    claude_env = {k: v for k, v in env.items() if k != "TYPESAFE_API_KEY"}
    prompt = build_prompt(day, json_path)
    try:
        proc = runner(claude_argv(claude, prompt), cwd=str(wiki), env=claude_env,
                      timeout=CLAUDE_TIMEOUT, capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
        claude_ok = proc.returncode == 0
        report.add("claude", "exit " + str(proc.returncode) +
                   ("" if claude_ok else "; " + tail(proc.stderr or proc.stdout, 400)))
    except subprocess.TimeoutExpired:
        claude_ok = False
        report.add("claude", "timed out after 45 minutes")
    except OSError as err:
        claude_ok = False
        report.add("claude", "could not start: " + str(err))

    checks_ok = run_checks(wiki, env, report)
    timesheet = wiki / "wiki" / "internal" / "timesheets" / (day.isoformat() + "-timesheet.md")
    timesheet_ok = timesheet.is_file()
    if not timesheet_ok:
        report.add("timesheet", "missing: " + timesheet.relative_to(wiki).as_posix())

    pending = changes(wiki, env)
    if pending is None:
        report.add("changes", "git status failed")
        park(wiki, env, day, "git status failed", report)
        return summary
    bad = outside(pending)
    if bad:
        report.add("changes", "outside the allowed paths: " + ", ".join(bad[:10]))
    summary["created"] = sum(1 for c, p in pending if p.startswith("wiki/") and ("?" in c or "A" in c))
    summary["updated"] = sum(1 for c, p in pending if p.startswith("wiki/") and "M" in c)
    report.add("changes", str(len(pending)) + " path(s): " + str(summary["created"]) +
               " created, " + str(summary["updated"]) + " updated")

    if not (claude_ok and checks_ok and timesheet_ok and not bad):
        why = []
        if not claude_ok:
            why.append("claude failed")
        if not checks_ok:
            why.append("wiki checks failed")
        if not timesheet_ok:
            why.append("no timesheet")
        if bad:
            why.append("changes outside the allowed paths")
        park(wiki, env, day, ", ".join(why), report)
        return summary

    if pending:
        paths = ["wiki", "index.md"] + ([CLIENT_NAMES] if (wiki / CLIENT_NAMES).is_file() else [])
        add = git(wiki, env, "add", "-A", "--", *paths)
        env_main = dict(env, VAULT_ALLOW_MAIN="1")
        commit = git(wiki, env_main, "commit", "-m", "Nightly digest " + day.isoformat())
        if add.returncode or commit.returncode:
            report.add("commit", "failed: " + tail(add.stderr + commit.stderr, 300))
            park(wiki, env, day, "commit failed", report)
            return summary
        report.add("commit", "committed on main")
        push = git(wiki, env_main, "push", "origin", "main")
        if push.returncode:
            report.add("push", "failed: " + tail(push.stderr, 300))
            park(wiki, env, day, "push failed", report)
            return summary
        report.add("push", "pushed to origin main")
        summary["pushed"] = True
    else:
        report.add("commit", "nothing changed")

    (done_dir(wiki) / (day.isoformat() + ".done")).write_text("", encoding="utf-8")
    summary["ok"] = True
    return summary


def notify(env, message):
    """Send one line through notify-me when it is on PATH. Returns True when it ran."""
    exe = shutil.which(NOTIFY, path=env.get("PATH"))
    if not exe:
        return False
    try:
        subprocess.run([exe, message], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def summarise(results):
    parts = []
    for r in results:
        if r["pushed"]:
            state = "pushed"
        elif r["ok"]:
            state = "nothing to push"
        else:
            state = "NOT pushed, parked on digest/" + r["day"]
        parts.append(r["day"] + ": " + str(r["created"]) + " created, " + str(r["updated"]) +
                     " updated, " + state)
    return "Nightly digest: " + "; ".join(parts)


def run(day=None, env=None, runner=subprocess.run, projects=None, today=None):
    """Run the digest for one day (or the days due). Returns 0 on success, 1 on failure, 2 without a wiki."""
    env = dict(os.environ) if env is None else dict(env)
    wiki = wiki_root.wiki_root(env=env)
    if wiki is None:
        print("wiki not found. Run: python " + BRAIN.as_posix() + "/scripts/install_vault.py --wiki <path>",
              file=sys.stderr)
        return 2
    tz = day_digest.nz_tz()
    today = today or dt.datetime.now(dt.timezone.utc).astimezone(tz).date()
    days = days_to_process(wiki, today, day)
    if not days:
        print("nothing to process: every day up to yesterday is done.")
        return 0
    report = Report(done_dir(wiki) / (days[0].isoformat() + "-report.md"), days[0])

    lock = take_lock(wiki)
    if lock is None:
        report.add("lock", "another run holds _local/digest/.lock; nothing done")
        return 0
    try:
        claude = shutil.which("claude", path=env.get("PATH"))
        if not claude:
            report.add("claude", "not on PATH; nothing done")
            notify(env, "Nightly digest for " + days[0].isoformat() + ": claude not on PATH, not run.")
            return 1
        why = preflight(wiki, env, report)
        if why:
            notify(env, "Nightly digest for " + days[0].isoformat() + " did not start: " + why +
                   ". Nothing was changed.")
            return 1

        repos = day_digest.load_repos(env.get("DAY_DIGEST_REPOS") or day_digest.REPOS)
        projects = pathlib.Path(projects) if projects else day_digest.projects_dir()
        results = []
        for due in days:
            day_report = Report(done_dir(wiki) / (due.isoformat() + "-report.md"), due)
            print("day " + due.isoformat())
            result = process_day(due, wiki, env, runner, projects, repos, claude, day_report)
            results.append(result)
            if not result["ok"]:
                break
        ok = all(r["ok"] for r in results)
        message = summarise(results)
        notify(env, message)
        print(message)
        return 0 if ok else 1
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Turn the day's transcripts into wiki notes and push.")
    ap.add_argument("--day", metavar="YYYY-MM-DD", help="run this one day (default: the days due)")
    ap.add_argument("--projects", metavar="PATH", help="projects folder (default: the config folder's)")
    args = ap.parse_args(argv)
    day = None
    if args.day:
        try:
            day = dt.date.fromisoformat(args.day)
        except ValueError:
            print("day must be YYYY-MM-DD: " + args.day, file=sys.stderr)
            return 2
    return run(day=day, projects=args.projects)


if __name__ == "__main__":
    sys.exit(main())
