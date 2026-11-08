# Setup — using this vault on a new machine

This vault is portable across Windows, macOS, and Linux/WSL. Shared knowledge lives here;
**machine- and person-specific values do not** — each person binds those in a local,
un-synced project `CLAUDE.md`.

## Quick start

**If you already have this folder**, open it in Claude Code and say "install the vault".
Claude follows [[update]], which runs `scripts/install_vault.py`. That binds the things a
clone cannot carry (git guards, the Claude Code plugins with auto-update on), clears what
an older install left behind, including the retired `central` and `humanizer` plugins, writes the `_local/` binding files from what the machine already knows, and then
walks you through what a script must not decide: your git identity, Obsidian, credentials,
and whether to build the index. Without Claude:

```bash
python scripts/install_vault.py --check     # is this machine set up?
python scripts/install_vault.py --yes       # apply it, then run the test plan
python scripts/verify_install.py            # the test plan on its own
python scripts/install_vault.py --detect    # what this machine knows about itself
python scripts/install_vault.py --bindings paymo_user_id=1234   # fill a blank field
python scripts/install_vault.py --yes --force                   # take the conflicts below
```

A machine that has used Claude Code before may already hold something in the
vault's way: skill copies in `~/.claude/skills/` from the layout that copied them out
of this repo, `core.hooksPath` pointing at another hooks directory, or
`disableAllHooks` turned on globally. Any of those leaves the install looking
successful while behaving as though it never ran, so the installer reports them and
`--force` takes them. Skill copies are moved to `~/.claude/skills-backup-<timestamp>/`
rather than deleted, and only the names the old layout installed count: a skill of
your own in that folder is never touched. Settings files it changes are backed up
beside themselves first, and an unrelated `UserPromptSubmit` hook of your own is
reported rather than removed.

Three things are cleared without `--force`, because each is the vault's own leftover.
A `skills` clone from an earlier install is updated before anything is installed
from it. An old clone can miss a newer plugin, and when the CLI's own refresh fails
it installs from that old clone and reports the plugin as "not found", hiding the
real cause (usually no access to the private repo). A retired plugin (`engineering`, `claude-mem`, `cache-handoff`, `gsd-core`, `central`, `humanizer`) is
uninstalled and its replacement installed where it has one, so the same skills do not load twice. A stale prompt-gate
hook in the global settings is removed.

### What each machine needs installed

None of it needs an administrator. Every Windows install below is per user
(`winget ... --scope user`), and pip installs go to your own site-packages (`--user`).
Run them from an ordinary terminal; if anything raises a UAC prompt, the command is
missing `--scope user`.

Claude Code runs hooks through a shell (Git Bash on Windows), and each hook starts a
program Claude Code does not ship. When that program is missing, every prompt and tool
call shows an error such as `node: command not found`. The session keeps working, but
the hook does nothing.

- **Python 3, as `python`.** This vault's own hooks, the PII gate among them, call
  `python` by that name. A machine with only `python3`, or where `python` is the
  Microsoft Store alias that opens the Store, fails every one of them, and the PII
  protection stops without saying so. Install it with `winget install --id Python.Python.3.13 -e --scope user` on
  Windows; on macOS put an unversioned `python` in your own bin folder, for example
  `mkdir -p ~/.local/bin && ln -s "$(command -v python3)" ~/.local/bin/python`, with
  `~/.local/bin` on PATH.
- **Node.js or Bun, for some plugins.** `context-mode` and `session-memory` run their
  hooks with Node.js. Install it
  (`winget install --id OpenJS.NodeJS.LTS -e --scope user` on Windows, `brew install node`
  on macOS) or
  uninstall the plugin.

The `hook runtimes` step reads the hooks of every loaded plugin and this vault, checks
that each program actually runs (`python` must answer as Python 3), and names the fix.
It never installs anything or removes a plugin itself.

Three more tools are reported as optional, because only one skill or report needs each.
They never fail `--check`:

- **uv**: `markdown-converter` runs `uvx markitdown`, and `data-model-audit` runs
  `uv run --with sqlglot`. `winget install --id astral-sh.uv -e --scope user` or
  `brew install uv`.
- **PyYAML**: `check_frontmatter.py`, and so the install report, import `yaml`.
  `python -m pip install --user pyyaml`.
- **tzdata**, Windows only: `timesheet-recall` reads times in Pacific/Auckland, and
  Windows has no timezone database of its own. `python -m pip install --user tzdata`.

