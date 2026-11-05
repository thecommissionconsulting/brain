#!/usr/bin/env python3
"""Pick the documents worth carrying into the vault, and write an include list.

The library holds 52,257 files, ~20,300 of which are documents. Converting all
of them produces a wiki nobody can navigate. This selects the few thousand that
carry real company knowledge -- statements of work, client contracts and
proposals, delivery playbooks, company policy -- and writes their paths for
onedrive-to-vault.py --include-list to consume.

Selection is by folder role first, filename second. `Customers/<Client>/SOW/`
and `Contracts & Agreements/` are structure the team already maintains, and
they are a far better signal than guessing from a filename.

    .\\scripts\\select-documents.ps1                 # write the list and report
    .\\scripts\\select-documents.ps1 --show sow      # list what one class matched
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SOURCE_DEFAULT = Path(r"C:\Users\DaruBroodryk\Company Ltd\Shared - Documents")
LIST_DEFAULT = VAULT / "_local" / "selection.txt"
REPORT_DEFAULT = VAULT / "_local" / "selection-report.tsv"

DOC_EXTS = {
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "xlsm",
    "txt", "msg", "rtf", "odt",
}

# First match wins, so order is priority.
RULES = [
    ("sow", r"^Customers/[^/]+/.*\b(sow|statement of work|scope of work)\b"),
    ("client-contract", r"^Customers/[^/]+/.*(contracts? & agreements?|/signed/|\bcontract\b|"
                        r"\bagreement\b|side letter|ratecard|rate card|\bmsa\b|\bsla\b)"),
    ("client-proposal", r"^Customers/[^/]+/.*(proposal|\bquote\b|quotation|tender|\brfp\b|\brfi\b)"),
    # Narrative assessments are written in Word or PDF. The same words --
    # "audit", "health check" -- also name operational data exports, and those
    # arrive as spreadsheets that convert into tables of tens of megabytes.
    # Restricting this rule to prose formats keeps the data dumps out.
    ("client-assessment", r"^Customers/[^/]+/.*(assessment|\baudit\b|\breview\b|roadmap|"
                          r"discovery|health check).*\.(pdf|docx?|pptx?)$"),
    ("playbook", r"^Services/"),
    ("company-policy", r"(^Admin/Policies/|handbook|code of conduct|\bpolicy\b|\bpolicies\b)"),
    ("company-contract", r"^Account Setup/.*(terms and conditions|agreement|contract|incorporation)"),
    # Deliberately anchored to company-level folders. An unanchored "template"
    # match pulls in things like moneyhub_invoice_template.xlsx from personal
    # scratch folders, which is noise.
    ("standard", r"^(Wiki|Services|Partners)/.*(standard|guideline|template|checklist|convention)"),
    ("marketing", r"^Marketing/.*(brochure|one.?pager|capability|overview|deck|profile)"),
]

# Never carried, whatever else matches.
EXCLUDE = re.compile(
    r"(win-library|site-packages|node_modules|__pycache__|\.venv|"
    r"my tableau repository|slack export|meet recordings|"
    r"^Training/|weekly challenge|/lab files/|certification|"          # 3rd-party courseware
    r"asb check|passport|criminal|credit check|candidate cvs|"        # personal data
    r"^Admin/Recruitment/|/cvs?/|curriculum vitae|"
    r"~\$|\.tmp$|/archive/old)", re.I)


def classify(rel: str) -> str | None:
    if EXCLUDE.search(rel):
        return None
    ext = rel.rpartition(".")[2].lower() if "." in rel.rsplit("/", 1)[-1] else ""
    if ext not in DOC_EXTS:
        return None
    for label, pattern in RULES:
        if re.search(pattern, rel, re.I):
            return label
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--out", type=Path, default=LIST_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument("--show", help="Print every path matched by one class and exit")
    args = parser.parse_args()

    counts, sizes = Counter(), Counter()
    selected: list[tuple[str, str, int]] = []

    for dirpath, dirnames, filenames in os.walk(args.source):
        dirnames.sort()
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(args.source).as_posix()
            label = classify(rel)
            if not label:
                continue
            try:
                size = full.stat().st_size
            except OSError:
                size = 0
            counts[label] += 1
            sizes[label] += size
            selected.append((label, rel, size))

    if args.show:
        for label, rel, _ in selected:
            if label == args.show:
                print(rel)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        for _, rel, _ in selected:
            handle.write(rel + "\n")
    with open(args.report, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("class\tbytes\tpath\n")
        for label, rel, size in selected:
            handle.write(f"{label}\t{size}\t{rel}\n")

    print(f"{'class':<20}{'docs':>7}{'MB':>9}")
    for label, count in counts.most_common():
        print(f"{label:<20}{count:>7,}{sizes[label] / 1048576:>9,.0f}")
    print(f"\n{'TOTAL':<20}{len(selected):>7,}{sum(sizes.values()) / 1048576:>9,.0f}")
    print(f"\nlist    {args.out}")
    print(f"report  {args.report}  (open in Excel to review before converting)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
