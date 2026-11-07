---
name: timesheet-recall
description: Reconstruct what you worked on from local Claude Code + Grok CLI session histories, to fill timesheet gaps. Use when someone asks "what did I do on <day>", "scan my sessions", "check claude/grok for <day>", or when a timesheet day is blank and needs reconstructing. Read-only on local session transcripts; produces a per-day timeline you then map to your own time-tracking.
---

# timesheet-recall

Reconstructs a day's work from local **Claude Code** and **Grok CLI** session histories so you can
remember what to put on your timesheet. It is **read-only** on the session transcripts and prints a
per-day timeline — it does not log time anywhere itself.

## When to use
- "What was I doing on Wednesday?" / a blank or patchy timesheet day.
- Any week where you know your meetings but not the heads-down work.

## Steps

1. **Resolve the date(s)** in NZT (`TZ='Pacific/Auckland' date` if unsure what "today"/"last week" is).

2. **Scan** (read-only):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/timesheet-recall/scan_sessions.py" 2026-08-19            # one day
   python "${CLAUDE_PLUGIN_ROOT}/skills/timesheet-recall/scan_sessions.py" 2026-08-17 2026-08-21 # a range
   ```
   Output is a per-day timeline: `[tool] project  HH:MM–HH:MM  (msgs)` + topic + sample prompts.
   **Empty days are called out explicitly** — that means meetings / offline / another tool, not a miss.

3. **Map each session to your work.** Read the project + topic + prompts and decide which client or
   internal bucket each block belongs to. The scan tells you *what* and *when*; you decide the
   billing category and hours — it does not know your time-tracking setup.

4. **Turn it into hours — sanity-check, don't blindly bill the span.** A session left open logs a
   long wall-clock span that includes thinking/idle time and overlaps real meetings. Propose hours
   that fit the day's open gaps and respect anything already booked.

## How it works
- Scans `~/.claude/projects/*/*.jsonl` (Claude) and `~/.grok/sessions/*/*/summary.json` (Grok).
- Claude active-days come from in-file message timestamps; Grok active-days from the session dir's
  file mtimes (its summary has no per-message times) — so a session shows only on days it was
  actually touched, not every day in its span.
- The current project (whatever you're scanning *from*, e.g. a personal timesheets project) can be
  excluded by adding its slug to `SKIP_PROJECTS` at the top of the script.

## Caveats
- File mtimes / in-file timestamps are the clock; verify against the real day length.
- No sessions on a day ≠ no work — say so and ask.
- The scan reads the content of your local transcripts. Keep its output in your own session; don't
  send it to any external service.
