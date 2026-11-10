"""Vault graph lint — complements check_frontmatter.py. Run from repo root.

Hard-fails on duplicate basenames (they make [[wikilinks]] ambiguous vault-wide).
Reports (non-failing) broken wikilinks and an over-budget index.md, so the
always-loaded router stays lean.

Scope = Obsidian's namespace: every .md EXCEPT dot-folders and gitignored
staging. Unlike check_frontmatter.py this KEEPS _ai/ — those files aren't
frontmatter-linted but they ARE real wikilink targets ([[rules]]).

Ported from obsidian-legacy per vault-restructure-design.md §7: `confluence/`
swapped for `raw/`, `archive/` dropped, and the budget check points at index.md.

Enforces R-02: basenames are unique vault-wide, so links are unambiguous.
"""
import collections
import pathlib
import re
import sys

SKIP_PREFIX = (".git/", ".obsidian/", ".claude/", ".agents/",
               "raw/", ".confluence-private/", "scripts/", "assets/", "_local/",
               ".superpowers/", "marketplace/")
# R-10 budgets BYTES, not lines. index.md sits in the prompt for the whole
# session, and what that costs is characters. The old 250-line budget was blind
# to the real problem: Obsidian's table formatter had padded the vault map to
# 92 KB, 69% of it spaces, at exactly the same line count. Rewriting it as a list
# cut 77% of the bytes and ADDED lines, which the line budget scored as worse.
# 32 KiB is roughly 8k tokens, leaves room for growth, and trips immediately if
# the map is ever reformatted back into a padded table.
INDEX_MD_MAX_BYTES = 32768
# README/CLAUDE are per-folder infra, not linked notes — exempt from the duplicate check.
# Per-folder infrastructure, not linked notes.
DUP_EXEMPT = {"README", "CLAUDE", "SKILL", "SECURITY"}
# Intentional red links: prose examples in rules.md + template placeholders.
ALLOW_UNRESOLVED = {"wikilink", "wikilinks", "wikilinked", "client-name", "relevant-note"}

files = [p for p in pathlib.Path(".").rglob("*.md")
         if not p.as_posix().startswith(SKIP_PREFIX)]

errors = 0

# 1) Duplicate basenames -> ambiguous wikilinks (HARD FAIL)
by_stem = collections.defaultdict(list)
for p in files:
    by_stem[p.stem].append(p.as_posix())
shown = 0
for stem, paths in sorted(by_stem.items()):
    if len(paths) > 1 and stem not in DUP_EXEMPT:
        errors += 1
        shown += 1
        if shown <= 15:
            print(f"::error::duplicate basename '{stem}' — [[{stem}]] is ambiguous: "
                  f"{', '.join(sorted(paths)[:4])}")
if shown > 15:
    print(f"::error::... and {shown - 15} further duplicate basenames.")
known = set(by_stem)

# 2) Broken wikilinks (REPORT ONLY) — strip code so syntax examples don't count
CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`]*`")
WIKI = re.compile(r"\[\[([^\]|#]+)")
broken = collections.Counter()
for p in files:
    t = INLINE.sub("", CODE_FENCE.sub("", p.read_text(encoding="utf-8", errors="replace")))
    for m in WIKI.finditer(t):
        tgt = m.group(1).strip()
        if tgt and tgt not in known and tgt not in ALLOW_UNRESOLVED:
            broken[tgt] += 1
for tgt, n in broken.most_common(20):
    print(f"::warning::unresolved wikilink [[{tgt}]] ({n}x)")
if len(broken) > 20:
    print(f"::warning::... and {len(broken) - 20} further unresolved link targets.")

# 3) index.md context budget (REPORT ONLY) — it loads every session
index = pathlib.Path("index.md")
if index.exists():
    n = len(index.read_text(encoding="utf-8", errors="replace").encode("utf-8"))
    if n > INDEX_MD_MAX_BYTES:
        print(f"::warning::index.md is {n:,} bytes (budget {INDEX_MD_MAX_BYTES:,}) — it sits "
              f"in the prompt all session; link out, don't grow it.")
    else:
        print(f"index.md context budget: {n:,} / {INDEX_MD_MAX_BYTES:,} bytes.")

print(f"\ncheck_links: {len(files):,} notes, {errors} duplicate-basename error(s), "
      f"{len(broken):,} unresolved link target(s).")
sys.exit(1 if errors else 0)