`claude-mem`'s successor, `session-memory`, is not installed for you: it needs Node.js, installs Bun, uv and Chroma, and sends transcripts
to an LLM provider, so it stays opt-in. Read its section in the skills README first.

Restart Claude Code after an apply run. Plugins, hooks and settings load only when a
session starts, and the installer says so when it changed any of them.

Every apply run ends by running `scripts/verify_install.py`, which executes the
automatable cases in [[vault-install-test-plan]] and writes
`raw/output/install-report-<timestamp>.md`: what passed, what failed with the
command that fixes it, and the checks only a person can make. Work down its
"Still needs you" list, then rerun it until nothing fails.

**If you do not have the folder yet**, start with `scripts/setup_vault.py`.
It does the mechanical half of this note — clone the workspace, set
your git identity, install Obsidian and register the vault, and stand up the search index.
It asks four questions, then `Proceed?`; press Enter to accept and it does the work.

```bash
python scripts/setup_vault.py
```

It is self-contained, so it also runs before the vault exists — download it and it clones
the workspace for you. Re-running is safe: it reports an empty plan on a machine that is
already set up.

**It never asks for a secret.** Credentials are the manual half, below: they live in each
tool's own config, never in a note ([[rules]] R-30). The rest of this note is the *why* —
the shared/local split, the branch rules, and the platform gotchas — which the script
cannot explain for you.

## 1. Open the vault
Clone the repo and **Open folder as vault** in Obsidian (Windows/Mac/Linux all work). The
Obsidian Git plugin ships in `.obsidian/plugins/` — accept the trust prompt to enable it.
On Windows it uses its built-in git engine, so a system git install is optional.

### Claude Code plugins (run once per machine)
No skill is committed in this vault. Every one arrives as a plugin, so it loads in
every repo you open rather than only inside this one, and there is no second copy
to drift. `install_vault.py` does this for you, or by hand:

```bash
claude plugin marketplace add ./marketplace               # from the vault root
claude plugin install token-weather-usage@skills
claude plugin install flightdeck@skills
claude plugin install next-steps@skills
claude plugin install superpowers@claude-plugins-official
claude plugin list                                        # what is installed and enabled
```

`central` (the company's in-house skills, the `answer-only` prompt gate and the
credential deny rules) and `humanizer` were retired on 2026-11-07. The installer
uninstalls both where it finds them. Their skills are no longer available.

`token-weather-usage` is this copy of Eric Cologni's plugin (Apache-2.0), kept in
`skills` with local changes. It draws one band above the prompt: the 5-hour and
7-day usage limits against the time elapsed, how long the prompt cache stays warm, the
session cost and the running subagents. Its Handoff button (press it twice to confirm)
writes a handoff note to `~/.claude/handoffs/`, never this vault, then runs `/compact` and
ends the session. It has no skills, only a function-hooks module. It replaced
`cache-handoff`, which left the marketplace; the installer swaps it out on a machine that
still has it.

`flightdeck` is this copy of Stephen Casella's plugin (MIT): a live pane of the
session's permission checks and subagents, opened with `/flightdeck` or from
token-weather-usage's agents pill. It has no file, network or model access.

`next-steps` is third-party (MIT, from Anthropic's community marketplace, pinned to a
reviewed commit). After each answer it suggests up to three follow-up prompts above the
input; press 1, 2 or 3 to put one in the box as a draft, 0 to dismiss. Each suggestion
is one short extra model call, so it adds a little usage.

Every "update the vault" run also keeps these current. The run pulls the vault, which
brings in any new plugin versions under `marketplace/`, then runs `claude plugin update`
for every installed skills plugin whose version there differs from the one installed.
When `VAULT_SKILLS_DIR` points at a marketplace that is its own git clone, the run also
pulls that clone when GitHub is ahead of it. Auto-update does the same when Claude Code
starts, but only once it has been switched on, so the update does not wait for it.

`superpowers` comes from `claude-plugins-official`, which ships with Claude Code, so it
usually needs no `marketplace add` of its own. It also replaced two vault skills:
`verification-before-completion` does what `verify-and-stop` did, and
`systematic-debugging` what `investigate-first` did.

