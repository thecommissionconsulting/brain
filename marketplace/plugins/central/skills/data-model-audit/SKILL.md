---
name: data-model-audit
description: Audit an existing analytical data model (dbt project, SQL or Databricks notebook exports) against the house dimensional, layering, testing and SAP standards, and report verified findings with file:line evidence. Use when asked to audit, review, check or assess a data model, star schema, dbt project, warehouse layer, or a model built on SAP sources. Not for building a new model, fixing SQL style or lint, or querying a warehouse.
---

# Data model audit

Find what makes the numbers wrong, rows go missing, or promotion fail, and prove each finding
from the code. The checks live in `references/checklist.md`; this file only says how to run
them. Overclaiming is the failure to avoid: a check that could not be decided is reported as
not checked, never as clean or as a defect.

## 1. Inventory

- Inputs:
  - **dbt project:** run `dbt compile` (or reuse a fresh `target/`). Audit
    `target/compiled/**` and use `target/manifest.json`. Never parse Jinja source.
  - **SQL or notebook exports:** audit the files as they are.
- Collect the documentation the model makes claims in: YAML descriptions, catalogues, star
  schema tables, comments. Write its documented joins to `claims.json` (format in the
  `audit_sql.py` docstring), with the doc's file:line on each. Write every path, in claims
  and findings, relative to one root: the directory you run the scripts from.
- Layer model: ask for the client's layer rules JSON (model-viewer format,
  `references/layers-and-dbt.md`). If there is none, write one only from the client's own
  layer documentation. Otherwise, skip the layer checks and say so.
- Ask whether any sources are restricted, and get the client's name pattern for them.
  `--restricted` takes a regex and replaces the default pattern.

## 2. Mechanical pass

```bash
S=<this skill's directory>/scripts
uv run --with sqlglot python $S/audit_sql.py <paths> --claims claims.json \
  [--restricted '<client pattern>'] -o candidates.json
# dbt with a rules file (optional; needs model-viewer):
python3 ~/projects/model-viewer/make_dbt_lineage.py <dbt project> \
  --rules rules.json -o lineage.html --all
```

- Read `candidates.json`: candidates, `not_checkable` items, and `unparsed` statements.
  Items with status `info` are not defects (e.g. wrappers in a source-aligned layer). They
  matter only in a sandbox-to-production review, where a wrapper over a production object
  duplicates it (`references/layers-and-dbt.md`, sandbox section).
- From the lineage page's data, read the layer flags (LAYER-01 to 03).
- `uv` needs network on first use. Offline: `pip install sqlglot`, then run the scripts with
  `python3`.

## 3. Judgement pass

Work down `references/checklist.md` in severity order:
- For each `judge` check, open the reference named in its Source column, at that section only.
- Read the SQL that matters: facts, their joins, keys, set operations.
- Run the SAP section only if the sources are SAP, with `references/sap.md`.
- Each candidate from step 2 is a lead, not a finding. Read the code at its line and keep it
  or drop it.
- One finding per defect: when several checks catch the same defect, merge them into one
  finding and list every check id.
- A real defect that no check covers is still reported, as `OTHER`, naming the reference
  rule it breaks.
- Missing tests are findings only when the test files were supplied: a dbt project with its
  YAML. For bare SQL exports, list them under Not checked.

## 4. Verify

- Write the findings as JSON (format in `scripts/verify_findings.py`), each with
  `evidence` tokens from the cited lines.
- Run `python3 $S/verify_findings.py findings.json --root <repo root>`.
- Drop every finding that fails. A `not_checkable` candidate is never CONFIRMED. A defect
  the code proves is CONFIRMED even if its size needs data; a consequence that exists only if
  the data looks a certain way is PLAUSIBLE (`references/report-template.md`).

## 5. Report

Use `references/report-template.md`. Write the report into the client's workspace or repo,
never into the vault or this plugin. Name no client in anything that leaves that
workspace.
