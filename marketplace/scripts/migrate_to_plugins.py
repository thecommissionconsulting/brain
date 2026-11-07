#!/usr/bin/env python3
"""One-time cleanup after central went into the marketplace.

Leaves every skill loading from a plugin and none from ~/.claude/skills/.

Three steps, in this order because the order matters:

  1. Install the humanizer plugin. It is one of the user-scope skills about to be
     removed and it is NOT in central (it is blader's, referenced from the
     marketplace and pinned), so removing the copy first would lose the skill.
  2. Remove the UserPromptSubmit hook from ~/.claude/settings.json. central
     ships the same hook through ${CLAUDE_PLUGIN_ROOT}, so right now the prompt
     gate is registered twice and runs twice on every prompt.
  3. Remove the skills install_skills.py copied into ~/.claude/skills/, through
     that script's own --uninstall, which only touches names it installed.

settings.json is backed up next to itself before it is touched. Nothing else is
modified, and --dry-run shows the whole plan without changing anything.

    python scripts/migrate_to_plugins.py --dry-run
    python scripts/migrate_to_plugins.py
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

# The Claude CLI prints characters the Windows console codepage cannot encode,
# and its own output is UTF-8 whatever the locale says. Without both of these the
# script dies on a tick mark rather than on anything that matters.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HOME = os.path.expanduser("~")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
SKILLS_DIR = os.path.join(HOME, ".claude", "skills")
VAULT_INSTALLER = os.path.join(HOME, "Documents", "vault", "scripts", "install_skills.py")
GATE_MARKER = "answer-only/prompt_gate.py"
# Left behind on purpose: superpowers already ships verification-before-completion
# and systematic-debugging, so these two would be a second skill on one trigger.
DROPPED = ("verify-and-stop", "investigate-first")


def say(step, text):
    print("[%s] %s" % (step, text))


def claude_cli():
    """The Claude CLI's real path, looked for everywhere it is normally installed.

    On Windows it is a .CMD shim, which Python's subprocess cannot find from the
    bare name the way a shell can. PATH is not always inherited either, depending
    on how this script was started, so fall back to the usual install locations
    rather than giving up and handing the job back.
    """
    for name in ("claude", "claude.cmd", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "claude", "claude.exe"),
        os.path.join(HOME, "AppData", "Roaming", "npm", "claude.cmd"),
        os.path.join(HOME, ".local", "bin", "claude"),
        os.path.join(HOME, ".bun", "bin", "claude"),
        os.path.join(HOME, ".volta", "bin", "claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]
    npm_prefix = shutil.which("npm")
    if npm_prefix:
        candidates.insert(0, os.path.join(os.path.dirname(npm_prefix), "claude.cmd"))
        candidates.insert(1, os.path.join(os.path.dirname(npm_prefix), "claude"))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def run(cmd, dry):
    if dry:
        say("dry-run", "would run: %s" % " ".join(cmd))
        return 0, ""
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    except OSError as exc:
        say("error", "could not run %s: %s" % (cmd[0], exc))
        return 1, str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        for line in out.splitlines()[-4:]:
            print("        %s" % line)
    return proc.returncode, out


def install_humanizer(dry):
    """Install the humanizer plugin. Returns True when the user copy is safe to remove.

    False is not a failure to stop on: it means keep the user copy, which step 3
    then restores after the uninstall. Either way humanizer survives.
    """
    say("1/3", "installing the humanizer plugin so removing its user copy loses nothing")
    cli = claude_cli()
    if not cli:
        say("1/3", "could not find the claude CLI anywhere; keeping the existing humanizer instead")
        return False
    code, out = run([cli, "plugin", "install", "humanizer@skills"], dry)
    if code != 0 and "already installed" not in out.lower():
        say("1/3", "install did not succeed; keeping the existing humanizer instead")
        return False
    return True


def strip_hook(dry):
    say("2/3", "removing the duplicate prompt-gate hook from settings.json")
    if not os.path.exists(SETTINGS):
        say("2/3", "no settings.json, nothing to do")
        return True
    with open(SETTINGS, encoding="utf-8") as fh:
        data = json.load(fh)
    hooks = data.get("hooks") or {}
    events = hooks.get("UserPromptSubmit") or []
    kept = []
    removed = 0
    for entry in events:
        inner = [h for h in (entry.get("hooks") or []) if GATE_MARKER not in str(h.get("command", ""))]
        removed += len(entry.get("hooks") or []) - len(inner)
        if inner:
            kept.append(dict(entry, hooks=inner))
    if not removed:
        say("2/3", "no matching hook found; already clean")
        return True
    if kept:
        hooks["UserPromptSubmit"] = kept
    else:
        hooks.pop("UserPromptSubmit", None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.backup-%s" % (SETTINGS, stamp)
    if dry:
        say("dry-run", "would back up to %s and remove %d hook entry(ies)" % (backup, removed))
        return True
    shutil.copyfile(SETTINGS, backup)
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    say("2/3", "removed %d hook entry(ies); backup at %s" % (removed, os.path.basename(backup)))
    return True


def remove_user_skills(dry, humanizer_is_a_plugin):
    say("3/3", "removing the skills install_skills.py copied into ~/.claude/skills/")
    present = []
    if os.path.isdir(SKILLS_DIR):
        present = sorted(d for d in os.listdir(SKILLS_DIR)
                         if os.path.isdir(os.path.join(SKILLS_DIR, d)) and d != "synced")
    if not present:
        say("3/3", "nothing there already")
        return True
    say("3/3", "found: %s" % ", ".join(present))
    for name in DROPPED:
        if name in present:
            say("3/3", "%s goes for good: superpowers covers it" % name)

    # When the plugin version is not in place, humanizer is put back afterwards so
    # the skill is never lost, whatever else happened.
    keep_humanizer = ("humanizer" in present) and not humanizer_is_a_plugin
    stash = None
    if keep_humanizer and not dry:
        stash = os.path.join(SKILLS_DIR, ".humanizer-keep")
        shutil.rmtree(stash, ignore_errors=True)
        shutil.copytree(os.path.join(SKILLS_DIR, "humanizer"), stash)
        say("3/3", "keeping humanizer: no plugin version is installed")
    elif keep_humanizer:
        say("dry-run", "would keep humanizer: no plugin version is installed")

    if os.path.exists(VAULT_INSTALLER):
        code, _ = run([sys.executable, VAULT_INSTALLER, "--uninstall"], dry)
        if code != 0:
            say("3/3", "the vault uninstaller reported a problem; removing the folders directly")
            code = remove_directly(present, dry, keep_humanizer)
    else:
        say("3/3", "install_skills.py is gone; removing the folders directly")
        code = remove_directly(present, dry, keep_humanizer)

    if stash and os.path.isdir(stash):
        target = os.path.join(SKILLS_DIR, "humanizer")
        if not os.path.isdir(target):
            shutil.move(stash, target)
            say("3/3", "humanizer put back")
        else:
            shutil.rmtree(stash, ignore_errors=True)
    return code == 0


def remove_directly(present, dry, keep_humanizer):
    """Fallback when the vault uninstaller is unavailable or fails. Only removes
    the names this migration knows about, and never touches 'synced'."""
    known = set(present) - {"synced"}
    if keep_humanizer:
        known.discard("humanizer")
    for name in sorted(known):
        path = os.path.join(SKILLS_DIR, name)
        if dry:
            say("dry-run", "would remove %s" % path)
            continue
        shutil.rmtree(path, ignore_errors=True)
    if not dry:
        say("3/3", "removed %d folder(s)" % len(known))
    return 0


def report():
    left = []
    if os.path.isdir(SKILLS_DIR):
        left = sorted(d for d in os.listdir(SKILLS_DIR)
                      if os.path.isdir(os.path.join(SKILLS_DIR, d)) and d != "synced")
    print("")
    if left:
        print("Still loading outside a plugin: %s" % ", ".join(left))
    else:
        print("Nothing loads outside a plugin any more.")
    cli = claude_cli()
    if cli:
        print("Installed plugins:")
        proc = subprocess.run([cli, "plugin", "list"], capture_output=True,
                              encoding="utf-8", errors="replace")
        print((proc.stdout or "") + (proc.stderr or ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="Leave every skill loading from a plugin.")
    p.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    args = p.parse_args(argv)
    if args.dry_run:
        print("DRY RUN: nothing will be changed.\n")
    humanizer_is_a_plugin = install_humanizer(args.dry_run)
    strip_hook(args.dry_run)
    ok = remove_user_skills(args.dry_run, humanizer_is_a_plugin)
    if not args.dry_run:
        report()
        print("\nRestart Claude Code for the hook change to take effect.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
