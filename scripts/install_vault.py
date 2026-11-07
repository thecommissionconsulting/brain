"""Install this vault on this machine: one command, everything a clone cannot carry.

A clone arrives with the rules, the notes and the scripts. It cannot arrive with
the four bindings that make them work, because each one lives outside the
repository:

  git guards        .git/hooks/ is never cloned, and core.hooksPath is per-clone
                    config, so a fresh clone can push to main until this runs
  plugins           every skill lives in a plugin now: superpowers,
                    token-weather-usage, flightdeck and next-steps, from two
                    marketplace repos cloned into ~/.claude/plugins/ by the
                    claude CLI and enabled in your GLOBAL settings. This vault
                    carries none
  the prompt gate   central, which shipped the answer-only UserPromptSubmit
                    hook, is retired. A copy of that hook left in your GLOBAL
                    settings by an older layout is removed
  old layout        a machine installed before the plugins carries leftovers
                    that shadow them: skill copies in ~/.claude/skills/ and
                    retired plugins such as engineering, central and humanizer.
                    Both are cleared
  auto-update       skills is set to update on startup, so a new plugin
                    version reaches this machine without a manual step
  plugin updates    each run also pulls skills when GitHub is ahead and
                    updates every installed plugin it has a newer version of
  hook runtimes     a hook that starts python, node or bun fails on every event
                    when that program is missing, and without python the vault's
                    PII gate does nothing. Reported, never fixed here:
                    installing it or removing the plugin is a person's call. uv,
                    PyYAML and tzdata are reported too, without failing --check

Each was a separate manual step in `_ai/setup.md`, each easy to skip, and
skipping any of them fails quietly: the skills are installed but never fire, or
the guards are absent and nothing says so until CI rejects a push. This runs all
of them, reports what it changed, and names what is left for a human.

    python scripts/install_vault.py --check     report state, change nothing
    python scripts/install_vault.py --dry-run   print the plan, change nothing
    python scripts/install_vault.py --yes       apply the plan, then run
                                                scripts/verify_install.py

Idempotent. On a machine that is already installed the plan is empty and --check
exits 0. Nothing here asks for a secret, sets your git identity, or starts the
~100 minute index build: those need a person, and the closing report names them.

`scripts/setup_vault.py` is the other half and the earlier one. It clones the
workspace, sets a git identity and installs Obsidian, which is what you need
BEFORE this folder exists. This is what you need once it does.

The global config directory is ~/.claude, or $VAULT_CLAUDE_HOME when that is set,
which is how the tests point it at a temporary directory instead of yours.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS_PATH = ".githooks"
GATE_MARKER = "prompt_gate.py"

BINDING_FILES = ("cli-bindings.md", "workspace-bindings.md")

# The plugins every company machine is expected to carry, as (plugin, marketplace,
# the source `marketplace add` clones from). None of this is committed here:
# a marketplace is a separate repo that the claude CLI clones
# into ~/.claude/plugins/marketplaces/, and enabling a plugin writes into your
# GLOBAL settings. A vault clone can carry neither, which is why this step exists.
#
# claude-plugins-official ships with Claude Code, so its `marketplace add` is
# usually a no-op; it is named anyway so a machine that removed it recovers.
#
# The skills marketplace is a folder beside this vault, not a GitHub repo:
# <workspace>/skills/skills-main next to <workspace>/vault/vault-main. Set
# $VAULT_SKILLS_DIR when yours lives somewhere else.
SKILLS_DIR = pathlib.Path(os.environ.get("VAULT_SKILLS_DIR")
                          or ROOT.parent.parent / "skills" / "skills-main")
SKILLS_SOURCE = str(SKILLS_DIR)

PLUGINS = (
    ("token-weather-usage", "skills", SKILLS_SOURCE),
    ("flightdeck", "skills", SKILLS_SOURCE),
    ("next-steps", "skills", SKILLS_SOURCE),
    ("superpowers", "claude-plugins-official", "anthropics/claude-plugins-official"),
)

# Plugins skills used to ship, mapped to what replaced them, or to None
# when nothing replaces them automatically. A machine installed before the change
# still has the old one, and it keeps loading.
#
# claude-mem was renamed session-memory, but session-memory is opt-in: it needs
# Node.js, auto-installs Bun, uv and Chroma, and sends transcripts to an LLM
# provider. So claude-mem is removed and its successor is only named, never
# installed. gsd-core left the marketplace with no replacement, and its hooks run
# node on every tool call. central and humanizer were dropped from the vault's
# plugin set on 2026-11-07 by the owner's decision, with no replacement.
RETIRED_PLUGINS = {
    "engineering@skills": None,
    "claude-mem@skills": None,
    "cache-handoff@skills": "token-weather-usage@skills",
    "gsd-core@skills": None,
    "central@skills": None,
    "humanizer@skills": None,
}

# What to tell a person about a retired plugin that has no automatic replacement.
RETIRED_NOTES = {
    "claude-mem@skills": "renamed session-memory; install it yourself if you "
                              "want it, after reading its section in the skills README",
}

# The programs a hook can need that Claude Code does not ship. A hook whose
# command starts one of these fails on every event when it is missing, with
# "node: command not found", and the session carries on with an error on screen.
#
# python is the one that matters most: this vault's own hooks, the PII gate among
# them, call `python` by that name. Without it they fail open, so the PII
# protection silently stops.
# A machine with only `python3`, or with the Microsoft Store's `python` alias that
# opens the Store instead of running anything, counts as missing.
HOOK_RUNTIMES = {"node": "node", "npx": "node", "bun": "bun", "bunx": "bun",
                 "python": "python"}


def winget_user(package):
    """A winget install for the current user only.

    Nothing the vault needs is installed as administrator. Without --scope user,
    winget picks the machine-wide installer where one exists (Node.js, Git), and
    that raises a UAC prompt. Every package named here has a per-user installer,
    so the person's own account is enough.
    """
    return ("winget install --id " + package + " -e --scope user --source winget "
            "--accept-package-agreements --accept-source-agreements")


# The claude CLI, installed for the current user. The desktop app does not put
# `claude` on PATH, and the plugin steps need it. Both installers write to the
# user's own ~/.local/bin and need no administrator.
CLAUDE_INSTALL = {
    "win32": "irm https://claude.ai/install.ps1 | iex",
    None: "curl -fsSL https://claude.ai/install.sh | bash",
}

RUNTIME_INSTALL = {
    "node": {"win32": winget_user("OpenJS.NodeJS.LTS"), "darwin": "brew install node"},
    "bun": {"win32": winget_user("Oven-sh.Bun"), "darwin": "brew install oven-sh/bun/bun"},
    "python": {"win32": winget_user("Python.Python.3.13"),
               "darwin": "mkdir -p ~/.local/bin && "
                         "ln -s \"$(command -v python3)\" ~/.local/bin/python"},
}
# Runtimes nothing can do without, so removing the plugin is never offered as the fix.
REQUIRED_RUNTIMES = ("python",)

# Tools that only some skills or reports need. Missing ones are reported and never
# fail --check: the hooks still run, and only the named skill or report breaks.
OPTIONAL_TOOLS = {
    "uv": ("markdown-converter and data-model-audit run it (uvx, uv run)",
           {"win32": winget_user("astral-sh.uv"), "darwin": "brew install uv"}),
    "PyYAML": ("check_frontmatter.py and the install report import yaml",
               {None: "python -m pip install --user pyyaml"}),
    "tzdata": ("timesheet-recall needs it for Pacific/Auckland, because Windows has no "
               "timezone database of its own", {None: "python -m pip install --user tzdata"}),
}
RUNTIME_CALL = re.compile(r"(?:^|[\s;&|(])(" + "|".join(HOOK_RUNTIMES) + r")(?=\s)")

# The marketplaces that should pull new plugin versions on startup without anyone
# running `marketplace update`. claude-plugins-official already does by default.
AUTO_UPDATE = ("skills",)

# Every skill the old layout copied out of .agents/skills/ into ~/.claude/skills/.
# Only these names are treated as ours: anything else in that directory is a
# person's own skill and is never touched.
LEGACY_SKILLS = (
    "answer-only", "cavecrew", "caveman", "caveman-commit", "caveman-compress",
    "caveman-discover", "caveman-evidence-review", "caveman-explore", "caveman-help",
    "caveman-learn", "caveman-manage", "caveman-optimize", "caveman-review",
    "caveman-setup", "caveman-stats", "humanizer", "investigate-first", "lean-build",
    "markdown-converter", "migration", "safe-refactor", "surgical-patch",
    "verify-and-stop",
)

# The fields the two binding files hold. Most of them the machine already knows,
# so asking a person to type them is asking them to transcribe. `detect()` reads
# what it can and leaves the rest blank; `--bindings key=value` fills a blank in.
FIELDS = ("workspace_root", "vault_clone", "rag", "client_workspaces",
          "git_name", "git_email", "gh_account", "snowflake", "dbt", "gws_config",
          "paymo_user_id")


def first_match(path, pattern):
    """The first capture of `pattern` in `path`, or "".

    Deliberately narrow. Three of the files read here (`connections.toml`,
    `dbt_cloud.yml`, `gh` `hosts.yml`) also hold passwords and tokens, so this
    returns one captured identifier and never the line, the section or the file.
    Nothing it returns is written anywhere but `_local/`, which is gitignored,
    and a value that looks like a secret is dropped by `safe()` below (R-30).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    found = re.search(pattern, text, re.M)
    return found.group(1).strip() if found else ""


