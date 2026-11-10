"""Cases for pii_gate.py, run from the repo root: python scripts/test_pii_gate.py

The denylist now lives in the wiki repo, so every case runs against a throwaway wiki
in the temp directory (BRAIN_WIKI points at it), never the real one.

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
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "pii_gate.py"
L = "wiki/internal/playbooks/services-team/ludo-s-schedule.md"
C = "wiki/internal/playbooks/services-team/2026-graduate-programme/candidates"


def run_gate(stdin_text, cwd, env):
    return subprocess.run([sys.executable, str(GATE)], input=stdin_text,
                          capture_output=True, text=True, cwd=str(cwd), env=env)


def verdict(stdin_text, cwd, env):
    p = run_gate(stdin_text, cwd, env)
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
    ("MultiEdit into the prefix",         {"tool_name": "MultiEdit", "tool_input": {"file_path": C + "/x.md",
                                           "edits": [{"old_string": "a", "new_string": "b"}]}}, "DENY"),

    ("commit message with '10 or more'",  bash("git commit -F -\n10 or more addresses in " + L), "ALLOW"),
    ("prose using less / type / more",    bash("echo " + L + " has less noise of this type and more besides"), "ALLOW"),
    ("git add the path",                  bash("git add " + L), "ALLOW"),
    ("ls the prefix",                     bash("ls " + C), "ALLOW"),
    ("python heredoc naming the path",    bash("python - <<PY\nskip = ['" + C + "']\nPY"), "ALLOW"),
    ("ordinary cat",                      bash("cat index.md"), "ALLOW"),
    ("Read an ordinary note",             read("index.md"), "ALLOW"),
    ("MultiEdit an ordinary note",        {"tool_name": "MultiEdit", "tool_input": {"file_path": "index.md",
                                           "edits": [{"old_string": "a", "new_string": "b"}]}}, "ALLOW"),
    ("broad grep over wiki (known gap)",  {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "wiki"}}, "ALLOW"),
]


def make_wiki(base, name="wiki-repo"):
    wiki = pathlib.Path(base) / name
    (wiki / "_ai").mkdir(parents=True)
    (wiki / "index.md").write_text("# index\n", encoding="utf-8")
    (wiki / "_ai" / "pii-denylist.txt").write_text(f"{L}\n{C}\n", encoding="utf-8")
    return wiki


def check(name, got, want, fails):
    ok = got == want
    fails[0] += not ok
    fails[1] += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name:42} want {str(want):5} got {got}")


def main():
    fails = [0, 0]
    with tempfile.TemporaryDirectory() as tmp:
        wiki = make_wiki(tmp)
        env = dict(os.environ, BRAIN_WIKI=str(wiki))

        # The old cases, now run from inside the wiki, which is where a session lives.
        for name, payload, want in CASES:
            check(name, verdict(json.dumps(payload), wiki, env), want, fails)

        # Malformed input must never take a tool call down with it.
        check("malformed payload fails open", verdict("not json at all", wiki, env),
              "ALLOW", fails)

        # A session started in the brain, reading the wiki by absolute path.
        brain_read = read(str(wiki / L))
        check("abs path to denied file, from brain", verdict(json.dumps(brain_read), ROOT, env),
              "DENY", fails)

        # No wiki on this machine: never block for that reason, never crash.
        nowhere = dict(os.environ, BRAIN_WIKI=str(pathlib.Path(tmp) / "no-such-wiki"))
        p = run_gate(json.dumps(brain_read), ROOT, nowhere)
        check("no wiki: denied-looking read allowed", "DENY" if p.stdout.strip() else "ALLOW",
              "ALLOW", fails)
        check("no wiki: gate exits 0", p.returncode, 0, fails)

        # The bulk-email check does not depend on the wiki, so it still runs without one.
        bulk = pathlib.Path(tmp) / "contacts.md"
        bulk.write_text("\n".join(f"person{i}@client{i}.com" for i in range(12)), encoding="utf-8")
        check("no wiki: bulk email file still denied", verdict(json.dumps(read(str(bulk))), ROOT, nowhere),
              "DENY", fails)

    print(f"\ntest_pii_gate: {fails[1] - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
