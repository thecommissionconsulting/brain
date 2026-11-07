---
max_turns: 40
runs: 2
allowed_tools: [Skill, Read, Glob, Grep, Write, Bash]
---

Audit the data model in the `fixtures` directory made available to this session (it may not
be inside your working directory; find it). `model.sql` holds the SQL, and `claims.json`
lists the star schema joins its documentation asserts (the doc is the comment table at the
top of `model.sql`). There is no layer rules file, and no source is restricted except
anything under an `hr_restricted` catalog. Write the full report to `audit-report.md` in your
working directory.

Your final message must be a compact summary, not the report: one line per finding, in the
form `F<n> | <check ids> | <object> | <CONFIRMED or PLAUSIBLE> | <one-line consequence>`,
then a `Not checked:` line per item you could not decide, then `Report: audit-report.md`.
