---
type: playbook
status: draft
owner: Daru Broodryk
created: 2026-09-23
tags: [playbook]
---

# vault-install-test-plan

> **Answers:** How do I prove a new workstation is set up correctly? What does
> "install the vault" actually bind, and what is left for a person? Which install
> cases are automated, which are manual, and what is not covered at all?

**When to use:** before trusting a new workstation, after changing
`scripts/install_vault.py` or [[update]], or when deciding what to automate next.
**Prerequisites:** a machine with git, Python 3.x, Claude Code and a clone of this
repository. A machine with none of those starts at `scripts/setup_vault.py`.

Companion to [[setup]], which is the prose. This is the proof.

Covers the one-command install path: `scripts/install_vault.py`, [[update]], and
the hooks and guards they bind. Written 2026-09-23, against the work on
`internal/index-context-budget`. Updated 2026-11-07, when the `central` and
`humanizer` plugins were retired and the `install-vault` skill, the prompt gate and
the deny-rules step went with them.

## 1. What the person does

Prerequisites, none of which this path installs: git, Python 3.x, Claude Code,
and a clone of the repository. A machine with none of those starts at
`scripts/setup_vault.py`, which clones the workspace, sets a git identity and
installs Obsidian.

With the folder present, the whole install is one sentence typed into Claude Code
opened on that folder:

> install the vault

Everything below happens from that. The person answers two kinds of question and
nothing else: a confirmation before the global settings file is touched, and the
handful of binding fields the machine cannot detect.

Outside the conversation, three things still need them: opening the folder as a
vault in Obsidian and accepting the Git plugin trust prompt, putting credentials
in each tool's own config, and deciding whether to spend about 100 minutes
building the vector index.

## 2. What happens behind it

Claude, following [[update]], runs `python scripts/install_vault.py --yes`. Every
apply run ends with `scripts/verify_install.py`, which runs this plan (§4) and
writes the report described there. Four steps, each idempotent:

| Step | Binds | Why a clone cannot carry it |
|---|---|---|
| git guards | `core.hooksPath=.githooks` | `.git/hooks/` is never cloned and `core.hooksPath` is per-clone config |
| plugins | the `skills` marketplace cloned, then `token-weather-usage`, `flightdeck`, `next-steps` and `superpowers` enabled | a marketplace is a separate repository, and `enabledPlugins` is global configuration |
| prompt gate | no stale `UserPromptSubmit` hook in `~/.claude/settings.json` | no prompt gate ships since `central` was retired; a hook left by the old layout points at a gate nobody maintains |
| local bindings | `_local/cli-bindings.md` and `_local/workspace-bindings.md` | `_local/` is gitignored in full |

The binding files are written from `--detect`, which reads the workspace and
clone paths, the git identity, `_local/rag.path`, the `gh` account, the
Snowflake connection names, the dbt project id and the `gws` config directory.
Only undetectable fields are asked about, then filled with `--bindings key=value`.

Once installed, these run without further action. From the committed
`.claude/settings.json`: `session_gate.py` on `SessionStart`, `pii_gate.py` on
`PreToolUse`, and `review_output.py --gate` on `Stop`. From `.githooks/`: `hooks_guard.py` on
commit and push. In CI: `vault-lint.yml`, `branch-policy.yml`, `secret-scan.yml`.

## 3. Test strategy

The pyramid here is unusual, because the unit under test is a machine's
configuration rather than a service. Most of the risk sits in two places: a merge
that damages configuration the vault does not own, and a step that reports
success without binding anything.

Unit level, already automated. `scripts/test_install_vault.py`, 178 cases, covers
the settings merge (other hooks and settings survive, a second run adds no
duplicate entry, the old file is backed up, malformed JSON is refused and left
byte-for-byte), the detection filter (`safe()` drops a token or an overlong
value), rendering (detected values land in the file, blank fields are named), the
binding writer (never overwrites by default, backs up under `--force`), and the
plugin step's reading of the two halves that go missing independently. It also
covers the old-layout cleanup: only legacy skill names are moved, and only under
`--force`, into a backup folder outside `skills/`; retired plugins are found in the
settings or in `installed_plugins.json`; auto-update is switched on without
touching other marketplaces; and `central` and `humanizer` are retired with no
replacement. It runs
against `$VAULT_CLAUDE_HOME` in a temporary directory, so no case can reach the
real `~/.claude/settings.json`.

