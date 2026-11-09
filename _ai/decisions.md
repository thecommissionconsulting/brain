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
