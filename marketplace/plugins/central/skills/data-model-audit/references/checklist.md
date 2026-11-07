# Checklist

Every check the audit runs, in one place. The `How` column says who finds it:
- **script:** `audit_sql.py` emits it as a candidate.
- **lineage:** model-viewer's `make_dbt_lineage.py` against a layer rules file.
- **judge:** read the code and the rule in the named reference.

The `Source` column says where the rule comes from. Never present a `common` or `field` rule
as a house standard.

| Source | Means |
|---|---|
| `dim` | `references/dimensional.md` (vault, dimensional-modelling notes) |
| `dbt` | `references/layers-and-dbt.md` (vault, dbt and SQL standards, dbt-testing) |
| `sap` | `references/sap.md` (vault SAP notes, sap-finance) |
| `common` | common practice the house notes don't state |
| `field` | a defect pattern found in real client models; not a written standard |

Severity, highest first:
- **S1, wrong numbers:** totals are off.
- **S2, silent row loss or duplication.**
- **S3, governance:** access, ownership, promotion blockers.
- **S4, maintainability.**

Style is out of scope.

## Grain and facts

| Id | Catches | How | Sev | Source |
|---|---|---|---|---|
| GRAIN-01 | Grain not written down as a sentence, or not enforced by a unique test on the grain columns | judge | S4 | dim, dbt |
| GRAIN-02 | Mixed grain in one fact (header and line amounts together, daily rows beside monthly) | judge | S1 | dim |
| GRAIN-03 | A 1:n join fans the fact out: a join to a table not unique on the join columns, with SUM over the result | judge | S1 | dim |
| GRAIN-04 | Dimension grain differs from the fact's join column (hierarchy dim holding level-1 nodes, joined on element) | judge | S2 | field |
| FACT-01 | Measures not additive across a dimension summed across it (balances, rates, snapshots summed over time) | judge | S1 | dim |
| FACT-02 | Stored running totals (YTD) or derived ratios summed | judge | S1 | dim |
| FACT-03 | Fact built by joining another fact | script | S1 | dim |
| FACT-04 | Snapshot fact without a snapshot date key, or gaps or duplicates per snapshot date | judge | S2 | dim, dbt |

## Keys and dimensions

| Id | Catches | How | Sev | Source |
|---|---|---|---|---|
| KEY-02 | Composite natural key joined on part of it | script (claims) + judge | S2 | field |
| KEY-03 | A key column that is a NULL or constant literal | script | S2 | field |
| KEY-04 | A documented join key that one side does not output | script (claims) | S2 | field |
| KEY-05 | Type-2 key built from natural key + timestamp, or `dbt_scd_id` used as the fact's foreign key. Allowed: sequence or identity, or hash of natural key + a dense version number. Do not flag those. | judge | S2 | dim |
| KEY-06 | No unknown (-1) and not-applicable (-2) members on a dimension, or facts allowed to carry NULL foreign keys | judge | S2 | dim |
| KEY-07 | Fact rows landing on the unknown member because the lookup is wrong (inclusive `BETWEEN` with a NULL `valid_to`, boundary dates shared by two versions, unpadded SAP keys). Report the count if a test or query shows it. | judge | S2 | dim, dbt |
| SCD-01 | SCD integrity: more than one current row per natural key, overlapping validity, `valid_from >= valid_to` | judge | S2 | dim, dbt |
| SCD-02 | Fact takes the current version instead of the version at measurement time (no as-at join, no ASOF) | judge | S1 | dim |
| SCD-03 | SCD type declared per table where the notes want it per attribute; `check_cols='all'` on a snapshot | judge | S4 | dim |
| DIM-01 | The same dimension built twice with different values or columns (not conformed) | judge | S2 | dim |
| DIM-02 | Role-playing dates not explicit (one date dim joined twice without role names) | judge | S4 | dim |
| DIM-03 | Snowflaked dimensions, centipede facts, generic "attribute" dimensions | judge | S4 | dim |

Not checking a rule file's layers is no reason to skip LAYER-04, GOV-02 or the KEY checks: they
run from the SQL alone.

Do **not** flag:
- a natural-key + as-at join that then assigns the surrogate key: that is the house pattern (dbt-common `dimension_keys`)
- `9999-12-31` as the open end date: the standards allow it, and the packages use it

## Set operations and SQL

| Id | Catches | How | Sev | Source |
|---|---|---|---|---|
| SET-01 | Set operation over `SELECT *` whose branches have the same columns in a different order | script | S1 | field |
| SET-02 | Explicit set operation with columns misaligned by position | script | S1 | common |

`SET-01` with status `not_checkable` means the branch columns aren't visible in the text. Say
so; never report it as clean or as a defect without reading each source's column order.

