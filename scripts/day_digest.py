"""Turn one day of Claude Code transcripts into a fact file. No AI runs here.

Reads the *.jsonl files directly under each folder in the Claude config projects folder
and writes one JSON file: the day's sessions, minutes per client and per other folder,
and the count of lines it could not read. The nightly digest hands this file to Claude;
this script never sends anything anywhere.

A session with no client keeps only its start, end, minutes and folder name. A session
whose first prompt starts with DIGEST_MARKER (the nightly run's own session) is dropped.

Client mapping: a cwd inside a registered client repo (_local/client-repos.json, written
by install_vault.py --client-repo) maps to that repo's client, the longest match first.
Otherwise a cwd inside <wiki>/wiki/clients/<slug>/ maps to <slug>.

Time: the day is cut in Pacific/Auckland. zoneinfo is used when it has the data; without
it (Windows without tzdata) nz_tz() falls back to the NZ rule written below.

CLI: python scripts/day_digest.py --day YYYY-MM-DD [--out PATH] [--projects PATH]
"""
import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
BRAIN = HERE.parent
sys.path.insert(0, str(HERE))
import install_vault  # noqa: E402
import wiki_root  # noqa: E402

REPOS = BRAIN / "_local" / "client-repos.json"
DIGEST_MARKER = "[nightly-digest]"
ZONE = "Pacific/Auckland"
GAP_CAP = 15 * 60  # seconds
PROMPT_CHARS = 500
MAX_PROMPTS = 40
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
COMMIT_MSG = re.compile(r"""-m\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""")
COMMIT_CMD = re.compile(r"\bgit(\s+-[Cc]\s+\S+)*\s+commit\b")
NZ_STD = dt.timedelta(hours=12)
NZ_DST = dt.timedelta(hours=13)


def _last_sunday(year, month):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    day = nxt - dt.timedelta(days=1)
    while day.weekday() != 6:
        day -= dt.timedelta(days=1)
    return day


def _first_sunday(year, month):
    day = dt.date(year, month, 1)
    while day.weekday() != 6:
        day += dt.timedelta(days=1)
    return day


def _nz_dst_utc(utc):
    """True when this naive UTC instant is in NZDT. DST runs 02:00 NZST late Sep to 03:00 NZDT early Apr."""
    year = utc.year
    start = dt.datetime.combine(_last_sunday(year, 9), dt.time(2)) - NZ_STD
    end = dt.datetime.combine(_first_sunday(year, 4), dt.time(3)) - NZ_DST
    return utc < end or utc >= start


def _nz_dst_wall(local, fold=0):
    """True when this naive NZ wall-clock time is NZDT.

    On the April change day 02:00-03:00 happens twice; fold 0 is the first pass (NZDT),
    fold 1 the second (NZST). Late September 02:00-03:00 never happens, so it needs no case.
    """
    year = local.year
    ambiguous = dt.datetime.combine(_first_sunday(year, 4), dt.time(2))
    end = dt.datetime.combine(_first_sunday(year, 4), dt.time(3))
    start = dt.datetime.combine(_last_sunday(year, 9), dt.time(2))
    if local < ambiguous:
        return True
    if local < end:
        return fold == 0
    return local >= start


class _NZ(dt.tzinfo):
    """The New Zealand rule, for machines without zone data."""

    def utcoffset(self, value):
        return NZ_DST if _nz_dst_wall(value.replace(tzinfo=None), value.fold) else NZ_STD

    def dst(self, value):
        dst_on = _nz_dst_wall(value.replace(tzinfo=None), value.fold)
        return NZ_DST - NZ_STD if dst_on else dt.timedelta(0)

    def tzname(self, value):
        return "NZDT" if _nz_dst_wall(value.replace(tzinfo=None), value.fold) else "NZST"

    def fromutc(self, value):
        naive = value.replace(tzinfo=None)
        is_dst = _nz_dst_utc(naive)
        local = naive + (NZ_DST if is_dst else NZ_STD)
        # Standard time landing in the repeated April hour is the second pass: fold 1.
        second_pass = (not is_dst) and _nz_dst_wall(local, 0) and not _nz_dst_wall(local, 1)
        return local.replace(tzinfo=self, fold=1 if second_pass else 0)


