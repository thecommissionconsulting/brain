# Layers and dbt: audit standard

Checklist for judging a dbt model's layering, structure, SQL, tests, docs and promotion readiness. Distilled from these vault notes (paths relative to the vault root); read them for depth:
`wiki/internal/knowledge-base/knowledge-base/standards-and-templates/snowflake-and-dbt-standards/{snowflake-and-dbt-standards,dbt-standards-and-best-practices,sql-standards-dbt-and-snowflake,snowflake-standards}.md`, `wiki/internal/knowledge-base/knowledge-base/modern-data-software/dbt-testing.md`. Layer checks use `model-viewer` (`make_dbt_lineage.py`, `examples/medallion-rules.json`).

The dbt and SQL notes were written for a Snowflake estate. Rules about transient tables, warehouses or Snowflake features don't apply on Databricks or other platforms; skip them there and say so.

**[house]** = stated in a vault note. **[common practice]** = not in the notes; do not cite it as a house standard. Cosmetic style (keyword case, indentation, line length, comma position) is out of scope; sqlfluff covers it.

## Layered architecture

The house generic layers are Raw → Refined → Consumption (Modelled, then Reporting). Clients may name them differently (bronze/silver/gold, staging/intermediate/marts). Judge against the client's own layer model, mapped onto these principles.

