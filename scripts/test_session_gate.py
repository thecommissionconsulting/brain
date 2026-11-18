"""Cases for session_gate.py, run from the repo root: python scripts/test_session_gate.py

Runs the gate against a throwaway wiki in the temp directory (BRAIN_WIKI points at it)
and against a BRAIN_WIKI that does not exist. Never touches a real wiki.
"""
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "session_gate.py"
spec = importlib.util.spec_from_file_location("session_gate", GATE)
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)


def run(wiki_value, home_value):
    env = dict(os.environ, BRAIN_WIKI=wiki_value, VAULT_CLAUDE_HOME=home_value)
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
        home = pathlib.Path(tmp) / "no-such-claude-home"

        p = run(str(empty), str(home))
        check("no wiki: exits 0", p.returncode == 0, fails)
        check("no wiki: says not configured", "wiki: not configured" in p.stdout, fails)
        check("no wiki: the gate checker runs", "gates ok" in p.stdout, fails)
        check("no wiki: the sync check runs", "sync ok" in p.stdout, fails)
        check("no wiki: no budget line", "index.md " not in p.stdout, fails)
        check("no wiki: Rules line is last",
              p.stdout.strip().splitlines()[-1] == f"Rules: {ROOT.as_posix()}/_ai/rules.md",
              fails)

        wiki = pathlib.Path(tmp) / "wiki-repo"
        wiki.mkdir()
        text = "# index\n" + "x" * 100 + "\n"
        (wiki / "index.md").write_text(text, encoding="utf-8")
        size = len(text.encode("utf-8"))

        p = run(str(wiki), str(home))
        check("wiki: exits 0", p.returncode == 0, fails)
        check("wiki: the gate checker runs", "gates ok" in p.stdout, fails)
        check("wiki: the sync check runs", "sync ok" in p.stdout, fails)
        check(f"wiki: budget in bytes ({size}/32768)",
              f"index.md {size}/32768" in p.stdout, fails)
        check("wiki: Rules line is last",
              p.stdout.strip().splitlines()[-1] == f"Rules: {ROOT.as_posix()}/_ai/rules.md",
              fails)

    print("jev median")
    with tempfile.TemporaryDirectory() as tmp:
        log = pathlib.Path(tmp)
        check("median: empty dir gives None", sg.jev_median(log) is None, fails)

        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        rows = [{"use": "prompt", "ms": ms} for ms in (100, 300, 200)]
        rows.append({"use": "prompt", "time": "no ms here"})
        (log / (today + ".jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        (log / "2000-01-01.jsonl").write_text(json.dumps({"ms": 9999}) + "\n", encoding="utf-8")
        check("median: records 100, 300, 200 give 200", sg.jev_median(log) == 200, fails)

    print("jev line")
    check("jev line: None gives no part", sg.jev_part(None) is None, fails)
    check("jev line: 200 ms", sg.jev_part(200) == "jev 200 ms", fails)
    check("jev line: 4000 ms is not over", sg.jev_part(4000) == "jev 4000 ms", fails)
    check("jev line: 4001 ms is over (R-67)", sg.jev_part(4001) == "jev OVER 4001 ms (R-67)", fails)

    print("pii line")
    check("pii line: 2 new", sg.pii_part(2) == "pii 2 new (R-65): python scripts/jev_pii.py --list",
          fails)
    check("pii line: 0 new gives no part", sg.pii_part(0) is None, fails)

    print(f"\ntest_session_gate: {fails[1] - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