def safe(value):
    """Drop anything that looks like a credential rather than an identifier."""
    value = (value or "").strip().strip('"\'')
    if len(value) > 80 or re.search(r"(?i)(secret|token|passw|bearer|api[_-]?key)", value):
        return ""
    return value


def detect():
    """What this machine can answer about itself, without asking anyone."""
    home = pathlib.Path.home()
    connections = home / ".snowflake" / "connections.toml"
    names = []
    try:
        names = re.findall(r"^\[(?:connections\.)?([^\]]+)\]",
                           connections.read_text(encoding="utf-8", errors="replace"), re.M)
    except OSError:
        pass
    rag = ROOT / "_local" / "rag.path"
    gws = os.environ.get("GWS_CONFIG_DIR") or str(home / ".gws")
    return {
        "workspace_root": str(ROOT.parent),
        "vault_clone": str(ROOT),
        "rag": rag.read_text(encoding="utf-8").strip() if rag.exists() else "",
        "client_workspaces": "",
        "git_name": run("git", "config", "--get", "user.name").stdout.strip(),
        "git_email": run("git", "config", "--get", "user.email").stdout.strip(),
        "gh_account": safe(first_match(home / ".config" / "gh" / "hosts.yml",
                                       r"^\s*user:\s*(\S+)")),
        "snowflake": ", ".join(safe(n) for n in names if safe(n)),
        "dbt": safe(first_match(home / ".dbt" / "dbt_cloud.yml", r"^\s*project-id:\s*(\S+)")),
        "gws_config": gws if pathlib.Path(gws).exists() else "",
        "paymo_user_id": "",
    }


