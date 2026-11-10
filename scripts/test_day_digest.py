"""Cases for day_digest.py, run from the repo root: python scripts/test_day_digest.py

Every transcript is a fake written into a temporary projects folder, with invented names
(Alpha Co, Beta Ltd, Gamma Two). VAULT_CLAUDE_HOME points at a temporary folder for the
whole run, so no case reads ~/.claude. The wiki is a temporary folder; no case reads the
real wiki or the real _local/. Time-zone cases force the built-in New Zealand rule by
passing a factory that fails, and compare it with zoneinfo where zoneinfo has data.
"""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("day_digest", ROOT / "scripts" / "day_digest.py")
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)

FAILS = [0]
RAN = [0]
SKIPS = []


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(50) +
          "want " + str(want)[:30].ljust(30) + " got " + str(got)[:30])


def fixture(base):
    """A temp wiki with one wiki client folder (gamma-two) and a projects folder."""
    base = pathlib.Path(base).resolve()
    wiki = base / "wiki"
    (wiki / "wiki" / "clients" / "gamma-two").mkdir(parents=True)
    (wiki / "index.md").write_text("# index\n", encoding="utf-8")
    return wiki, base / "projects", base


def write(projects, folder, name, rows):
    """Write one fake transcript; dict rows are dumped, str rows are written as they are."""
    path = projects / folder / (name + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def user(ts, sid, cwd, text):
    return {"type": "user", "timestamp": ts, "sessionId": sid, "cwd": cwd,
            "isMeta": False, "isSidechain": False,
            "message": {"role": "user", "content": text}}


def tool_use(ts, sid, cwd, name, inp):
    return {"type": "assistant", "timestamp": ts, "sessionId": sid, "cwd": cwd,
            "isMeta": False, "isSidechain": False,
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "t1", "name": name, "input": inp}]}}


def tool_result(ts, sid, cwd):
    return {"type": "user", "timestamp": ts, "sessionId": sid, "cwd": cwd,
            "isMeta": False, "isSidechain": False,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "done"}]}}


def title(sid, text):
    return {"type": "custom-title", "sessionId": sid, "customTitle": text}


def session_by_id(result, sid):
    for s in result["sessions"]:
        if s.get("session_id") == sid:
            return s
    return None


def raiser():
    raise RuntimeError("tzdata missing (forced for the test)")


def zone_or_none():
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo("Pacific/Auckland")
    except Exception:
        return None


def run_day(day, tz, projects, wiki, repos):
    return dd.extract(dt.date.fromisoformat(day), tz, projects, wiki, repos)


