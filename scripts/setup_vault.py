#!/usr/bin/env python3
"""Set up a company workspace on a new machine, in one command.

`_ai/setup.md` describes this by hand. Prose rots silently: at the time this
script was written, setup.md told the reader to `@import` a master note that does
not exist, and to copy `_local/*.template.md` files that cannot survive a clone
because `_local/` is wholly gitignored. Two of its five steps were impossible to
follow and nothing caught it. A script is executable, so it fails loudly instead.

    python setup_vault.py              # interview, show the plan, confirm, apply
    python setup_vault.py --dry-run    # interview and show the plan, change nothing

Three questions, always the same three, always in this order:

    1. Where should the workspace live?
    2. Git name, then email.
    3. Install Obsidian?              (skipped when it is already installed)

The interview is a pure function over an IO facade (`ask`), so the whole thing
replays from a list of canned answers in tests and the resulting plan can be
asserted exactly. Side effects live in `apply`, behind a printed plan and one
confirmation, so nothing happens that was not shown first.

Self-contained on purpose. It imports nothing from the vault, so it can be
downloaded and run BEFORE the vault exists - which is the situation it is for.
Run from inside an existing clone it detects that and skips what is already done.

Every step is idempotent. Re-running on a configured machine prints an empty
plan and exits.

This script never asks for a secret. It asks which tools you use and writes
placeholders naming the file each real credential belongs in. Vault rule R-30:
secrets live in the tools' own config, never in a note.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

VAULT_REPO = "https://github.com/<owner>/vault.git"
VAULT_DIR = "vault"
# The brain is VAULT_DIR; the knowledge base is the wiki, cloned next to it.
WIKI_REPO = "https://github.com/DataWithDaru/wiki.git"
WIKI_DIR = "wiki"


# ---------------------------------------------------------------------------
# IO facade
# ---------------------------------------------------------------------------

class ConsoleIO:
    def ask(self, prompt, default=None):
        hint = f" [{default}]" if default else ""
        return input(f"{prompt}{hint}: ").strip() or (default or "")

    def confirm(self, prompt, default=False):
        hint = "Y/n" if default else "y/N"
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if not answer:
            return default
        return answer in ("y", "yes")

    def tell(self, message=""):
        print(message)


@dataclass
class ScriptedIO:
    """Replays canned answers. Lets the interview be tested end to end."""

    answers: list = field(default_factory=list)
    output: list = field(default_factory=list)

    def _next(self):
        return self.answers.pop(0).strip() if self.answers else ""

    def ask(self, prompt, default=None):
        self.output.append(prompt)
        return self._next() or (default or "")

    def confirm(self, prompt, default=False):
        self.output.append(prompt)
        answer = self._next().lower()
        if not answer:
            return default
        return answer in ("y", "yes")

    def tell(self, message=""):
        self.output.append(message)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@dataclass
class Detected:
    """What is already true about this machine, before we ask anything."""

    platform: str = "windows"
    obsidian_exe: Path = None
    obsidian_running: bool = False
    git_name: str = ""
    git_email: str = ""
    vault_registered: bool = False
    wsl: bool = False


def platform_name(system=None):
    name = (system or _platform.system()).lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def is_wsl():
    """WSL reports itself as Linux, so platform_name() alone cannot tell them
    apart. /proc/version carries the marker on both WSL 1 and 2."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def default_workspace(platform=None):
    """On Windows the workspace is the root of C:, so the vault lands at
    C:\vault: a short path outside the user profile, clear of OneDrive
    folder redirection and the 260-character path limit. Everywhere else
    ~/workspace is the convention - and on WSL ~/Documents usually does not exist
    at all, so defaulting there would create an empty folder the user never
    asked for."""
    platform = platform or platform_name()
    if platform == "windows":
        return Path("C:/")
    return Path.home() / "workspace"


# Derived, not literal: the right default differs per platform. Kept as a
# module constant so callers and tests can refer to one value.
DEFAULT_WORKSPACE = default_workspace()


def obsidian_registry(platform=None):
    """Obsidian's list of known vaults. Undocumented, found by inspection."""
    platform = platform or platform_name()
    if platform == "windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif platform == "macos":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "obsidian" / "obsidian.json"


def find_obsidian(platform=None):
    """Where Obsidian actually is, or None.

    `shutil.which` alone is not enough: on Windows the installer does not put
    Obsidian on PATH, so a PATH-only check reports "missing" on a machine that
    has it and the script offers to install it again.
    """
    platform = platform or platform_name()
    found = shutil.which("obsidian")
    if found:
        return Path(found)
    candidates = []
    if platform == "windows":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        candidates = [local / "Obsidian" / "Obsidian.exe",
                      Path("C:/Program Files/Obsidian/Obsidian.exe")]
    elif platform == "macos":
        candidates = [Path("/Applications/Obsidian.app")]
    else:
        candidates = [Path("/usr/bin/obsidian"), Path("/opt/Obsidian/obsidian")]
    for c in candidates:
        if c.exists():
            return c
    # A registry file is proof it has run here, even if the binary moved.
    reg = obsidian_registry(platform)
    if reg.exists():
        return reg
    return None


