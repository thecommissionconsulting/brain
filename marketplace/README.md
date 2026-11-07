# skills

A local Claude Code marketplace. It distributes the skills we
want everyone to have, so they live in version control and go through review
rather than sitting in one person's `~/.claude/skills/` directory.

## Install

```sh
claude plugin marketplace add <path to this folder>
claude plugin install central@skills --scope user
```

central is the in-house plugin everyone should have. The others are
optional; install each one you want the same way, by the name in the list
below:

| Plugin | What it is |
| --- | --- |
| `central` | In-house skills: answer-only replies with a PII prompt gate, security hooks for credentials, the caveman token-compression suite, document conversion, method skills for code changes, and the vault tooling. |
| `humanizer` | Third-party, MIT. Rewrites AI-sounding prose. |
| `next-steps` | Third-party, MIT. Suggests up to three follow-up prompts after each answer. |
| `token-weather-usage` | This copy of a third-party plugin, Apache-2.0. A band above the prompt with context, usage limits, prompt cache and cost. |
| `flightdeck` | This copy of a third-party plugin, MIT. A live pane of permission checks and subagents. |
| `context-mode` | Third-party, Elastic License 2.0. Keeps large tool output out of the context window. |
| `session-memory` | Third-party, Apache-2.0 (upstream name `claude-mem`). Cross-session memory. |

Read a third-party plugin's section below before installing it: some run
background processes, send data off the machine or overlap with each other.

User scope makes a plugin available in every directory. Use `--scope project`
instead if a plugin should only load inside one repository; that writes the
install to that repository's `.claude/settings.json`, so it applies to everyone
who clones it.

If you installed `engineering@skills` before it was merged into
central, uninstall it and install central instead. The same goes for
`claude-mem@skills`, now listed as `session-memory`.

New versions arrive on their own once auto-update is on for this marketplace. It is
off by default for any marketplace that isn't Anthropic's. Turn it on in `/plugin`
under Marketplaces, or add `"autoUpdate": true` to the `skills` entry under
`extraKnownMarketplaces` in `~/.claude/settings.json`. The vault installer
(`/install-vault`) sets it for you. To pull a new version by hand instead:

```sh
claude plugin marketplace update skills
```

On a machine that installed the vault before central existed, run
`/install-vault` from the vault clone rather than installing by hand. It updates the
old marketplace clone first, swaps retired plugins for central, and moves the
skill copies the old layout left in `~/.claude/skills/` aside, each of which would
otherwise shadow or duplicate central's skills.

## What is here

### central

The single in-house plugin. It absorbed the four method skills that used to
ship as engineering, plus the skills that used to be copied out of the
vault repository, so none of them has to be committed inside a working
repo to be available.

It also ships one hook: a `UserPromptSubmit` command that runs
`skills/answer-only/prompt_gate.py` on every prompt. It blocks prompts carrying
personal data and adds the answer-only reply style. It needs `python` on the
PATH.

Method skills, deliberately short, because a skill competes for attention with
every other loaded skill and a long one is less likely to be followed:

| Skill | Use when |
| --- | --- |
| `lean-build` | Building new behavior where the risk is overbuilding: product slices, integrations, anything with fuzzy scope. |
| `surgical-patch` | Fixing a bug or making a small behavior change that must not disturb the code around it. |
| `safe-refactor` | Restructuring without changing behavior: extraction, consolidation, moving ownership. |
| `migration` | Schema, data, API, protocol, configuration, or dependency transitions that need a rollback path. |

`data-model-audit` audits an existing data model (dbt project, SQL or notebook
exports) against the house dimensional, layering, testing and SAP standards. It
reports only findings whose file:line evidence passes a scripted check.
Its eval case is `plugins/central/evals/data-model-audit-roastery/`. Run it with
`claude plugin eval plugins/central --case data-model-audit-roastery --judge-model sonnet --allow-tools Bash Write`.
The default Haiku judge fails reports that meet the answer key, so use Sonnet. Bash needs a
sandbox: on Linux, `apt install bubblewrap socat`. The sandbox blocks PyPI, so `audit_sql.py`
cannot install sqlglot inside the eval. The eval therefore measures the judgement pass on its own.

