"""Cases for session_gate.py, run from the repo root: python scripts/test_session_gate.py

Runs the gate against a throwaway wiki in the temp directory (BRAIN_WIKI points at it)
and against a BRAIN_WIKI that does not exist. Never touches a real wiki.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "session_gate.py"


def run(wiki_value):
    env = dict(os.environ, BRAIN_WIKI=wiki_value)
    return subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True,
                          cwd=str(ROOT), env=env)


def check(name, ok, fails):
    fails[0] += not ok
    fails[1] += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}")


def main():
    fails = [0, 0]
    with tempfile.TemporaryDirectory() as tmp:
        empty = pathlib.Path(tmp) / "no-such-wiki"

        p = run(str(empty))
        check("no wiki: exits 0", p.returncode == 0, fails)
        check("no wiki: says not configured", "wiki: not configured" in p.stdout, fails)
        check("no wiki: no budget line", "index.md " not in p.stdout, fails)
        check("no wiki: Rules line is last",
              p.stdout.strip().splitlines()[-1] == f"Rules: {ROOT.as_posix()}/_ai/rules.md",
              fails)

        wiki = pathlib.Path(tmp) / "wiki-repo"
        wiki.mkdir()
        text = "# index\n" + "x" * 100 + "\n"
        (wiki / "index.md").write_text(text, encoding="utf-8")
        size = len(text.encode("utf-8"))

        p = run(str(wiki))
        check("wiki: exits 0", p.returncode == 0, fails)
        check(f"wiki: budget in bytes ({size}/32768)",
              f"index.md {size}/32768" in p.stdout, fails)
        check("wiki: Rules line is last",
              p.stdout.strip().splitlines()[-1] == f"Rules: {ROOT.as_posix()}/_ai/rules.md",
              fails)

    print(f"\ntest_session_gate: {fails[1] - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