None of the plugin cases runs the `claude` CLI: a case that did would clone a
private marketplace into whatever config directory it found. The apply path is
checked against a stub that records the calls, which proves an existing clone is
updated before anything installs from it and a retired plugin is uninstalled and
replaced. Acceptance cases 22 to 28 cover the real CLI.

Also automated: `scripts/test_review_output.py` (10 cases, the Stop gate),
`scripts/test_pii_gate.py`,
`scripts/test_setup_vault.py`, and the four lints in CI.

Integration level, manual, below. These need a real clone, a real git config and
a real Claude Code session, which is exactly what the unit tests stub out.

## 4. Acceptance cases

`python scripts/verify_install.py` runs these. It checks the prerequisites (git,
Python, Claude Code on PATH, long paths, `gh` login, git identity), cases 5 to 9
and 12, and the automated suites from §3, then writes
`raw/output/install-report-<timestamp>.md` with four sections: Failed (each with
its fix), Skipped, Passed, and Still needs you, which lists cases 7b, 11, 13 and
14, Obsidian, blank binding fields and credentials as a checklist. Case 12 runs
in a throwaway repository, never in the clone. It is read-only otherwise and
exits 1 when anything fails. `install_vault.py` calls it at the end of every
apply run.

Cases 1 to 4 and 10 describe the install itself, and 15 to 25 simulate a broken
machine; the script names those in the report but does not run them.

Run on a workstation that has never held this repository. A Windows and a macOS
or Linux run are both worth doing, because the path handling and the hook shell
differ.

| # | Given | When | Then |
|---|---|---|---|
| 1 | Fresh clone, nothing installed | `python scripts/install_vault.py --check` | Every step listed; plugins, auto-update, git guards and local bindings `PENDING`, exit code 1 |
| 2 | Fresh clone | `--dry-run` | Same plan printed, exit code 0, and `git config --get core.hooksPath` is still unset |
| 3 | Fresh clone, Claude Code open on the folder | Type "install the vault" | Claude follows [[update]], shows the plan, asks before touching `~/.claude/settings.json` |
| 4 | Plan shown | Answer yes | The pending steps apply, a line says to restart Claude Code, the gate lines print, the "still needs you" list prints |
| 5 | Just applied | `--check` | Every step `ok`, exit code 0 |
| 6 | Just applied | `git config --get core.hooksPath` | `.githooks` |
| 7 | Just applied | `ls ~/.claude/skills` | none of the old layout's skill names: no vault skill loads as a loose file any more |
| 7a | Just applied | `claude plugin list` | `token-weather-usage@skills`, `flightdeck@skills`, `next-steps@skills` and `superpowers@claude-plugins-official` all enabled; no `central@skills` or `humanizer@skills` |
| 7b | Just applied | Ask Claude to use `superpowers:systematic-debugging` | It resolves, and no bare `systematic-debugging` exists to compete with it |
| 8 | Just applied | Read `~/.claude/settings.json` | No `UserPromptSubmit` entry naming `prompt_gate.py`. Every pre-existing setting intact |
| 9 | Just applied | Read `_local/cli-bindings.md` and `_local/workspace-bindings.md` | Detected values filled in, undetected ones named under "Still blank" |
| 10 | Already installed | Run `--yes` again | "nothing to do", no second hook entry, no file rewritten |
| 11 | Already installed | Start a new Claude Code session | `SessionStart` prints the gate line |
| 12 | Installed, on `main` | `git commit` | Refused by `hooks_guard.py` |
| 13 | Installed | Write a file to `raw/output/`, end the turn | The Stop gate fires once and opens the triage review |
| 14 | Installed | End a second turn without triaging | The gate stays silent for the rest of that session |

Failure and edge cases, all of which must fail safely rather than loudly:

