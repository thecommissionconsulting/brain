---
type: instruction
status: review
owner: Daru Broodryk
created: 2026-10-09
---

# update

> **Answers:** What does Claude do when someone says "update the vault" or "install
> the vault"? How does a workstation that already has the vault pick up a new
> installer, new plugins and new settings?

Instructions for Claude, in order. Installing and updating are the same procedure:
`scripts/install_vault.py` only does what is missing, so a fresh clone and a machine
set up months ago take the same path. The script makes the decisions. This note only
sets the order and says where to stop and ask.

This note lives in the vault rather than in a skill on purpose. A skill ships in a
plugin, which is exactly what is missing or out of date on an old workstation, and the
`install-vault` skill left with the retired `central` plugin on 2026-11-07. This note
arrives with `git pull`, so it always matches the installer in the same commit.

## 1. Ask once, up front

Pulling is a git operation, and the installer is a writing script that edits the global
`~/.claude/settings.json` and the plugin install outside this repo. All of that is on
the "ask first" list in `CLAUDE.md`. Ask one question before doing anything:

> This will switch to `main`, pull, show you the install plan, and then apply it after
> you've read it. Applying it can change your global Claude Code settings (backed up
> first) and install or remove plugins. Go ahead?

Stop if the answer is no.

Never run anything as administrator, with `sudo`, or through a UAC prompt. Everything
the vault needs installs for the current user: winget with `--scope user`, and pip with
`--user`. If a command asks for elevation, stop and tell the person rather than
accepting it.

## 2. Check the tools and the login

```bash
claude --version
ls marketplace/.claude-plugin/marketplace.json
```

`claude` must be on PATH: the installer adds and removes plugins through it. The
desktop app does not put it there. If the command is not found, ask the person whether
to install it for their user, then run it in PowerShell (never as administrator):

```powershell
irm https://claude.ai/install.ps1 | iex
```

On macOS or Linux it is `curl -fsSL https://claude.ai/install.sh | bash`. It installs
into `~/.local/bin`; the new command is only found after Claude Code restarts, so ask
them to restart now and say "update the vault" again.

The `skills` marketplace is this vault's own `marketplace/` folder, and the plugin step
adds it from there. If the `ls` line finds no `marketplace.json`, the clone is
incomplete: stop and say so. If the person keeps the marketplace somewhere else, set
`VAULT_SKILLS_DIR` to it before running the installer. Do not continue past the plugin
step without it; the rest of the install would apply but the plugins would not.

The wiki is a second repo, `DataWithDaru/wiki`. It sits beside this clone as `../wiki`,
which is where `scripts/setup_vault.py` puts it on a new machine. If `../wiki` is
missing, say so and ask before cloning it. The installer wires it in §5 with
`--wiki ../wiki`; without a wiki it reports `wiki: not configured` and the rest still applies.

## 3. Pull, then re-read this note

```bash
git status --short
git branch --show-current
```

If the working tree has changes, or the branch is not `main`, stop and say so. Do not
stash, commit or switch branches on your own. Otherwise:

```bash
git pull
```

Then read `_ai/update.md` again and follow the new copy from §4. The copy you read
before pulling may be older than the installer you just pulled.

## 4. Show the plan

Run `python scripts/install_vault.py --yes` after every clone or pull. Since 2026-11-17 the brain's gate hooks are written per machine into `.claude/settings.local.json`; without this run no PII, edit or session gate loads.

```bash
python scripts/install_vault.py --dry-run
```

If `python` is not found, opens the Microsoft Store, or is Python 2, run the same
commands with `python3` or `py -3` instead for the rest of this note. The installer
then reports the broken `python` under `hook runtimes`, because the hooks call it by
that name.

Print the plan in your reply: each step and whether it is `ok` or `PENDING`. If every
step is `ok` and there is no "existing setup on this machine" section, say the machine
is up to date and stop.

If there is an "existing setup on this machine" section, explain what `--force` would
do before asking whether to use it:

- skill copies the old layout left in `~/.claude/skills/` are moved to
  `~/.claude/skills-backup-<timestamp>/`, not deleted, and any skill of the person's own
  under another name is left alone;
- `core.hooksPath` is pointed at `.githooks`;
- `disableAllHooks` is set to false.

Another `UserPromptSubmit` hook is reported, never removed. Say so if one is listed.