## Layers and promotion

| Id | Catches | How | Sev | Source |
|---|---|---|---|---|
| LAYER-01 | A model reads a layer its layer may not read | lineage | S3 | dbt |
| LAYER-02 | A source-aligned layer not one-to-one where the rules require it | lineage | S4 | dbt |
| LAYER-03 | Wrong materialisation for the layer | lineage | S4 | dbt |
| LAYER-04 | A plain `SELECT *` wrapper over an upstream object, ABOVE the source-aligned layers. Raw and staging wrappers are by design. With no rules file, judge by the object's schema and name: a wrapper in a mart, reporting or modelled schema counts. | script | S4 | field |
| LAYER-05 | Consumers (BI) reading below the serving or presentation layer | judge | S3 | dbt |
| LAYER-06 | Long chains of views with no materialised step | script | S4 | common |
| GOV-01 | A sandbox or lower-trust model reading restricted or confidential sources. Only with a client-specific `--restricted` pattern; never with the default pattern alone. | script | S3 | field |
| GOV-02 | Hard-coded literal lists of 5 or more values (plants, accounts, codes), or the same list repeated across objects. A short filter on a few enumerated values is not a finding. | script | S4 | field |
| GOV-03 | Manually maintained reference tables with no owner, source or ingestion path | judge | S3 | dbt, field |
| GOV-04 | Environment or catalog names hard-coded in SQL where the platform promotes by config | judge | S3 | dbt |

## Tests and documentation

| Id | Catches | How | Sev | Source |
|---|---|---|---|---|
| TEST-01 | No reconciliation to a control total (source totals, trial balance), the test that matters most | judge | S1 | dbt |
| TEST-02 | No unique and not-null test on each model's grain | judge | S2 | dbt |
| TEST-03 | No relationships tests from facts to dimensions, and no test that facts avoid the unknown member | judge | S2 | dbt |
| TEST-04 | No SCD integrity tests on type-2 dimensions | judge | S2 | dbt |
| TEST-05 | Business rules without unit tests; no contract on the modelled layer | judge | S4 | dbt |
| DOC-01 | Documentation contradicts the code: grain, keys, object counts, row meaning | judge | S4 | field |
| DOC-02 | Generated or AI-drafted documentation treated as authoritative (precise-looking catalogues nobody checked) | judge | S4 | field |
| DOC-03 | A comment names a source the SQL does not read | script | S4 | field |

## SAP sources

Only when sources are SAP. Detail and what to look for: `references/sap.md`. Ranked by how
often each one moves totals.

| Id | Catches | Sev | sap.md |
|---|---|---|---|
| SAP-01 | FI and CO summed together (COEP primary postings duplicate FI; COIN), or real-time integration rows counted twice | S1 | §2–3 |
| SAP-02 | Parallel ledgers (`RLDNR`) not filtered to one ledger | S1 | §2 |
| SAP-03 | Compatibility views over `ACDOCA` (BSEG, FAGLFLEXA, COEP views) read alongside `ACDOCA` | S1 | §2 |
| SAP-04 | Sign taken from `SHKZG` alone, ignoring `XNEGP`; or assuming `ACDOCA` amounts are signed without testing | S1 | §2 |
| SAP-05 | Carry-forward rows (`BSTAT = 'C'`, period 000) in actuals, or openings taken from both ECC totals and migrated S/4 rows | S1 | §2 |
| SAP-06 | Brownfield `MIG_SOURCE` rows dropped as junk, or double-counted against ECC history | S1 | §2 |
| SAP-07 | Period derived from the posting date instead of the fiscal year variant; special periods 13–16 lost | S1 | §2 |
| SAP-08 | Line keys mixed (`BUZEI` vs `DOCLN`, `BELNR` vs `DOCNR`), or no source system in the key when ECC and S/4 coexist | S2 | §2, §5 |
| SAP-09 | Leading zeros (ALPHA) or compounded keys breaking joins; blanks treated as NULL | S2 | §5 |
| SAP-10 | `MANDT` ignored where more than one client lands | S2 | §5 |
| SAP-11 | Currency field or decimal shift wrong (`TCURX`), or document and local currency mixed | S1 | §2 |
| SAP-12 | Hierarchies: sets and HRRP mixed for one hierarchy, set validity assumed, time-dependent master data joined without dates | S2 | §4 |
| SAP-13 | BW: `OBJVERS` not filtered to `A`; record mode handled as sum where it is upsert, or the reverse | S1 | §6 |
| SAP-14 | Sources that are transaction-report extracts (IW39, KSB1, ME2M …) treated as base tables: the report's grain, filters and keys inherited without being stated | S2 | §1 |

SAP-14 is field-found. Check it after the finance traps, not before.
