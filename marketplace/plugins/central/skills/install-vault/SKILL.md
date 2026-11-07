---
name: install-vault
description: >-
  Install or update the vault on this machine, from a fresh clone or over
  an older install, by following the vault's own _ai/update.md. Use when the
  user says "install the vault", "update the vault", "check the vault", "set up
  the vault", "set this up on my machine", asks what a new machine needs, or
  types /install-vault. Do NOT use for ordinary vault work, and do not run it
  unasked in an already-installed clone.
allowed-tools: Read, Bash, Edit
metadata:
  scope: vault-bound
---

# install-vault

> **Answers:** What happens when someone says "install the vault" or "update the
> vault"?

The steps live in the vault, in `_ai/update.md`, not here. This skill ships in
central, and central is exactly what is missing or out of date on the
workstations that need an update most. The note arrives with `git pull`, so it
always matches the installer in the same commit. Keeping a second copy here would
let the two drift.

## What to do

1. Make sure you are in a vault clone: `scripts/install_vault.py` exists at
   the repository root. If it does not, say so and stop. A machine without the
   vault starts with `scripts/setup_vault.py`, which the vault's `_ai/setup.md` covers.
2. Read `_ai/update.md` and follow it from §1. It asks before pulling, pulls, and
   then has you re-read it, so the steps you finish with are the current ones.
3. If `_ai/update.md` does not exist, the clone predates it. Ask before running
   `git pull` on `main`, since a pull is a git operation the vault's `CLAUDE.md`
   puts on the "ask first" list, then read the note. If it is still missing after
   the pull, run `python scripts/install_vault.py --dry-run`, show the plan, and
   ask before applying anything.

Do not apply the installer from memory of an earlier version of this skill. The
note is the contract.