Writing and token skills:

| Skill | Use when |
| --- | --- |
| `answer-only` | Explaining or tuning the prompt gate above; it runs from the hook without being invoked. |
| `caveman` | Asking for ultra-compressed replies (`/caveman`, "be brief"). |
| `caveman-commit` | Writing a compressed Conventional Commits message. |
| `caveman-compress` | Compressing a memory file such as CLAUDE.md, keeping a readable backup. |
| `caveman-explore` | Read-only orientation in an unfamiliar repository, answered as `path:line` citations. |
| `caveman-review` | Formatting a review already under way as one line per finding. |
| `caveman-stats` | Showing the session's real token use and estimated savings. |
| `caveman-help` | A quick-reference card for the caveman skills. |
| `markdown-converter` | Converting PDF, Office, HTML, images, audio and other files to Markdown with markitdown. |

Personal admin:

| Skill | Use when |
| --- | --- |
| `timesheet-recall` | Reconstructing what you worked on for a blank timesheet day, from your local Claude Code and Grok CLI session histories. Read-only. |

vault skills, which only make sense inside a vault clone:

| Skill | Use when |
| --- | --- |
| `install-vault` | Installing or updating vault on a machine (`/install-vault`, "update the vault"). It follows the vault's own `_ai/update.md`. |
| `vault-rag` | Explicitly asking for semantic search over the vault's embedding index (`/vault-rag`). |

### central security hooks

Three hooks keep credentials out of the model's context and the session transcript.
None of them needs invoking.

- **Prompt gate** (`UserPromptSubmit`, part of answer-only) blocks a prompt that carries a
  credential or personal data.
- **Credential gate** (`PreToolUse`) denies a Read call, or a Grep call whose `path` is a
  credential file. It also denies a Bash or PowerShell command that names a credential file
  and starts with one of these readers, on its own or behind `sudo` or `cmd /c`: `cat`,
  `bat`, `head`, `tail`, `less`, `more`, `nl`, `strings`, `xxd`, `od`, `type`, `sed`, `awk`,
  `sort`, `tac`, `base64`, `grep`, `rg`, `ag`, `ack`, `findstr`, `Get-Content`, `gc` and
  `Select-String`. Credential files are the names, suffixes and home paths in
  `plugins/central/security/credential-files.json`, plus any `.env.<stage>` file such as
  `.env.uat`. The templates `.env.example`, `.env.sample`, `.env.template` and `.env.dist`
  stay readable. It also refuses any write that carries a redaction placeholder.
- **Output redaction** (`PostToolUse`) replaces secrets and card or bank numbers in Read,
  Bash, PowerShell, Grep and WebFetch output with placeholders like `<<redacted:api-token:1a2b3c4d>>`. The
  same value gets the same placeholder for the whole session. Contact details are left in
  tool output on purpose.

Each hook lets the call through if it fails, and shows a message saying it did.

A plugin can't ship permission rules, so run this once per machine to add matching
`Read` deny rules to your own `~/.claude/settings.json`. They have no code that can fail.
Each command runs the installer from the highest central version in your plugin cache.

