#!/usr/bin/env python3
"""
Scan Claude Code + Grok CLI session histories for what was worked on, per NZT day.

Usage:
  scan_sessions.py                     # today (NZT)
  scan_sessions.py 2026-08-19          # one day
  scan_sessions.py 2026-08-17 2026-08-21   # inclusive range

Reads (never writes):
  ~/.claude/projects/*/*.jsonl                 (Claude transcripts)
  ~/.grok/sessions/*/*/summary.json            (Grok session summaries)

Prints a per-day timeline: tool, project, NZT span, message count, topic, sample prompts.
Days in the range with no sessions are called out explicitly (likely meetings / offline work).
Timestamps come from in-file activity times (Claude) / summary created+last-active (Grok),
converted to Pacific/Auckland.
"""
import json, sys, glob, os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NZ = ZoneInfo("Pacific/Auckland")
CLAUDE_GLOB = os.path.expanduser("~/.claude/projects/*/*.jsonl")
GROK_GLOB   = os.path.expanduser("~/.grok/sessions/*/*/summary.json")

# the logging session itself is never the work being logged
SKIP_PROJECTS = {"timesheets"}


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def nz(dt):
    return dt.astimezone(NZ)


def daterange(argv):
    if len(argv) >= 2:
        return argv[0], argv[1]
    if len(argv) == 1:
        return argv[0], argv[0]
    today = datetime.now(NZ).strftime("%Y-%m-%d")
    return today, today


def proj_from_claude(path):
    slug = os.path.basename(os.path.dirname(path))
    slug = slug.lstrip("-")
    return slug.split("projects-")[-1] if "projects-" in slug else slug


def scan_claude(start, end):
    out = []
    for f in glob.glob(CLAUDE_GLOB):
        try:
            mt = nz(datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc))
        except OSError:
            continue
        if mt.strftime("%Y-%m-%d") < start:      # last write before the range → cannot overlap
            continue
        first = last = None
        days = set()
        summaries, prompts = [], []
        try:
            for line in open(f, encoding="utf-8", errors="ignore"):
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = parse_ts(o.get("timestamp"))
                if ts:
                    first = first or ts
                    last = ts
                    days.add(nz(ts).strftime("%Y-%m-%d"))
                if o.get("type") == "summary" and o.get("summary"):
                    summaries.append(o["summary"])
                m = o.get("message", {})
                if isinstance(m, dict) and m.get("role") == "user":
                    c = m.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c
                                     if isinstance(x, dict) and x.get("type") == "text")
                    c = str(c).strip()
                    if c and not c.startswith("<") and "system-reminder" not in c:
                        prompts.append(c.replace("\n", " ")[:160])
        except OSError:
            continue
        if not first:
            continue
        if proj_from_claude(f) in SKIP_PROJECTS:
            continue
        fnz, lnz = nz(first), nz(last)
        if fnz.strftime("%Y-%m-%d") <= end and lnz.strftime("%Y-%m-%d") >= start:
            out.append(dict(tool="claude", project=proj_from_claude(f),
                            first=fnz, last=lnz, days=sorted(days),
                            topic=(summaries[0] if summaries else (prompts[0] if prompts else "?")),
                            prompts=prompts[:3], nmsg=len(prompts)))
    return out


def scan_grok(start, end):
    out = []
    for f in glob.glob(GROK_GLOB):
        try:
            o = json.load(open(f, encoding="utf-8", errors="ignore"))
        except (ValueError, OSError):
            continue
        ca = parse_ts(o.get("created_at"))
        ua = parse_ts(o.get("last_active_at") or o.get("updated_at"))
        if not ca and not ua:
            continue
        fnz = nz(ca or ua)
        lnz = nz(ua or ca)
        if fnz.strftime("%Y-%m-%d") <= end and lnz.strftime("%Y-%m-%d") >= start:
            cwd = (o.get("info", {}) or {}).get("cwd", "?")
            proj = cwd.split("/projects/")[-1] if "/projects/" in cwd else cwd
            # summary.json has no per-message times; derive active days from the mtimes of the
            # session dir's files (chat_history, events, per-turn recap_requests/*) — real activity,
            # not a span-fill that would mark every day between first and last touch.
            sess_dir = os.path.dirname(f)
            days = set()
            for root, _, files in os.walk(sess_dir):
                for fn in files:
                    try:
                        m = nz(datetime.fromtimestamp(os.path.getmtime(os.path.join(root, fn)), tz=timezone.utc))
                        days.add(m.strftime("%Y-%m-%d"))
                    except OSError:
                        pass
            out.append(dict(tool="grok", project=proj, first=fnz, last=lnz, days=sorted(days),
                            topic=o.get("session_summary", "?"),
                            prompts=[o["last_turn_summary"]] if o.get("last_turn_summary") else [],
                            nmsg=o.get("num_chat_messages", 0)))
    return out


def main():
    # Windows consoles default to cp1252, which cannot print the arrows and dashes below
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    start, end = daterange(sys.argv[1:])
    sessions = scan_claude(start, end) + scan_grok(start, end)

    # list each session under EVERY NZ day it was active (within range)
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    print(f"\nSession scan  {start} → {end}  (NZT)\n" + "=" * 60)
    day = d0
    while day <= d1:
        ds = day.isoformat()
        rows = sorted((s for s in sessions if ds in s["days"]), key=lambda r: r["first"])
        print(f"\n{day.strftime('%a %d %b %Y')}")
        if not rows:
            print("   (no Claude/Grok sessions — meetings / offline / another tool)")
        for r in rows:
            # if the session spans days, show the span end date for context
            same = r["first"].date().isoformat() == ds and r["last"].date().isoformat() == ds
            span = f"{r['first']:%H:%M}–{r['last']:%H:%M}" if same else f"{r['first']:%d %b %H:%M}→{r['last']:%d %b %H:%M}"
            print(f"   [{r['tool']:6}] {r['project']:<34} {span}  ({r['nmsg']} msgs)")
            print(f"       {r['topic']}")
            for p in r["prompts"]:
                print(f"         > {p}")
        day += timedelta(days=1)
    print()


if __name__ == "__main__":
    main()