If the `hook runtimes` step is `PENDING`, a hook that loads here starts `python`, `node`
or `bun`, and that program does not run on this machine. Every prompt and tool call then
shows an error such as `node: command not found`. The installer never fixes this itself.
Say which program and which plugin or hook needs it, then:

- For `python`, there is no choice to offer. This vault's own hooks, the PII gate among
  them, call it, and without it they do nothing. Ask to install Python 3 with the command the plan prints
  (on Windows, `winget install --id Python.Python.3.13 -e --scope user`). If `python` opens the Microsoft
  Store, the person turns off its App execution alias in Settings > Apps > Advanced app
  settings; you cannot do that for them.
- For `node` or `bun`, ask which they want: install the runtime with the command the
  plan prints (for Node.js on Windows, `winget install --id OpenJS.NodeJS.LTS -e --scope user`,
  a per-user copy with no admin prompt), or remove the
  plugin if they do not use it: `claude plugin uninstall <plugin>`.

Either way a Claude Code restart is needed before the hooks can find a new program. Run
what they choose after the installer in §5. Installing software is outside this repo,
so it needs their yes like the rest.

If the plan ends with "optional tools missing", name each tool and what needs it, and
offer to install it with the command shown: `uv` (markdown-converter and
data-model-audit), PyYAML (the install report and `check_frontmatter.py`) and, on
Windows, tzdata (timesheet-recall). These never fail `--check`, so skipping them is
fine; the named skill or report just won't work until they are installed.

## 5. Apply

With their go-ahead for `--force`:

```bash
python scripts/install_vault.py --yes --force --wiki ../wiki
```

Without it:

```bash
python scripts/install_vault.py --yes --wiki ../wiki
```

The wiki steps run with the rest when the wiki is found. `--wiki-only --yes` runs only
them, and never a global step. The flag is only needed when the wiki is not at `../wiki`.

`hook runtimes` reads FAILED until the program from §4 is installed or its plugin
removed. That is expected, and its line names the fix. Read the result back: each step marked `done` or `FAILED`, the
gate lines, the "still needs you" list, and the verification summary with the path of its report in
`raw/output/`. If the plugin step failed, the line after FAILED gives the cause. It is
almost always the `claude` command or the login in §2. Fix that and run this section again; every other step
reports nothing to do.

## 6. Restart, then check

If the output says to restart Claude Code, or a runtime was installed in §4, tell the
person to do it now. Plugins, hooks and settings load only when a session starts. You cannot restart it yourself.

After the restart, when they say "check the vault":

```bash
python scripts/install_vault.py --check
```

Exit code 0 with every line `ok` is done. If a line still says `PENDING`, say which and
why, rather than calling the update done.

## 7. What is left for a person

Go through the "still needs you" list from §5 with them: git identity, any optional
tools still missing, and credentials. [[setup]] has the reasoning for each. Obsidian and the
`_local/` binding files are not part of the install for now: they
are set up by hand as they are added, so do not create, check or ask for them.

## Guard a client repo

A client's own repo can have its edits checked against that client's names, so a name
from another client cannot land in it. Run once per repo, from the brain:

    python scripts/install_vault.py --client-repo <path> --client <slug> --check
    python scripts/install_vault.py --client-repo <path> --client <slug> --yes

`<path>` must be the top of a git repo and `<slug>` must be a client in the wiki. The
command writes the gate into the repo's `.claude/settings.local.json`, ignores that file
through git's exclude file (never a committed file), and records the repo in
`_local/client-repos.json`. A second run changes nothing. It never touches the global
Claude settings.

## Schedule the nightly digest

`python scripts/install_vault.py --nightly --yes` (needs a configured wiki) schedules
`scripts/nightly_digest.py` at midnight, Pacific/Auckland. Linux: the systemd user timer
`brain-nightly-digest.timer`, with `Persistent=true` so a machine that was off runs the
missed day on its next boot. Windows: the Task Scheduler task `brain-nightly-digest`,
made from an XML file that starts when available. `--check` reports whether it is in
place and points at this brain. A second run changes nothing. The run needs `claude` and
`git` on the scheduler's PATH; the unit passes the current PATH on Linux.

Related: [[setup]] · [[vault-install-test-plan]] · [[new-machine]]