No prompt gate ships any more: the `answer-only` `UserPromptSubmit` hook left with
`central`. Prompts are no longer checked for personal data before they reach the model.
The vault's own `pii_gate.py` still checks file and shell tool calls. If you still have a
hook in `~/.claude/settings.json` pointing at `~/.claude/skills/answer-only/prompt_gate.py`
from the old layout, the installer removes it.

One setting goes into `~/.claude/settings.json` with the plugins: `autoUpdate: true` on
the `skills` entry under `extraKnownMarketplaces`, because a third-party marketplace does
not update on its own, and without it a machine keeps the plugin versions it first
installed. The credential-file `Read` deny rules came from `central` and are no longer
added on a new machine; rules an earlier install wrote stay in place.

This vault's own `.claude/settings.json` enables the same plugins. It does not declare
the `skills` marketplace, because that is a folder whose path differs per machine (R-31);
the installer, or `claude plugin marketplace add`, registers it in your global settings.

`skills` is this vault's own `marketplace/` folder, so a clone carries it and no second
repo is needed. If you keep the marketplace somewhere else, set `VAULT_SKILLS_DIR` to the
folder that holds its `.claude-plugin/marketplace.json`. Without a marketplace there,
`install_vault.py` reports that step as FAILED while finishing the rest.

### Git guards (run once per clone)
The guards that refuse a commit on `main`, a `vault backup:` message there, a secret, or a
`git add -f` of `raw/` live in `.githooks/`. Git never clones `.git/hooks/`, and
`core.hooksPath` is per-clone config, so a clone starts with none of them until you run:

```bash
python scripts/install_hooks.py            # enable
python scripts/install_hooks.py --check    # report, change nothing
python scripts/install_hooks.py --remove   # disable
```

`setup_vault.py` does not do this for you. Until it is run, nothing local stops a push to
`main`; `branch-policy.yml` and the TruffleHog scan in CI still catch it afterwards, which
is a slower and more public place to find out. `--check` exits non-zero when the guards are
off, so it also works in a shell prompt or a startup script.

### Git / Obsidian Git (branching)
- Canonical branch is **`main`** — change it via **PR** (see [[vault-git]]).
- For continuous Obsidian backups, check out **`capture`** (not `main`):
  `git fetch origin && git checkout capture && git pull --ff-only`
- The plugin commits on the **current** branch; status bar should show `capture` during auto-backup sessions.
- Do not auto-backup onto `main` — CI fails pushes that introduce `vault backup:` commits there.

### Company vs personal directories
Keep firm and personal trees apart (projects + vaults). Personal clients must **not** get
`clients/` stubs in this vault. See [[client-engagement-structure]].


## 2. Install the tools you use (per OS)
- **Python** — for `paymo-sync`. Any 3.x; invoke as `python` on Windows, or your conda/venv
  interpreter elsewhere.
- **OneDrive** — sync the SharePoint library once so it appears in your file explorer; see
  [[20260619-post-migration-advice]]. This replaced the Google Drive share in June 2026.
- **dbt Cloud CLI** — only if you work in `masking-sandbox`.

## 3. Your personal `CLAUDE.md` lives in `_local/` (NOT committed)
Create `_local/CLAUDE.md` in this vault. The vault's own `CLAUDE.md` imports it with
`@_local/CLAUDE.md`, so it loads in every Claude Code session inside the vault and nowhere
else. `_local/` is gitignored, so it is never committed. If the file is missing the import is
skipped.

Put in it:
- Your **identity**: git `user.name` / `user.email`, your company Microsoft 365 account.
- Anything else personal you want Claude to know when working in the vault.

**No secrets.** Your Paymo API key and user ID go in user environment variables,
`PAYMO_API_KEY` and `PAYMO_USER_ID`, not in this file ([[rules]] R-30). On Windows:

```powershell
[Environment]::SetEnvironmentVariable('PAYMO_API_KEY', '<your key>', 'User')
[Environment]::SetEnvironmentVariable('PAYMO_USER_ID', '<your id>', 'User')
```

On Linux, macOS and WSL, export them from your shell profile.