def render(values):
    """The two binding files, as text. A blank cell is a question still open."""
    v = {k: values.get(k, "") or "" for k in FIELDS}
    cli = f"""# CLI bindings, this machine only

Gitignored (R-31). How this machine is wired, never the credentials themselves:
those stay in each tool's own config (R-30). Written by
`scripts/install_vault.py`; edit it freely, nothing reads it but you.

| Tool | Binding on this machine | Where the real credential lives |
|---|---|---|
| git identity | {v['git_name']} <{v['git_email']}> | not a credential |
| Snowflake | {v['snowflake']} | `~/.snowflake/connections.toml` |
| dbt Cloud | {v['dbt']} | `~/.dbt/dbt_cloud.yml` |
| GitHub `gh` | {v['gh_account']} | `~/.config/gh/hosts.yml` |
| Google Workspace `gws` | {v['gws_config']} | its own config |
| Paymo | {v['paymo_user_id']} | user environment variables `PAYMO_API_KEY`, `PAYMO_USER_ID` |
"""
    workspace = f"""# Workspace bindings, this machine only

Gitignored (R-31). Absolute machine paths belong here and nowhere else in the
vault. Written by `scripts/install_vault.py`.

| What | Path on this machine |
|---|---|
| workspace root | {v['workspace_root']} |
| this vault clone | {v['vault_clone']} |
| rag installer | {v['rag']} |
| client workspaces | {v['client_workspaces']} |
"""
    blank = [k for k in FIELDS if not v[k]]
    if blank:
        note = "\nStill blank: " + ", ".join(blank) + ". Fill them in here, or run\n" \
               "`python scripts/install_vault.py --bindings " + \
               " ".join(k + "=..." for k in blank) + "`.\n"
        cli += note
        workspace += note
    return {"cli-bindings.md": cli, "workspace-bindings.md": workspace}


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT))


def claude_home():
    override = os.environ.get("VAULT_CLAUDE_HOME")
    return pathlib.Path(override) if override else pathlib.Path.home() / ".claude"


def claude_cli():
    """The claude executable, or "" when it is not on PATH.

    The plugin step is the only one that needs it: git guards, skills, the gate
    and the bindings are all file and config work this script does itself. So a
    machine without the CLI reports that one step and installs the rest.
    """
    return shutil.which("claude") or ""


def claude_cli_fix():
    """How a person without `claude` on PATH gets it, as their own user."""
    if sys.platform == "win32":
        how = "in PowerShell, not as administrator: `" + CLAUDE_INSTALL["win32"] + "`"
    else:
        how = "`" + CLAUDE_INSTALL[None] + "`"
    return ("install the claude CLI for your user " + how +
            ", then open a new terminal (or restart Claude Code) and re-run this script")


def ls_remote():
    """(True, head commit) when the skills marketplace folder is there, else (False, why).

    The commit is "" when the folder is not a git repository, which is fine: the
    update step then compares plugin versions only.
    """
    if not (SKILLS_DIR / ".claude-plugin" / "marketplace.json").is_file():
        return False, "no marketplace at " + SKILLS_SOURCE
    if not (SKILLS_DIR / ".git").exists():
        return True, ""
    r = run("git", "-C", SKILLS_SOURCE, "rev-parse", "HEAD")
    return True, r.stdout.strip() if r.returncode == 0 else ""


def repo_access():
    """(True, "") when the skills marketplace folder is readable, else (False, why)."""
    ok, out = ls_remote()
    return (True, "") if ok else (False, out)


def remote_head():
    """The commit the skills folder is on, or "" when it is not a git repository."""
    ok, out = ls_remote()
    return out if ok else ""


def repo_access_fix():
    """How a person makes the skills marketplace folder findable."""
    return ("put the skills marketplace at " + SKILLS_SOURCE + ", or set "
            "VAULT_SKILLS_DIR to the folder that holds its .claude-plugin/marketplace.json")


def run_claude(*args):
    """Run the claude CLI against the same config directory the rest of this uses.

    The CLI reads CLAUDE_CONFIG_DIR, not VAULT_CLAUDE_HOME. Translating one into
    the other is what keeps a test, or a rehearsal against a temporary directory,
    from installing plugins into your real ~/.claude.
    """
    env = dict(os.environ)
    override = env.get("VAULT_CLAUDE_HOME")
    if override:
        env["CLAUDE_CONFIG_DIR"] = override
    # stdin closed and a ceiling on the wait, because this is the only step that
    # hands work to a program the vault does not own. A CLI that stops to ask
    # something would otherwise hang the whole install with no prompt on screen.
    try:
        return subprocess.run([claude_cli() or "claude"] + list(args),
                              capture_output=True, text=True, cwd=str(ROOT), env=env,
                              stdin=subprocess.DEVNULL, timeout=300)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timed out after 300s")


def settings_file():
    return claude_home() / "settings.json"


def read_settings(path):
    """The global settings, or an empty dict when absent. A malformed file raises:
    overwriting someone's whole Claude Code configuration because it failed to
    parse is worse than stopping and saying so."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def gate_registered(settings):
    for entry in settings.get("hooks", {}).get("UserPromptSubmit", []) or []:
        for hook in entry.get("hooks", []) or []:
            if GATE_MARKER in str(hook.get("command", "")):
                return True
    return False


def drop_gate_hooks(settings):
    """Remove the gate's UserPromptSubmit entry, leaving every other hook alone.

    The gate shipped with central, which is retired. A copy here from the old
    layout points at ~/.claude/skills/, which may not exist, so it fails or runs
    a gate the vault no longer maintains.
    """
    out = dict(settings)
    hooks = dict(out.get("hooks", {}))
    kept = []
    for entry in hooks.get("UserPromptSubmit", []) or []:
        inner = [h for h in (entry.get("hooks") or [])
                 if GATE_MARKER not in str(h.get("command", ""))]
        if inner:
            kept.append(dict(entry, hooks=inner))
    if kept:
        hooks["UserPromptSubmit"] = kept
    else:
        hooks.pop("UserPromptSubmit", None)
    if hooks:
        out["hooks"] = hooks
    else:
        out.pop("hooks", None)
    return out


def clear_hook_blocks(settings):
    """Turn off the global switch that would stop every hook this vault installs."""
    out = dict(settings)
    if out.get("disableAllHooks"):
        out["disableAllHooks"] = False
    return out


def conflicts(settings, hooks_path, skill_conflicts):
    """What an existing Claude Code setup on this machine already claims.

    A machine that has never run Claude Code installs cleanly. A machine that has
    is where this went wrong, because every one of these leaves the install
    looking successful while behaving as though it never ran: a personal skill
    under the same name as one of ours, `core.hooksPath` pointed at someone
    else's hooks, or `disableAllHooks` turned on in the global settings.

    `fix` says who decides. "override" is ours to take, because the vault owns
    that binding and a clone is useless without it. "report" is not: another
    person's unrelated hook keeps running and we say so rather than removing it.
    """
    found = []
    if settings.get("disableAllHooks"):
        found.append({
            "label": "hooks are switched off globally",
            "detail": "disableAllHooks is true in the global settings, so none of "
                      "the vault's hooks would run",
            "fix": "override"})
    for entry in settings.get("hooks", {}).get("UserPromptSubmit", []) or []:
        for hook in entry.get("hooks", []) or []:
            command = str(hook.get("command", ""))
            if command and GATE_MARKER not in command:
                found.append({
                    "label": "another UserPromptSubmit hook is registered",
                    "detail": command + " runs on every prompt alongside the vault's gate",
                    "fix": "report"})
    if hooks_path and hooks_path != HOOKS_PATH:
        found.append({
            "label": "core.hooksPath points elsewhere",
            "detail": hooks_path + " is configured, so the vault's guards in "
                      + HOOKS_PATH + " never run",
            "fix": "override"})
    if skill_conflicts:
        found.append({
            "label": "skills are still installed as files, not plugins",
            "detail": ", ".join(skill_conflicts) + " sit in ~/.claude/skills/ from the "
                      "layout that copied them out of this repo. Each one shadows the "
                      "plugin's copy of the same skill, and --force moves them to a "
                      "backup folder",
            "fix": "override"})
    return found


def conflict_report(found):
    """One line per conflict, saying who decides it."""
    lines = []
    for item in found:
        if item["fix"] == "override":
            lines.append(item["label"] + ": " + item["detail"] +
                         ". Re-run with --force to take it.")
        else:
            lines.append(item["label"] + ": " + item["detail"] +
                         ". Left alone; remove it yourself if it gets in the way.")
    return lines


def machine_conflicts():
    """What this machine's existing setup claims, read off the machine itself."""
    try:
        settings = read_settings(settings_file())
    except ValueError:
        settings = {}
    hooks_path = run("git", "config", "--get", "core.hooksPath").stdout.strip()
    return conflicts(settings, hooks_path, stale_skill_copies())