def nz_tz(make=None):
    """The Auckland zone: zoneinfo when it has the data, else the built-in rule."""
    if make is None:
        def make():
            import zoneinfo
            return zoneinfo.ZoneInfo(ZONE)
    try:
        return make()
    except Exception:
        return _NZ()


def projects_dir():
    """The projects folder under the config folder install_vault.py uses."""
    return install_vault.claude_home() / "projects"


def load_repos(path=REPOS):
    """The client repo registry. Missing is empty; malformed is empty with a warning."""
    path = pathlib.Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("warning: " + str(path) + " is malformed; no client repos are mapped.", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _key(path):
    """One comparable form of a path: forward slashes, abspath, normcase."""
    text = str(path).replace("\\", "/")
    return os.path.normcase(os.path.abspath(text)).replace("\\", "/")


def client_for(cwd, wiki, repos):
    """The client slug for a working folder, or None."""
    if not cwd:
        return None
    here = _key(cwd)
    best, best_len = None, -1
    for repo, slug in repos.items():
        key = _key(repo)
        if (here == key or here.startswith(key + "/")) and len(key) > best_len:
            best, best_len = slug, len(key)
    if best:
        return best
    base = _key(pathlib.Path(wiki) / "wiki" / "clients")
    if here.startswith(base + "/"):
        slug = here[len(base) + 1:].split("/")[0]
        if slug:
            return slug
    return None


def folder_of(cwd):
    """The last folder name of a working folder, for a session that is not a client's."""
    if not cwd:
        return "(unknown)"
    parts = [p for p in re.split(r"[\\/]+", cwd) if p]
    return parts[-1] if parts else "(unknown)"


def _parse_ts(text):
    if not isinstance(text, str):
        raise ValueError("timestamp is not text")
    when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("timestamp has no zone")
    return when.astimezone(dt.timezone.utc)


def _prompt_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [p.get("text") for p in content
                 if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)]
        return "\n".join(texts).strip()
    return ""


def _new_session():
    return {"events": [], "prompts": [], "files": set(), "commits": [], "cwds": collections.Counter()}


def _scan_file(path, day, tz, sessions, titles, cur):
    """Read one transcript. Returns the number of lines it could not use."""
    skipped = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(obj, dict):
            skipped += 1
            continue
        sid = obj.get("sessionId")
        if not isinstance(sid, str) or not sid:
            skipped += 1
            continue
        if isinstance(obj.get("relocatedCwd"), str):
            cur[sid] = obj["relocatedCwd"]
        elif isinstance(obj.get("cwd"), str):
            cur[sid] = obj["cwd"]
        kind = obj.get("type")
        if kind == "custom-title":
            if isinstance(obj.get("customTitle"), str):
                titles[sid] = obj["customTitle"]
            continue
        if kind == "queue-operation" or "timestamp" not in obj:
            continue
        try:
            when = _parse_ts(obj["timestamp"])
        except (TypeError, ValueError):
            skipped += 1
            continue
        local = when.astimezone(tz)
        if local.date() != day:
            continue
        rec = sessions.setdefault(sid, _new_session())
        cwd = cur.get(sid)
        if cwd:
            rec["cwds"][cwd] += 1
        rec["events"].append((when, cwd))
        content = obj.get("message", {}).get("content") if isinstance(obj.get("message"), dict) else None
        if kind == "user" and not obj.get("isMeta") and not obj.get("isSidechain"):
            text = _prompt_text(obj.get("message"))
            if text and len(rec["prompts"]) < MAX_PROMPTS:
                rec["prompts"].append(text[:PROMPT_CHARS])
        if kind == "assistant" and isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "tool_use":
                    continue
                name, inp = part.get("name"), part.get("input")
                if not isinstance(inp, dict):
                    continue
                if name in WRITE_TOOLS:
                    target = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(target, str) and target:
                        rec["files"].add(target)
                elif name == "Bash" and isinstance(inp.get("command"), str):
                    command = inp["command"]
                    if COMMIT_CMD.search(command):
                        m = COMMIT_MSG.search(command)
                        if m:
                            rec["commits"].append(next(g for g in m.groups() if g is not None))
    return skipped


