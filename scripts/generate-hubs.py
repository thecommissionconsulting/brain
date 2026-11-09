#!/usr/bin/env python3
"""Build the index layer: one hub per folder, plus index.md §9.

directory-instructions.md requires a hub named after its folder, carrying an
Answers block and a row per note with a "reach for it when" column. A bare list
of filenames is explicitly rejected, so the column is derived from facts the
note actually carries: its document class, its engagement, and its title.

Nothing here invents a description. A SOW is described as a SOW because its
filename says so; where nothing is derivable the note's own title is used.

The generated routing table lives between markers. Everything outside them is
authored content and is carried through untouched on every re-run, so running
this twice is safe. An earlier version absorbed a folder's sibling note and
then overwrote it on the next run, which cost 46 authored Confluence notes;
they came back from git, and the markers are why that cannot recur.

    .\\scripts\\generate-hubs.ps1              # dry run
    .\\scripts\\generate-hubs.ps1 --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

VAULT = wiki_root.wiki_root() or wiki_root.MISSING
WIKI = VAULT / "wiki"
INDEX = VAULT / "index.md"
OWNER = "Daru Broodryk"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

MARK_START = "<!-- generated:routing -->"
MARK_END = "<!-- /generated:routing -->"
GENERATED_BLOCK = re.compile(
    re.escape(MARK_START) + r".*?" + re.escape(MARK_END), re.S)

CLASSES = [
    (re.compile(r"\bsow\b|statement-of-work|scope-of-work", re.I), "Statement of work"),
    (re.compile(r"contract|agreement|side-letter|ratecard|nda", re.I), "Signed agreement"),
    (re.compile(r"proposal|quote|tender|\brfp\b|\brfi\b", re.I), "Proposal or tender response"),
    (re.compile(r"assessment|audit|review|roadmap|discovery", re.I), "Assessment or review"),
    (re.compile(r"playbook|runbook|template|checklist|standard", re.I), "Template or standard"),
    (re.compile(r"training|workshop|course|case-study", re.I), "Training material"),
]

BUCKET_TESTS = {
    "clients": "About a client, engagement or their environment.",
    "internal": "About how the company does the work: method, standard, SOP, product.",
    "company": "About who the company is or how the company runs: people, sales, plans, vault ops.",
}

BUCKET_ANSWERS = {
    "clients": "Which clients has the company worked with? Where is a client's SOW or signed "
               "agreement? What engagements ran for this client?",
    "internal": "How does the company run a discovery or a delivery? What is our standard for this "
                "tool? Which playbook covers this stage?",
    "company": "Who works at the company and what do they own? How does the company sell and price work? "
               "What is the current strategy? How is the vault operated?",
}


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter block including delimiters, body)."""
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^(---\n.*?\n---\n)(.*)$", text, re.S)
    return (match.group(1), match.group(2)) if match else ("", text)


def fields_of(path: Path) -> dict:
    try:
        block, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}
    out = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() not in ("---",):
            out[key.strip()] = value.strip().strip('"')
    return out


