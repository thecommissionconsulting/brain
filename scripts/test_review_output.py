"""Cases for review_output.py, run from the repo root: python scripts/test_review_output.py

Every case runs against a throwaway vault in the temp directory, never this one.
`review_output.py` finds the vault from its own location, so copying the script
into `<tmp>/scripts/` is enough to move it: no environment override, and no test
that can write to the real `_local/` ledger or delete a real artifact.

The cases that matter are the silences. A Stop hook that blocks twice traps the
session in its own review, so "same session, second turn" and "stop_hook_active"
are the ones to watch, alongside the malformed payload -- this gate sits between
the model and the end of every turn, and it has to fail open.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "review_output.py"


class Vault:
    """A temp vault with review_output.py installed in it."""

    def __init__(self, stack):
        self.root = pathlib.Path(stack)
        (self.root / "scripts").mkdir()
        (self.root / "raw" / "output").mkdir(parents=True)
        shutil.copy(SOURCE, self.root / "scripts" / "review_output.py")

    def artifact(self, name, text="report body"):
        path = self.root / "raw" / "output" / name
        path.write_text(text, encoding="utf-8")
        return path

    def run(self, *args, stdin=""):
        return subprocess.run([sys.executable, str(self.root / "scripts" / "review_output.py"), *args],
                              input=stdin, capture_output=True, text=True, cwd=str(self.root))

    def gate(self, session="s1", active=False):
        payload = json.dumps({"session_id": session, "stop_hook_active": active})
        out = self.run("--gate", stdin=payload).stdout.strip()
        return json.loads(out)["decision"] if out else "pass"


def case(name, got, want, state):
    ok = got == want
    state[0] += not ok
    print(f"  {'ok  ' if ok else 'FAIL'}  {name:42} want {str(want):5} got {got}")


def main():
    fails = [0]
    with tempfile.TemporaryDirectory() as tmp:
        v = Vault(tmp)
        case("empty raw/output passes", v.gate(), "pass", fails)

        v.artifact("2026-09-23-audit.md")
        case("one artifact blocks", v.gate(), "block", fails)
        case("same session, second turn passes", v.gate(), "pass", fails)
        case("a new session blocks again", v.gate(session="s2"), "block", fails)
        case("stop_hook_active passes", v.gate(session="s3", active=True), "pass", fails)

        v.run("--keep", "raw/output/2026-09-23-audit.md")
        case("kept artifact passes", v.gate(session="s4"), "pass", fails)

        v.artifact("2026-09-23-audit.md", text="edited, so the ruling is stale")
        case("edited artifact blocks again", v.gate(session="s5"), "block", fails)

        case("malformed payload fails open",
             "block" if v.run("--gate", stdin="not json at all").stdout.strip() else "pass",
             "pass", fails)

        listing = v.run("--list").stdout
        case("--list names the artifact", "2026-09-23-audit.md" in listing, True, fails)

        hidden = Vault(tempfile.mkdtemp())
        hidden.artifact(".keepme")
        case("dotfile is not an artifact", hidden.gate(), "pass", fails)
        shutil.rmtree(hidden.root, ignore_errors=True)

    total = 10
    print(f"\ntest_review_output: {total - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