def write_bindings(local, values=None, force=False):
    """Write the gitignored binding files no clone can carry.

    Without `force` an existing file is left alone, because it may hold something
    a person typed that no detection can recover. With it, the old file is backed
    up beside itself first.
    """
    written = []
    local.mkdir(parents=True, exist_ok=True)
    bodies = render(values if values is not None else detect())
    for name in BINDING_FILES:
        path = local / name
        if path.exists():
            if not force:
                continue
            shutil.copy2(path, str(path) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        path.write_text(bodies[name], encoding="utf-8", newline="\n")
        written.append(path)
    return written


# ---- steps ------------------------------------------------------------------
# Each step answers two questions: is it done, and how is it done. Nothing runs
# until the plan built from every step has been printed.

def step_hooks():
    current = run("git", "config", "--get", "core.hooksPath").stdout.strip()
    return current == HOOKS_PATH, (
        "core.hooksPath = " + (current or "(unset)"),
        "enable the git guards in .githooks/ (refuses main, secrets, raw/)")


def apply_hooks():
    r = run(sys.executable, str(ROOT / "scripts" / "install_hooks.py"))
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def stale_skill_copies():
    """Skills left in ~/.claude/skills/ by the layout that copied them out of here.

    Every one is now provided by a plugin or was retired, so a copy under that
    directory is an older version shadowing the plugin's, and which one wins
    depends on the machine. Only the names in LEGACY_SKILLS count: a person's own
    skill in the same directory is theirs, and 'synced' is claude.ai's.
    """
    root = claude_home() / "skills"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and d.name in LEGACY_SKILLS and (d / "SKILL.md").exists())


def step_skills():
    stale = stale_skill_copies()
    return not stale, (", ".join(stale) + " in ~/.claude/skills/" if stale else "none left",
                       "move the old skill copies out of ~/.claude/skills/ (needs --force)")


def apply_skills(force=False):
    """Move the old copies into a dated folder beside ~/.claude/skills/.

    Moved, not deleted, so a person who edited one keeps their edit. The backup
    sits outside skills/ because anything inside it would still load.
    """
    stale = stale_skill_copies()
    if not stale:
        return True, "none left"
    if not force:
        return False, ("left in place: " + ", ".join(stale) +
                       ". Re-run with --force to move them to a backup folder.")
    backup = claude_home() / ("skills-backup-" + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True, exist_ok=True)
    for name in stale:
        shutil.move(str(claude_home() / "skills" / name), str(backup / name))
    return True, "moved " + ", ".join(stale) + " to " + str(backup)


def installed_plugin_ids(settings):
    """Every plugin id this machine knows about, enabled or not.

    `enabledPlugins` holds what the global settings turn on; installed_plugins.json
    holds what the CLI installed at any scope. A retired plugin can sit in either.
    """
    ids = set((settings.get("enabledPlugins") or {}).keys())
    try:
        record = json.loads((claude_home() / "plugins" / "installed_plugins.json")
                            .read_text(encoding="utf-8"))
        ids.update((record.get("plugins") or {}).keys())
    except (OSError, ValueError):
        pass
    return ids


def retired_plugins(settings):
    return sorted(p for p in RETIRED_PLUGINS if p in installed_plugin_ids(settings))


def step_retired():
    found = retired_plugins(plugin_settings())
    return not found, (", ".join(found) if found else "none installed",
                       "uninstall the retired plugins and install what replaced them, "
                       "where something does")


def apply_retired():
    if not claude_cli():
        return False, "the claude CLI is not on PATH; nothing uninstalled. " + claude_cli_fix()
    settings = plugin_settings()
    enabled = settings.get("enabledPlugins") or {}
    done, failed = [], []
    for old in retired_plugins(settings):
        # The replacement goes in first, so a failed install never leaves the
        # machine with neither.
        new = RETIRED_PLUGINS[old]
        if new and not enabled.get(new):
            r = run_claude("plugin", "install", new)
            if r.returncode != 0:
                failed.append(new + " (" + tail(r) + "); kept " + old)
                continue
            done.append("installed " + new)
        r = run_claude("plugin", "uninstall", old)
        note = " (" + RETIRED_NOTES[old] + ")" if old in RETIRED_NOTES else ""
        (done if r.returncode == 0 else failed).append(
            "removed " + old + note if r.returncode == 0 else old + " (" + tail(r) + ")")
    detail = ", ".join(done) or "nothing to do"
    if failed:
        detail += "; FAILED: " + ", ".join(failed)
    return not failed, detail


