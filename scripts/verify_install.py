"""Run the install acceptance cases and export what passed, what failed, and what is left.

`_ai/vault-install-test-plan.md` lists the cases that prove a workstation is set
up. Most of them are a command and an expected answer, so this runs every one a
script can run without changing the machine, and writes the result to
`raw/output/install-report-<timestamp>.md` (R-48: gitignored, never committed).

    python scripts/verify_install.py

`install_vault.py` calls this at the end of every apply run, so a person who only
ever types "install the vault" still gets the report.

Three kinds of row come out:

  PASS / FAIL   run here, with the fix for every FAIL
  SKIP          could not run here, with the reason
  MANUAL        needs a person inside Claude Code or Obsidian; listed as a to-do

Read-only. The one case that needs a write, the guard refusing a commit on main,
runs in a throwaway repository under the system temp directory, never in this
clone. The failure cases (15 to 25) simulate a broken machine and are for
whoever changes the installer, so they are named in the report but not run.

Exits 1 when any case FAILs, 0 otherwise.
"""
import datetime
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import install_vault as iv  # noqa: E402

results = []


def record(case, name, status, detail="", fix=""):
    results.append((case, name, status, detail.strip(), fix.strip()))


def run(*args, cwd=ROOT, timeout=600, env=None):
    try:
        return subprocess.run(list(args), capture_output=True, text=True, cwd=str(cwd),
                              stdin=subprocess.DEVNULL, timeout=timeout, env=env,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as err:
        return subprocess.CompletedProcess(args, 1, "", str(err))


def last_line(result):
    lines = [l.strip() for l in (result.stdout + result.stderr).splitlines() if l.strip()]
    return lines[-1][:200] if lines else "exit " + str(result.returncode)


def py(script, *args):
    return run(sys.executable, str(SCRIPTS / script), *args)


# ---- prerequisites ---------------------------------------------------------
def prerequisites():
    for tool, fix in (("git", "run the script in _ai/new-machine.md"),
                      ("python", "run the script in _ai/new-machine.md"),
                      ("claude", "run the script in _ai/new-machine.md")):
        exe = shutil.which(tool)
        if exe:
            record("pre", tool + " on PATH", "PASS", last_line(run(exe, "--version")))
        else:
            record("pre", tool + " on PATH", "FAIL", "not found", fix)

    if os.name == "nt":
        longpaths = run("git", "config", "--global", "--get", "core.longpaths").stdout.strip()
        record("pre", "git core.longpaths", "PASS" if longpaths == "true" else "FAIL",
               "core.longpaths = " + (longpaths or "(unset)"),
               "git config --global core.longpaths true")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                enabled = winreg.QueryValueEx(key, "LongPathsEnabled")[0]
        except OSError:
            enabled = 0
        # A machine-wide setting that needs an administrator, so it is reported and
        # never required. git core.longpaths covers checkout; a short clone path
        # such as C:\vault keeps every file under Windows' 260 character limit.
        record("pre", "Windows LongPathsEnabled", "PASS" if enabled == 1 else "SKIP",
               "LongPathsEnabled = " + str(enabled) +
               ("" if enabled == 1 else " (machine setting, not required)"),
               "nothing to do as long as the vault is cloned at a short path such as "
               "C:\\vault")

    if shutil.which("gh"):
        r = run("gh", "auth", "status")
        said = [l.strip() for l in (r.stdout + r.stderr).splitlines() if "Logged in" in l]
        record("pre", "GitHub CLI logged in", "PASS" if r.returncode == 0 else "FAIL",
               said[0] if said else last_line(r), "gh auth login, and ask Daru for access to the GitHub organisation")
    else:
        record("pre", "GitHub CLI logged in", "SKIP", "gh is not installed",
               "only needed if the plugin step fails with `repository not found`")

    name = run("git", "config", "--get", "user.name").stdout.strip()
    email = run("git", "config", "--get", "user.email").stdout.strip()
    record("pre", "git identity", "PASS" if name and email else "FAIL",
           (name + " <" + email + ">") if name and email else "user.name or user.email unset",
           'git config --global user.name "Your Name"; '
           'git config --global user.email "you@example.nz"')


# ---- acceptance cases 5 to 12 ----------------------------------------------
def acceptance():
    r = py("install_vault.py", "--check")
    record("5", "install_vault.py --check", "PASS" if r.returncode == 0 else "FAIL",
           last_line(r), "python scripts/install_vault.py --yes "
           "(add --force only for a conflict you have read)")

    ok, (detail, _) = iv.step_hooks()
    record("6", "git guards armed", "PASS" if ok else "FAIL", detail,
           "python scripts/install_hooks.py")

    stale = iv.stale_skill_copies()
    record("7", "no loose skills in ~/.claude/skills", "FAIL" if stale else "PASS",
           ", ".join(stale) if stale else "none from the old layout",
           "python scripts/install_vault.py --yes --force (moves " + ", ".join(stale) +
           " to a backup folder)")

    if iv.claude_cli():
        # Same config directory as the installer: CLAUDE_CONFIG_DIR follows
        # VAULT_CLAUDE_HOME, so a rehearsal never reads the real ~/.claude.
        env = dict(os.environ)
        if env.get("VAULT_CLAUDE_HOME"):
            env["CLAUDE_CONFIG_DIR"] = env["VAULT_CLAUDE_HOME"]
        listing = run(iv.claude_cli(), "plugin", "list", env=env, timeout=120)
        text = listing.stdout + listing.stderr
        missing = [n + "@" + m for n, m, _ in iv.PLUGINS if (n + "@" + m) not in text]
        record("7a", "plugins installed", "FAIL" if missing else "PASS",
               "missing: " + ", ".join(missing) if missing else "all listed",
               iv.repo_access_fix() + ", then python scripts/install_vault.py --yes")
    else:
        record("7a", "plugins installed", "SKIP", "the claude CLI is not on PATH",
               iv.claude_cli_fix())

    try:
        settings = iv.read_settings(iv.settings_file())
        stale_gate = iv.gate_registered(settings)
        disabled = bool(settings.get("disableAllHooks"))
        bad = stale_gate or disabled
        detail = ("old prompt_gate.py hook still registered" if stale_gate else
                  "disableAllHooks is on" if disabled else
                  "no competing hook, hooks enabled")
        record("8", "global settings clean", "FAIL" if bad else "PASS", detail,
               "python scripts/install_vault.py --yes --force")
    except ValueError as err:
        record("8", "global settings clean", "FAIL",
               str(iv.settings_file()) + " is not valid JSON: " + str(err),
               "fix the JSON by hand; the installer will not overwrite it")

    # 8a, the prompt gate tests, left with central on 2026-11-07: no prompt gate
    # ships any more. The PreToolUse PII gate is still tested in the suite below.


    guard_refuses_main()


def guard_refuses_main():
    """Case 12, in a scratch repository so this clone's branch is never touched."""
    if not shutil.which("git"):
        record("12", "guard refuses a commit on main", "SKIP", "git is not on PATH")
        return
    with tempfile.TemporaryDirectory() as tmp:
        run("git", "init", "-q", "-b", "main", cwd=tmp)
        env_allow = os.environ.pop("VAULT_ALLOW_MAIN", None)
        try:
            r = run(sys.executable, str(SCRIPTS / "hooks_guard.py"), "pre-commit", cwd=tmp)
        finally:
            if env_allow is not None:
                os.environ["VAULT_ALLOW_MAIN"] = env_allow
    record("12", "guard refuses a commit on main", "PASS" if r.returncode == 1 else "FAIL",
           "refused" if r.returncode == 1 else last_line(r),
           "python scripts/install_hooks.py, then tell Daru: hooks_guard.py let main through")


# ---- the automated suites from section 3 -----------------------------------
SUITES = (
    ("test_install_vault.py", "installer unit tests"),
    ("test_review_output.py", "Stop gate tests"),
    ("test_pii_gate.py", "PreToolUse PII gate tests"),
    ("check_schema_sync.py", "schema in sync"),
)

# The two wiki checks read the wiki's own files, so they run with the wiki as cwd.
# check_maps.py and check_frontmatter.py look at ./ and nothing else.
WIKI_SUITES = (
    ("check_maps.py", "router matches reality"),
    ("check_frontmatter.py", "every note well formed"),
)
WIKI_IMPORT = "wiki imports this brain's CLAUDE.md"
WIKI_FIX = "python scripts/install_vault.py --wiki-only --yes --wiki <path to the wiki clone>"


def brain_import_check(wiki):
    """(PASS or FAIL, detail): the wiki's _local/brain.md imports this brain's CLAUDE.md."""
    path = wiki / "_local" / "brain.md"
    if not path.is_file():
        return "FAIL", "_local/brain.md is missing in the wiki"
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    line = next((l for l in lines if l.startswith("@")), "")
    if not line:
        return "FAIL", "_local/brain.md holds no @ import"
    target = pathlib.Path(os.path.expanduser(line[1:])).resolve()
    if target == (ROOT / "CLAUDE.md").resolve():
        return "PASS", line
    return "FAIL", "_local/brain.md imports " + line + ", not this brain's CLAUDE.md"


def wiki_suites(wiki):
    """The wiki checks, run in the wiki. With no wiki each one is SKIPPED with the reason."""
    if wiki is None:
        for script, name in WIKI_SUITES:
            record("wiki", name + " (" + script + ")", "SKIP", "wiki not configured",
                   "python scripts/install_vault.py --wiki <path to the wiki clone>")
        record("wiki", WIKI_IMPORT, "SKIP", "wiki not configured", WIKI_FIX)
        return
    for script, name in WIKI_SUITES:
        r = run(sys.executable, str(SCRIPTS / script), cwd=wiki)
        record("wiki", name + " (" + script + ")", "PASS" if r.returncode == 0 else "FAIL",
               last_line(r), "run python " + str(SCRIPTS / script) + " in " + str(wiki)
               + " and read its errors")
    status, detail = brain_import_check(wiki)
    record("wiki", WIKI_IMPORT, status, detail, WIKI_FIX)


def suites():
    for script, name in SUITES:
        r = py(script)
        record("suite", name + " (" + script + ")", "PASS" if r.returncode == 0 else "FAIL",
               last_line(r), "python scripts/" + script + " and read its errors")
    try:
        import pytest  # noqa: F401
    except ImportError:
        record("suite", "setup script tests (test_setup_vault.py)", "SKIP",
               "pytest is not installed", "pip install pytest, then rerun this")
        return
    r = run(sys.executable, "-m", "pytest", "-q", str(SCRIPTS / "test_setup_vault.py"))
    record("suite", "setup script tests (test_setup_vault.py)",
           "PASS" if r.returncode == 0 else "FAIL", last_line(r),
           "python -m pytest scripts/test_setup_vault.py -v")


# ---- what only a person can check --------------------------------------------
MANUAL = (
    ("7b", "In Claude Code, ask it to use `superpowers:systematic-debugging`. It resolves, "
           "and no bare `systematic-debugging` competes with it."),
    ("11", "Start a new Claude Code session in this folder. The SessionStart gate line "
           "prints."),
    ("13", "Ask Claude to write any file to `raw/output/`, then end the turn. The triage "
           "review opens once."),
    ("14", "End a second turn without triaging. The gate stays silent."),
    ("credentials", "Put credentials in each tool's own config, never in this repo (R-30)."),
)


def blank_bindings():
    blank = [k for k in iv.FIELDS if not iv.detect().get(k)]
    if blank:
        return ("python scripts/install_vault.py --bindings "
                + " ".join(k + "=..." for k in blank))
    return ""


# ---- report ------------------------------------------------------------------
def render(stamp):
    passed = [r for r in results if r[2] == "PASS"]
    failed = [r for r in results if r[2] == "FAIL"]
    skipped = [r for r in results if r[2] == "SKIP"]
    out = ["# Install report " + stamp, "",
           "Machine: " + platform.system() + " " + platform.release()
           + ", Python " + platform.python_version(),
           "Clone: `" + str(ROOT) + "`", "",
           f"{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped, "
           f"{len(MANUAL)} manual checks left.", ""]

    out += ["## Failed", ""]
    if failed:
        for case, name, _, detail, fix in failed:
            label = f" (case {case})" if case[0].isdigit() else ""
            out.append(f"- **{name}**{label}: {detail}")
            out.append(f"  - Fix: `{fix}`" if fix else "")
    else:
        out.append("Nothing failed.")
    out.append("")

    if skipped:
        out += ["## Skipped", ""]
        for case, name, _, detail, fix in skipped:
            out.append(f"- **{name}**: {detail}" + (f". {fix}" if fix else ""))
        out.append("")

    out += ["## Passed", ""]
    for case, name, _, detail, _ in passed:
        out.append(f"- {name}: {detail}")
    out.append("")

    out += ["## Still needs you", ""]
    for case, text in MANUAL:
        out.append(f"- [ ] ({case}) {text}")
    out.append("")

    out += ["## Not run", "",
            "Failure cases 15 to 25 in `_ai/vault-install-test-plan.md` simulate a broken "
            "machine. Run them when changing the installer, not when setting one up.", ""]
    return "\n".join(l for l in out if l is not None)


def main():
    # A piped Windows console is cp1252, and gh prints a check mark.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print("verifying the install against _ai/vault-install-test-plan.md ...")
    prerequisites()
    acceptance()
    suites()
    wiki_suites(iv.find_wiki())

    for case, name, status, detail, _ in results:
        print(f"  {status:<5} {name}: {detail}")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    target = ROOT / "raw" / "output"
    target.mkdir(parents=True, exist_ok=True)
    path = target / ("install-report-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                     + ".md")
    path.write_text(render(stamp), encoding="utf-8", newline="\n")

    failed = sum(1 for r in results if r[2] == "FAIL")
    print(f"\n{failed} failed. Report: {path}" if failed else f"\nall automated checks passed. "
          f"Report, with the manual checks left: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
