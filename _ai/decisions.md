---
type: note
status: active
owner: Daru Broodryk
created: 2026-11-10
---

# Decisions log

> **Answers:** Which detail decisions were made in the brain / wiki split, when, why, and
> which option was rejected? One line per decision. Big-picture decisions go to the owner;
> everything else is logged here.

| Date | Decision | Why | Rejected |
|---|---|---|---|
| 2026-11-10 | Wiki repo keeps the old vault's content layout (`index.md`, `wiki/**`, `_ai/templates/`, `_ai/retrieval.md`, `_ai/pii-denylist.txt`). | Every path rule and glob stays valid without rewrites. | Renaming into a new layout. |
| 2026-11-10 | Files move by plain copy; the wiki's first commit names the brain commit it copied from. | History stays in the brain; the copy is simple to check. | History rewrite with filter-repo or subtree split. |
| 2026-11-10 | One-off migration scripts get a guard only (`wiki_root` check at the top of `main()`). | They are historical; porting them costs more than it saves. | Porting each one to a full wiki_root call path. |
| 2026-11-10 | Wiki pre-push runs the lints: `check_links` blocks; `check_frontmatter` runs only if PyYAML imports; `check_maps` warns. | Catches broken links before they reach the remote, without a CI dependency on the brain. | Lints only in CI. |
| 2026-11-10 | Wiki CI is secret scan only. | The wiki CI cannot run brain scripts without a brain checkout. | Running the full lint suite in wiki CI. |
| 2026-11-10 | Brain and wiki are added to each other's `permissions.additionalDirectories`. | A session in one repo can read the other without a copy. | Duplicating files into both repos. |
| 2026-11-10 | Wiki clone at `~/wiki`, repo `DataWithDaru/wiki` (private). (owner decision) | Sits next to `~/brain`; private because it holds client history. | Public repo; a folder inside the brain. |
| 2026-11-10 | Commit without asking inside an approved Build; push, PR and merge always ask. (owner decision) | Commits are local and reversible; anything that leaves the machine needs a yes every time. | Asking before every commit; auto-pushing. |
| 2026-11-10 | `generate-hubs.py --root PATH` is checked after the first-line guard, so it needs a configured wiki on the machine. | The plan puts the guard first in `main()`; the gap is recorded rather than changed. | Parsing `--root` before the guard (changes the plan's guard placement). |
| 2026-11-10 | With no wiki, `pii_gate.py` runs the bulk-email check only and never blocks because the wiki is missing. | Fail-open is the rule; a missing wiki is a setup problem, not a privacy event. | Blocking every read until the wiki is configured. |
| 2026-11-10 | `session_gate.py` prints a per-gate command for each red check, with the right working folder. | The old single hint named `check_schema.py`, which does not exist. | Keeping one generic hint. |
| 2026-11-10 | `generate-hubs.py --root` works on a machine with no configured wiki; the guard runs only without `--root`. | `--root` is the explicit way to point the script at a wiki. | Guard first, as the plan first said. |
| 2026-11-10 | `setup_vault.py` registers the wiki folder with Obsidian, not the brain, and clones `DataWithDaru/wiki` as `wiki` beside the brain. | The owner opens the wiki in Obsidian; the brain is not a vault. | Registering the brain, as the old single-repo script did. |
| 2026-11-10 | `setup_vault.py` uses the https URL for the wiki clone, the same form as its `VAULT_REPO`. | Matches the script's existing style; a private https clone needs a credential that the script does not handle. | An SSH alias, which exists only on the owner's machine. |
| 2026-11-10 | Rules that name a moved path get "(wiki)" in the rule cell (R-07, R-08, R-10, R-19, R-48); the retrieval wikilinks become plain text. | The plan asks for it; the reader sees which repo holds the path without following a link. | Rewriting the rules around the moved paths. |
| 2026-11-10 | Brain `vault-lint.yml` keeps `check_schema_sync.py` only; the three content lints run in the wiki pre-push. | The brain has no content to lint; the wiki hook runs them where the content lives. | Keeping the lints in the brain's CI against an empty tree. |
| 2026-11-10 | Wiki `.github/CODEOWNERS` lists only the `/wiki/` and `/index.md` lines the plan names; no `/_ai/` line. | The plan names those lines; the wiki holds only two `_ai/` files, both under the brain's review. | Copying the full brain CODEOWNERS. |
| 2026-11-10 | `test_setup_vault.py::test_registering_adds_the_vault_and_keeps_existing_entries` fails on Linux before and after this change. | A `Path("C:/...")` assumption; it is not part of Task 3, so it is reported, not fixed. | Changing the test in Task 3. |
| 2026-11-10 | `test_setup_vault.py::test_registering_adds_the_vault_and_keeps_existing_entries` left failing. | It fails the same way on `main` before the split (Windows path slashes); not caused by this work. | Fixing it inside this Build. |
| 2026-11-10 | Brain `CLAUDE.md` "writing outside" line scoped to the brain repo. | Wiki sessions import the brain `CLAUDE.md`; unscoped, it would ask before every wiki note edit. | Leaving it unscoped. |
| 2026-11-10 | Wiki steps run in the normal install when a wiki is found; `--wiki-only` runs only them and skips the global steps, conflict and tool reports, and `verify_install`. | The owner's wiki wiring must not reach `~/.claude`; the plan asks for a wiki-only run that touches nothing global. | A separate wiki installer script. |
| 2026-11-10 | Brain `permissions.deny` for wiki files uses the `//` absolute form, `Read(//<wiki>/raw/**)`; a drive-letter wiki gets `Read(//C:/...)`, which is not verified. | Claude Code reads a single leading slash as project-relative, so `/<wiki>` would not block the wiki. | Single-slash paths. |
| 2026-11-10 | Hook entries are ours when their command runs `session_gate.py`, `pii_gate.py` or `review_output.py`; ours are replaced in place, all other hooks are kept. | A second run writes the same file, and a hook the owner added by hand survives. | Rewriting the whole file, or matching on the path. |
| 2026-11-10 | JSON files the wiki steps change are backed up beside themselves first, as the global settings are. | Per-machine files still hold a person's edits; a backup costs nothing. | No backup for gitignored files. |
| 2026-11-10 | `verify_install` runs `check_maps.py` and `check_frontmatter.py` with the wiki as cwd; they left the brain's suite list. | Both read `./` and find nothing in the brain. | Running them in the brain against an empty tree. |
| 2026-11-10 | `_local/brain.md` is checked by resolved path, so the `~/` and absolute forms both pass. | The two forms name the same file; a text compare would fail one. | Comparing the text of the line. |
| 2026-11-10 | `--wiki PATH` without an `index.md` exits 2; `--wiki-only` with no wiki exits 2; a full run with no wiki prints `wiki: not configured` and carries on. | A wrong path must not fall back silently to `../wiki`; the global install does not need a wiki. | Exit 0 with nothing done. |
| 2026-11-10 | Wiki git hooks are marked executable in the index with `update-index --chmod=+x`, and on disk where the OS has an exec bit. | Git keeps the mode in the index, so the clone works on Windows, where the disk bit means nothing. | `chmod` alone. |
| 2026-11-10 | Absolute deny rules use `//` plus the POSIX path; a Windows drive path `C:/x` is written `//c/x`. | Claude Code matches Windows paths in POSIX form. | `//C:/x`, which would never match. |