- Make data flow one way, from source to business-ready. No layer reads a later layer. **[house]** (look for: a refined/staging model that `ref`s a modelled or reporting model; a lineage flag "X reads Y")
- Keep a layer's reads to the layers it may read; skipping layers (consumption reading raw directly) needs a stated reason. **[common practice]** (look for: a mart or fact that reads a source or raw model directly)
- Keep the first layer source-aligned: one model per source table, no transformation in Raw, only light casting, renaming and cleaning in Refined. **[house]** (look for: joins, aggregations or business rules in raw/refined; a staging model with more than one input)
- Make the modelled layer business-aligned and source-agnostic: facts and dimensions in a star schema with connectable keys. **[house]** (look for: modelled tables shaped like one source system's tables; no fact/dim split)
- Put business logic in the business-aligned layers, once, not in the source-aligned layer and not repeated in reporting. **[common practice]** (look for: the same CASE/derivation in several models; KPIs computed inside a report view)
- Consumers (BI tools, reports, extracts) read only the reporting/presentation layer, where row-level security sits on the views. **[house]** for RLS on reporting views; **[common practice]** for "consumers read nothing else" (look for: dashboards or exposures pointing at refined/modelled objects; RLS applied anywhere but the presentation views)
- Set materialisation per layer in `dbt_project.yml`, by folder: schema, materialisation, transient flag and warehouse are all compulsory there. **[house]** (look for: no folder-level `+materialized`/`+schema`/`+transient` config; per-model overrides with no reason)
- Build Raw as transient tables; persist Refined and keep its history (snapshots). **[house]** (look for: refined history only in a transient table; snapshot without `transient=false`)
- Build heavy, widely read business-aligned models as tables or incremental, not views. **[common practice]** (look for: a large fact materialised as a view and read by many models)

### Layer rules file

`make_dbt_lineage.py` checks a project against a JSON rules file; it knows nothing of any client's layers. Write one per client layer model, then run:
`python3 make_dbt_lineage.py <dbt-project> --rules layers.json -o lineage.html --all` (needs a fresh `target/manifest.json`, so `dbt parse` first). It prints "N models break a <name> rule" and flags each model on the page.

Keys: `name`; `lanes` (in flow order); `folders` ({model folder: lane}, first matching path segment wins); `source_lane`; `may_read` ({lane: [lanes]}, anything else is flagged); `one_to_one` (lanes whose models must have exactly one input); `must_be_table` (lanes that must be table, incremental or snapshot); optional `lane_sub`, `why`, `keep_from`.

Gotchas when writing it:
- A lane may read itself only if listed in its own `may_read`. A lane missing from `may_read` is never flagged, so list every model lane.
- Seeds and other projects' models get their lane from a `<lane>__` name prefix (case-insensitive); with no prefix, seeds fall into `source_lane` and others into the middle lane. Check those placements by hand.
- A model in no mapped folder also falls into the middle lane: map every model folder.
- `keep_from` hides models nothing in those lanes reads. Audit with `--all` so orphans show.

```json
{
  "name": "raw-refined-consumption",
  "lanes": ["Source", "Raw", "Refined", "Modelled", "Reporting"],
  "folders": {"raw": "Raw", "refined": "Refined", "modelled": "Modelled", "reporting": "Reporting"},
  "source_lane": "Source",
  "may_read": {"Raw": ["Source"], "Refined": ["Raw", "Refined"],
               "Modelled": ["Refined", "Modelled"], "Reporting": ["Modelled", "Reporting"]},
  "one_to_one": ["Raw"],
  "must_be_table": ["Refined", "Modelled"]
}
```

## dbt project structure and naming

- Use the standard project layout (`models`, `seeds`, `snapshots`, `macros`, `tests`, `analyses`) with model folders that follow the layer flow; split by business area as the project grows. **[house]** (look for: model folders that map to no layer; one flat folder of mixed layers)
- Name models by layer: `raw_<ds>_<name>`, `refined_<ds>_<name>`, `dim_`/`fact_` in Modelled, `rpt_` tables and `vw_rpt_` views in Reporting. **[house]** (look for: layer and filename prefix disagreeing; facts or dims without the prefix)
- Name objects singular, snake_case, unquoted, with suffixes for type (`customer_id`, `order_date`) and no unclear abbreviations. **[house]** (look for: quoted or mixed-case identifiers; `id_customer`; cryptic abbreviations)
- Keep a properties YAML per model folder, named `<ds>_<folder_name>_properties.yml`. **[house]** (look for: models with no YAML entry at all)
- Tag models (source, refresh frequency, business area) with dbt tags, kept separate from Snowflake object tags. **[house]** (look for: no tags; dbt tags reused to drive masking)
- Put reusable logic in macros (DRY), with simple Jinja in models. **[house]** (look for: the same expression copied across models; models that are mostly Jinja)
- Give every incremental model an `is_incremental()` filter and a `unique_key`, and set `on_schema_change` deliberately. **[house]** (look for: incremental with no `unique_key`, which appends duplicates; `on_schema_change` left at `ignore` on a changing source)
- Snapshots: set `unique_key`, choose `timestamp` only where `updated_at` is reliable, else `check`; if `invalidate_hard_deletes=true`, guard against a partial load invalidating everything. **[house]** (look for: timestamp strategy on an unreliable column; hard-delete invalidation with no guard)
- Use `9999-12-31` as the open-ended end date, never NULL, in SCD and validity ranges. **[house]** (look for: NULL `valid_to` under a `BETWEEN` join)

## SQL that affects correctness

- Reference every relation through `ref()`/`source()`; never hard-code database.schema.table. **[house]** (Jinja for table references) (look for: literal three-part names in model SQL)
- Put every `ref`/`source` in import CTEs at the top, named after the table they read. **[house]** (look for: `ref` calls buried mid-query or inside joins)
- In import CTEs select only the columns used and filter early. **[house]** (look for: wide imports never narrowed). Note the house example itself imports with `select *`; flag `select *` only where it passes unknown columns to a contract or consumer.
- End the model with `select * from <final CTE>`, and list the final CTE's columns explicitly. **[house]** for the final `select *`; **[common practice]** for the explicit list (look for: a final CTE that is itself `select *` from an upstream model, so the output shape is whatever upstream returns)
- One logical unit of work per CTE, named for what it does. **[house]** (look for: one CTE doing joins, filters and aggregation at once, hiding a fan-out)
- Prefix every column with its table alias when more than one table is joined; use meaningful aliases with explicit `AS`. **[house]** (look for: unqualified columns in a join, which silently bind to the wrong table when a column is added upstream)
- Write the join type explicitly (`inner join`, `left join`), not bare `join`. **[house]** (look for: bare `join`)
- Join left to right; replace `right join` by swapping the FROM table. **[house]** (look for: any `right join`)
- Aggregate before joining, on the smallest set. **[house]** (look for: join then `group by` that double-counts measures through a one-to-many join)
- Check each join's cardinality: a join to a non-unique key fans out rows. **[common practice]** (look for: a join key with no `unique` test on the joined side; `distinct` added to hide duplicates)
- Avoid positional `group by 1, 2` / `order by 1` in models whose column list changes. **[common practice]**; the house sqlfluff config allows implicit grouping (see conflicts). (look for: positional grouping beside an edited select list)

## Testing

Rule: test the grain, the joins and the money as you build; a model is not done until its tests would fail if its logic broke. **[house]**

- Test every model's grain: `unique` + `not_null` on the key, or `dbt_utils.unique_combination_of_columns` on the declared grain. **[house]** (look for: no unique/not_null test on a model's primary key)
- Test every fact key with `relationships` to its dimension. **[house]** (look for: fact foreign keys with no `relationships` test)
- Test that no fact row sits on the unknown member (`-1`); `-2` not-applicable is fine. **[house]** (look for: unknown-member handling with no `no_unknown_members` test)
- Use `accepted_values`, `accepted_range` and `not_null` where they matter in Refined and Modelled. **[house]** (look for: status/type codes with no accepted values test)
- Test SCD2 dimensions: no overlapping versions, exactly one current row, `valid_from < valid_to`, no future `valid_from`. **[house]** (look for: type 2 dims with only generic tests)
- Reconcile every fact to a control source the model does not depend on, by company, period, account; reconcile balances as well as movements, and across cutovers. **[house]** (look for: no reconciliation test on any fact; reconciling to an upstream model of itself)
- For finance facts: documents net to zero, trial balance nets to zero per period, closing equals next opening. **[house]** (look for: ledger facts with no balance or continuity test)
- Unit-test every non-trivial rule (sign convention, exclusion filter, hierarchy walk, date edge) with hand-made rows; important rules get unit and data tests. **[house]** (look for: complex CASE/filter logic with no `unit_tests:` entry)
- Mock every direct parent in unit tests; scope tests on var-disabled models with `config: {enabled: ...}`. **[house]** (look for: unit tests erroring on disabled parents)
- Write generic tests for rules used on more than one model; singular tests only for one model's shape. **[house]** (look for: the same singular SQL copied across models)
- Prove tests can fail: break the logic once and record which test caught it in the README, or keep `expect_fail` fixtures run in CI. **[house]** (look for: no record of a deliberate break; no `expect_fail` tag)
- Incremental models: full refresh equals incremental, reruns are idempotent, late changes inside the lookback land. **[house]** (look for: incremental models with none of these tests)
- Enforce contracts (column names and data types) on the modelled layer, with adapter-specific type names. **[house]** per dbt-testing; optional per dbt-standards (see conflicts) (look for: modelled models with no `contract: {enforced: true}`)
- Add source freshness tests on sources with a load timestamp. **[house]** (look for: sources with no `freshness`/`loaded_at_field`)
- In CI: build every variant (all vars), then the `expect_fail` run, then sqlfluff; fail on any status other than pass/success in `run_results.json`. **[house]** (look for: CI relying on exit code alone; var-disabled models never built, so their tests never run)
- Trust no green build that relied on stale partial parse or a local-only file. **[house]** (look for: tests that read a seed or database only present locally)

