"""Point this clone's git at .githooks/.

Hooks live in .git/hooks/, which git never clones -- so a guard that is only
installed on one laptop protects only that laptop. `core.hooksPath` is per-clone
config, so every person who clones this vault runs this once. There is no way to
make it automatic; that is git's design, not an oversight.

    python scripts/install_hooks.py            enable
    python scripts/install_hooks.py --check    report, change nothing
    python scripts/install_hooks.py --remove   disable
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ".githooks"


def config(*args):
    return subprocess.run(["git", "-C", str(ROOT), "config", *args],
                          capture_output=True, text=True).stdout.strip()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    current = config("--get", "core.hooksPath")

    if arg == "--check":
        print(f"core.hooksPath = {current or '(unset)'}")
        print("enabled" if current == HOOKS else "NOT enabled -- run: python scripts/install_hooks.py")
        return 0 if current == HOOKS else 1

    if arg == "--remove":
        subprocess.run(["git", "-C", str(ROOT), "config", "--unset", "core.hooksPath"])
        print("vault guards disabled. Nothing now stops a commit on main or a secret.")
        return 0

    names = ("pre-commit", "commit-msg", "pre-push", "pre-merge-commit", "_python")
    missing = [h for h in names if not (ROOT / HOOKS / h).exists()]
    if missing:
        print(f"missing hook files: {', '.join(missing)}")
        return 1

    # git SILENTLY SKIPS a hook that is not executable, so a bad mode looks
    # exactly like working protection. Windows clones set core.fileMode=false and
    # record 100644, which is fine there (git runs hooks through sh) and fatal on
    # macOS and Linux. Repair the bit rather than warn about it.
    ls = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", HOOKS],
                        capture_output=True, text=True).stdout
    flat = [ln.split()[-1] for ln in ls.splitlines() if ln.startswith("100644")]
    if flat:
        subprocess.run(["git", "-C", str(ROOT), "update-index", "--chmod=+x", *flat])
        print(f"repaired the executable bit on: {', '.join(f.split('/')[-1] for f in flat)}")
    for h in names:
        f = ROOT / HOOKS / h
        f.chmod(f.stat().st_mode | 0o111)

    subprocess.run(["git", "-C", str(ROOT), "config", "core.hooksPath", HOOKS], check=True)
    print(f"core.hooksPath -> {HOOKS}")
    print("Guards now run on commit and push. See scripts/hooks_guard.py for what they block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