def plugin_gaps(settings):
    """The expected plugins this machine is missing, and whether the marketplace is too.

    Two halves go missing independently. The marketplace is a clone under
    ~/.claude/plugins/marketplaces/, which only `marketplace add` creates; the
    plugin is an entry in `enabledPlugins` in the global settings, which only
    `plugin install` writes. A machine can hold the first and not the second, so
    each is reported on its own and the apply step does only what is absent.
    """
    enabled = settings.get("enabledPlugins") or {}
    gaps = []
    for name, marketplace, source in PLUGINS:
        missing = not marketplace_location(marketplace).is_dir()
        if missing or not enabled.get(name + "@" + marketplace):
            gaps.append({"name": name, "marketplace": marketplace, "source": source,
                         "marketplace_missing": missing})
    return gaps


def marketplace_location(name):
    """Where a marketplace's files are: the CLI's clone, or, for one added from a
    folder, the folder itself. A folder marketplace is never cloned, so it is read
    from the CLI's own record of where it was added from."""
    clone = claude_home() / "plugins" / "marketplaces" / name
    if clone.is_dir():
        return clone
    try:
        known = json.loads((claude_home() / "plugins" / "known_marketplaces.json")
                           .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return clone
    where = (known.get(name) or {}).get("installLocation")
    return pathlib.Path(where) if where else clone


def plugin_settings():
    """The global settings for the plugin step, or {} when they cannot be read.

    A malformed file is the gate step's to report and refuse; here it only means
    nothing is known to be enabled, so every plugin reads as pending.
    """
    try:
        return read_settings(settings_file())
    except ValueError:
        return {}


def step_plugins():
    gaps = plugin_gaps(plugin_settings())
    if not gaps:
        # Reported before the CLI check on purpose: a machine that already holds
        # both plugins is installed whether or not `claude` is on today's PATH.
        return True, ("installed", "")
    names = ", ".join(g["name"] + "@" + g["marketplace"] for g in gaps)
    if not claude_cli():
        return False, ("the claude CLI is not on PATH",
                       "not install " + names + " until it is: " + claude_cli_fix())
    if any(g["marketplace"] == "skills" for g in gaps):
        ok, why = repo_access()
        if not ok:
            blocked = ", ".join(g["name"] + "@skills" for g in gaps
                                if g["marketplace"] == "skills")
            return False, ("the skills marketplace is not readable (" + why + ")",
                           "not install " + blocked + " until it can: " + repo_access_fix())
    return False, (names, "clone the marketplaces and install the plugins they carry")


def apply_plugins():
    if not claude_cli():
        return False, "the claude CLI is not on PATH; nothing installed. " + claude_cli_fix()
    done, failed = [], []
    # Each marketplace is added or updated once, and a failure skips every plugin
    # it carries rather than trying again for each one.
    ready, broken = set(), set()
    gaps = plugin_gaps(plugin_settings())
    if any(g["marketplace"] == "skills" for g in gaps):
        ok, why = repo_access()
        if not ok:
            # Checked once, before the CLI tries to clone, so the person sees the
            # login problem and its fix instead of a clone error per plugin.
            failed.append("the skills marketplace is not readable (" + why + "). " +
                          repo_access_fix())
            broken.add("skills")
    for gap in gaps:
        full = gap["name"] + "@" + gap["marketplace"]
        if gap["marketplace"] in broken:
            continue
        if gap["marketplace"] not in ready:
            if gap["marketplace_missing"]:
                r = run_claude("plugin", "marketplace", "add", gap["source"])
                what = gap["source"]
            else:
                # A clone left by an earlier install can predate the plugin.
                # `plugin install` tries to refresh it, but when that fails it
                # falls back to the old clone and reports the plugin as "not
                # found", which hides the real cause (usually no access to the
                # private repo). Updating first fails with that cause instead.
                r = run_claude("plugin", "marketplace", "update", gap["marketplace"])
                what = gap["marketplace"] + " update"
            if r.returncode != 0:
                failed.append(what + " (" + tail(r) + ")")
                broken.add(gap["marketplace"])
                continue
            ready.add(gap["marketplace"])
        r = run_claude("plugin", "install", full)
        (done if r.returncode == 0 else failed).append(
            full if r.returncode == 0 else full + " (" + tail(r) + ")")
    detail = ", ".join(done) or "nothing to install"
    if failed:
        detail += "; FAILED: " + ", ".join(failed)
    return not failed, detail


def tail(result):
    """The last thing a claude CLI run said, for a one-line failure report."""
    lines = [l.strip() for l in (result.stdout + result.stderr).splitlines() if l.strip()]
    return lines[-1][:120] if lines else "exit " + str(result.returncode)


def step_gate():
    """No prompt gate ships any more: central, which carried it, is retired.
    This step only clears what an older layout left behind.

    Two ways it can be wrong. A hook left in the global settings by the layout that
    copied the skill out of this repo still points at a gate nobody maintains, and
    `disableAllHooks` stops this vault's own hooks firing at all, which loses the
    PII check silently.
    """
    path = settings_file()
    try:
        settings = read_settings(path)
    except ValueError as err:
        return False, (str(path) + " is not valid JSON (" + str(err) + ")",
                       "REPORT IT, and change nothing")
    stale = gate_registered(settings)
    disabled = bool(settings.get("disableAllHooks"))
    if not stale and not disabled:
        return True, ("no stale gate hook, hooks are on", "nothing to do")
    state = "a stale gate hook is registered here" if stale else "hooks are switched off globally"
    return False, (str(path) + ": " + state,
                   "remove the stale hook and turn hooks back on")


def apply_gate():
    path = settings_file()
    try:
        settings = read_settings(path)
    except ValueError as err:
        return False, str(path) + " is not valid JSON (" + str(err) + "). Left untouched."
    if not gate_registered(settings) and not settings.get("disableAllHooks"):
        return True, "no stale gate hook; nothing to do"
    backup = ""
    if path.exists():
        backup = str(path) + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = drop_gate_hooks(clear_hook_blocks(settings))
    unblocked = merged.get("disableAllHooks") is False and settings.get("disableAllHooks")
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True, ("stale hook removed" + (", hooks un-disabled" if unblocked else "")
                  + (", backup at " + backup if backup else ""))


def auto_update_gaps(settings):
    """The marketplaces in AUTO_UPDATE whose settings entry does not turn it on.

    Third-party marketplaces are off by default, so without this a machine keeps
    the plugin versions it first installed until someone runs `marketplace update`.
    """
    known = settings.get("extraKnownMarketplaces") or {}
    return [m for m in AUTO_UPDATE if (known.get(m) or {}).get("autoUpdate") is not True]


def with_auto_update(settings):
    out = dict(settings)
    known = dict(out.get("extraKnownMarketplaces") or {})
    sources = {m: s for _, m, s in PLUGINS}
    for name in auto_update_gaps(settings):
        entry = dict(known.get(name) or {})
        entry.setdefault("source", {"source": "directory", "path": sources[name]})
        entry["autoUpdate"] = True
        known[name] = entry
    out["extraKnownMarketplaces"] = known
    return out


# ---- keeping installed plugins current ---------------------------------------
# Auto-update only runs when Claude Code starts, and only when it is switched on.
# "Update the vault" should leave the machine on the newest skills whatever
# that state is, so it pulls the marketplace clone when GitHub is ahead of it and
# updates every installed skills plugin the clone offers a newer version of.

def marketplace_dir():
    return marketplace_location("skills")


def local_head():
    """The commit the local skills clone is on, or "" when there is no clone."""
    d = marketplace_dir()
    if not (d / ".git").exists():
        return ""
    r = run("git", "-C", str(d), "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def offered_versions():
    """{plugin id: what the clone offers}: plugin.json's version for a plugin kept in
    the marketplace repo, or the pinned commit for one referenced from elsewhere."""
    try:
        listing = json.loads((marketplace_dir() / ".claude-plugin" / "marketplace.json")
                             .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    offered = {}
    for entry in listing.get("plugins") or []:
        plugin, source = entry.get("name", "") + "@skills", entry.get("source")
        if isinstance(source, str):
            try:
                manifest = json.loads((marketplace_dir() / source / ".claude-plugin" /
                                       "plugin.json").read_text(encoding="utf-8"))
                offered[plugin] = {"version": manifest.get("version", "")}
            except (OSError, ValueError):
                pass
        elif isinstance(source, dict) and source.get("sha"):
            offered[plugin] = {"sha": source["sha"]}
    return offered


def installed_versions():
    """{plugin id: {"version", "sha"}} for each skills plugin installed here."""
    try:
        record = json.loads((claude_home() / "plugins" / "installed_plugins.json")
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {}
    for plugin, entries in (record.get("plugins") or {}).items():
        if not plugin.endswith("@skills") or not entries:
            continue
        entry = next((e for e in entries if e.get("scope") == "user"), entries[0])
        found[plugin] = {"version": entry.get("version", ""),
                         "sha": entry.get("gitCommitSha", "")}
    return found


def outdated_plugins():
    """Installed skills plugins the local clone offers a different version of."""
    offered, installed = offered_versions(), installed_versions()
    outdated = []
    for plugin, have in sorted(installed.items()):
        want = offered.get(plugin)
        if not want:
            continue
        if "version" in want and want["version"] and want["version"] != have["version"]:
            outdated.append(plugin)
        elif "sha" in want and want["sha"] != have["sha"]:
            outdated.append(plugin)
    return outdated


def step_updates():
    local = local_head()
    if not local and not marketplace_dir().is_dir():
        return True, ("no skills clone yet; the plugins step adds it", "")
    remote = remote_head()
    behind = bool(remote) and bool(local) and remote != local
    outdated = outdated_plugins()
    if not behind and not outdated:
        return True, ("skills and its plugins are current", "")
    parts = (["the skills clone is behind GitHub"] if behind else []) + \
            (["newer versions of " + ", ".join(outdated)] if outdated else [])
    return False, ("; ".join(parts),
                   "pull skills and update every installed plugin it has a newer "
                   "version of")


def apply_updates():
    if not claude_cli():
        return False, "the claude CLI is not on PATH; nothing updated. " + claude_cli_fix()
    done, failed = [], []
    local, remote = local_head(), remote_head()
    if local and remote and remote != local:
        r = run_claude("plugin", "marketplace", "update", "skills")
        if r.returncode != 0:
            return False, "skills update failed (" + tail(r) + "). " + repo_access_fix()
        done.append("pulled skills")
    for plugin in outdated_plugins():
        r = run_claude("plugin", "update", plugin)
        (done if r.returncode == 0 else failed).append(
            "updated " + plugin if r.returncode == 0 else plugin + " (" + tail(r) + ")")
    detail = ", ".join(done) or "nothing to update"
    if failed:
        detail += "; FAILED: " + ", ".join(failed)
    return not failed, detail


def step_auto_update():
    path = settings_file()
    try:
        gaps = auto_update_gaps(read_settings(path))
    except ValueError as err:
        return False, (str(path) + " is not valid JSON (" + str(err) + ")",
                       "REPORT IT, and change nothing")
    return not gaps, ("off for " + ", ".join(gaps) if gaps else "on",
                      "turn on auto-update for " + ", ".join(gaps) + " in the global settings")


def apply_auto_update():
    path = settings_file()
    try:
        settings = read_settings(path)
    except ValueError as err:
        return False, str(path) + " is not valid JSON (" + str(err) + "). Left untouched."
    gaps = auto_update_gaps(settings)
    if not gaps:
        return True, "already on"
    backup = ""
    if path.exists():
        backup = str(path) + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(with_auto_update(settings), indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return True, ("on for " + ", ".join(gaps) + (", backup at " + backup if backup else ""))


def active_plugin_roots(settings):
    """Where each plugin that loads in this vault is installed, as {id: path}.

    A plugin loads here when the global settings or this vault's own
    .claude/settings.json enable it. installed_plugins.json says where its files are.
    """
    enabled = {k for k, v in (settings.get("enabledPlugins") or {}).items() if v}
    try:
        project = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        enabled |= {k for k, v in (project.get("enabledPlugins") or {}).items() if v}
    except (OSError, ValueError):
        pass
    try:
        record = json.loads((claude_home() / "plugins" / "installed_plugins.json")
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    roots = {}
    for plugin, entries in (record.get("plugins") or {}).items():
        if plugin not in enabled:
            continue
        for entry in entries or []:
            path = pathlib.Path(entry.get("installPath") or "")
            if str(path) and path.is_dir():
                roots[plugin] = path
                if entry.get("scope") == "user":
                    break
    return roots


def hook_runtimes(plugin_root):
    """The runtimes a plugin's hooks start, read from its hooks/hooks.json."""
    try:
        hooks = json.loads((plugin_root / "hooks" / "hooks.json")
                           .read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return set()
    return runtimes_in(hooks)


def vault_hook_runtimes():
    """The runtimes this vault's own hooks in .claude/settings.json start."""
    try:
        hooks = json.loads((ROOT / ".claude" / "settings.json")
                           .read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return set()
    return runtimes_in(hooks)


def runtimes_in(hooks):
    found = set()
    for entries in hooks.values():
        for entry in entries or []:
            for hook in entry.get("hooks") or []:
                for call in RUNTIME_CALL.findall(str(hook.get("command", ""))):
                    found.add(HOOK_RUNTIMES[call])
    return found


def probe(*args):
    """Run a short command and return the CompletedProcess, or None if it cannot start."""
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def hook_python():
    """The `python` hooks will run, or "" when that name does not run Python 3.

    Found on PATH is not enough. The Microsoft Store alias is on PATH and only
    prints a message, and on some machines `python` is still Python 2.
    """
    exe = shutil.which("python")
    if not exe:
        return ""
    r = probe(exe, "-c", "import sys; print(sys.version_info[0])")
    return exe if r is not None and r.returncode == 0 and r.stdout.strip() == "3" else ""


def runtime_available(runtime):
    return bool(hook_python()) if runtime == "python" else bool(shutil.which(runtime))


def missing_runtimes(settings):
    """{runtime: [who needs it]} for each runtime a loaded plugin's hooks, or this
    vault's own hooks, start and this machine cannot run."""
    needs = {}
    for plugin, root in sorted(active_plugin_roots(settings).items()):
        for runtime in hook_runtimes(root):
            needs.setdefault(runtime, []).append(plugin)
    for runtime in vault_hook_runtimes():
        needs.setdefault(runtime, []).append("this vault's hooks")
    return {r: sorted(who) for r, who in sorted(needs.items()) if not runtime_available(r)}


def runtime_fix(runtime, plugins):
    """One line a person can act on: install the runtime, or remove what needs it."""
    install = RUNTIME_INSTALL.get(runtime, {}).get(sys.platform)
    how = ("`" + install + "`") if install else ("install " + runtime + " from its website")
    if runtime in REQUIRED_RUNTIMES:
        fix = (runtime + " does not run Python 3 here, and " + ", ".join(plugins) +
               " call it on every event, so the PII and credential gates do nothing. "
               "Install it (" + how + ") and restart Claude Code")
        if sys.platform == "win32":
            fix += (". If `python` opens the Microsoft Store, turn off its App execution "
                    "alias in Settings > Apps > Advanced app settings")
        return fix
    removable = [p for p in plugins if "@" in p]
    return (runtime + " is not on PATH, and the hooks of " + ", ".join(plugins) +
            " run it on every event. Either " + how + " and restart Claude Code, or "
            "remove the plugin: " + "; ".join("`claude plugin uninstall " + p + "`"
                                              for p in removable))


def module_available(python, module):
    r = probe(python, "-c", "import " + module)
    return r is not None and r.returncode == 0


def optional_gaps():
    """[(tool, what needs it, how to install)] for the optional tools this machine lacks.

    Modules are checked in the `python` hooks and skills run, falling back to the
    interpreter running this script when that name does not work.
    """
    python = hook_python() or sys.executable
    missing = []
    if not shutil.which("uv"):
        missing.append("uv")
    if not module_available(python, "yaml"):
        missing.append("PyYAML")
    if sys.platform == "win32" and not module_available(python, "tzdata"):
        missing.append("tzdata")
    gaps = []
    for tool in missing:
        why, installs = OPTIONAL_TOOLS[tool]
        how = installs.get(sys.platform) or installs.get(None) or "install " + tool
        gaps.append((tool, why, how))
    return gaps


def optional_report(gaps):
    return [tool + " is missing: " + why + ". Install: `" + how + "`" for tool, why, how in gaps]


def step_runtimes():
    missing = missing_runtimes(plugin_settings())
    if not missing:
        return True, ("every hook can run", "")
    names = ", ".join(r + " (" + ", ".join(p) + ")" for r, p in missing.items())
    return False, ("missing " + names,
                   "not be fixed here; ask the person. " +
                   " | ".join(runtime_fix(r, p) for r, p in missing.items()))


def apply_runtimes():
    """Never applied: installing software or removing someone's plugin is their call."""
    missing = missing_runtimes(plugin_settings())
    if not missing:
        return True, "every hook can run"
    return False, " | ".join(runtime_fix(r, p) for r, p in missing.items())


def step_bindings():
    local = ROOT / "_local"
    missing = [n for n in BINDING_FILES if not (local / n).exists()]
    return not missing, ("missing: " + ", ".join(missing) if missing else "present",
                         "write the gitignored _local/ binding files from what this "
                         "machine already knows")


def apply_bindings():
    values = detect()
    written = write_bindings(ROOT / "_local", values)
    blank = [k for k in FIELDS if not values.get(k)]
    detail = ", ".join(p.name for p in written) or "nothing to write"
    return True, detail + ("; still blank: " + ", ".join(blank) if blank else "")


# Order matters: plugins before the retired ones are removed, so a replacement
# is already there when the plugin it replaces goes.
#
# There was a "deny rules" step that copied central's credential-file Read deny
# rules into the global settings. It left with central. Rules it already wrote
# stay in the global settings; nothing adds them on a new machine any more.
STEPS = (
    ("git guards", step_hooks, apply_hooks),
    ("plugins", step_plugins, apply_plugins),
    ("retired plugins", step_retired, apply_retired),
    ("plugin updates", step_updates, apply_updates),
    ("skill copies", step_skills, apply_skills),
    ("auto-update", step_auto_update, apply_auto_update),
    ("prompt gate", step_gate, apply_gate),
    ("hook runtimes", step_runtimes, apply_runtimes),
)
# Not a step for now: ("local bindings", step_bindings, apply_bindings). The binding
# files, Obsidian and the vector index are being set up by hand as they are added, so
# nothing here writes, checks or asks for them. `--bindings` still writes the files.

# The steps that take something already on the machine, and so only do it with --force.
FORCED = ("skill copies",)

# The steps after which Claude Code must restart to load what changed.
NEEDS_RESTART = ("plugins", "retired plugins", "plugin updates", "skill copies",
                 "auto-update",
                 "prompt gate")


def manual():
    """What a script must not decide. Reported, never applied."""
    name = run("git", "config", "--get", "user.name").stdout.strip()
    email = run("git", "config", "--get", "user.email").stdout.strip()
    left = []
    if name and email:
        left.append("git identity: " + name + " <" + email + ">")
    else:
        left.append("git identity is unset: git config --global user.name / user.email")
    for line in optional_report(optional_gaps()):
        left.append(line)
    left.append("credentials go in each tool's own config, never in this repo (R-30)")
    return left


def plan():
    rows = []
    for label, state, apply_step in STEPS:
        done, (detail, what) = state()
        rows.append((label, done, detail, what, apply_step))
    return rows


def report(rows):
    for label, done, detail, what, _ in rows:
        print("  " + ("ok     " if done else "PENDING") + "  " + label.ljust(16) + detail)
        if not done:
            print(" " * 27 + "will " + what)


def main(argv):
    ap = argparse.ArgumentParser(description="Install this vault on this machine.")
    ap.add_argument("--check", action="store_true", help="report state, change nothing")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--yes", action="store_true", help="apply without the confirmation prompt")
    ap.add_argument("--detect", action="store_true",
                    help="print what this machine knows about itself, as JSON, and stop")
    ap.add_argument("--bindings", nargs="*", metavar="KEY=VALUE",
                    help="rewrite the _local/ binding files, filling these fields in")
    ap.add_argument("--force", action="store_true",
                    help="take the conflicts this vault owns: move old skill copies out "
                         "of ~/.claude/skills/, repoint core.hooksPath, turn hooks back on")
    args = ap.parse_args(argv)

    if args.detect:
        print(json.dumps(detect(), indent=2, sort_keys=True))
        return 0

    if args.bindings is not None:
        values = detect()
        for pair in args.bindings:
            key, _, value = pair.partition("=")
            if key not in FIELDS:
                print("unknown field: " + key + ". Known: " + ", ".join(FIELDS))
                return 2
            values[key] = value.strip()
        written = write_bindings(ROOT / "_local", values, force=True)
        for path in written:
            print("wrote " + str(path))
        blank = [k for k in FIELDS if not values.get(k)]
        print("still blank: " + ", ".join(blank) if blank else "every field filled.")
        return 0

    rows = plan()
    print("vault install:")
    report(rows)
    pending = [r for r in rows if not r[1]]

    clashes = machine_conflicts()
    if clashes:
        print("\nexisting setup on this machine:")
        for line in conflict_report(clashes):
            print("  " + line)

    gaps = optional_gaps()
    if gaps:
        print("\noptional tools missing (some skills or reports need them):")
        for line in optional_report(gaps):
            print("  " + line)

    takeable = [c for c in clashes if c["fix"] == "override"]
    if args.check:
        print("\n" + (str(len(pending)) + " step(s) pending." if pending else "fully installed.")
              + (" " + str(len(takeable)) + " conflict(s) need --force." if takeable else ""))
        return 1 if (pending or takeable) else 0
    if args.dry_run:
        return 0
    if takeable and not args.force:
        print("\nThose conflicts are the vault's to take, and taking them replaces what is\n"
              "there. Nothing is applied to them without --force. Every file it replaces is\n"
              "backed up beside itself first.")

    if not pending:
        print("\nnothing to do.")
    else:
        if not args.yes:
            answer = input("\napply " + str(len(pending)) + " step(s)? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("nothing applied.")
                return 1
        print()
        restart = False
        for label, _, _, _, apply_step in pending:
            ok, detail = apply_step(args.force) if label in FORCED else apply_step()
            head = detail.splitlines()[0] if detail else ""
            print("  " + ("done" if ok else "FAILED") + "  " + label + ": " + head)
            restart = restart or (ok and label in NEEDS_RESTART)
        if restart:
            print("\nRestart Claude Code. Plugins, hooks and settings changed above load "
                  "only in a new session.")

    print("\ngates:")
    gate = run(sys.executable, str(ROOT / "scripts" / "session_gate.py"))
    for line in (gate.stdout + gate.stderr).strip().splitlines():
        print("  " + line)

    print("\nstill needs you:")
    for line in manual():
        print("  - " + line)

    # The acceptance cases in _ai/vault-install-test-plan.md, run against what was
    # just applied, so the person leaves with a report rather than a claim.
    print()
    sys.stdout.flush()
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_install.py")],
                          cwd=str(ROOT)).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
