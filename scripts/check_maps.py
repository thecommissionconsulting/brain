"""Vault lint: index.md's skill map (§5) and vault map (§9) stay true.

index.md is the always-loaded router. If it lists a skill that no longer exists,
or a leaf folder appears that index.md never names, Claude navigates on a stale
map. This fails CI on that drift. Run from repo root.

Two changes from the obsidian-legacy original, per vault-restructure-design.md §7:

  - The folder check walks LEAF folders under wiki/ and matches their full
    PATH, not a bare name. After the restructure only wiki/ and _ai/ sit at
    root, both trivially named, so a top-level check would pass green while
    every leaf vanished from the map. Path matching also fixes the old
    weakness where a word-boundary match on "people" was satisfied by any
    prose mention of the word.
  - SKIP_DIRS drops confluence and archive, and adds raw.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
INDEX_PATH = ROOT / "index.md"
if not INDEX_PATH.exists():
    print("::error::index.md is missing — the router has no map.")
    sys.exit(1)
INDEX = INDEX_PATH.read_text(encoding="utf-8", errors="replace")
errors = warnings = 0


def err(m):
    global errors
    print(f"::error::{m}")
    errors += 1


def warn(m):
    global warnings
    print(f"::warning::{m}")
    warnings += 1


# ---- 1. Skill map (index.md §5) <-> the skills installed plugins provide ----
#
# No skill is committed here any more. Every one arrives as a plugin. Today only
# superpowers, from Anthropic's marketplace, ships skills; the company's own
# plugins (token-weather-usage, flightdeck) ship none. central and humanizer were
# retired on 2026-11-07. The trees this used to read, .agents/skills/ and .claude/skills/, are gone. A
# skill committed inside a working repo only loads when you are in that repo, so
# they had to be copied to ~/.claude/skills/ by a script, and the copies drifted.
#
# "Live" therefore means "provided by an installed plugin", and that is what §5
# is checked against. On a machine with no plugins installed -- CI, or a clone
# before install_vault.py has run -- there is nothing to compare against, so the
# check says so instead of failing every entry.
PLUGIN_CACHE = pathlib.Path.home() / ".claude" / "plugins" / "cache"
INSTALLED = pathlib.Path.home() / ".claude" / "plugins" / "installed_plugins.json"
# The company's own plugins: every skill one of them ships must be listed in §5.
COMPANY_PLUGINS = ("token-weather-usage", "flightdeck")
on_disk, no_desc, origin, tally = set(), set(), {}, {}


def installed_paths():
    """The install folders the CLI records as installed, or None if it records none.

    `claude plugin uninstall` leaves the cache folder behind, so the cache alone
    would still count an uninstalled plugin's skills as live.
    """
    try:
        data = json.loads(INSTALLED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {pathlib.Path(e["installPath"]).resolve()
            for entries in (data.get("plugins") or {}).values()
            for e in entries if e.get("installPath")}


def plugin_skills():
    """(plugin name, skill name, SKILL.md) for every installed plugin.

    Two layouts in the wild: a multi-skill plugin keeps them under skills/, and a
    single-skill plugin puts SKILL.md at its root with the plugin's own name.
    """
    keep = installed_paths()
    for version_dir in sorted(PLUGIN_CACHE.glob("*/*/*")):
        if not version_dir.is_dir():
            continue
        if keep is not None and version_dir.resolve() not in keep:
            continue
        label = version_dir.parent.name            # .../cache/<market>/<plugin>/<ver>
        skills_dir = version_dir / "skills"
        if skills_dir.is_dir():
            for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
                yield label, d.name, d / "SKILL.md"
        elif (version_dir / "SKILL.md").exists():
            yield label, label, version_dir / "SKILL.md"


for label, name, sk in plugin_skills():
    if not sk.exists() or sk.stat().st_size == 0:
        continue
    # One name from two plugins shadows itself, and which wins depends on load
    # order rather than on anything anyone chose.
    if name in origin and origin[name] != label:
        err(f"skill '{name}' is provided by BOTH the {origin[name]} and "
            f"{label} plugins — they will shadow each other. Keep one.")
        continue
    origin[name] = label
    tally[label] = tally.get(label, 0) + 1
    on_disk.add(name)
    head = sk.read_text(encoding="utf-8", errors="replace")[:2000]
    fm = re.match(r"^---\n(.*?)\n---\n", head, re.S)
    if not (fm and re.search(r"^\s*description\s*:", fm.group(1), re.M)):
        no_desc.add(name)

sec = re.search(r"## 5\..*?(?=\n## \d)", INDEX, re.S)
# §5 writes entries as **plugin:skill**, or **skill** for the ones with no prefix.
# Compare on the skill half so a plugin rename is not a false failure.
listed = ({m.split(":")[-1] for m in
           re.findall(r"\*\*([a-z0-9][a-z0-9:-]+)\*\*", sec.group(0))} if sec else set())

if not on_disk:
    warn("no plugins are installed, so index.md sec 5 cannot be checked. "
         "Run `python scripts/install_vault.py` to install them.")
elif not sec:
    warn("index.md has no '## 5.' skill map section — skill drift is unguarded.")
else:
    print(f"check_maps: {len(on_disk)} skill(s) from installed plugins "
          f"({', '.join(f'{n} in {t}' for t, n in sorted(tally.items()))}).")
    # Only the company's own plugins are required to be listed. Anthropic's ship and
    # change on their own schedule, and §5 names the few that matter here.
    ours = {n for n, t in origin.items() if t in COMPANY_PLUGINS}
    for name in sorted(ours - listed):
        err(f"skill '{name}' is provided by the {origin[name]} plugin but is NOT "
            f"in index.md sec 5 — add it.")
    for name in sorted(listed - on_disk):
        err(f"index.md sec 5 lists skill '{name}' but no installed plugin provides it.")
    for name in sorted(no_desc & ours):
        warn(f"skill '{name}' has no `description:` frontmatter — auto-invocation falls back "
             f"to the first paragraph. Add one.")

# ---- 2. Vault map (§9): every leaf folder's PATH is named in index.md -------
SKIP_DIRS = {".git", ".github", ".obsidian", ".claude", ".agents",
             ".confluence-private", "raw", "_local", "scripts", "assets"}


def leaf_folders(root: pathlib.Path):
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        if any(part in SKIP_DIRS or part.startswith(".") for part in d.parts):
            continue
        if any(child.is_dir() for child in d.iterdir()):
            continue          # not a leaf
        if not any(child.suffix == ".md" for child in d.iterdir()):
            continue          # holds no notes
        yield d


missing = 0
for wiki_root in (ROOT / "wiki", ROOT / "_ai"):
    if not wiki_root.is_dir():
        continue
    for leaf in leaf_folders(wiki_root):
        rel = leaf.as_posix()
        if rel not in INDEX:
            err(f"leaf folder '{rel}/' is absent from index.md §9 — the router cannot reach it.")
            missing += 1
            if missing > 20:
                err("... further missing leaves suppressed.")
                break
    if missing > 20:
        break

print(f"\ncheck_maps: {len(on_disk)} live skill(s) from {len(tally)} plugin(s); "
      f"{errors} error(s), {warnings} warning(s).")
sys.exit(1 if errors else 0)