The workspace root is no longer where this file goes. On Windows the workspace is `C:\`,
and a `CLAUDE.md` there would load into every Claude Code session on the drive. A client
workspace that needs the vault's router imports it from its own `CLAUDE.md`, e.g.
`@C:/vault/index.md` (Windows) or `@/home/you/workspace/vault/index.md` (Linux/WSL/Mac).
`index.md` is the router; there is no other master note.

## 4. Your machine-local config lives in `_local/` (gitignored)

Personal, machine-specific bindings — projects root, vault clone, client workspaces,
Snowflake/dbt/GitHub connection names, config-file paths, `gh` account, git identity — go
in the vault's **`_local/`** folder, which is gitignored and never syncs.
`python scripts/install_vault.py` writes `_local/cli-bindings.md` and
`_local/workspace-bindings.md` for you, reading the paths, the git identity, the `gh`
account, the Snowflake connection names and the dbt project off the machine itself. Only the
fields it cannot detect are left blank, and it names them; fill them with
`--bindings key=value`.

- **Never put real secrets/tokens in `_local/`** — they stay in the tools' own config
  (`~/.snowflake/connections.toml`, `~/.dbt/dbt_cloud.yml`, `~/.config/gh/hosts.yml`). `_local/`
  records *how you're wired*, not the credentials. A CI secret-scan guards the repo as a backstop.
- Shared, non-personal infra facts (accounts, hosts, org, project ids) live in `/cli-access`.
- On a new machine, write `_local/` from scratch — it doesn't sync, by design.

## OS gotchas
- **Line endings** — normalised to LF by `.gitattributes`; don't override `core.autocrlf`.
- **Filenames** — avoid `: \ / * ? " < > |` and reserved names (`CON`, `PRN`, `AUX`) in note
  titles; keep wikilink casing matching the filename (Linux is case-sensitive, Windows/Mac aren't).
- **Paths** — never hardcode another machine's absolute paths into a synced note; put them in
  your local `CLAUDE.md`.
- **Workspace location** — on Windows `setup_vault.py` defaults the workspace to `C:\`, so the
  vault clones to `C:\vault`: a short path outside the
  user profile, clear of OneDrive redirection and the 260-character path limit. On Linux and
  macOS the default is `~/workspace`.
- **WSL** — reports itself as Linux, so `setup_vault.py` defaults the workspace to `~/workspace`,
  not `C:\`. The script says so before it asks. Obsidian discovery uses the Linux paths (`/usr/bin/obsidian`,
  `/opt/Obsidian/obsidian`, `~/.config/obsidian/`), which is right for a Linux build running
  inside WSL — a Windows-side Obsidian reading `/mnt/...` will not be found.

## 5. Vector retrieval (removed)

The vault no longer has vector search. It was removed on 2026-11-09. Use `index.md`, then the
folder hub, then grep.

## 6. What runs by itself, once this is done

Three Claude Code hooks are configured in `.claude/settings.json`, which is committed, so
they apply to every clone without further setup. A fourth, the `answer-only`
`UserPromptSubmit` gate, left with the retired `central` plugin on 2026-11-07.

`SessionStart` runs `scripts/session_gate.py`: the two sub-second gates plus the `index.md`
byte budget, so a session opens knowing which rules in [[rules]] are currently red. It
always exits 0 and never blocks a session.

`PreToolUse` runs `scripts/pii_gate.py` in front of every read, search and write. It blocks
reads of the vault's bulk personal data before it can reach the prompt, using the static
list in `_ai/pii-denylist.txt` plus a count of distinct external addresses computed at read
time. It fails open: if the gate itself errors, the tool call proceeds.

`Stop` runs `scripts/review_output.py --gate`. Generated artifacts go to `raw/output/`
(R-48), which is gitignored and therefore invisible to every lint. When a turn ends and an
artifact there has no ruling, the gate fires once per session and Claude opens the triage
review: promote it into `wiki/`, keep it, or delete it. See [[rules]] §Artifact triage. Its
state is machine-local, in `_local/output-triage.json` and `_local/output-triage/`.

The git hooks from `.githooks/` run on commit and push: `hooks_guard.py` refuses `main`,
a force-push or delete of it, a `vault backup:` commit message on `main`, a credential, and
a `git add -f` of `raw/`, `assets/` or `.confluence-private/`. It warns on charge-out rates,
tenant GUIDs and bulk external addresses rather than blocking them.

CI runs on every push and PR: `vault-lint.yml` for frontmatter, links, maps and schema sync,
`branch-policy.yml` for the branch and commit rules, and `secret-scan.yml`, which scans the
full history as the backstop behind the local secret guard.

How to prove an install actually took, with 27 acceptance cases and the coverage gaps:
[[vault-install-test-plan]].

Related: [[rules]] · [[retrieval]] · [[vault-install-test-plan]]