def main():
    saved_home = os.environ.get("VAULT_CLAUDE_HOME")
    saved_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VAULT_CLAUDE_HOME"] = str(pathlib.Path(tmp) / "claude-home")
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            run_cases(tmp)
        finally:
            for name, value in (("VAULT_CLAUDE_HOME", saved_home), ("CLAUDE_CONFIG_DIR", saved_cfg)):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    for line in SKIPS:
        print("  skipped: " + line)
    print("\ntest_day_digest: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


def run_cases(tmp):
    wiki, projects, base = fixture(tmp)
    repo = base / "work" / "acme-repo"
    repo_s = str(repo)
    repos = {repo_s: "alpha-co"}
    gamma_notes = str(wiki / "wiki" / "clients" / "gamma-two" / "notes")
    tz = dd.nz_tz()
    # 2026-11-10 is NZDT (+13) in every zone source, so these cases hold either way.

    print("day boundaries and time zone")
    write(projects, "acme", "late", [
        user("2026-11-10T10:59:00Z", "s-late", repo_s, "Build the thing"),
        user("2026-11-10T11:01:00Z", "s-late", repo_s, "Next day"),
    ])
    day10 = run_day("2026-11-10", tz, projects, wiki, repos)
    s = session_by_id(day10, "s-late")
    case("10:59Z counts for the 10th (23:59 NZDT)", s["start"], "2026-11-10T23:59:00+13:00")
    case("11:01Z is not on the 10th", s["end"], "2026-11-10T23:59:00+13:00")
    day11 = run_day("2026-11-11", tz, projects, wiki, repos)
    s = session_by_id(day11, "s-late")
    case("11:01Z counts for the 11th (00:01 NZDT)", s["start"], "2026-11-11T00:01:00+13:00")
    case("the 11th holds only its own line", s["prompts"], ["Next day"])

    print("gap cap")
    write(projects, "acme", "gap", [
        user("2026-11-10T01:00:00Z", "s-gap", repo_s, "one"),
        user("2026-11-10T01:05:00Z", "s-gap", repo_s, "two"),
        user("2026-11-10T01:55:00Z", "s-gap", repo_s, "three"),
    ])
    gap = run_day("2026-11-10", tz, projects, wiki, repos)
    case("gaps of 5 and 50 minutes give 5 + 15", session_by_id(gap, "s-gap")["minutes"], 20.0)
    case("the client total is 20 minutes", gap["clients"].get("alpha-co"), 20.0)

    print("client mapping")
    nested = wiki / "wiki" / "clients" / "gamma-two" / "repo"
    case("repo mapping beats the wiki folder",
         dd.client_for(str(nested / "src"), wiki, {str(nested): "alpha-co"}), "alpha-co")
    case("the wiki folder maps without a repo",
         dd.client_for(gamma_notes, wiki, {}), "gamma-two")
    case("the wiki clients folder itself maps to nothing",
         dd.client_for(str(wiki / "wiki" / "clients"), wiki, {}), None)
    case("an unrelated folder maps to nothing",
         dd.client_for(str(base / "elsewhere"), wiki, {}), None)
    case("no cwd maps to nothing", dd.client_for(None, wiki, repos), None)
    longest = {"/x/a": "one", "/x/a/b": "two"}
    case("longest repo match wins", dd.client_for("/x/a/b/c", wiki, longest), "two")
    case("a shorter repo still maps", dd.client_for("/x/a/c", wiki, longest), "one")
    case("a sibling folder with the same prefix does not match",
         dd.client_for(repo_s + "-old/src", wiki, repos), None)
    case("a trailing slash on the repo is ignored",
         dd.client_for(repo_s + "/src/", wiki, {repo_s + "/": "alpha-co"}), "alpha-co")
    case("Windows-style repo path matches its forward-slash form",
         dd.client_for("C:/work/acme/src", wiki, {"C:\\work\\acme": "alpha-co"}), "alpha-co")
    case("Windows-style cwd matches a forward-slash repo",
         dd.client_for("C:\\work\\acme\\src", wiki, {"C:/work/acme/": "alpha-co"}), "alpha-co")

    print("no-client sessions")
    scratch = str(base / "scratch" / "notes-dir")
    write(projects, "notes-dir", "free", [
        title("s-free", "Free talk"),
        user("2026-11-10T02:00:00Z", "s-free", scratch, "private prompt text"),
        user("2026-11-10T02:04:00Z", "s-free", scratch, "another private prompt"),
    ])
    free = run_day("2026-11-10", tz, projects, wiki, repos)
    s = session_by_id(free, "s-free")
    case("no-client session has no session id in the output", s is None, True)
    got = [x for x in free["sessions"] if x.get("folder") == "notes-dir"]
    case("no-client session keeps start, end, minutes, folder",
         sorted(got[0]) if got else None, ["end", "folder", "minutes", "start"])
    case("no-client session has no prompts or title", "prompts" in str(got), False)
    case("no-client minutes go to the folder", free["other"].get("notes-dir"), 4.0)
    case("no-client prompt text never reaches the fact file",
         "private prompt" in json.dumps(free, ensure_ascii=False), False)

    print("digest-marker session")
    marker_proj = base / "p-marker"
    write(marker_proj, "acme", "digest", [
        user("2026-11-10T03:00:00Z", "s-digest", repo_s, "[nightly-digest] write the notes"),
        user("2026-11-10T03:05:00Z", "s-digest", repo_s, "more"),
    ])
    marked = run_day("2026-11-10", tz, marker_proj, wiki, repos)
    case("a session started with the marker is dropped", session_by_id(marked, "s-digest"), None)
    case("the marker session adds no minutes", marked["clients"], {})

    print("content shapes")
    write(projects, "acme", "shapes", [
        user("2026-11-10T04:00:00Z", "s-shape", repo_s, "Please check the SOW"),
        tool_result("2026-11-10T04:01:00Z", "s-shape", repo_s),
        {"type": "user", "timestamp": "2026-11-10T04:02:00Z", "sessionId": "s-shape",
         "cwd": repo_s, "isMeta": False, "isSidechain": False,
         "message": {"role": "user", "content": [
             {"type": "text", "text": "Also the budget"},
             {"type": "tool_result", "tool_use_id": "t9", "content": "x"}]}},
        {"type": "user", "timestamp": "2026-11-10T04:03:00Z", "sessionId": "s-shape",
         "cwd": repo_s, "isMeta": True, "isSidechain": False,
         "message": {"role": "user", "content": "caveat: local command output"}},
        {"type": "user", "timestamp": "2026-11-10T04:04:00Z", "sessionId": "s-shape",
         "cwd": repo_s, "isMeta": False, "isSidechain": True,
         "message": {"role": "user", "content": "sidechain prompt"}},
        user("2026-11-10T04:05:00Z", "s-shape", repo_s, "x" * 600),
    ])
    shapes = run_day("2026-11-10", tz, projects, wiki, repos)
    s = session_by_id(shapes, "s-shape")
    case("tool results are not prompts", s["prompts"][0], "Please check the SOW")
    case("text parts of a list are prompts", s["prompts"][1], "Also the budget")
    case("meta and sidechain user lines are not prompts",
         [p for p in s["prompts"] if "caveat" in p or "sidechain" in p], [])
    case("a prompt is cut to 500 characters", len(s["prompts"][2]), 500)

    write(projects, "acme", "many", [
        user("2026-11-10T05:%02d:00Z" % i, "s-many", repo_s, "p%d" % i) for i in range(45)
    ])
    many = run_day("2026-11-10", tz, projects, wiki, repos)
    case("at most 40 prompts are kept", len(session_by_id(many, "s-many")["prompts"]), 40)

    print("files, commits and titles")
    write(projects, "acme", "work", [
        user("2026-11-10T06:00:00Z", "s-work", repo_s, "Write the page"),
        tool_use("2026-11-10T06:01:00Z", "s-work", repo_s, "Write",
                 {"file_path": repo_s + "/notes/b.md"}),
        tool_use("2026-11-10T06:02:00Z", "s-work", repo_s, "Edit",
                 {"file_path": repo_s + "/notes/a.md"}),
        tool_use("2026-11-10T06:03:00Z", "s-work", repo_s, "MultiEdit",
                 {"file_path": repo_s + "/notes/a.md"}),
        tool_use("2026-11-10T06:04:00Z", "s-work", repo_s, "Bash",
                 {"command": "git commit -m \"Add the thing\""}),
        tool_use("2026-11-10T06:05:00Z", "s-work", repo_s, "Bash", {"command": "ls -la"}),
        tool_use("2026-11-10T06:06:00Z", "s-work", repo_s, "Bash",
                 {"command": "git commit -m 'Fix it'"}),
        title("s-work", "Page work"),
    ])
    work = run_day("2026-11-10", tz, projects, wiki, repos)
    s = session_by_id(work, "s-work")
    case("files are sorted and unique",
         s["files"], [repo_s + "/notes/a.md", repo_s + "/notes/b.md"])
    case("commit messages come from -m", s["commits"], ["Add the thing", "Fix it"])
    write(projects, "acme", "gitc", [
        user("2026-11-10T08:00:00Z", "s-gitc", repo_s, "Commit from the repo folder"),
        tool_use("2026-11-10T08:01:00Z", "s-gitc", repo_s, "Bash",
                 {"command": "git -C " + repo_s + " commit -m \"Via dash C\""}),
        tool_use("2026-11-10T08:02:00Z", "s-gitc", repo_s, "Bash",
                 {"command": "git -c user.name=x -C " + repo_s + " commit -m 'Via lower c'"}),
        tool_use("2026-11-10T08:03:00Z", "s-gitc", repo_s, "Bash",
                 {"command": "git -C " + repo_s + " status"}),
    ])
    gitc = run_day("2026-11-10", tz, projects, wiki, repos)
    case("git -C and -c commits are captured",
         session_by_id(gitc, "s-gitc")["commits"], ["Via dash C", "Via lower c"])
    case("the custom title is kept for a client session", s["title"], "Page work")
    write(projects, "acme", "untitled", [
        user("2026-11-10T07:00:00Z", "s-plain", repo_s, "hello"),
    ])
    plain = run_day("2026-11-10", tz, projects, wiki, repos)
    case("a client session without a title has null", session_by_id(plain, "s-plain")["title"], None)

    print("malformed lines, folders and relocation")
    write(projects, "acme", "bad", [
        "{not json",
        user("2026-11-10T08:00:00Z", "s-bad", repo_s, "fine"),
        {"type": "user", "timestamp": "not-a-date", "sessionId": "s-bad", "cwd": repo_s,
         "message": {"role": "user", "content": "x"}},
    ])
    bad = run_day("2026-11-10", tz, projects, wiki, repos)
    case("malformed and bad-timestamp lines are counted", bad["skipped_lines"], 2)
    write(projects, "acme/sub", "nested", [
        user("2026-11-10T09:00:00Z", "s-nested", repo_s, "in a subfolder"),
    ])
    nested_run = run_day("2026-11-10", tz, projects, wiki, repos)
    case("files in subfolders are ignored", session_by_id(nested_run, "s-nested"), None)

    beta = base / "work" / "beta-repo"
    beta_s = str(beta)
    move_proj = base / "p-move"
    write(move_proj, "move", "relocate", [
        user("2026-11-10T01:00:00Z", "s-move", repo_s, "start here"),
        {"type": "relocated", "timestamp": "2026-11-10T01:05:00Z", "sessionId": "s-move",
         "relocatedCwd": beta_s},
        user("2026-11-10T01:10:00Z", "s-move", beta_s, "continue there"),
    ])
    moved = run_day("2026-11-10", tz, move_proj, wiki, {repo_s: "alpha-co", beta_s: "beta-ltd"})
    case("minutes before a relocation go to the old client", moved["clients"].get("alpha-co"), 5.0)
    case("minutes after a relocation go to the new client", moved["clients"].get("beta-ltd"), 5.0)

    print("ordering and output")
    case("the day is in the output", day10["day"], "2026-11-10")
    starts = [x.get("start") for x in shapes["sessions"]]
    case("sessions are ordered by start", starts, sorted(starts))

    print("time zone fallback")
    fb = dd.nz_tz(make=raiser)
    case("a failing zoneinfo gives the built-in rule", isinstance(fb, dd._NZ), True)
    points = {
        "2026-04-04T13:59:00Z": "2026-04-05T02:59:00+13:00",  # last NZDT minute, April
        "2026-04-04T14:00:00Z": "2026-04-05T02:00:00+12:00",  # NZST again
        "2026-09-26T13:59:00Z": "2026-09-27T01:59:00+12:00",  # last NZST minute, September
        "2026-09-26T14:00:00Z": "2026-09-27T03:00:00+13:00",  # NZDT from 03:00
        "2026-07-01T12:00:00Z": "2026-07-02T00:00:00+12:00",  # winter
        "2026-11-10T10:59:00Z": "2026-11-10T23:59:00+13:00",  # summer
        "2027-01-10T10:59:00Z": "2027-01-10T23:59:00+13:00",  # January, year edge
        "2026-12-31T11:30:00Z": "2027-01-01T00:30:00+13:00",  # December, year edge
    }
    for utc, want in points.items():
        when = dt.datetime.fromisoformat(utc.replace("Z", "+00:00"))
        got = when.astimezone(fb).isoformat()
        case("built-in rule at " + utc, got, want)
    zi = zone_or_none()
    if zi is None:
        SKIPS.append("zoneinfo has no Pacific/Auckland data; the built-in rule is checked against fixed values only")
    else:
        agree = True
        for utc in points:
            when = dt.datetime.fromisoformat(utc.replace("Z", "+00:00"))
            agree = agree and when.astimezone(fb).isoformat() == when.astimezone(zi).isoformat()
        case("built-in rule matches zoneinfo at each boundary", agree, True)
    write(projects, "dst", "edge", [
        user("2026-09-26T11:30:00Z", "s-edge-a", repo_s, "before the change"),   # 23:30 NZST, Sep 26
        user("2026-09-26T13:30:00Z", "s-edge-b", repo_s, "after the change"),    # 01:30 NZST, Sep 27
    ])
    edge26 = run_day("2026-09-26", fb, projects, wiki, repos)
    edge27 = run_day("2026-09-27", fb, projects, wiki, repos)
    case("a line before the September change counts for the 26th",
         session_by_id(edge26, "s-edge-a") is not None, True)
    case("a line after the September change counts for the 27th",
         session_by_id(edge27, "s-edge-b") is not None, True)

    print("config folder")
    case("projects follows VAULT_CLAUDE_HOME",
         dd.projects_dir(), pathlib.Path(os.environ["VAULT_CLAUDE_HOME"]) / "projects")
    os.environ["CLAUDE_CONFIG_DIR"] = str(pathlib.Path(tmp) / "ignored")
    case("CLAUDE_CONFIG_DIR is not read",
         dd.projects_dir(), pathlib.Path(os.environ["VAULT_CLAUDE_HOME"]) / "projects")
    os.environ.pop("CLAUDE_CONFIG_DIR", None)

    print("command line")
    cli_wiki = base / "cli-wiki"
    (cli_wiki / "wiki" / "clients" / "gamma-two").mkdir(parents=True)
    (cli_wiki / "index.md").write_text("# index\n", encoding="utf-8")
    cli_projects = base / "cli-projects"
    cli_cwd = str(cli_wiki / "wiki" / "clients" / "gamma-two" / "notes")
    write(cli_projects, "acme", "cli", [user("2026-11-10T01:00:00Z", "s-cli", cli_cwd, "cli")])
    empty_repos = base / "empty-repos.json"
    empty_repos.write_text("{}\n", encoding="utf-8")
    env = dict(os.environ, BRAIN_WIKI=str(cli_wiki), DAY_DIGEST_REPOS=str(empty_repos))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "day_digest.py"),
                           "--day", "2026-11-10", "--projects", str(cli_projects)],
                          env=env, capture_output=True, text=True, encoding="utf-8")
    out_file = cli_wiki / "_local" / "digest" / "2026-11-10.json"
    case("the command exits 0", proc.returncode, 0)
    case("the default output is in the wiki's _local/digest",
         out_file.is_file(), True)
    if out_file.is_file():
        data = json.loads(out_file.read_text(encoding="utf-8"))
        case("the output names the day", data["day"], "2026-11-10")
        case("the output holds the client session", session_by_id(data, "s-cli") is not None, True)


if __name__ == "__main__":
    sys.exit(main())
