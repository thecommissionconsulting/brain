"""Cases for pii_gate.py, run from the repo root: python scripts/test_pii_gate.py

The denied paths appear here as data rather than on a shell command line, because
the gate reads the command text of any Bash call and would block a test that
spelled `cat <denied path>` directly -- as it did, twice, while this was written.

Half these cases are ALLOW cases. Every false positive found so far came from the
Bash branch firing on a command that merely mentioned a path: writing the
denylist, git-adding the file, or a commit message containing both a denied
filename and the ordinary words "more" and "less". A gate that blocks its own
configuration gets switched off, so the allow cases are the ones that matter.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "pii_gate.py"
L = "wiki/internal/playbooks/services-team/ludo-s-schedule.md"
C = "wiki/internal/playbooks/services-team/2026-graduate-programme/candidates"


def verdict(stdin_text):
    p = subprocess.run([sys.executable, str(GATE)], input=stdin_text,
                       capture_output=True, text=True, cwd=str(ROOT))
    return "DENY" if p.stdout.strip() else "ALLOW"


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def read(path):
    return {"tool_name": "Read", "tool_input": {"file_path": path}}


CASES = [
    ("Read the denied file",              read(L), "DENY"),
    ("Read a CV under the prefix",        read(C + "/all-applications/final-list/cv-jack-simmonds.md"), "DENY"),
    ("cat it",                            bash("cat " + L), "DENY"),
    ("piped into grep",                   bash("git show HEAD | grep " + L), "DENY"),
    ("after &&",                          bash("cd x && head -3 " + L), "DENY"),
    ("on its own line",                   bash("cd x\nless " + L), "DENY"),
    ("by basename alone",                 bash("head -5 ludo-s-schedule.md"), "DENY"),
    ("grep -r into the prefix",           bash("grep -r x " + C), "DENY"),
    ("Grep scoped into the prefix",       {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": C}}, "DENY"),
    ("Write into the prefix",             {"tool_name": "Write", "tool_input": {"file_path": C + "/x.md"}}, "DENY"),

    ("commit message with '10 or more'",  bash("git commit -F -\n10 or more addresses in " + L), "ALLOW"),
    ("prose using less / type / more",    bash("echo " + L + " has less noise of this type and more besides"), "ALLOW"),
    ("git add the path",                  bash("git add " + L), "ALLOW"),
    ("ls the prefix",                     bash("ls " + C), "ALLOW"),
    ("python heredoc naming the path",    bash("python - <<PY\nskip = ['" + C + "']\nPY"), "ALLOW"),
    ("ordinary cat",                      bash("cat index.md"), "ALLOW"),
    ("Read an ordinary note",             read("index.md"), "ALLOW"),
    ("broad grep over wiki (known gap)",  {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "wiki"}}, "ALLOW"),
]


def main():
    fails = 0
    for name, payload, want in CASES:
        got = verdict(json.dumps(payload))
        ok = got == want
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:38} want {want:5} got {got}")

    # Malformed input must never take a tool call down with it.
    got = verdict("not json at all")
    ok = got == "ALLOW"
    fails += not ok
    print(f"  {'ok  ' if ok else 'FAIL'}  {'malformed payload fails open':38} want ALLOW got {got}")

    total = len(CASES) + 1
    print(f"\ntest_pii_gate: {total - fails} passed, {fails} failed.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
