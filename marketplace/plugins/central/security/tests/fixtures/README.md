Captured from Claude Code 2.1.292 on 2026-10-07 with a throwaway plugin whose PostToolUse hook
replaced a marker string via `hookSpecificOutput.updatedToolOutput`.

- Model saw the replaced output (Read, Bash, Grep): yes
- Model saw `additionalContext` from PostToolUse: yes
- Transcript stored the replaced output: yes
- A Read() deny rule makes `cd sub && cat file` prompt (denied under -p): no. Tested with the rule
  `Read(**/.env)`, deliberately NOT matching the file read. The claim under test (from gsd's hook
  source, reported on Claude Code 2.1.259) is that the mere presence of any Read() deny rule makes
  `cd DIR && cat relative-path` compounds prompt. With that rule present, and in a no-rule control,
  `cd sub && cat note.txt` ran and printed hello both times, so the answer on 2.1.292 is no.
- On Windows the model may use the PowerShell tool instead of Bash, which a `Read|Bash|Grep|WebFetch`
  matcher misses; the first Bash probe showed this.

Session ids, paths and the image bytes are scrubbed. Re-capture after a Claude Code upgrade
that changes tool result shapes.
