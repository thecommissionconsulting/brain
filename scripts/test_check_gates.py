"""Cases for check_gates.py, run from the repo root: python scripts/test_check_gates.py

Each case builds a small brain in the temp directory (a rules file and gate files) and
checks the result. The last case reads the real _ai/rules.md of this checkout.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_gates", ROOT / "scripts" / "check_gates.py")
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(50) +
          "want " + str(want)[:40].ljust(40) + " got " + str(got)[:40])


def reg(rule_id, level, gate, status="ok"):
    return "| %s | Test | A rule | §Test | %s | %s | %s |" % (rule_id, gate, level, status)


def make_brain(base, rows, files):
    """A temp brain: _ai/rules.md from the rows, and each file from the mapping."""
    brain = pathlib.Path(base)
    (brain / "_ai").mkdir(parents=True, exist_ok=True)
    text = "# Rules\n\n| ID | Area | Rule | Written in | Enforced by | Level | Status |\n" \
           "|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    (brain / "_ai" / "rules.md").write_text(text, encoding="utf-8")
    for path, body in files.items():
        target = brain / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return brain


def run_cli(brain):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "check_gates.py")],
                          capture_output=True, text=True, encoding="utf-8", cwd=str(brain))


def main():
    print("register parsing")
    real = cg.rows((ROOT / "_ai" / "rules.md").read_text(encoding="utf-8"))
    hard = [r for r in real if "HARD" in r["level"]]
    case("the real register has at least 10 HARD rows", len(hard) >= 10, True)
    case("a register row gives id, gate and level", real[0]["id"].startswith("R-"), True)
    case("a register row gives its gate cell", isinstance(real[0]["gate"], str), True)

    print("bare-name resolution")
    with tempfile.TemporaryDirectory() as tmp:
        files = {
            "scripts/alpha.py": "# R-101 lives here\n",
            ".githooks/pre-commit.sh": "echo R-102\n",
            ".github/workflows/branch.yml": "name: R-103\n",
            ".gitignore": "_local/\n",
        }
        brain = make_brain(tmp, [], files)
        case("scripts/ is searched", cg.resolve("alpha.py", brain),
             brain / "scripts" / "alpha.py")
        case(".githooks/ is searched", cg.resolve("pre-commit.sh", brain),
             brain / ".githooks" / "pre-commit.sh")
        case(".github/workflows/ is searched", cg.resolve("branch.yml", brain),
             brain / ".github" / "workflows" / "branch.yml")
        case("the repo root is searched", cg.resolve(".gitignore", brain), brain / ".gitignore")
        case("a missing name resolves to None", cg.resolve("nope.py", brain), None)
        case("a path as given resolves", cg.resolve("scripts/alpha.py", brain),
             brain / "scripts" / "alpha.py")

    print("gate cells")
    case("a bare token is a gate file", cg.gate_files("`check_links.py` §1"), ["check_links.py"])
    case("a file with a space is not a gate",
         cg.gate_files("`check_links py` §1"), [])
    case("a bare folder name is not a gate", cg.gate_files("`.githooks/` names"), [])
    case("a .githooks path is a gate", cg.gate_files("`.githooks/pre-commit`"), [".githooks/pre-commit"])
    case("a .gitignore token is a gate", cg.gate_files("`.gitignore`"), [".gitignore"])

    print("check outcomes")
    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            reg("R-101", "**HARD**", "`alpha.py`"),
            reg("R-102", "**HARD** (local)", "`pre-commit.sh`"),
            reg("R-103", "**HARD**", "`branch.yml`"),
            reg("R-104", "**HARD**", "`.gitignore`"),
            reg("R-105", "**HARD**", "`missing.py`"),
            reg("R-106", "**HARD**", "by hand"),
            reg("R-107", "**HARD**", "`plain.py`"),
            reg("R-108", "**HARD**", "`wiki_gate.py` (wiki)"),
            reg("R-109", "WARN", "no file at all"),
        ]
        files = {
            "scripts/alpha.py": "# R-101 checks it\n",
            ".githooks/pre-commit.sh": "echo\n",
            ".github/workflows/branch.yml": "name: x\n",
            ".gitignore": "_local/\n",
            "scripts/plain.py": "# does the job\n",
        }
        brain = make_brain(tmp, rows, files)
        errors, warnings = cg.check(brain)
        case("a resolved .py that names its rule is clean",
             any("R-101" in e for e in errors + warnings), False)
        case("a non-.py gate is not checked for its id",
             any("R-102" in w or "R-104" in w for w in warnings), False)
        case("a missing gate file is an error",
             "R-105: gate file missing.py not found" in errors, True)
        case("a gate cell with no file is an error",
             "R-106: no gate file named" in errors, True)
        case(".py gate without its id is an error",
             any("scripts/plain.py does not name R-107" in e for e in errors), True)
        case("a (wiki) gate that is missing is a warning, not an error",
             "R-108: gate wiki_gate.py is in the wiki repo; not checked here" in warnings
             and not any("R-108" in e for e in errors), True)
        case("non-HARD rows are ignored", any("R-109" in x for x in errors + warnings), False)
        case("the error count is 3", len(errors), 3)

        (brain / "scripts" / "missing.py").write_text("", encoding="utf-8")
        proc = run_cli(brain)
        case("the CLI exits 1 on an error", proc.returncode, 1)
        case("the CLI prints ::error:: lines", "::error::R-106" in proc.stdout, True)
        case("the CLI prints a summary line", "check_gates: 8 HARD rule(s)" in proc.stdout, True)

    print("level counts")
    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            reg("R-201", "**HARD**", "`a.py`"),
            reg("R-202", "**HARD**", "`b.py`"),
            reg("R-203", "WARN", "by hand"),
            reg("R-204", "MANUAL", "—"),
            reg("R-205", "**HARD**", "`c.py`", status="retired"),
        ]
        brain = make_brain(tmp, rows, {})
        case("counts_basic: retired rows are counted apart",
             cg.level_counts(brain),
             {"HARD": 2, "WARN": 1, "MANUAL": 1, "retired": 1})
    with tempfile.TemporaryDirectory() as tmp:
        brain = make_brain(tmp, [reg("R-206", "**HARD** (local)", "`d.py`")], {})
        case("counts_local_suffix: '**HARD** (local)' counts as HARD",
             cg.level_counts(brain)["HARD"], 1)
    with tempfile.TemporaryDirectory() as tmp:
        brain = make_brain(tmp, [reg("R-207", "HARD; WARN for x", "`e.py`"),
                                 reg("R-208", "MANUAL; WARN above 30", "—")], {})
        counts = cg.level_counts(brain)
        case("counts_semicolon: 'HARD; WARN for x' counts as HARD", counts["HARD"], 1)
        case("counts_semicolon: 'MANUAL; WARN above 30' counts as MANUAL", counts["MANUAL"], 1)
        case("counts_semicolon: nothing counted as WARN", counts["WARN"], 0)

    print("ask rules for guarded files")

    def ask_brain(base, entries):
        """A temp brain whose .claude/settings.json asks before the given entries."""
        brain = make_brain(base, [], {})
        (brain / ".claude").mkdir(parents=True, exist_ok=True)
        body = json.dumps({"permissions": {"ask": entries}})
        (brain / ".claude" / "settings.json").write_text(body, encoding="utf-8")
        return brain

    def full_ask(overrides=None):
        """Edit and Write entries for every guarded path, in the anchored / form."""
        overrides = overrides or {}
        entries = []
        for path in cg.GUARDED:
            for tool in ("Edit", "Write"):
                entries.append(overrides.get((tool, path), tool + "(/" + path + ")"))
        return entries

    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, full_ask())
        case("ask_complete: all guarded paths have Edit and Write", cg.missing_ask_rules(brain), [])
    with tempfile.TemporaryDirectory() as tmp:
        entries = [e for e in full_ask() if "scripts/pii_gate.py" not in e]
        brain = ask_brain(tmp, entries)
        case("ask_missing: a path with no entries is reported",
             cg.missing_ask_rules(brain), ["scripts/pii_gate.py"])
    with tempfile.TemporaryDirectory() as tmp:
        entries = [e for e in full_ask() if e != "Write(/scripts/pii_gate.py)"]
        brain = ask_brain(tmp, entries)
        case("ask_missing: Edit without Write is still reported",
             cg.missing_ask_rules(brain), ["scripts/pii_gate.py"])
    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, full_ask({("Edit", "scripts/pii_gate.py"): "Edit(./scripts/pii_gate.py)",
                                         ("Write", "scripts/pii_gate.py"): "Write(./scripts/pii_gate.py)"}))
        case("ask_anchored: ./ form counts as present", cg.missing_ask_rules(brain), [])
    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, full_ask({("Edit", "scripts/pii_gate.py"): "Edit(/scripts/pii_gate.py)",
                                         ("Write", "scripts/pii_gate.py"): "Write(./scripts/pii_gate.py)"}))
        case("ask_anchored: mixed / and ./ forms count as present", cg.missing_ask_rules(brain), [])
    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, full_ask({("Edit", ".githooks/**"): "Edit(/.githooks/**)"}))
        case("ask_anchored: a glob path counts as present", cg.missing_ask_rules(brain), [])
    with tempfile.TemporaryDirectory() as tmp:
        brain = pathlib.Path(tmp)
        case("ask_no_file: no settings file reports every guarded path",
             cg.missing_ask_rules(brain), list(cg.GUARDED))
    with tempfile.TemporaryDirectory() as tmp:
        brain = pathlib.Path(tmp)
        (brain / ".claude").mkdir()
        (brain / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        case("ask_bad_json: an unreadable settings file reports every guarded path",
             cg.missing_ask_rules(brain), list(cg.GUARDED))
    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, full_ask())
        proc = run_cli(brain)
        case("ask_warning: the CLI prints no ask warning when complete",
             "::warning::" in proc.stdout and "permissions.ask" in proc.stdout, False)
    with tempfile.TemporaryDirectory() as tmp:
        brain = ask_brain(tmp, [e for e in full_ask() if "scripts/pii_gate.py" not in e])
        proc = run_cli(brain)
        case("ask_warning: the CLI prints a warning for a missing path",
             "::warning::scripts/pii_gate.py" in proc.stdout, True)
        case("ask_warning: a missing ask rule does not fail the run", proc.returncode, 0)

    print("this checkout")
    errors, _ = cg.check(ROOT)
    case("the real brain has 0 gate errors", errors, [])
    case("the real brain has no missing ask rules", cg.missing_ask_rules(ROOT), [])

    print(f"\ntest_check_gates: {RAN[0] - FAILS[0]} passed, {FAILS[0]} failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
