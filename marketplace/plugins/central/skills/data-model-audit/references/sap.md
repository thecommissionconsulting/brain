# SAP source audit checklist

Pitfalls to check when a model's sources are SAP ECC, S/4HANA or BW. Distilled from the vault notes `wiki/internal/knowledge-base/knowledge-base/sap/` (`sap.md`, `sap-landscape.md`, `sap-ecc-and-s4-finance-model.md`, `sap-bw-for-lakehouse-engineers.md`) and the `sap-finance` repo (`packages/sap_utils` macros, `dbt/` models, `src/sap_synthetic` generator, `tests/test_landscape.py`). Read those for depth.

**[house note]** = stated in a vault note. **[sap-finance]** = implemented or proven in the repo (synthetic data; the repo flags its own simplifications). **[SAP general]** = standard SAP knowledge not in house sources. "(verify)" = field or value not confirmed; check against the client system before citing it.

## 1. Source shape: base tables vs transaction-report extracts

A report extract (the output of a transaction, a list layout, or an `RFC_READ_TABLE`-style dump) is not the table behind it. Identify which one landed before judging grain or keys.

- Grain is the report layout's grain, not the table's: one row per order (IW39), per order × operation (IW49N), per CO line item (KSB1, CJI3). Subtotal and total rows may be in the file. **[SAP general]** (look for: no grain test on a model reading a report extract; rows where key columns are blank but amounts are filled; amounts that double when summed)
- Internal keys are usually not displayed (`AUFPL`/`APLZL`, `PSPNR`, `OBJNR`, `BUZEI`, `DOCLN`), so the model cannot dedupe or join on the true key. **[SAP general]** (look for: `select distinct` over a report extract; joins on description columns; no uniqueness test on the columns used as key)
- The selection variant bakes in filters: date range, company code / plant / controlling area, order status (IW39's Outstanding / In process / Completed / Historical boxes), deletion flags, layout. Rows outside the variant are silently absent. **[SAP general]** (look for: no documentation of the variant used; a fact claiming full history from a report extract; counts that drop at a status change)
- The extracting user's authorisations filter rows without warning. **[SAP general]** (look for: extract run under a personal or restricted user; totals below the GL control total)
- Snapshots, not deltas: changed or deleted source rows are not re-delivered, and overlapping reruns duplicate rows. **[SAP general]** (look for: append-only loads of report files with no dedupe key; no reload window)
- Values arrive in external format: leading zeros stripped (`sap_alpha_out` form), user date format, user decimal notation, numbers as text with a trailing minus (`123.45-`), currency amounts already decimal-shifted. **[sap-finance]** (`sap_number`, `sap_alpha_in`) (look for: `cast(amount as decimal)` on text that can end in `-`; joins between a report key and a table key with no ALPHA padding; `sap_currency_amount` applied to an already-shifted report amount)
- Report-computed columns (status strings, "still to be delivered" quantities, report-currency values) have no table equivalent; reproducing them needs the report's logic. **[SAP general]** (look for: a model treating a report-derived column as a stored fact)

Report code → base tables, all **[SAP general]** (ECC names; S/4 in brackets). Only the core tables are listed.

| Code | Shows | Base tables |
|---|---|---|
| IW39 | PM/maintenance orders (list) | `AUFK`, `AFKO`, `AFIH`; status `JEST` |
| IW49N | Orders and their operations | `AUFK`, `AFKO`, `AFVC`, `AFVV` |
| KSB1 | Cost-centre actual line items | `COEP`, `COBK` (S/4: `ACDOCA`, `COEP` is a compatibility view) |
| CJI3 | Project actual line items | `COEP`, `COBK` (S/4: `ACDOCA`) |
| ME2M / ME2N | Purchase orders by material / by PO number | `EKKO`, `EKPO`; schedule lines `EKET`, history `EKBE` (verify which the report reads) |
| CN43N | WBS elements overview | `PRPS`, `PROJ` |
| IH06 | Functional locations (list) | `IFLOT`, `IFLOTX`, `ILOA` |
| IH08 | Equipment (list) | `EQUI`, `EQKT`, `EQUZ`, `ILOA` |
| FBL3N | GL account line items | `BSIS`/`BSAS` (S/4: `ACDOCA`) (verify for ECC new GL) |

## 2. Finance

- `BSEG.DMBTR` (and `WRBTR`) are unsigned; `SHKZG` gives the side: `S` debit (+), `H` credit (−). **[house note]** (look for: `SUM(dmbtr)` / `SUM(wrbtr)` with no `SHKZG` sign handling on BSEG-sourced lines)
- Negative postings (`XNEGP = 'X'`) keep the original side, so the sign from `SHKZG` alone is wrong; flip it. **[sap-finance]** (`sap_signed_amount(amount, shkzg, xnegp)`) (look for: `case when shkzg = 'S' then dmbtr else -dmbtr end` with no `xnegp` term)
- `ACDOCA`/`FAGLFLEXA` amounts (`HSL`, `TSL`, `KSL`) are treated as already signed, debit positive. No SAP source states it; test against a known document. Do not re-apply `DRCRK` to them. **[house note]** (look for: `DRCRK`/`SHKZG` sign logic applied on top of `HSL`; no reconciliation test against a trial balance)
- Take the sign from the amount, not the indicator: with negative postings the two can disagree. **[house note]** (look for: `case when drcrk = 'H' then -abs(hsl)`)
- `BSTAT` on `BKPF`/`ACDOCA`: blank is a normal posting; `C` is balance carry-forward. Other values mark non-postings that still have `BKPF` (and often `BSEG`) rows: `V` parked, `S` noted item, `D` recurring entry, `M` sample document; `L` (non-leading-ledger postings), `W`, `Z` (verify). **[house note]** for `C`, **[SAP general]** for the rest (look for: BSEG/BKPF actuals with no `BSTAT` filter; a filter `bstat = ''` that also drops wanted rows without saying so)
- `BSTAT = 'C'` rows (`POPER`/period `000`) are balances, not movements: exclude from actuals, use for openings. They come from migration and from normal year-end alike. **[sap-finance]** (`refined_s4_gl_actuals`, `refined_s4_gl_opening_balances`) (look for: actuals fact over `ACDOCA` with no `bstat <> 'C'`; balances that double in period 0)
- Reversals: `STBLG`/`STJAH` link the pair, `XREVERSAL` `1` = reversed, `2` = reversal. Keep both or drop both; dropping one side breaks the balance. **[sap-finance]** (generator `BKPF`) (look for: `where stblg = ''` or `xreversal = ''` on one side only)
- Classic GL vs new GL decides the build: classic is `BSEG` (lines) + `GLT0` (totals) + EC-PCA `GLPCA` for profit centre; new GL is `FAGLFLEXA`/`FAGLFLEXT` with segment and document splitting. Detect by `FAGL_ACTIVEC.ACTIVE = 'X'` or a populated `FAGLFLEXA`. **[house note]** (look for: a profit-centre P&L built from classic `BSEG` without `GLPCA`; no documented check of which GL is active)
- New GL line grain is `RLDNR` + `DOCLN`, not `BUZEI`: splitting, tax and ledger multiplication give several `DOCLN` per `BUZEI`, and `BSEG` has fewer lines than `FAGLFLEXA`. **[house note]** (look for: fact key on `BELNR`+`BUZEI` from FAGLFLEXA/ACDOCA; line-count reconciliation BSEG vs FAGLFLEXA expected to match)
- In `FAGLFLEXA` the document number is `DOCNR`; on non-leading ledgers it differs from `BELNR`. Non-leading-ledger-only postings have their entry view in `BSEG_ADD`, not `BSEG`. **[house note]** / **[sap-finance]** (look for: joins `FAGLFLEXA.DOCNR = BKPF.BELNR` without `RLDNR = '0L'`)
- Totals tables (`GLT0`, `FAGLFLEXT`) are wide: carry-forward `HSLVT` plus `HSL01`..`HSL16`, one row per key and `DRCRK` side. **[sap-finance]** (look for: a balance from one period column; one `DRCRK` side only; `HSLVT` omitted from cumulative balance)
- `GLT0` record type `RRCTY` (`0` actual, `1` plan) and version `RVERS` (verify) must be filtered. **[SAP general]** (look for: GLT0 sums with no `rrcty` filter)
- ECC FI + CO double-counts: `COEP` value type `WRTTP = '04'` carries copies of FI primary postings (business transaction `VRGNG = 'COIN'`). Take CO secondary lines only. **[sap-finance]** (`ecc_co_secondary`) (look for: `FAGLFLEXA` or `BSEG` `union all` `COEP` with no `vrgng <> 'COIN'`)
- New-GL real-time CO-FI integration documents (`AWTYP = 'COBK'` in FI) mirror CO flows already taken from `COEP`; skip one side. **[sap-finance]** (look for: FAGLFLEXA + COEP secondary with no `awtyp <> 'COBK'`)
- S/4: `FAGLFLEXA`, `GLT0`, `BSIS`/`BSAS`, `COEP` (`V_COEP`) are compatibility views over `ACDOCA`. Read `ACDOCA` only. **[house note]** (look for: `ACDOCA` unioned with any of those objects from the same S/4 system)
- `BSEG` still exists in S/4 but is not 1:1 with `ACDOCA` (no row for CO-only, material-ledger, asset lines). **[house note]** (look for: S/4 actuals built from `BSEG`; ACDOCA-to-BSEG line-count checks)
- Parallel ledgers repeat every posting: filter `RLDNR` to the reported ledger (usually `0L`) or model ledger as a dimension. **[house note]** (look for: `SUM(hsl)` over `ACDOCA`/`FAGLFLEXA` with no `rldnr` filter or group)
- `ACDOCA.MIG_SOURCE` is filled on every migrated row in a brownfield conversion (`F`/`G`/`C`/`M`/`A`; `R`/`S`/`U` corrections): it is the ECC history, not noise. Union ECC + S/4 with a hard cutover, `MIG_SOURCE = ''` from go-live. **[house note]** / **[sap-finance]** (look for: ECC history unioned with all `ACDOCA` rows; or `mig_source <> ''` dropped while ECC is not loaded)
- ECC and S/4 rows share `RBUKRS`/`GJAHR`/`BELNR`/`DOCLN`: put the source system in the fact key. **[house note]** (look for: fact unique key with no source-system column; `merge` on the SAP key across both systems)
- Use one system's carry-forward per year: ECC `HSLVT` before cutover, S/4 native `BSTAT 'C'` after; migrated S/4 carry-forward duplicates ECC's. **[sap-finance]** (look for: openings from both `FAGLFLEXT`/`GLT0` and migrated `ACDOCA` `BSTAT 'C'`)
- Currencies. `BSEG`: `WRBTR` document currency (`BKPF.WAERS`), `DMBTR` local (company code), `DMBE2`/`DMBE3` second and third local. `ACDOCA`: `WSL`/`RWCUR` transaction, `TSL`/`RTCUR` balance transaction, `HSL`/`RHCUR` company code, `KSL`/`RKCUR` global, `OSL`/`ROCUR` freely defined. `COEP`: `WKGBTR` CO area, `WTGBTR` transaction, `WOGBTR` object. **[SAP general]** (look for: `SUM(wrbtr)`/`SUM(wsl)`/`SUM(tsl)` across rows with different currencies; an amount column with no currency column beside it)
- `KSL`/`OSL` do not map 1:1 to ECC currency fields; depends on currency-type config. **[house note]** (look for: ECC `DMBE2` unioned into S/4 `KSL` without a documented mapping)
- SAP stores amounts with two decimals regardless of currency; `TCURX.CURRDEC` gives the real decimals (JPY 1000 stored as `10.00`). **[sap-finance]** (`sap_currency_amount`) (look for: table-sourced amounts in JPY, KRW, KWD etc. with no `TCURX` shift)
- Fiscal year and period come from the source (`BKPF.GJAHR`/`MONAT`, `ACDOCA.GJAHR`/`POPER`, `COEP.GJAHR`/`PERIO`), never derived from the posting date. Variants differ per company code (`T001.PERIV`). **[house note]** (look for: `year(budat)`, `month(budat)`, `date_trunc('month', posting_date)` used as fiscal period)
- Fiscal calendar comes from `T009` (`XKALE = 'X'` calendar-year variant; `ANZBP` regular, `ANZSP` special periods) and `T009B` (`BUMON`, `BUTAG`, `POPER`, year shift `RELJR`). Year-dependent variants (`BDATJ` filled) need separate handling. **[sap-finance]** (`refined_s4_fiscal_year_variant`, `dim_finance_fiscal_period`) (look for: a hard-coded calendar or a period dim with only 12 periods)
- Special periods 13–16 post on a date inside the last regular period, so a date-only model folds them into period 12. Period 0 holds opening balances. **[house note]** (look for: period dim with `accepted_range` 1–12; facts with no period column, only `posting_date`)
- `FISCPER`/`FISCYEARPER` is `YYYYPPP` (`2024013`), meaningful only with the variant; period 001 is not always January. **[house note]** (`sap_fiscper`) (look for: `fiscper` parsed as `YYYYMM`; joins on period without the variant)

## 3. Controlling and other modules

- `OBJNR` is a two-letter type then the key: `KS` + controlling area (4) + cost centre (10); `PR` + WBS internal number (8); `OR` + order (12). **[sap-finance]** (`sap_objnr_*`) (look for: `substring(objnr, …)` with wrong offsets; `OBJNR` joined to `KOSTL` directly)
- Other prefixes seen: `KL` cost centre/activity type, `OV` order operation, `NV` network activity, `PD` project definition, `IE` equipment, `IF` functional location (all verify). **[SAP general]** (look for: CO line items filtered to `KS%` when the model claims project or order costs)
- Cost centre is unique only within controlling area (`KOKRS`); company code maps to it via `TKA02`. **[house note]** (look for: dims keyed on `KOSTL` alone across several controlling areas)
- `CSKS` (cost centre) and `CEPC` (profit centre) are time-sliced by `DATAB`..`DATBI`, and `DATBI` is in the table key. Join on posting date between the two. `DATBI` is inclusive; `99991231` is open. **[sap-finance]** (`refined_s4_cost_centre`, `sap_intersect_validity`) (look for: join on `KOSTL`/`PRCTR` only, which fans out; `valid_to` NULL under a `BETWEEN` join; exclusive-end logic on inclusive dates)
- Text tables carry the same validity (`CSKT` keyed with `DATBI`) and a language (`SPRAS`/`LANGU`): pick one language and one slice. **[sap-finance]** (`sap_text`) (look for: join to `CSKT`/`CEPCT`/`SKAT` with no language filter)
- ECC landed at decommissioning holds only the master-data slice valid then; earlier attributes are gone. **[sap-finance]** (look for: ECC history joined to ECC master data claiming as-was attributes)
- Report profit centre as posted on the line (`PRCTR`), not re-derived from the cost centre's current `CSKS.PRCTR`. **[sap-finance]** (look for: profit centre looked up from cost-centre master instead of the fact line)
- WBS: `PRPS.PSPNR` is the internal number used on postings (`ACDOCA.PS_PSP_PNR`, `BSEG.PROJK`); `POSID` is the external edited key shown in reports (CJI3, CN43N). Project definition: `PROJ.PSPNR` internal, `PSPID` external. **[SAP general]** (look for: report `POSID` joined to `PS_PSP_PNR`)
- Orders: `AUFK` holds all order types; `AUTYP` `01` internal (CO) order, `30` maintenance order (others verify). PM header in `AFKO` + `AFIH`; location via `AFIH.ILOAN` → `ILOA`. **[SAP general]** (look for: order counts over `AUFK` with no `AUTYP` filter)
- PM/PS operations live in `AFVC` keyed by `AUFPL` + `APLZL` (`AFKO.AUFPL` links the order). `VORNR` is the displayed operation number and is not unique per order (sequences, sub-operations `UVORN`, verify). **[SAP general]** (look for: operation key `AUFNR` + `VORNR` without a uniqueness test; joins `AFVC` to orders on `AUFNR`)
- Object status is in `JEST` by `OBJNR`; only rows with `INACT = ''` are active. Texts in `TJ02T` (system) / `TJ30T` (user, verify). **[SAP general]** (look for: status from `JEST` with no `inact` filter; status taken from a report's concatenated string)
- Deletion flags: `EKPO.LOEKZ` (`L` deleted, `S` blocked), `AUFK.LOEKZ`. **[SAP general]** (look for: PO value `SUM(netwr)` with no `loekz` filter)
- Statistical CO postings (e.g. a statistical order alongside a real cost centre) add extra CO lines; value type `WRTTP = '11'` (verify). **[SAP general]** (look for: `COEP` sums with no `wrttp` filter)
- Vendors and customers become business partners in S/4 (CVI); map `LFA1` → `CVI_VEND_LINK` → `BUT000`. Number clashes get a different BP number. **[house note]** / **[sap-finance]** (look for: `lifnr = partner` equality joins)
- In S/4, cost elements are GL accounts (`SKA1`); ECC keeps them in `CSKA`/`CSKB` with `DATAB`/`DATBI`. **[sap-finance]** (look for: S/4 model reading `CSKB` as the cost-element master)

## 4. Master data and hierarchies

- ECC cost-centre and profit-centre groups are sets: `SETHEADER`/`SETNODE`/`SETLEAF`, cost-centre standard hierarchy set class `0101`, `SUBCLASS` = controlling area. Sets have no validity dates: only the current state. **[house note]** / **[sap-finance]** (look for: history reported under a set-based hierarchy labelled as-was)
- `SETLEAF` leaves can be ranges (`VALOPTION = 'BT'`, `VALFROM`..`VALTO`), not just `EQ` values. **[SAP general]** (look for: join `setleaf.valfrom = kostl` with no range handling)
- Financial statement versions are not sets: `T011`, `FAGL_011PC` (nodes), `FAGL_011ZC` (account ranges `VONKT`..`BISKT`). Accounts outside every range belong under "not assigned". **[house note]** / **[sap-finance]** (look for: accounts dropped by an inner join to the FS version; trial balance not netting to zero)
- S/4 `HRRP_*` is the runtime copy of sets (via `HRRP_REP` or auto-replication); only Manage Global Hierarchies objects are HRRP-native. Take each hierarchy from one source, set or HRRP. **[house note]** (look for: set and HRRP versions of the same hierarchy unioned)
- `HRRP_DIRECTORY`/`HRRP_NODE` validity `HRYVALFROM`..`HRYVALTO` is inclusive (`20231231` then `20240101`). Half-open handling loses the last day of each version. **[sap-finance]** (`sap_hrrp_flatten(valid_to_is_inclusive=true)`) (look for: `posting_date >= valid_from and posting_date < valid_to` on HRRP dates)
- HRRP replicates every node per hierarchy version: collapse adjacent identical paths, or an unchanged leaf gets a new version at every change. **[sap-finance]** (look for: SCD2 hierarchy dim with many versions per leaf and identical level columns)
- Flatten by walking up from each leaf and intersecting validity at every step, so a move anywhere in the path makes a version. Texts from `HRRP_NODET` (`NODETXT`, by `NODECLS`). **[sap-finance]** (look for: flatten that takes validity only from the leaf row)
- The flatten must never emit a NULL validity window, or a date-bounded join drops the key to unknown. Decide a point-in-time rule for set-based ECC history. **[house note]** (look for: `valid_to` NULL in a hierarchy dim; no `no_unknown_members` test on the fact)
- Combine master-data slices and hierarchy versions into one versioned dim, assigned as at posting date. **[sap-finance]** (`sap_intersect_validity`) (look for: hierarchy joined at `current` while master data is as-was, or the reverse)
- Build one flatten per hierarchy source (sets, FS versions, HRRP), each emitting the same level columns. **[house note]** (look for: one flatten forced over sets, FS versions and HRRP together; level columns that differ by source)

## 5. Client and keys

- ERP tables carry the client (`MANDT`; `RCLNT` on `ACDOCA`, `FAGLFLEXA`, `GLT0`). Filter to production client. BW-generated tables generally carry none. **[house note]** (look for: no `mandt`/`rclnt` filter or key column where several clients landed)
- ALPHA conversion: numeric keys are stored zero-padded (`4711` → `0000004711` in a 10-character field); alphanumerics as typed. Join on the internal form. **[house note]** / **[sap-finance]** (`sap_alpha_in`/`sap_alpha_out`) (look for: `ltrim(x, '0')` on one side of a join; casts of keys to integer; report keys joined to table keys)
- Not every key uses ALPHA: WBS `POSID` and project `PSPID` use their own edit masks. **[SAP general]** (look for: `lpad` applied to `POSID`)
- SAP stores blanks, zeros and `00000000`, not NULL; `99991231` is open-ended. **[house note]** / **[sap-finance]** (`sap_date`) (look for: `is null` tests on SAP char columns; `cast(budat as date)` without handling `00000000`)
- Composite natural keys. FI document `BUKRS` + `BELNR` + `GJAHR`; line `+ BUZEI`. `ACDOCA` `RCLNT` + `RLDNR` + `RBUKRS` + `GJAHR` + `BELNR` + `DOCLN`. CO document `KOKRS` + `BELNR` (+ `BUZEI`; `GJAHR` in key, verify). `EKPO` `EBELN` + `EBELP`. `AFVC` `AUFPL` + `APLZL`. **[house note]** for FI/ACDOCA, **[SAP general]** for the rest (look for: join on `BELNR` alone, which fans out across company codes and years)
- Compounding: some keys are unique only with their parent (cost centre within controlling area; fiscal period within variant). **[house note]** (look for: dim unique test on the child column alone)

## 6. BW

- Master data tables: `/BI0/` (content) or `/BIC/` (customer) + `P` time-independent, `Q` time-dependent (`DATEFROM`/`DATETO`), `T` texts, `S` SIDs, `H` hierarchy. Treat `Q` as SCD2. **[house note]** (look for: `Q` table joined without a date condition)
- Filter `OBJVERS = 'A'` (active). `M` is loaded but not activated and duplicates the key; `D` is delivered content. **[house note]** / **[sap-finance]** (look for: reads of `/BI0/P…`, `Q…`, `T…`, `H…` with no `objvers` filter)
- ADSO: read the `8` external SQL view or the active `2` table; never the inbound `1` table (unactivated requests); `3` is the change log. Classic DSO: active `00` table, not activation queue `40`. **[house note]** / **[sap-finance]** (look for: `/BIC/A…1` or `…40` as a source)
- InfoCube: union `F` (uncompressed) and `E` (compressed) fact tables; dimension tables hold SIDs. CompositeProviders and Open ODS views have no table. **[house note]** (look for: only `E` or only `F` read)
- `0RECORDMODE`: blank after image, `X` before image (key figures negated), `A` additive, `D` delete, `R` reverse, `N` new. Sum every image, or upsert by key dropping `X` and treating `R`/`D` as deletes; never mix. **[house note]** / **[sap-finance]** (look for: change-log sums that drop `X`; upserts that keep `X`)
- After-image-only deltas (AIE/AIM; `0FI_GL_14` is AIED) upsert cleanly but deletes may never arrive. **[house note]** (look for: no delete handling or periodic full reload on AIE sources)
- `0FI_GL_14` carries the leading ledger only; other ledgers need generated DataSources. **[house note]** (look for: non-leading-ledger reporting built on `0FI_GL_14`)
- SIDs are system-specific integers, not keys: join on business keys. **[house note]** (look for: joins on `SID` columns across systems or after reloads)
- Hierarchies: one `H` table per characteristic; pick one through `RSHIEDIR` (`HIEID`, version, validity). Watch several roots, interval leaves (`J` table), link nodes (`LINK = 'X'`), the `REST_H` root, and compounded `NODENAME`. **[house note]** (look for: `H` table read with no `HIEID` filter; link nodes counted twice)
- Pre-flattened customer level attributes must match the hierarchy before they are trusted. **[house note]** / **[sap-finance]** (look for: level attributes used with no reconciliation to the `H` walk)
- Business logic often sits in BW queries (restricted/calculated key figures, currency translation), not in tables. **[house note]** (look for: model reconciled to the provider table but not to the BW query users see)
- Non-cumulative key figures (stock) are movements plus a reference point, not balances. **[house note]** (look for: inventory balance summed straight from a provider)

## 7. Extraction caveats affecting completeness

- SAP Note 3255746: third-party ODP-RFC use is "not permitted"; a patch (around June 2026, per vendors) blocks non-SAP ODP-RFC callers, opt-out to December 2026. Microsoft confirms it blocks ADF's SAP CDC connector. Feeds on that route can stop or go stale. Self-check: SAP Note 3439624. **[house note]** (look for: freshness tests absent on ODP-RFC-fed sources; silent gaps after mid-2026)
- ADF SAP Table reads one table or view with no native delta; full reloads or custom watermarks only. **[house note]** (look for: incremental model keyed on a change date the table does not reliably maintain)
- Extractors give a fixed column set; raw-table routes give every field but no delta or sign logic. **[house note]** (look for: sign or ledger rules assumed to be applied upstream)
- ECC line items archived with SARA leave gaps in the tables. **[house note]** (look for: history reconciled only from line items, not to totals tables)
- Mid-load reads (inbound tables, `OBJVERS = 'M'`) do not match reports. **[house note]** (look for: extract schedules overlapping BW activation)
