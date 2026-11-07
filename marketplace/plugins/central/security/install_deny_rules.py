"""Add central's credential-file deny rules to a Claude Code settings file.

A plugin cannot ship permission rules: Claude Code drops every plugin setting
except `agent` and `subagentStatusLine`
(https://code.claude.com/docs/en/plugins/manifest-reference.md). So the rules
go into the user's own settings, by this script, run once per machine:

    python install_deny_rules.py                 # ~/.claude/settings.json
    python install_deny_rules.py --dry-run       # show what would be added
    python install_deny_rules.py --settings PATH # another file, e.g. managed settings

`Read` deny rules also cover Grep, Glob and the Bash file commands Claude Code
recognises, and unlike the PreToolUse gate they have no code that can fail
(https://code.claude.com/docs/en/permissions.md). The rules are added to
whatever is there and never replace it. The file is backed up first, and a
second run changes nothing.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
DATA = json.loads((HERE / "credential-files.json").read_text(encoding="utf-8"))
DEFAULT = pathlib.Path.home() / ".claude" / "settings.json"


def rules():
    # One rule per listed name. Read(**/.env.*) would also deny .env.example, and a
    # deny rule cannot be carved back out, so unlisted .env.<stage> files are caught
    # by the PreToolUse gate only (credential_paths.is_credential_path).
    return ([f"Read(**/{n})" for n in DATA["names"]]
            + [f"Read(**/*{s})" for s in DATA["suffixes"]]
            + [f"Read(~/{p})" for p in DATA["home_paths"]])


def merge(settings, new):
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    added = [r for r in new if r not in deny]
    deny.extend(added)
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--settings", type=pathlib.Path, default=DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    try:
        # utf-8-sig: Windows PowerShell 5.1 writes a BOM. The file is written back without one.
        settings = json.loads(a.settings.read_text(encoding="utf-8-sig")) if a.settings.exists() else {}
    except json.JSONDecodeError as exc:
        print(f"{a.settings} is not valid JSON ({exc.msg}, line {exc.lineno}); fix it first. Nothing changed.")
        return 1

    added = merge(settings, rules())
    if not added:
        print("All rules are already present. Nothing changed.")
        return 0
    for r in added:
        print(f"add     {r}")
    if a.dry_run:
        return 0
    if a.settings.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        backup = a.settings.with_name(f"{a.settings.name}.bak-{stamp}")
        shutil.copy2(a.settings, backup)
        print(f"backup  {backup}")
    else:
        a.settings.parent.mkdir(parents=True, exist_ok=True)
    a.settings.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"wrote   {a.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
