# skills

A local Claude Code marketplace. It distributes the skills we
want everyone to have, so they live in version control and go through review
rather than sitting in one person's `~/.claude/skills/` directory.

## Install

```sh
claude plugin marketplace add <path to this folder>
claude plugin install <name>@skills --scope user
```

Every plugin is optional. Install each one you want the same way, by the name in
the list below:

| Plugin | What it is |
| --- | --- |
| `humanizer` | Third-party, MIT. Rewrites AI-sounding prose. |
| `next-steps` | Third-party, MIT. Suggests up to three follow-up prompts after each answer. |
| `token-weather-usage` | This copy of a third-party plugin, Apache-2.0. A band above the prompt with context, usage limits, prompt cache and cost. |
| `flightdeck` | This copy of a third-party plugin, MIT. A live pane of permission checks and subagents. |
| `context-mode` | Third-party, Elastic License 2.0. Keeps large tool output out of the context window. |
| `session-memory` | Third-party, Apache-2.0 (upstream name `claude-mem`). Cross-session memory. |

`central` was retired on 2026-11-07 and removed from this marketplace on 2026-11-17.

Read a third-party plugin's section below before installing it: some run
background processes, send data off the machine or overlap with each other.

User scope makes a plugin available in every directory. Use `--scope project`
instead if a plugin should only load inside one repository; that writes the
install to that repository's `.claude/settings.json`, so it applies to everyone
who clones it.

If `engineering@skills` or `central@skills` is installed, uninstall it. Both are
retired. The same goes for `claude-mem@skills`, now listed as `session-memory`.

New versions arrive on their own once auto-update is on for this marketplace. It is
off by default for any marketplace that isn't Anthropic's. Turn it on in `/plugin`
under Marketplaces, or add `"autoUpdate": true` to the `skills` entry under
`extraKnownMarketplaces` in `~/.claude/settings.json`. The vault installer
(`python scripts/install_vault.py --yes` in the brain clone) sets it for you. To pull a new version by hand instead:

```sh
claude plugin marketplace update skills
```

Run `python scripts/install_vault.py --yes` from the brain clone. It uninstalls
retired plugins (`central`, `humanizer`, `engineering`) where it finds them.

## What is here

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
claude plugin eval plugins/<plugin>
```

`eval` runs any suite under the plugin's `evals/` directory against a no-plugin
baseline, so you can see whether the skill actually changes the outcome.

To cut a release, tag it. This checks that `plugin.json` and the marketplace
entry agree before creating the tag:

```sh
claude plugin tag plugins/<plugin>
```

## Adding a third-party plugin

List it in `.claude-plugin/marketplace.json` with a `url` or `git-subdir` source
pinned by `sha`. Read every `SKILL.md` and hook in it first. A plugin runs with
the same access the person running Claude Code has.
