---
type: note
status: active
owner: Daru Broodryk
created: 2026-09-08
tags:
  - ai
---

# Retrieval — how to find things in this vault

> **Answers:** How do I find the right note? How should I write a note so it can be found later?
> Why does search sometimes return nothing?

The vault is designed to be findable with nothing but the filesystem. This note records the
retrieval order and the authoring rules that keep it working.

Companion to [[rules]] (the rule set) and [[index]] (the map itself).

## The retrieval order — use it in this order

| # | Step | Why it comes first |
|---|---|---|
| 1 | **[[index]]** — the master index | Always loaded, every session, via `CLAUDE.md`. §9 names every top-level folder and points at its index note. CI (`scripts/check_maps.py`) **fails** if a folder exists that `legacy-index.md` does not name, so the map cannot silently go stale |
| 2 | **The folder index** | [[clients]] · [[knowledge-base]] · [[playbooks]] · [[products]] · [[strategy]] · [[sales]] · [[people]] · [[tool-index]] · this note for `_ai/`. Each lists what is inside and when to reach for it, so you go one level deep without loading the whole vault |
| 3 | **Grep the content** | The fallback that always works. Every note is keyword-findable — verified across 20 representative questions |

All three need nothing but the filesystem.

## Grep recipe

Always exclude the staging and archive trees — they hold superseded copies and NDA/PII material,
and they will drown a search:

```
grep -rli --include='*.md' \
  --exclude-dir=.git --exclude-dir=confluence --exclude-dir=.confluence-private \
  --exclude-dir=archive --exclude-dir=_local \
  -e 'your pattern' .
```

Broad terms are noisy on purpose — `Coalesce` hits 25 files, `mission|vision` hits 33. That is
what steps 1 and 2 are for: the map tells you *which* of those is the home for the idea. Grep
confirms; the map decides.

## Writing a findable note

Two rules, both load-bearing.

**1. Open with an `> **Answers:**` block.** Three to five of the questions a human would actually
type, in their words. It lets a reader see the note's scope in one glance, and it puts the
asker's own keywords in the file where grep will hit them.

Write the *asker's* vocabulary, not the vault's. "Is this body shopping or a project?" beats
"engagement qualification criteria".

**2. Keep each section single-topic and short.** This is the [[rules]] "one idea per note"
rule, and it is a retrieval requirement too. A reader scanning grep hits lands on a section, not
a file, so a long section covering four subjects buries all four.

> Worked example: a short section purely about IP ownership answers "who owns the IP we build for
> a client?" on sight, while a longer one covering IP *plus* payment, liability and termination
> forces the reader to hunt. Splitting the second into [[sow-commercial-terms]] fixed it.
>
> **Rule of thumb: if a section covers more than one question, split it.**

## Keeping the map honest

- `scripts/check_maps.py` — fails CI if a top-level folder or live skill is missing from [[index]].
- `scripts/check_links.py` — hard-fails on duplicate basenames (which would make `[[links]]`
  ambiguous), and reports broken wikilinks.
- `scripts/check_frontmatter.py` — every note carries a valid `type`, and the required fields for
  that type.

This is why the map can be trusted as step 1: it is enforced, not maintained by goodwill.

Related: [[rules]] · [[index]] · [[setup]] · [[strategy]] · [[vault-git]] · [[tool-index]]