def extract(day, tz, projects, wiki, repos):
    """The day's facts as a dict. See the module docstring for the rules."""
    projects = pathlib.Path(projects)
    sessions, titles, cur = {}, {}, {}
    skipped = 0
    if projects.is_dir():
        for folder in sorted(p for p in projects.iterdir() if p.is_dir()):
            for path in sorted(folder.glob("*.jsonl")):
                if path.is_file():
                    skipped += _scan_file(path, day, tz, sessions, titles, cur)

    clients = collections.Counter()
    other = collections.Counter()
    out = []
    for sid, rec in sessions.items():
        if rec["prompts"] and rec["prompts"][0].startswith(DIGEST_MARKER):
            continue
        events = sorted(rec["events"], key=lambda e: e[0])
        dominant = rec["cwds"].most_common(1)[0][0] if rec["cwds"] else None
        slug = client_for(dominant, wiki, repos)
        total = 0.0
        for (prev_when, prev_cwd), (when, _) in zip(events, events[1:]):
            gap = min((when - prev_when).total_seconds(), GAP_CAP)
            total += gap
            owner = client_for(prev_cwd, wiki, repos)
            if owner:
                clients[owner] += gap / 60
            else:
                other[folder_of(prev_cwd)] += gap / 60
        local_first = events[0][0].astimezone(tz).isoformat()
        local_last = events[-1][0].astimezone(tz).isoformat()
        minutes = round(total / 60, 1)
        if slug:
            out.append((events[0][0], {
                "session_id": sid,
                "start": local_first,
                "end": local_last,
                "minutes": minutes,
                "cwd": dominant,
                "client": slug,
                "title": titles.get(sid),
                "prompts": rec["prompts"],
                "files": sorted(rec["files"]),
                "commits": rec["commits"],
            }))
        else:
            out.append((events[0][0], {
                "start": local_first,
                "end": local_last,
                "minutes": minutes,
                "folder": folder_of(dominant),
            }))

    out.sort(key=lambda pair: (pair[0], str(pair[1].get("session_id", ""))))
    return {
        "day": day.isoformat(),
        "sessions": [item for _, item in out],
        "clients": {k: round(v, 1) for k, v in sorted(clients.items())},
        "other": {k: round(v, 1) for k, v in sorted(other.items())},
        "skipped_lines": skipped,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write one day's transcript facts as JSON.")
    ap.add_argument("--day", required=True, metavar="YYYY-MM-DD")
    ap.add_argument("--out", metavar="PATH", help="output file (default: wiki _local/digest/<day>.json)")
    ap.add_argument("--projects", metavar="PATH", help="projects folder (default: the config folder's)")
    args = ap.parse_args(argv)
    try:
        day = dt.date.fromisoformat(args.day)
    except ValueError:
        print("day must be YYYY-MM-DD: " + args.day, file=sys.stderr)
        return 2
    wiki = wiki_root.require_wiki()
    projects = pathlib.Path(args.projects) if args.projects else projects_dir()
    repos = load_repos(os.environ.get("DAY_DIGEST_REPOS") or REPOS)
    result = extract(day, nz_tz(), projects, wiki, repos)
    out = pathlib.Path(args.out) if args.out else wiki / "_local" / "digest" / (day.isoformat() + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