| # | Given | When | Then |
|---|---|---|---|
| 15 | `~/.claude/settings.json` contains invalid JSON | `--yes` | The prompt gate step reports it, the file is unchanged, other steps still apply |
| 16 | `~/.claude/settings.json` already holds other hooks | `--yes` | Those hooks survive and a `settings.json.bak-<timestamp>` exists |
| 17 | A binding file the person has edited | `--yes` | It is left exactly as they wrote it |
| 18 | A binding file the person has edited | `--bindings paymo_user_id=1234` | The file is rewritten and the old one is backed up beside it |
| 19 | `~/.snowflake/connections.toml` holds a password | `--detect` | Only connection names appear, no value from the file |
| 20 | No git identity set | `--yes` | The report says the identity is unset rather than inventing one |
| 21 | No network | `--yes` | The four local steps still apply; the plugin step fails and says so, and only the optional index build needs the network besides |
| 22 | The skills marketplace folder is missing | `--yes` | The plugin step reports FAILED naming the marketplace, every other step still applies, exit is not a crash |
| 23 | Case 22, then `gh auth login` | `--yes` again | The plugin step alone applies, and the other four report nothing to do |
| 24 | `claude` not on PATH | `--yes` | The plugin step reports "the claude CLI is not on PATH", the other four apply |
| 25 | `skills` already added, plugin not installed | `--yes` | `marketplace update skills` runs, then `plugin install`; the marketplace is not re-cloned |
| 26 | `skills` clone from before flightdeck existed | `--yes` | The clone is updated first and flightdeck installs, rather than failing as "not found" |
| 27 | `engineering@skills`, `cache-handoff@skills`, `central@skills` or `humanizer@skills` enabled from an older install | `--yes` | It is uninstalled, token-weather-usage replaces cache-handoff, the others get no replacement, and `claude plugin list` no longer shows it |
| 28 | Old-layout skill copies and a skill of your own in `~/.claude/skills/` | `--yes`, then `--yes --force` | The first run leaves both and says `--force` is needed; the second moves only the old-layout copies to `~/.claude/skills-backup-<timestamp>/` |
| 29 | `context-mode` installed, no Node.js on PATH | `--check` | `hook runtimes` is `PENDING` and names `context-mode@skills`; `--yes` reports it FAILED with both fixes and installs nothing |
| 30 | `claude-mem@skills` installed | `--yes` | It is uninstalled, the report says it was renamed session-memory, and session-memory is not installed |
| 31 | `python` is missing, is Python 2, or is the Microsoft Store alias | Run the installer with `py -3` or `python3`, `--check` | `hook runtimes` is `PENDING`, names this vault's hooks, and offers only installing Python, never removing a plugin |
| 32 | No `uv`, no PyYAML, or on Windows no tzdata | `--check` | Each is listed under "optional tools missing" with its install command, and none of them changes the exit code |
| 33 | skills on GitHub is ahead of the local clone, or an installed plugin is older than the clone offers | `--yes` | `plugin updates` pulls the clone, runs `claude plugin update` for each outdated skills plugin, and says to restart Claude Code |
| 34 | flightdeck or next-steps not installed | `--yes` | Both install with the other expected plugins |

## 5. Coverage gaps, stated plainly

No automated end-to-end case runs the install on a clean clone.
`verify_install.py` proves the end state of cases 5 to 9 and 12, but cases 1 to
4 and 10 are still manual, and a container or a throwaway user account is the obvious
place to automate them.

`install_hooks.py` is driven by this installer but has no tests of its own; its
failure shows up here only as a non-zero exit.

The plugin step's apply path is unproven by any automated case, for the reason in
§3. The stubbed cases prove the order of calls; cases 22 to 28 are the only
coverage of the real CLI and all of them are manual. The
private marketplace makes this the one step that can fail for a reason outside
the machine, which is also the one failure mode nothing here exercises
automatically.

The Stop, SessionStart and PreToolUse hooks are tested as scripts, not as hooks.
Nothing proves Claude Code actually fires them on a fresh machine, which is what
cases 11, 13 and 14 exist for.

The Obsidian half is entirely manual, and nothing checks that the Git plugin is
enabled or that the person is on `capture` rather than `main` during backups.

Windows is the only platform this has run on so far. The `gh`, Snowflake, dbt and
`gws` detection returned empty there because those tools were not configured, so
those four branches are unproven against real files.

Related: [[setup]] · [[rules]] · [[retrieval]]
