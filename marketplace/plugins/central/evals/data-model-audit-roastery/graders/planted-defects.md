---
type: llm
weight: 3
---

The final message summarises a data model audit, one line per finding, then "Not checked"
lines. Grade it with this checklist. Work through every item, then decide.

FOUND: for each item, is there a finding line about it? Any check id or wording is fine;
judge by meaning.
1. fact_roasts: union by position swaps kg and kind.
2. fact_sales.customer_id is a NULL literal (the customer join never matches).
3. fact_sales does not output the documented store_key.
4. fact_roasts to dim_shift joins on shift_code alone, but dim_shift's grain is store + shift.
5. fact_sales_per_kg joins two facts.
6. dim_employee reads the restricted hr_restricted catalog.
7. order_lines is a plain SELECT * wrapper.
8. A comment on fact_sales names the order header (vbak) but the SQL reads order lines/items.
9. The same store list is hard-coded in two objects.

NOT FLAGGED: each of these fails the check only if a finding line calls it a defect.
A. src_open_orders reported as a wrapper or as a defect.
B. fact_movements reported as a column-order or union misalignment. (A finding about its
   missing sign or movement type is fine.)
C. The notes column being NULL, reported as a key problem.
D. The short channel IN list ('web', 'shop', 'phone') reported as a hard-coded list problem.
E. The fact_sales to dim_date join reported as broken.

UNCHECKABLE: fact_all_batches must appear only under "Not checked", or as a finding marked
PLAUSIBLE that says its column order can't be verified. It fails if it is marked CONFIRMED.

Extra findings not listed above (for example, closed stores missing from dim_store, or no
grain stated) are allowed and must not count against the report.

PASS if at least 7 of items 1–9 are found, including 1 and 2, none of A–E is flagged, and
the UNCHECKABLE rule holds. Otherwise FAIL. Before the verdict, list the items found, the
items missed, and any A–E that were flagged.