def title_of(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip()
                if text:
                    return re.sub(r"\s+", " ", text)[:90]
    except OSError:
        pass
    return path.stem.replace("-", " ")


def describe(path: Path, fields: dict) -> str:
    for pattern, label in CLASSES:
        if pattern.search(path.stem):
            engagement = fields.get("engagement", "")
            return f"{label} — {engagement.replace('/', ' / ')}" if engagement else label
    return title_of(path)


def routing_block(folder: Path, notes: list[Path], subfolders: list[Path],
                  stems: dict[Path, str]) -> str:
    lines = [MARK_START, ""]
    rel = folder.relative_to(VAULT).as_posix()
    bucket = folder.relative_to(WIKI).parts[0] if folder != WIKI else None

    if bucket and folder.parent == WIKI:
        lines += [f"> **Answers:** {BUCKET_ANSWERS[bucket]}", "",
                  f"**Placement test.** {BUCKET_TESTS[bucket]}", ""]
    else:
        lines += [f"> **Answers:** What is held under `{rel}`? Which note here answers my "
                  f"question? Where did these notes come from?", ""]

    if subfolders:
        lines += ["## Folders", "", "| Folder | Reach for it when |", "|---|---|"]
        for sub in subfolders:
            count = len(list(sub.rglob("*.md")))
            lines.append(f"| [[{stems.get(sub, sub.name)}]] | {count:,} notes under `{sub.name}` |")
        lines.append("")

    if notes:
        grouped: dict[str, list[Path]] = defaultdict(list)
        for note in notes:
            grouped[fields_of(note).get("engagement", "")].append(note)
        lines += ["## Notes", ""]
        for engagement in sorted(grouped):
            if engagement and len(grouped) > 1:
                lines += [f"### {engagement.replace('/', ' / ')}", ""]
            lines += ["| Note | Reach for it when |", "|---|---|"]
            for note in sorted(grouped[engagement]):
                lines.append(f"| [[{note.stem}]] | {describe(note, fields_of(note))} |")
            lines.append("")

    lines += [MARK_END, ""]
    return "\n".join(lines)


def main() -> int:
    global VAULT, WIKI, INDEX
    wiki_root.require_wiki(VAULT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root", metavar="PATH", help="work on this wiki folder")
    args = parser.parse_args()
    if args.root:
        VAULT = wiki_root.require_wiki(Path(args.root).expanduser().resolve())
        WIKI = VAULT / "wiki"
        INDEX = VAULT / "index.md"

    folders = sorted([d for d in WIKI.rglob("*") if d.is_dir()] + [WIKI])
    stems: dict[Path, str] = {}

    # A generated hub must not collide with an authored note anywhere in the
    # vault, so the taken-name set starts with every note that is not itself a
    # generated hub. Without this the generator and the deduplicator chase each
    # other: rename the file, the generator recreates the bare name next run.
    def is_generated(path: Path) -> bool:
        try:
            return MARK_START in path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False

    generated_hubs = {p for p in WIKI.rglob("*.md") if is_generated(p)}
    used: set[str] = {p.stem for p in WIKI.rglob("*.md") if p not in generated_hubs}
    leaves: list[Path] = []
    plan: list[tuple[Path, Path, Path | None, list[Path], list[Path]]] = []

    for folder in folders:
        if folder.name == "attachments":
            continue
        subfolders = sorted(d for d in folder.iterdir()
                            if d.is_dir() and d.name != "attachments")
        # Folder names repeat across buckets (alteryx appears four times).
        # Vault-wide filename uniqueness is CI-enforced and the harder rule, so
        # qualify with the parent when the bare name is taken.
        stem = folder.name
        own = folder / f'{folder.name}.md'
        if own in generated_hubs and stem in used:
            used.discard(stem)
        if stem in used:
            stem = f"{folder.parent.name}-{folder.name}"
            n = 2
            while stem in used:
                stem = f"{folder.parent.name}-{n}-{folder.name}"
                n += 1
        hub = folder / f"{stem}.md"
        notes = sorted(p for p in folder.glob("*.md") if p != hub)
        if not notes and not subfolders:
            continue
        used.add(stem)
        stems[folder] = stem
        if not subfolders:
            leaves.append(folder)
        # The Confluence import filed folder notes beside their folder. That
        # note is the authored hub; it moves in rather than being replaced.
        sibling = folder.parent / f"{folder.name}.md"
        plan.append((folder, hub, sibling if sibling.exists() and sibling != hub else None,
                     notes, subfolders))

    written = adopted = 0
    for folder, hub, sibling, notes, subfolders in plan:
        authored_fm, authored_body = "", ""
        if hub.exists():
            authored_fm, body = split_frontmatter(
                hub.read_text(encoding="utf-8", errors="replace"))
            authored_body = GENERATED_BLOCK.sub("", body).strip()
        elif sibling is not None:
            authored_fm, authored_body = split_frontmatter(
                sibling.read_text(encoding="utf-8", errors="replace"))
            authored_body = authored_body.strip()
            adopted += 1

        if not authored_fm:
            authored_fm = ("---\ntype: note\nstatus: review\n"
                           f"owner: {OWNER}\ncreated: {TODAY}\n---\n")
        if not authored_body:
            authored_body = f"# {folder.name.replace('-', ' ')}"

        content = (authored_fm + "\n" + authored_body.rstrip() + "\n\n"
                   + routing_block(folder, [n for n in notes if n != sibling],
                                   subfolders, stems))
        if args.apply:
            hub.write_text(content, encoding="utf-8", newline="\n")
            if sibling is not None and sibling.exists() and sibling != hub:
                sibling.unlink()
        written += 1

    # check_maps.py walks wiki/ and _ai/, so the map must cover both.
    ai_root = VAULT / "_ai"
    if ai_root.is_dir():
        for d in sorted(x for x in ai_root.rglob("*") if x.is_dir()):
            if any(c.is_dir() for c in d.iterdir()):
                continue
            if any(c.suffix == ".md" for c in d.iterdir()):
                leaves.append(d)
                stems[d] = d.name

    # A LIST, not a table. Obsidian's table formatter pads every cell to the widest
    # row in its column; on 271 leaves with paths up to 170 chars that had grown this
    # section to 87 KB, 69% of it spaces, and it silently re-pads whenever someone
    # opens index.md. A list has no columns to pad, so the saving cannot drift back.
    # The hub is the folder name except where R-02 forced a prefixed basename, so
    # naming it per row repeated the same string three times for 258 of 271 rows.
    rows, odd = [], []
    for leaf in leaves:
        rel = leaf.relative_to(VAULT).as_posix()
        rows.append(f"`{rel}/`")
        if stems[leaf] != leaf.name:
            odd.append(f"- `{rel}/` → [[{stems[leaf]}]]")

    # §5 skill map: check_maps.py fails CI when this drifts from the skills the
    # installed plugins provide. No skill is committed in this repo any more, so
    # the rows are read from the company's own plugins under ~/.claude/plugins/cache/.
    # A machine with none installed writes no rows rather than an empty table.
    cache = Path.home() / ".claude" / "plugins" / "cache"
    skill_rows = []
    # central, the only company plugin that shipped skills, was retired on
    # 2026-11-07. token-weather-usage and flightdeck ship none today.
    manifests = [m for p in ("token-weather-usage", "flightdeck")
                 for m in cache.glob(f"*/{p}/*/skills/*/SKILL.md")]
    for manifest in sorted(manifests):
        if manifest.stat().st_size == 0:
            continue
        plugin = manifest.parents[2].parent.name
        head = manifest.read_text(encoding="utf-8", errors="replace")[:2000]
        found = re.search(r"^description:\s*(.+)$", head, re.M)
        desc = re.sub(r"\s+", " ", found.group(1)).strip('"')[:110] if found else ""
        skill_rows.append(f"| **{plugin}:{manifest.parent.name}** | {desc} |")

    index_text = "\n".join([
        "---", "type: instruction", "status: review", f"owner: {OWNER}",
        f"created: {TODAY}", "---", "",
        "# index", "",
        "> **Answers:** What is in this vault and where? Which folder holds the note I need?",
        "> Where do I put a new note? What must never be imported?", "",
        "Master index, loaded every session. Retrieval route: this map, then the folder hub,",
        "then grep. Two hops before a note.", "",
        "## Placement", "",
        "- About a client, engagement or their environment → `wiki/clients/`",
        "- About how the company does the work → `wiki/internal/`",
        "- About who the company is or how the company runs → `wiki/company/`", "",
        "## 5. Skills", "",
        "Every skill is a plugin. Do not maintain a second list.", "",
        "| Skill | Use it for |", "|---|---|", *skill_rows, "",
        "## 9. Vault map", "",
        f"Every leaf folder under `wiki/` and `_ai/`, one per line. {len(leaves):,} leaves.", "",
        "A folder's hub note is named after the folder, so `wiki/clients/aa-life/` means",
        "[[aa-life]]. The few where R-02 forced a prefixed basename are listed at the end.", "",
        "Written as a list, not a table, on purpose: Obsidian's table formatter pads every",
        "cell to the widest row in the column, which had grown this section to 87 KB of",
        "which 69% was spaces. A list has no columns to pad, so it cannot drift back.", "",
        *rows, "",
        "### Hubs not named after their folder", "",
        *odd, "",
        "Related: [[rules]] · [[retrieval]]", "",
    ])
    if args.apply:
        INDEX.write_text(index_text, encoding="utf-8", newline="\n")

    print(f"{'' if args.apply else 'DRY RUN '}index layer")
    print(f"  hubs         {written:,}  ({adopted:,} adopted an authored folder note)")
    print(f"  leaf folders {len(leaves):,}")
    print(f"  index.md     {len(index_text.splitlines()):,} lines")
    if not args.apply:
        print("\nrerun with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