## Documentation

- Document in YAML, for every model: name, description, every column's description and data type, constraints, and tags. **[house]** (look for: models or columns missing from YAML, or with empty descriptions)
- State each model's grain in its description. **[common practice]** (look for: a fact description that does not say what one row is)
- Keep docs and code consistent: every YAML column exists in the SQL output and vice versa; documented types match the built types. **[common practice]**; enforced contracts make it checkable **[house]** (look for: YAML columns the model no longer returns; returned columns absent from YAML; descriptions that contradict the logic)
- Record in the project README which deliberate break each test catches. **[house]** (look for: no such record)
- Document known gaps (e.g. changes outside an incremental lookback) rather than leave them implicit. **[house]** (look for: lookback window with no stated gap)

## Sandbox-to-production readiness

The vault has no promotion checklist; these are mostly common practice.

- Build business logic in the model, not as a thin wrapper that re-exposes a production object under a new name. **[common practice]** (look for: models that are `select * from` a production table or view with no transformation; would duplicate an existing governed object)
- Read only data the production service account is entitled to read. **[common practice]** (look for: sources in personal schemas, restricted or masked tables read via an analyst's role, cross-environment reads)
- Give every reference dataset an ingestion path: a governed source or a reviewed seed, not a hand-loaded table or local file. **[common practice]**; **[house]** for the local-file trap (look for: sources nothing loads; tables uploaded by hand; seeds edited outside version control)
- Move hard-coded lists (cost centres, accounts, IDs in `IN (...)`) into a seed, mapping table or var with an owner. **[common practice]** (look for: long literal lists in WHERE/CASE)
- Keep environment names out of SQL: database, schema and warehouse come from targets and `dbt_project.yml`. **[common practice]**; the house setup separates DEV/UAT/PROD by project and sets warehouses per folder **[house]**. (look for: `DEV`, `SANDBOX`, `PROD` or personal schema names in model SQL or macros; `target.name` branches that change business logic)
- Put one-off objects (file formats, masking/tag policies, clustering) in macros or Terraform, not ad hoc scripts. **[house]** (look for: manual DDL the model depends on)
- Meet every Testing and Documentation rule above before promotion. **[common practice]** (look for: sandbox model with no tests or YAML)
