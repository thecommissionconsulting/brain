# Report template

Write the report as markdown in the client's own workspace or repo (e.g. `docs/` or an
engagement `_working/` folder). Never into the vault or skills: it describes client
code. Keep it an engineer's working document. Plain sentences, no scores.

```markdown
# Data model audit: <model name>, <date>

## Shape
<3–6 lines: what was audited (paths, object count by kind, sources by system or catalog),
the layer model used (rules file, or "none given: layer checks not run"), and what the
model is for.>

## Findings
<Ranked S1 to S4, then by confidence. One block each:>

### F<n>. <one-line statement of the defect> (<check id>, S<n>, CONFIRMED | PLAUSIBLE)
- **Where:** `<file>:<line>`, and the other side if there is one (`<doc>:<line>`)
- **What happens:** <the concrete consequence, e.g. "spoilage rows put the weight in `kind`
  and the label in `kg`, so spoilage drops out of every SUM(kg)">
- **Evidence:** <the two or three lines that show it, quoted>
- **Fix:** <one or two lines>

## Not checked
<Each check that could not be run, and why: no manifest, no rules file, SELECT * hides the
columns, statement unparsed, needs warehouse access. Include every `not_checkable` candidate
and every unparsed statement, grouped.>

## Clean
<Checks run that found nothing, in one line each, so the reader knows they were run.>
```

Verdicts:
- **CONFIRMED:** the cited lines show the defect directly, and `verify_findings.py` passed. The
  defect can be CONFIRMED from the code while its size still needs data ("drops 4% of rows").
  When it does, say so and give the query that would measure it. A consequence that exists
  only if the data looks a certain way is PLAUSIBLE.
- **PLAUSIBLE:** the code is consistent with the defect but doesn't prove it.

Drop any finding that fails verification, rather than softening it.
