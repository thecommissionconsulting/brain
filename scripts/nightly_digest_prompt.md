Nightly digest for {day}. The fact file is {json_path}. The brain is {brain}.

Do these steps in order. You work only in this wiki.

1. Read the fact file {json_path}. It lists the day's sessions, the minutes per client
   (clients) and per other folder (other), and the lines it could not read.

2. For each client that has sessions, append a dated bullet summary to the client's
   active engagement note's "## Log" section. Use the client slug from the fact file.
   If the client has no engagement note, create one first with
   `python scripts/new_note.py engagement <client> "<Title>" --date {day} --source nightly-digest`.

3. When a client's sessions held a discussion, decisions or actions, create a meeting
   note with `python scripts/new_note.py meeting <client> "<Topic>" --date {day} --source nightly-digest`
   and fill its Notes, Decisions and Actions sections.

4. For each client with sessions, review that client's notes changed in the last 30
   days and update them: tick an action only when the transcripts show it done, set
   `last_touch:` on an engagement when there was work on it, and add a dated line where
   a fact changed.

5. Add `source: nightly-digest` to the frontmatter of every note you create or edit.

6. Never delete a note, and never delete a line you did not write.

7. Never name one client inside another client's folder.

8. Never write outside `wiki/` and `index.md`.

9. Last, run `python scripts/new_note.py timesheet --date {day} --source nightly-digest`
   and fill its "## Hours" section with a table: hours per client (from clients) and
   hours per other folder (from other). Hours are minutes divided by 60, one decimal place.

Use only facts in the fact file and in the wiki. Where the transcripts do not say, write
"unclear from transcripts" rather than guess. Do not invent a name, a date, a decision
or an amount.