def describe_obsidian(found):
    """Say what was actually found. `find_obsidian` falls back to the registry
    file, which proves Obsidian has run here but is not the binary - reporting
    that path as the install location reads as a bug."""
    if found is None:
        return "not found"
    if found.name == "obsidian.json":
        return f"has run on this machine (registry at {found})"
    return f"installed at {found}"


def is_obsidian_running(platform=None):
    platform = platform or platform_name()
    try:
        if platform == "windows":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                 capture_output=True, text=True, timeout=10).stdout
            return "Obsidian.exe" in out
        out = subprocess.run(["pgrep", "-i", "obsidian"],
                             capture_output=True, text=True, timeout=10)
        return out.returncode == 0
    except Exception:
        return False        # cannot tell; register_vault still backs up first


def git_identity():
    def cfg(key):
        try:
            r = subprocess.run(["git", "config", "--global", key],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip()
        except Exception:
            return ""
    return cfg("user.name"), cfg("user.email")


def vault_is_registered(registry, vault_path):
    try:
        data = json.loads(Path(registry).read_text(encoding="utf-8"))
    except Exception:
        return False
    target = str(Path(vault_path))
    return any(str(Path(v.get("path", ""))) == target
               for v in data.get("vaults", {}).values())


def detect(platform=None):
    platform = platform or platform_name()
    exe = find_obsidian(platform)
    name, email = git_identity()
    return Detected(platform=platform, obsidian_exe=exe,
                    obsidian_running=is_obsidian_running(platform) if exe else False,
                    git_name=name, git_email=email, wsl=is_wsl())


# ---------------------------------------------------------------------------
# The interview - pure, no side effects
# ---------------------------------------------------------------------------

@dataclass
class Answers:
    workspace: Path
    git_name: str
    git_email: str
    install_obsidian: bool


def ask(io, detected):
    """The three questions. Same order, same defaults, every time."""
    io.tell("Company workspace setup. Three questions, then a plan you confirm.")
    io.tell()

    if detected.wsl:
        io.tell("Detected WSL. Defaulting to a Linux-side path, ~/workspace, rather "
                "than the Windows C:\vault.")
    raw = io.ask("1. Where should the workspace live?", str(DEFAULT_WORKSPACE))
    workspace = Path(raw).expanduser()

    git_name = io.ask("2. Git name", detected.git_name or None)
    git_email = io.ask("   Git email", detected.git_email or None)

    if detected.obsidian_exe:
        io.tell(f"3. Obsidian: {describe_obsidian(detected.obsidian_exe)} - skipping install.")
        install_obsidian = False
    else:
        install_obsidian = io.confirm("3. Install Obsidian?", default=True)

    return Answers(workspace=workspace, git_name=git_name, git_email=git_email,
                   install_obsidian=install_obsidian)


# ---------------------------------------------------------------------------
# The plan - what apply() would do, as text, before it does any of it
# ---------------------------------------------------------------------------

def plan(answers, detected):
    steps = []
    ws = answers.workspace
    if not ws.exists():
        steps.append(f"create {ws}")
    if not (ws / VAULT_DIR / ".git").exists():
        steps.append(f"clone {VAULT_REPO} -> {ws / VAULT_DIR}")
    if not (ws / WIKI_DIR / ".git").exists():
        steps.append(f"clone {WIKI_REPO} -> {ws / WIKI_DIR}")
    if answers.git_name and answers.git_name != detected.git_name:
        steps.append(f"git config --global user.name {answers.git_name!r}")
    if answers.git_email and answers.git_email != detected.git_email:
        steps.append(f"git config --global user.email {answers.git_email!r}")
    if answers.install_obsidian:
        steps.append("install Obsidian")
    if not detected.vault_registered:
        steps.append(f"register {ws / WIKI_DIR} as an Obsidian vault")
    return steps


# ---------------------------------------------------------------------------
# Obsidian vault registration
# ---------------------------------------------------------------------------

def register_vault(registry, vault_path, obsidian_running):
    """Add `vault_path` to Obsidian's known vaults. Returns (ok, message).

    This file is undocumented - its shape was established by reading one. Three
    refusals follow from that, and each one leaves the file byte-identical:

      running       Obsidian rewrites obsidian.json when it exits, so an edit
                    made while it is open is silently discarded. Worse, the user
                    believes it worked.
      unparseable   Overwriting a file we cannot read loses every vault in it.
      wrong shape   If a future Obsidian changes the format, guessing at it is
                    how you corrupt someone's entire vault list. Say so instead.
    """
    registry = Path(registry)
    if obsidian_running:
        return False, ("Obsidian is running - it would overwrite this change on "
                       "exit. Quit Obsidian and re-run, or add the vault by hand "
                       "with Open folder as vault.")

    if registry.exists():
        raw = registry.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except ValueError:
            return False, (f"{registry} is not valid JSON. Not touching it - "
                           "add the vault by hand with Open folder as vault.")
        if not isinstance(data, dict) or not isinstance(data.get("vaults"), dict):
            return False, (f"{registry} is not in the expected format (no "
                           "'vaults' object). Obsidian may have changed it. Not "
                           "guessing - add the vault by hand.")
        backup = registry.with_suffix(f".json.bak.{int(time.time())}")
        backup.write_text(raw, encoding="utf-8")
    else:
        data = {"vaults": {}}
        registry.parent.mkdir(parents=True, exist_ok=True)

    target = str(Path(vault_path))
    for entry in data["vaults"].values():
        if str(Path(entry.get("path", ""))) == target:
            return True, f"already registered: {target}"

    data["vaults"][secrets.token_hex(8)] = {
        "path": target,
        "ts": int(time.time() * 1000),
    }
    registry.write_text(json.dumps(data), encoding="utf-8")
    return True, f"registered: {target}"


def obsidian_install_command(platform):
    """None means 'we do not install on this platform, report instead'."""
    if platform == "windows":
        # Per user, so it never asks for an administrator.
        return ["winget", "install", "--id", "Obsidian.Obsidian", "-e", "--scope", "user",
                "--accept-source-agreements", "--accept-package-agreements",
                "--disable-interactivity"]
    if platform == "macos":
        return ["brew", "install", "--cask", "obsidian"]
    return None


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def run(cmd, cwd=None, io=None):
    """One external command. Failures are reported, never fatal - a machine
    missing winget should not cost you the git config you already asked for."""
    if io:
        io.tell(f"  $ {' '.join(str(c) for c in cmd)}")
    try:
        r = subprocess.run(cmd, cwd=cwd, text=True)
        return r.returncode == 0
    except FileNotFoundError:
        if io:
            io.tell(f"  ! {cmd[0]} not found - skipped")
        return False
    except Exception as e:
        if io:
            io.tell(f"  ! failed: {e}")
        return False


def installer_command(ws):
    """The one command that wires this machine to the wiki (install_vault.py --wiki)."""
    return (f"python {ws / VAULT_DIR / 'scripts' / 'install_vault.py'} "
            f"--wiki {ws / WIKI_DIR}")


def apply(answers, detected, io):
    ws = answers.workspace
    ws.mkdir(parents=True, exist_ok=True)

    if (ws / VAULT_DIR / ".git").exists():
        io.tell(f"  {VAULT_DIR}: already cloned")
    elif not run(["git", "clone", VAULT_REPO, str(ws / VAULT_DIR)], io=io):
        io.tell(f"  ! could not clone {VAULT_DIR}. If the repo does not exist "
                "yet, create it and re-run - everything else is done.")

    if (ws / WIKI_DIR / ".git").exists():
        io.tell(f"  {WIKI_DIR}: already cloned")
    elif not run(["git", "clone", WIKI_REPO, str(ws / WIKI_DIR)], io=io):
        io.tell(f"  ! could not clone {WIKI_DIR}. Check access to {WIKI_REPO}, "
                "then re-run - everything else is done.")

    if answers.git_name and answers.git_name != detected.git_name:
        run(["git", "config", "--global", "user.name", answers.git_name], io=io)
    if answers.git_email and answers.git_email != detected.git_email:
        run(["git", "config", "--global", "user.email", answers.git_email], io=io)

    if answers.install_obsidian:
        cmd = obsidian_install_command(detected.platform)
        if cmd is None:
            io.tell("  Obsidian: install it from https://obsidian.md/download "
                    "(no scripted install on this platform)")
        else:
            run(cmd, io=io)

    vault_path = ws / WIKI_DIR
    if vault_path.exists():
        ok, msg = register_vault(obsidian_registry(detected.platform), vault_path,
                                 is_obsidian_running(detected.platform))
        io.tell(f"  Obsidian vault: {msg}")

    io.tell()
    io.tell(f"Connect the brain to the wiki: {installer_command(ws)}")
    io.tell("Done. Next: open the wiki in Obsidian and read index.md.")
    io.tell("Secrets (Paymo, Google, Snowflake) are not handled here - see "
            "_ai/setup.md; they live in each tool's own config, never in a note.")


# ---------------------------------------------------------------------------

def main(argv=None, io=None):
    parser = argparse.ArgumentParser(description="Set up a company workspace.")
    parser.add_argument("--dry-run", action="store_true",
                        help="ask, show the plan, change nothing")
    args = parser.parse_args(argv)
    io = io or ConsoleIO()

    detected = detect()
    answers = ask(io, detected)
    # Only now do we know which folder the vault will live in, so this is the
    # first point at which "is it already a known Obsidian vault?" is answerable.
    # Without it the plan promises to register a vault that is already registered.
    detected.vault_registered = vault_is_registered(
        obsidian_registry(detected.platform), answers.workspace / WIKI_DIR)
    steps = plan(answers, detected)

    io.tell()
    if not steps:
        io.tell("Nothing to do - this machine is already set up.")
        return 0
    io.tell("Plan:")
    for s in steps:
        io.tell(f"  - {s}")
    io.tell()

    if args.dry_run:
        io.tell("Dry run - nothing was changed.")
        return 0
    if not io.confirm("Proceed?", default=True):
        io.tell("Stopped. Nothing was changed.")
        return 1

    apply(answers, detected, io)
    return 0


if __name__ == "__main__":
    sys.exit(main())
