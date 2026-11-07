# Dimensional modelling audit standard

Checklist for judging a star schema against the house standard; distilled from the vault notes `wiki/internal/knowledge-base/knowledge-base/dimensional-modelling/` (`dimensional-modelling.md`, `fact-tables.md`, `dimension-tables.md`, `conformed-dimensions.md`, `slowly-changing-dimensions.md`) and the `dbt-common` dimension macros. Read the notes for depth.

**[house]** = stated in a vault note or implemented in dbt-common. **[common practice]** = standard Kimball, not stated in the notes. Do not cite common practice as a house standard.

## Grain

- Declare the grain as one written sentence ("one row per order line at posting") before dimensions or facts. **[house]** (look for: no grain statement in the model description or YAML)
- Enforce the grain with a primary-key / unique test on the grain columns. **[house]** (look for: fact model with no `unique` / `unique_combination_of_columns` test; `select distinct` used to hide duplicates)
- One grain per table, no exceptions. **[house]** (look for: `union all` of header rows and line rows; a `row_type`/`level` column; nullable line columns that are only filled on some rows; amounts that double when summed)
- Start at the atomic grain the process captures; a natively coarse process (monthly balance, forecast) is atomic for itself. **[house]** (look for: fact built from a `group by` over a finer source when the finer rows are not modelled anywhere)
- Model from the physical measurement event, not from a report. **[house]** (look for: fact shaped to one dashboard, report-specific columns, pre-filtered rows)
- Every fact and every dimension FK must be true at the declared grain. **[house]** (look for: header-level amounts repeated on every line; FK to a dimension that has many values per fact row)

## Keys