In PowerShell (Windows PowerShell 5.1 doesn't expand `~`):

```powershell
python (Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\skills\central\*\security\install_deny_rules.py" | Sort-Object { [version]$_.Directory.Parent.Name } | Select-Object -Last 1).FullName
```

In Git Bash, macOS or Linux:

```sh
python "$(ls -d ~/.claude/plugins/cache/skills/central/*/security/install_deny_rules.py | sort -V | tail -n 1)"
```

Add `--dry-run` to see the rules first. To roll them out to the whole team, put the same
rules in managed settings instead.

What these don't stop:

- a script that opens a file itself, such as `python -c "print(open('.env').read())"`;
- a reader that isn't in the list above, such as `cut`, `jq` or `[IO.File]::ReadAllText`;
- a glob or wildcard in place of the name, such as `cat .en*` or `Get-Content *.env*`;
- a Grep call aimed at a folder that holds a `.env` file, or `grep -r` across one;
- a `.env.<stage>` file on a machine without the hooks, since the deny rules cover only the
  stages listed in `credential-files.json`.

Output redaction is the backstop for these, for the patterns it knows.

Run the tests with:

```sh
cd plugins/central && python -m unittest discover -s security/tests -t .
```

### humanizer

Third-party, MIT licensed, by [blader](https://github.com/blader/humanizer). It
is listed here rather than copied in, pinned to a specific commit so an upstream
change cannot alter what our machines run. Review the diff before moving the pin.

### next-steps

Third-party, MIT licensed, from Anthropic's
[community marketplace](https://github.com/anthropics/claude-plugins-community/tree/main/next-steps).
After each answer it suggests up to three follow-up prompts above the input box;
press 1, 2 or 3 to put one in the box as a draft, 0 to dismiss. It never submits
anything itself. It has no skills, only a function-hooks module, and each
suggestion costs one short forked model call that shares the session's prompt
cache. It is pinned the same way as humanizer, to the commit its files were
reviewed at.

```sh
claude plugin install next-steps@skills --scope user
```

If you installed it earlier as `next-steps@claude-community`, uninstall that copy
so the suggestions are not drawn twice.

### token-weather-usage

This copy of [Eric Cologni's plugin](https://github.com/augiefra/claude-mods/tree/main/plugins/token-weather-usage)
(Apache-2.0), vendored in `plugins/token-weather-usage` from upstream commit
`701aa6f` with its LICENSE and NOTICE. It draws one band above the prompt: the
context in tokens with a weather icon and a bar per recent prompt, the 5-hour and
7-day limits against the time elapsed, the time left before the prompt cache
lapses, and the session cost. It has no skills, only a function-hooks module.
It reads the usage figures Claude Code provides and keeps recent readings in the
plugin's local store, deleted after 8 idle days.

Local changes:

- In the desktop app the pills wrap onto a second row when the band is narrower
  than they are, for example with a side pane open, instead of being cut off at
  the edge. The pills stay packed from the left, with a gap between the rows.
- The context pill (weather icon, tokens and turns chart) is off by default; its
  `context` option brings it back.
- The cost pill shows the session cost alone (coin icon and "≈ $71.98"), without
  upstream's last-prompt share.
- A **Handoff** button: a pill right after the cache pill in the app, a button at
  the end of the line in the terminal, hidden while the model is mid-turn. It ends
  the session, so it takes two presses: the first reads "Confirm handoff?" for 5
  seconds, and a second within that window writes a handoff note (what the session
  was doing, its state, decisions, open items and next steps) with a forked model
  call to `~/.claude/handoffs/<session id>-<time>.md`, shows a toast with the path,
  runs `/compact`, then ends the session with `/exit`. If any step fails the rest
  do not run and the pill reads "Handoff failed: <reason>"; it never exits without
  a saved note.
- The agents pill ("1 agent") is pressable: it runs `/flightdeck` to open the
  flightdeck pane. Without flightdeck installed, a toast says it isn't available.

Permissions: upstream makes no model calls, writes no files and runs no commands.
This copy calls `$.model` (the forked call for the handoff note), `$.fs` (to
write it under `~/.claude/handoffs/`, reading `USERPROFILE` or `HOME`) and
`$.command` (`/compact`, `/exit`, `/flightdeck`), each only when you press a
button. Upstream changes are merged by hand; review the diff first.

```sh
claude plugin install token-weather-usage@skills --scope user
```

### flightdeck

This copy of [Stephen Casella's plugin](https://github.com/scasella/claude-flightdeck)
(MIT), vendored in `plugins/flightdeck` from upstream commit `f31daca` with its
LICENSE. A live pane of the session's permission checks and subagents. Open it
with `/flightdeck`. It has no skills, only a function-hooks module, and the module
has no file, process, network or model access: everything it shows comes from the
session's own events, kept in session state.

Local changes:

- It no longer opens when a session starts. Open it with `/flightdeck` or by
  pressing token-weather-usage's agents pill; set `openOnStart` to bring back
  the old behaviour.
- By default it shows only the permission gate and the agents. The `panels`
  option brings back main, architect, loops, receipt and log.
- Three new options: `header` (the title line and colour legend) and `timeline`
  (the desktop time axis under the panels), both off by default, and `details`
  (a lane's hotkey or a click opens its task, model, steps and recent tool calls;
  again to close), on by default.
- Every agent the pane keeps (the last 24) gets a lane, where upstream showed six
  and folded the rest into "+N earlier". The first nine have hotkeys, and every
  lane is clickable. Lane titles and bars scale with the pane's width.
- The detail card shows how long the agent has run and a rough estimate of
  the time left: the median run of agents of the same type and model that
  finished earlier in this session, once there are three of them. Nothing is
  kept between sessions, and the estimate is only as good as those runs.
- A running agent's detail card has a Stop button (hotkey `x`). It is a soft
  stop: the agent's further tool calls are refused and its next model request
  is answered with a closing message, so it ends its turn and the card reads
  stopped. A command it is already running finishes first.

It also writes context, agents and denials to the status line. If you run
token-weather-usage as well and find the two noisy, turn flightdeck's off with its
`statusLine` option. Upstream changes are merged by hand; review the diff first.

```sh
claude plugin install flightdeck@skills --scope user
```

### context-mode

Third-party, by [Mert Koseoglu](https://github.com/mksglu/context-mode), pinned
to a reviewed commit. It routes large tool output through a local sandbox and an
FTS5 index instead of the context window. It is under the Elastic License 2.0,
which is source-available, not open source. Its hooks intercept Bash, Read,
Grep, WebFetch and Agent calls, and its `ctx_execute` tool runs arbitrary code
by design.

### session-memory

Third-party, Apache-2.0, by [thedotmack](https://github.com/thedotmack/claude-mem),
pinned to a reviewed commit. Upstream calls it claude-mem, and its own CLI is
still `npx claude-mem`; it is listed here as session-memory because Claude Code
reserves plugin names that start with `claude-`. It compresses session
transcripts into a searchable store across sessions.

Read this before installing it. It runs a persistent local worker, auto-installs
Bun, uv and Chroma, hooks every tool call, and sends transcripts to an LLM
provider for compression. PostHog telemetry is on by default: run
`npx claude-mem telemetry disable` after installing. Do not use it in a session
that handles client material under NDA without checking where compression runs.

## Adding or changing a skill

1. Put the skill in `plugins/<plugin>/skills/<skill-name>/SKILL.md`.
2. Write the `description` as a trigger condition, not a summary. It is the only
   text the model sees when deciding whether to load the skill, so "Use when X,
   Y, or Z" works and "Helps with X" does not.
3. Bump `version` in the plugin's `.claude-plugin/plugin.json`.
4. Open a PR. Skills are prompts that execute, so review them the way you would
   review code with the same reach.

Validate the manifest and the skill before merging:

```sh
claude plugin validate .
claude plugin eval plugins/central
```

`eval` runs any suite under the plugin's `evals/` directory against a no-plugin
baseline, so you can see whether the skill actually changes the outcome.

To cut a release, tag it. This checks that `plugin.json` and the marketplace
entry agree before creating the tag:

```sh
claude plugin tag plugins/central
```

## Adding a third-party plugin

List it in `.claude-plugin/marketplace.json` with a `url` or `git-subdir` source
pinned by `sha`. Read every `SKILL.md` and hook in it first. A plugin runs with
the same access the person running Claude Code has.
