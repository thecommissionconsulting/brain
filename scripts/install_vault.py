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

The wiki (the knowledge base, its own repo) is wired by the same command when it
is found: `--wiki PATH` names it, otherwise scripts/wiki_root.py finds it. Its five
steps write per-machine, gitignored files only. `--wiki-only` runs just those, and
never a global step.

Idempotent. On a machine that is already installed the plan is empty and --check
exits 0. Nothing here asks for a secret or sets your git identity: those need a person, and
the closing report names them.

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

# wiki_root sits beside this file. Put the folder on the path before importing it,
# so this works however the script was started.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

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
# The skills marketplace lives in this vault, under `marketplace/`, so a clone
# carries it. Set $VAULT_SKILLS_DIR when yours lives somewhere else.
SKILLS_DIR = pathlib.Path(os.environ.get("VAULT_SKILLS_DIR")
                          or ROOT / "marketplace")
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
FIELDS = ("workspace_root", "vault_clone", "client_workspaces",
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
    gws = os.environ.get("GWS_CONFIG_DIR") or str(home / ".gws")
    return {
        "workspace_root": str(ROOT.parent),
        "vault_clone": str(ROOT),
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


JEV_ROUTE = "jev_route.py"
JEV_MODES = ("off", "meta")


def jev_policy_path():
    return ROOT / "_local" / "jev-policy.json"


def jev_policy_mode(path):
    """'missing', 'malformed', or the mode the file holds ("off" or "meta")."""
    if not path.exists():
        return "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "malformed"
    if not isinstance(data, dict) or data.get("mode") not in JEV_MODES:
        return "malformed"
    return data["mode"]


def jev_policy_line():
    return "jev policy: " + jev_policy_mode(jev_policy_path())


def jev_key_line(env=None):
    """Whether the key is set. The value is never read out, printed or stored."""
    env = os.environ if env is None else env
    set_ = bool((env.get("TYPESAFE_API_KEY") or "").strip())
    return "TYPESAFE_API_KEY set: " + ("yes" if set_ else "no")


def step_jev_policy(mode=None):
    """The egress policy file. With no flag: a missing file is pending, an existing one is left alone.
    With a flag: the file must hold that mode."""
    path = jev_policy_path()
    state = jev_policy_mode(path)
    if state == "malformed":
        return False, (str(path) + " is not valid JSON or holds no known mode",
                       "REPORT IT, and change nothing")
    if mode is None:
        if state == "missing":
            return False, ("missing", "create it with mode off")
        return True, ("mode " + state + ", left alone", "nothing to do")
    if state == mode:
        return True, ("mode " + mode, "nothing to do")
    return False, ("mode " + state, "set the mode to " + mode)


def apply_jev_policy(mode=None):
    done, (detail, _) = step_jev_policy(mode)
    if done:
        return True, "nothing to do"
    if detail.startswith(str(jev_policy_path())):
        return False, detail + ". Left untouched."
    path = jev_policy_path()
    data = {"mode": mode or "off"}
    backup = write_json(path, data)
    return True, "mode " + data["mode"] + (", backup at " + backup if backup else "")


def jev_rows(mode):
    """Report row for the policy file, shaped like plan() rows."""
    done, (detail, what) = step_jev_policy(mode)
    return [("jev policy", done, detail, what, lambda m=mode: apply_jev_policy(m))]


def conflicts(settings, hooks_path, skill_conflicts, project=None):
    """What an existing Claude Code setup on this machine already claims.

    A machine that has never run Claude Code installs cleanly. A machine that has
    is where this went wrong, because every one of these leaves the install
    looking successful while behaving as though it never ran: a personal skill
    under the same name as one of ours, `core.hooksPath` pointed at someone
    else's hooks, or `disableAllHooks` turned on in the global settings.

    `fix` says who decides. "override" is ours to take, because the vault owns
    that binding and a clone is useless without it. "report" is not: another
    person's unrelated hook keeps running and we say so rather than removing it.

    `project` is the brain's own .claude/settings.json. A Jev prompt hook in the
    global settings covers every project, the brain included, so a copy in both
    places, or two in one file, runs twice on every prompt. That is reported.
    """
    found = []
    if settings.get("disableAllHooks"):
        found.append({
            "label": "hooks are switched off globally",
            "detail": "disableAllHooks is true in the global settings, so none of "
                      "the vault's hooks would run",
            "fix": "override"})
    jev = []
    for source in (settings, project or {}):
        for entry in source.get("hooks", {}).get("UserPromptSubmit", []) or []:
            for hook in entry.get("hooks", []) or []:
                if JEV_ROUTE in str(hook.get("command", "")):
                    jev.append(str(hook.get("command", "")))
    for entry in settings.get("hooks", {}).get("UserPromptSubmit", []) or []:
        for hook in entry.get("hooks", []) or []:
            command = str(hook.get("command", ""))
            if command and GATE_MARKER not in command and JEV_ROUTE not in command:
                found.append({
                    "label": "another UserPromptSubmit hook is registered",
                    "detail": command + " runs on every prompt alongside the vault's gate",
                    "fix": "report"})
    if len(jev) > 1:
        found.append({
            "label": "a second Jev prompt hook is registered",
            "detail": str(len(jev)) + " copies of " + JEV_ROUTE + " run on every prompt; "
                      "keep one, in ~/.claude/settings.json",
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
    try:
        project = read_settings(ROOT / ".claude" / "settings.json")
    except ValueError:
        project = {}
    return conflicts(settings, hooks_path, stale_skill_copies(), project)


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


# ---- the wiki ---------------------------------------------------------------
# The knowledge base is its own repo, cloned beside this one. The wiki steps wire
# that clone to this brain with per-machine files only, all gitignored or outside
# both repos: the pointer in _local/brain.json, _local/brain.md in the wiki, the
# wiki's and the brain's .claude/settings.local.json, and git config in the wiki
# clone. A fresh clone of either repo is therefore still plug and play.
#
# Each wiki step takes the wiki folder. Each state reads only; each apply is
# idempotent, so a second run finds nothing to do.

WIKI_HOOK_NAMES = ("pre-commit", "commit-msg", "pre-push")

# An entry is ours when its command runs one of these scripts. Ours are replaced;
# anything else in the same file, including a hook the owner added by hand, is kept.
OUR_SCRIPTS = ("session_gate.py", "pii_gate.py", "review_output.py", "wiki_edit_gate.py")
PII_MATCHER = "Read|Grep|Glob|Bash|Write|Edit|MultiEdit|NotebookEdit"
EDIT_MATCHER = "Write|Edit|MultiEdit"
ABSOLUTE_READ = re.compile(r"Read\(//.+\)")
DENY_READ = re.compile(r"Read\(\./(.+)\)")


def brain_config():
    return ROOT / "_local" / "brain.json"


def find_wiki(explicit=None):
    """The wiki folder to wire, or None. An explicit path is used as given and must hold index.md."""
    if explicit:
        path = pathlib.Path(explicit).expanduser().resolve()
        return path if (path / "index.md").is_file() else None
    return wiki_root.wiki_root(config=brain_config())


def load_json(path):
    """A JSON object from path, or {} when it is absent. A malformed file raises ValueError."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    data = json.loads(text) if text else {}
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def write_json(path, data):
    """Write a JSON file, backing up the one it replaces. Returns the backup path or ""."""
    backup = ""
    if path.exists():
        backup = str(path) + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return backup


def brain_import_line(brain, home=None):
    """The @ line the wiki's _local/brain.md holds, and a warning when the path is risky.

    Under home the line is `@~/<brain>/CLAUDE.md`, which holds a space. Outside home it
    is an absolute forward-slash path, and a space in that path is warned about.
    """
    home = pathlib.Path(home) if home else pathlib.Path.home()
    home = home.resolve()
    target = (pathlib.Path(brain) / "CLAUDE.md").resolve()
    try:
        return "@~/" + target.relative_to(home).as_posix(), ""
    except ValueError:
        line = "@" + target.as_posix()
        warn = ("the brain is outside your home folder, so the wiki imports it by absolute "
                "path, and Claude Code may not follow a path with a space in it") if " " in line else ""
        return line, warn


def wiki_hook_entries(brain, wiki):
    """The hook groups this brain owns in the wiki's settings.local.json, by event.

    Each event maps to a list of groups. Written as plain strings with forward slashes,
    quoted, so a path with spaces such as `C:/Users/Daru Broodryk/wiki` stays valid JSON
    and valid shell.
    """
    return {
        "SessionStart": [{"hooks": [{"type": "command",
                                     "command": f'python "{brain}/scripts/session_gate.py"'}]}],
        "PreToolUse": [
            {"matcher": PII_MATCHER,
             "hooks": [{"type": "command",
                        "command": f'python "{brain}/scripts/pii_gate.py"'}]},
            {"matcher": EDIT_MATCHER,
             "hooks": [{"type": "command", "timeout": 5,
                        "command": f'python "{brain}/scripts/wiki_edit_gate.py"'}]},
        ],
        "Stop": [{"hooks": [{"type": "command",
                             "command": f'python "{brain}/scripts/review_output.py" '
                                        f'--root "{wiki}" --gate'}]}],
    }


def is_ours(hook):
    return any(name in str(hook.get("command", "")) for name in OUR_SCRIPTS)


def merge_hooks(settings, wanted):
    """Replace this brain's hook groups in place and keep every other group.

    `wanted` maps each event to a list of groups. In each event, the first group that
    holds one of ours takes the place of the whole wanted list; the other groups of ours
    go. A group that also holds someone else's hook keeps that hook, in its place. So a
    second run writes the same file, and a hand-added group keeps its position.
    """
    out = dict(settings)
    hooks = dict(out.get("hooks") or {})
    for event, groups in wanted.items():
        merged, placed = [], False
        for existing in hooks.get(event) or []:
            inner = existing.get("hooks") or []
            if any(is_ours(h) for h in inner) and not placed:
                merged.extend(groups)
                placed = True
            rest = [h for h in inner if not is_ours(h)]
            if rest:
                merged.append(dict(existing, hooks=rest))
        if not placed:
            merged.extend(groups)
        hooks[event] = merged
    out["hooks"] = hooks
    return out


def add_unique(settings, section, key, items):
    """Add items to settings[section][key], keeping order and dropping duplicates."""
    if not items:
        return dict(settings)
    out = dict(settings)
    block = dict(out.get(section) or {})
    current = list(dict.fromkeys(block.get(key) or []))
    for item in items:
        if item not in current:
            current.append(item)
    block[key] = current
    out[section] = block
    return out


def absolute_read(wiki, rest):
    """A `Read` rule for one path under the wiki, written as an absolute path.

    Claude Code reads `//` as the filesystem root, so a POSIX path gets one more slash.
    On Windows it matches paths in POSIX form, `C:/x` as `/c/x`, so a drive-letter path
    becomes `//c/x`.
    """
    drive = re.match(r"^([A-Za-z]):/(.*)$", wiki)
    if drive:
        prefix = "//" + drive.group(1).lower() + "/" + drive.group(2)
    else:
        prefix = "/" + wiki if wiki.startswith("/") else "//" + wiki
    return f"Read({prefix}/{rest})"


def deny_tails(wiki):
    """The tails of the wiki's committed `Read(./x)` deny rules, e.g. `raw/**`."""
    settings = load_json(wiki / ".claude" / "settings.json")
    rules = (settings.get("permissions") or {}).get("deny") or []
    return [m.group(1) for m in (DENY_READ.fullmatch(r) for r in rules
                                 if isinstance(r, str)) if m]


def wiki_deny_rules(wiki):
    """The wiki's committed `Read(./x)` deny rules, rewritten as absolute rules."""
    return [absolute_read(wiki.as_posix(), tail) for tail in deny_tails(wiki)]


def configured_wiki():
    try:
        return str(json.loads(brain_config().read_text(encoding="utf-8")).get("wiki") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def wiki_snapshot(wiki):
    """What the wiki steps rewrite, read before any of them runs.

    The brain's pointer and the wiki's git `brain.root` are the old paths the installer
    wrote; once a step rewrites them the old values are gone, so every step gets this
    snapshot from wiki_rows, read once before the first apply.
    """
    r = git_in(wiki, "config", "--get", "brain.root")
    return {"brain_root": r.stdout.strip() if r.returncode == 0 else "",
            "wiki": configured_wiki()}


def permission_list(settings, key):
    block = settings.get("permissions")
    value = block.get(key) if isinstance(block, dict) else None
    return value if isinstance(value, list) else []


def stale_dirs(entries, keep, marker, old):
    """Extra directories the installer wrote for an older brain or wiki, to be removed.

    An entry that exists, is not `keep`, and holds `marker` is an old copy. A missing
    entry equal to `old` (the value the installer wrote before) is an old copy too. Any
    other entry stays, including a folder the owner added by hand.
    """
    out = []
    for entry in entries:
        if not isinstance(entry, str) or entry == keep:
            continue
        path = pathlib.Path(entry)
        if path.is_dir():
            if (path / marker).is_file():
                out.append(entry)
        elif old and entry == old:
            out.append(entry)
    return out


def stale_deny(rules, wiki, tails):
    """Absolute `Read(//...)` rules the wiki wrote before, to be removed.

    A rule is stale when its tail is one of the wiki's deny tails and it is not the rule
    absolute_read writes for the wiki now. The drive form `//c/...` is matched like any
    other head, because only the tail decides it.
    """
    current = {absolute_read(wiki.as_posix(), t) for t in tails}
    out = []
    for rule in rules:
        if not isinstance(rule, str) or not ABSOLUTE_READ.fullmatch(rule) or rule in current:
            continue
        if any(rule.endswith("/" + t + ")") for t in tails):
            out.append(rule)
    return out


def drop_items(settings, section, key, items):
    """Remove the listed items from settings[section][key]. A missing list is left alone."""
    block = settings.get(section)
    if not items or not isinstance(block, dict) or not isinstance(block.get(key), list):
        return dict(settings)
    kept = [x for x in block[key] if x not in items]
    if len(kept) == len(block[key]):
        return dict(settings)
    out = dict(settings)
    nblock = dict(block)
    nblock[key] = kept
    out[section] = nblock
    return out


def wiki_local(wiki):
    return wiki / ".claude" / "settings.local.json"


def brain_local():
    return ROOT / ".claude" / "settings.local.json"


def wiki_local_merged(wiki, existing, old):
    """The wiki's settings.local.json with our hooks, this brain's directory, and no stale copy."""
    out = merge_hooks(existing, wiki_hook_entries(ROOT.as_posix(), wiki.as_posix()))
    stale = stale_dirs(permission_list(existing, "additionalDirectories"),
                       ROOT.as_posix(), "scripts/wiki_root.py", old["brain_root"])
    out = drop_items(out, "permissions", "additionalDirectories", stale)
    return add_unique(out, "permissions", "additionalDirectories", [ROOT.as_posix()])


def brain_local_merged(wiki, existing, old):
    """The brain's settings.local.json: the wiki as a directory, its deny rules, no stale copy."""
    stale_dir = stale_dirs(permission_list(existing, "additionalDirectories"),
                           wiki.as_posix(), "_local/brain.md", old["wiki"])
    stale_rule = stale_deny(permission_list(existing, "deny"), wiki, deny_tails(wiki))
    out = drop_items(existing, "permissions", "additionalDirectories", stale_dir)
    out = drop_items(out, "permissions", "deny", stale_rule)
    out = add_unique(out, "permissions", "additionalDirectories", [wiki.as_posix()])
    return add_unique(out, "permissions", "deny", wiki_deny_rules(wiki))


def step_wiki_pointer(wiki, old):
    have = configured_wiki()
    return have == wiki.as_posix(), (
        "points at " + (have or "(unset)"),
        "write " + str(brain_config()) + " so this brain finds the wiki")


def apply_wiki_pointer(wiki, old):
    wiki_root.write_config(wiki, config=brain_config())
    return True, "wiki = " + wiki.as_posix()


def step_wiki_import(wiki, old):
    line, warn = brain_import_line(ROOT)
    path = wiki / "_local" / "brain.md"
    have = path.read_text(encoding="utf-8") if path.is_file() else ""
    done = have == line + "\n"
    return done, (
        "_local/brain.md imports this brain" if done else "_local/brain.md is missing or stale",
        "write _local/brain.md as " + line + (". WARNING: " + warn if warn else ""))


def apply_wiki_import(wiki, old):
    line, warn = brain_import_line(ROOT)
    path = wiki / "_local" / "brain.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(line + "\n", encoding="utf-8", newline="\n")
    return True, line + (". WARNING: " + warn if warn else "")


def step_wiki_hooks(wiki, old):
    path = wiki_local(wiki)
    try:
        existing = load_json(path)
    except ValueError as err:
        return False, (str(path) + " is not valid JSON (" + str(err) + ")",
                       "REPORT IT, and change nothing")
    done = wiki_local_merged(wiki, existing, old) == existing
    return done, (
        "session, PII, edit and review gates wired, no stale path" if done
        else "gates missing or stale",
        "write the four gate hooks, this brain's extra directory, and remove stale paths in "
        + str(path))


def apply_wiki_hooks(wiki, old):
    path = wiki_local(wiki)
    try:
        existing = load_json(path)
    except ValueError as err:
        return False, str(path) + " is not valid JSON (" + str(err) + "). Left untouched."
    merged = wiki_local_merged(wiki, existing, old)
    if merged == existing:
        return True, "already wired"
    backup = write_json(path, merged)
    return True, "wired" + (", backup at " + backup if backup else "")


def step_brain_for_wiki(wiki, old):
    path = brain_local()
    try:
        existing = load_json(path)
        done = brain_local_merged(wiki, existing, old) == existing
    except ValueError as err:
        return False, (str(path) + " or the wiki's settings is not valid JSON (" + str(err) + ")",
                       "REPORT IT, and change nothing")
    return done, (
        "brain allows the wiki, denies its files by absolute path, no stale path" if done
        else "brain is missing the wiki's directory or deny rules, or has a stale path",
        "write the wiki as an extra directory and its Read rules as absolute deny rules, "
        "and remove stale paths, in " + str(path))


def apply_brain_for_wiki(wiki, old):
    path = brain_local()
    try:
        existing = load_json(path)
        merged = brain_local_merged(wiki, existing, old)
    except ValueError as err:
        return False, str(path) + " or the wiki's settings is not valid JSON (" + str(err) + \
            "). Left untouched."
    if merged == existing:
        return True, "already wired"
    backup = write_json(path, merged)
    return True, "wired" + (", backup at " + backup if backup else "")


def git_in(wiki, *args):
    return subprocess.run(["git", "-C", str(wiki)] + list(args),
                          capture_output=True, text=True)


def git_problems(wiki):
    """What is still missing in the wiki clone, as words. Empty when all of it is done."""
    if git_in(wiki, "rev-parse", "--git-dir").returncode != 0:
        return ["not a git clone"]
    problems = []
    if git_in(wiki, "config", "--get", "brain.root").stdout.strip() != ROOT.as_posix():
        problems.append("brain.root")
    if git_in(wiki, "config", "--get", "core.hooksPath").stdout.strip() != HOOKS_PATH:
        problems.append("core.hooksPath")
    for name in WIKI_HOOK_NAMES:
        rel = HOOKS_PATH + "/" + name
        if not git_in(wiki, "ls-files", "-s", "--", rel).stdout.startswith("100755"):
            problems.append(rel + " not executable in git")
        if os.name != "nt" and not os.access(wiki / HOOKS_PATH / name, os.X_OK):
            problems.append(rel + " not executable on disk")
    return problems


def step_wiki_git(wiki, old):
    problems = git_problems(wiki)
    return not problems, (
        "in order" if not problems else "missing: " + ", ".join(problems),
        "set brain.root and core.hooksPath, mark the hooks executable in git and on disk")


def apply_wiki_git(wiki, old):
    if git_in(wiki, "rev-parse", "--git-dir").returncode != 0:
        return False, str(wiki) + " is not a git clone; clone DataWithDaru/wiki there first"
    failed = []
    for key, value in (("brain.root", ROOT.as_posix()), ("core.hooksPath", HOOKS_PATH)):
        if git_in(wiki, "config", key, value).returncode != 0:
            failed.append("git config " + key)
    for name in WIKI_HOOK_NAMES:
        path = wiki / HOOKS_PATH / name
        if not path.is_file():
            failed.append(name + " is missing")
            continue
        r = git_in(wiki, "update-index", "--chmod=+x", "--", HOOKS_PATH + "/" + name)
        if r.returncode != 0:
            failed.append(name + " (" + tail(r) + ")")
        if os.name != "nt":
            path.chmod(path.stat().st_mode | 0o111)
    return not failed, ("hooks wired and executable" if not failed
                        else "FAILED: " + ", ".join(failed))


# Each step: (label, state(wiki), apply(wiki)). The label is shown in the report.
WIKI_STEPS = (
    ("wiki pointer", step_wiki_pointer, apply_wiki_pointer),
    ("wiki import", step_wiki_import, apply_wiki_import),
    ("wiki hooks", step_wiki_hooks, apply_wiki_hooks),
    ("brain for wiki", step_brain_for_wiki, apply_brain_for_wiki),
    ("wiki git", step_wiki_git, apply_wiki_git),
)


def wiki_rows(wiki):
    """Report rows for the wiki steps, shaped like plan() so report() and apply can use them.

    The old paths are read once here, before any step applies, so a step that rewrites
    the pointer or git's brain.root cannot hide the path it replaced from a later step.
    """
    old = wiki_snapshot(wiki)
    rows = []
    for label, state, apply_step in WIKI_STEPS:
        done, (detail, what) = state(wiki, old)
        rows.append((label, done, detail, what, lambda w=wiki, o=old, f=apply_step: f(w, o)))
    return rows


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
# files and Obsidian are being set up by hand as they are added, so
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
    ap.add_argument("--wiki", metavar="PATH",
                    help="the wiki clone to wire to this brain (default: the one wiki_root finds)")
    ap.add_argument("--wiki-only", action="store_true",
                    help="run only the wiki steps, never a global one")
    ap.add_argument("--jev-mode", choices=JEV_MODES, metavar="off|meta",
                    help="set the Jev egress policy in _local/jev-policy.json. Without it, a "
                         "missing file is created as off and an existing one is left alone")
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

    wiki = find_wiki(args.wiki)
    if args.wiki and wiki is None:
        print("not a wiki folder: " + args.wiki + " (it holds no index.md)")
        return 2
    if args.wiki_only and wiki is None:
        print("wiki: not configured. Pass --wiki PATH, the wiki clone that holds index.md.")
        return 2
    print("wiki: " + (str(wiki) if wiki else "not configured"))

    if args.wiki_only:
        rows = wiki_rows(wiki)
        print("wiki install:")
    else:
        rows = plan() + jev_rows(args.jev_mode) + (wiki_rows(wiki) if wiki else [])
        print("vault install:")
    report(rows)
    if not args.wiki_only:
        print(jev_policy_line())
        if args.check:
            print(jev_key_line())
    pending = [r for r in rows if not r[1]]

    clashes = [] if args.wiki_only else machine_conflicts()
    if clashes:
        print("\nexisting setup on this machine:")
        for line in conflict_report(clashes):
            print("  " + line)

    gaps = [] if args.wiki_only else optional_gaps()
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

    all_ok = True
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
            all_ok = all_ok and ok
            restart = restart or (ok and label in NEEDS_RESTART)
        if restart:
            print("\nRestart Claude Code. Plugins, hooks and settings changed above load "
                  "only in a new session.")

    if args.wiki_only:
        return 0 if all_ok else 1

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