- Dimensions have one primary key, platform-owned, not the source natural key. **[house]** (look for: dim PK = source code column; fact joins to dim on a natural key column where the dim has a surrogate key)
- Keep the natural key on the dimension as an attribute; facts resolve it to the surrogate key in the build. **[house]** (`dimension_join_as_at` joins on the dim's natural key columns) (look for: natural key dropped from the dim, so facts cannot be keyed)
- Type 1 dimensions may use a hash of the natural key (`dbt_utils.generate_surrogate_key`). **[house]** (look for: non-deterministic keys such as `row_number()` over unordered data on a type 1 rebuild)
- Type 2 surrogate keys: sequence/identity, or a hash of natural key plus a dense, self-assigned version number. Never hash the effective date/timestamp, load time or `updated_at` into the key. **[house]** (`scd2_versions` hashes keys + `version_number`) (look for: `generate_surrogate_key([..., 'valid_from'])`, `md5(nk || updated_at)`, `current_timestamp()` in key expressions; `dbt_scd_id` used as fact FK without a documented decision)
- Do not use Snowflake `HASH()` for keys. **[house]** (look for: `hash(` in a key expression)
- Composite natural keys: include every column that makes the member unique (e.g. company + code). **[house]** (macros take a list/dict of key columns) (look for: join on one column of a multi-column natural key; fan-out after the dim join)
- Carry a durable key across all type 2 versions of a member, separate from the source natural key where the source can reissue identifiers. **[house]** (look for: no durable key column on a type 2 dim; snapshot `unique_key` assumed to be the durable key)
- Every dimension has an unknown member `-1` and a not-applicable member `-2`, present before any fact loads. **[house]** (`dimension_special_members`) (look for: dim with no `-1`/`-2` rows; ad-hoc sentinels like `0`, `'N/A'`, `'~'`)
- Fact FKs are never null: `-2` when the fact has no natural key value (null/blank), `-1` when it has one but nothing matched. **[house]** (`dimension_key`) (look for: `left join` to a dim with the raw `dim.key` selected, no `coalesce`; `inner join` to a dim in the fact build, which silently drops rows; FK columns without `not_null`)
- Test that every fact key resolves to a dim row, including the unknown member. **[house]** (look for: no `relationships` test from fact FK to dim PK)
- Date dimension key is a `DATE` (the stated exception to anonymous keys) unless something downstream needs the integer; it still needs an unknown row. **[house]** (see Tensions) (look for: facts joining on `YYYYMMDD` integers built with `to_char`; no unknown date row)
- Filter and group on dimension attributes, never on the key's encoded meaning. **[house]** (look for: `where date_key between 20240101 and ...`; `substr(key, ...)`)
- Fact surrogate key is optional; add one where loads must be resumable. **[house]** (not a defect if absent)

## Facts

- Choose one of three fact types per table and state it. **[house]**
  - Transaction: one row per event, sparse. Start here. (look for: zero-filled rows for non-events in a transaction fact)
  - Periodic snapshot: one row per entity per period whether or not anything happened; dense FKs. (look for: gaps for entities with no activity; snapshot built from a transaction `group by` that drops quiet entities)
  - Accumulating snapshot: one row per pipeline instance, updated in place via incremental `merge` with `unique_key`; one date FK per milestone plus lag measures. (look for: `append` strategy on an accumulating snapshot; no lookback so old rows never update; lags computed as many date diffs instead of lag-from-start columns)
- Factless facts (FKs, no measures) are valid for events and coverage. **[house]** (not a defect)
- Classify every measure as additive, semi-additive or non-additive. **[house]**
  - Semi-additive (balances, on-hand) must not be summed across time; state the rule in the semantic layer. (look for: `sum(balance)` across periods)
  - Non-additive (ratios, %, unit price): store numerator and denominator, divide after aggregation. (look for: stored `margin_pct`, `avg_price`; `avg()` over a stored ratio or average)
- Do not store YTD or other to-date facts; compute at query time. **[house]** (look for: `ytd_`, `mtd_`, `_to_date` columns; windowed running sums in the fact)
- Degenerate dimensions (order/invoice number) stay on the fact with no dim table. **[house]** (look for: a dim table holding only an order number; order number missing from a line fact)
- Header/line: put header FKs and degenerate keys on the line fact; allocate header amounts down by a written business rule. **[house]** (look for: users must join header fact to line fact; freight repeated unallocated on each line)
- Never join two fact tables on their FKs; drill across on conformed attributes. **[house]** (look for: `fct_a join fct_b on a.customer_key = b.customer_key`)
- No centipede facts: FK to the lowest hierarchy level only. **[house]** (look for: `date_key`, `month_key`, `quarter_key`, `year_key` together on one fact)
- No measure-type dimension unless facts number in the hundreds and few apply per row. **[house]** (look for: `measure_type_key` + single `value` column)
- Multi-currency: transaction-currency and standard-currency columns per amount, converted once in the build. **[house]** (look for: conversion in the BI layer; one amount column with mixed currencies)
- Late-arriving facts take the dimension version in effect at measurement time. **[house]** (look for: type 2 join with `is_current = true` in a fact build; join with no as-at condition)
- Free text goes to a comments dimension, not the fact. **[house]** (look for: long `varchar` notes columns on a fact)
- Facts hold only measures, FKs, degenerate keys and precision timestamps; descriptive attributes live in dims. **[common practice]** (look for: `customer_name`, `product_category` on a fact)
- Consistent measure units: store once at a standard unit with conversion factors on the row. **[house]** (look for: same measure column in mixed units)

## Dimensions

- Wide, flat, denormalised; verbose labels over codes; split smart codes into parts. **[house]** (look for: only codes like `HD`; `Y`/`N` flags with no text sibling)
- No nulls in attributes: use `Unknown` / `Not applicable`. **[house]** (look for: string attributes without `coalesce`; `group by` producing a null bucket)
- No snowflaking: flatten hierarchies into the dimension. **[house]** (look for: `dim_product` with `category_key` FK to `dim_category`)
- No abstract generic dimensions (party, location-for-everything). **[house]** (look for: `party_type`/`entity_type` discriminator column)
- Conformed dimensions: same business definition, then same column names, then same domain values. One shared model with an enforced contract, plus `accepted_values` against a shared seed and `relationships` from every fact. **[house]** (look for: per-mart copies of `dim_customer`; same column name with different value sets (`North` vs `N`); missing contract or domain tests)
- Conformed facts: same name only if same definition. **[house]** (look for: `net_revenue` computed differently in two facts)
- Shrunken rollup dims are built from the base dim, not from source, and keep identical names and values. **[house]** (look for: `dim_month_brand` selecting from staging)
- Role-playing: one physical dim, one view per role with every column prefixed by the role. **[house]** (`role_playing_dimension`) (look for: several unaliased joins to `dim_date` exposing ambiguous `date`/`month` columns; copied date tables)
- Junk dimension for scattered low-cardinality flags, holding only combinations that occur. **[house]** (look for: many flag columns on a fact; junk dim built by `cross join` of all values)
- Separate time-of-day dimension; do not explode the date dim. **[house]** (look for: date dim at minute grain)
- Calendar logic (fiscal periods, holidays, working days) lives in the date dim once. **[house]** (look for: fiscal-year `case` expressions or holiday lists in fact or report SQL)
- Hierarchies: fixed depth as positional attributes; slightly ragged force-fitted to max depth by a business rule; truly ragged via a bridge (materialised from a recursive CTE) or pathstring. Multiple hierarchies in one dim are normal. **[house]** (look for: recursive CTE run at query time in reports; ragged levels left null)
- Multivalued dims via group key and bridge; a bridge over type 2 dims needs its own effective/expiry dates; document whether an allocation factor exists. **[house]** (look for: bridge with no validity columns joined to type 2 dims; sums across a bridge with no weighting factor and no note on double counting)
- Outriggers only sparingly; a type 2 outrigger moves to the fact. **[house]** (look for: dim FK to a type 2 dim)
- Late-arriving dims: placeholder row, key assigned once, type 1 overwrite when context lands. **[house]** (look for: placeholder keys that change when the real row arrives)
- Mini-dimension rows: band continuous values first. **[house]** (look for: mini-dim keyed on raw scores or amounts)

### SCD types

- Choose the type per attribute, not per table, and document it. **[house]** (look for: whole-row snapshot with no per-column decision recorded)
- 0 retain original (name it `original_*`); 1 overwrite for corrections; 2 new row for "as it was"; 3 prior-value column for one planned realignment; 4 mini-dimension for fast-churning clusters; 5 = 4 + type 1 outrigger; 6 type 1 `current_*` copies on a type 2 dim; 7 durable key + surrogate key on the fact with two views. **[house]**
- Default to type 6 for as-was plus as-is; move to type 7 when the type 6 overwrite gets expensive (versions x dual attributes). **[house]** (look for: type 7 current-view join on durable key without `is_current` constraint, which fans out)
- Type 2 rows carry `valid_from`, `valid_to`, a current flag and the durable key. **[house]** (look for: any of the four missing)
- Type 6 `current_*` columns overwrite all versions sharing the durable key, not only the current row. **[house]** (look for: `update ... where is_current`)
- `dbt snapshot`: snapshot only type 2 columns, from source not from a transformed model; prefer `timestamp` strategy; never `check_cols: all`; no volatile columns (`_fivetran_synced`, write-bumped `updated_at`) in the check set; set `hard_deletes` deliberately. **[house]** (look for: `check_cols: all`; snapshot `ref()`ing a mart; sync-metadata columns in `check_cols`; no `hard_deletes`)
- One change-detection mechanism per source: no snapshot over CDC rows, no stream plus snapshot. **[house]** (look for: snapshot on a Fivetran history/CDC table)
- Required singular tests: one current row per durable key; no overlapping ranges; `valid_from < valid_to`; no future `valid_from`; every fact key resolves. **[house]** (look for: their absence)
- Change-detection hashes use `row_hash` with a stable column order. **[house]** (look for: hand-rolled `md5(a||b)` without null handling)

## Bus matrix and process orientation

- One business process per design target; each value-chain step gets at least one atomic fact. **[house]** (look for: one fact mixing orders, shipments and returns because they share "cost")
- Maintain a bus matrix (processes x dimensions) and a detailed version with grain and fact list per fact table. **[house]** (look for: no matrix; a dimension used by several processes but defined more than once)
- Build one process (row) at a time, accumulating shared dims. **[house]**
- Anything going into a semantic layer gets a star, even with one fact. Exceptions: ML feature tables, throwaway prototypes. **[house]** (look for: one wide denormalised table feeding Power BI Import)
- Aggregates: materialised view for single-table rollups, dynamic table for joined rollups (queried by name); clustering is not an aggregate. **[house]** (look for: hand-rolled incremental aggregate tables; MV with a join)

## Naming

The notes state no formal convention. Observed in notes and macros: **[house]**
- `dim_` / `fct_` model prefixes (`dim_customer`, `fct_sales`); `valid_from`, `valid_to`, `is_current`, `version_number`.
- Role-playing columns prefixed with the role (`posting_date_key`); type 0 `original_*`; type 6 `current_*`.
- Key suffix: macros and README use `*_key`; one note example uses `_sk` / `_nk`. Flag inconsistency within a project, not either choice.
- Conformed columns: identical names across dims and shrunken dims. **[house]**

## Tensions

- **Type 2 key hashing.** `dimensional-modelling.md` rejects hashing a natural key into a type 2 key and maps type 2 to sequence/identity; `dimension-tables.md` allows hash of natural key + dense version; `scd2_versions` implements exactly that. Accept NK+version hashes; still flag them where the natural key is a sensitive identifier (`dimension-tables.md`: hashes of small identifier spaces are enumerable, undermining masking).
- **Key type.** Notes describe surrogate keys as anonymous integers; `dimension_key` returns text (md5 or `'-1'`/`'-2'`) and `dimension_special_members` defaults to string keys. Check fact and dim key types match.
- **Open-ended `valid_to`.** `slowly-changing-dimensions.md` prefers `NULL` over `9999-12-31` (pruning); `scd2_versions` defaults `open_end` to `9999-12-31` and `dimension_join_as_at` uses an inclusive `BETWEEN`, which breaks with `NULL`.
- **As-at join.** The SCD note recommends `ASOF JOIN` on `valid_from`; the macro uses inclusive `BETWEEN valid_from AND valid_to`, so adjacent versions must not share a boundary date or facts double up.
- **Date key.** `dimension-tables.md` says use a `DATE` key; README documents `dim_date` with unknown member `date_key -1`, which a `DATE` column cannot hold.
- **Special-member attributes.** "No nulls in attributes" vs `dimension_special_members` defaulting non-string, non-boolean columns to `NULL`.
