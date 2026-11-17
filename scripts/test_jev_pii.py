"""Cases for jev_pii.py, run from the repo root: python3 scripts/test_jev_pii.py

Every case works in a temporary folder that the script removes at the end. No case
touches the real _local/jev-pii.
"""
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("jev_pii", ROOT / "scripts" / "jev_pii.py")
jp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jp)

FAILS = [0]
RAN = [0]
CREATED = []


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(46) +
          "want " + str(want)[:28].ljust(28) + " got " + str(got)[:28])


def tmp():
    """A new temporary folder, removed at the end of the run."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="jev-pii-test-"))
    CREATED.append(d)
    return d


def line(time, sha, text="my card is [PII:card number]"):
    return json.dumps({"time": time, "use": "prompt", "confidence": 0.93,
                       "tags": ["card number"], "sha256": sha, "text": text}) + "\n"


def write_log(folder, lines, name="2026-11-18.jsonl"):
    (folder / name).write_text("".join(lines), encoding="utf-8")


def main():
    print("new entries")
    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa"), line("2026-11-18T09:05:00Z", "bbb")])
    case("no marker: two lines give two", len(jp.new_entries(d)), 2)

    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa"), line("2026-11-18T09:05:00Z", "bbb")])
    (d / ".reviewed").write_text("2026-11-18T09:00:00Z aaa\n", encoding="utf-8")
    got = jp.new_entries(d)
    case("marker on first line: one left", len(got), 1)
    case("marker on first line: the second is left", got[0]["sha256"], "bbb")

    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa"), "this is not json\n",
                  line("2026-11-18T09:05:00Z", "bbb")])
    case("garbage line is skipped", len(jp.new_entries(d)), 2)

    d = tmp()
    write_log(d, [json.dumps({"use": "prompt"}) + "\n", line("2026-11-18T09:05:00Z", "bbb")])
    case("line with no time or sha256 is skipped", len(jp.new_entries(d)), 1)

    case("missing folder gives []", jp.new_entries(d / "no-such-folder"), [])

    d = tmp()
    write_log(d, [line("2026-11-18T10:00:00Z", "ccc"), line("2026-11-18T09:00:00Z", "aaa")])
    case("oldest first", [e["sha256"] for e in jp.new_entries(d)], ["aaa", "ccc"])

    print("mark reviewed")
    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa"), line("2026-11-18T09:05:00Z", "bbb")])
    case("mark_reviewed returns 2", jp.mark_reviewed(d), 2)
    case("after marking, nothing new", jp.new_entries(d), [])

    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa")])
    case("mark_reviewed creates a missing folder", jp.mark_reviewed(d / "fresh"), 0)
    case("mark_reviewed on empty folder: no entries", jp.new_entries(d / "fresh"), [])

    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa")])
    jp.mark_reviewed(d)
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa"), line("2026-11-18T09:00:00Z", "zzz")])
    case("same second, new sha256 is still new", [e["sha256"] for e in jp.new_entries(d)],
         ["zzz"])

    print("cli")
    d = tmp()
    write_log(d, [line("2026-11-18T09:00:00Z", "aaa", text="card 4111 [PII:card number]")])
    saved = jp.PII_DIR
    jp.PII_DIR = d
    try:
        out = io.StringIO()
        with redirect_stdout(out):
            code_list = jp.main(["--list"])
        case("--list exit 0", code_list, 0)
        case("--list prints time, confidence, tags, text",
             out.getvalue(),
             "2026-11-18T09:00:00Z  0.93  card number  card 4111 [PII:card number]\n")

        out = io.StringIO()
        with redirect_stdout(out):
            code_done = jp.main(["--done"])
        case("--done exit 0", code_done, 0)
        case("--done prints marked 1 reviewed", out.getvalue(), "marked 1 reviewed\n")

        out = io.StringIO()
        with redirect_stdout(out):
            jp.main(["--list"])
        case("--list after done says none", out.getvalue(), "no new PII entries\n")
    finally:
        jp.PII_DIR = saved

    for folder in CREATED:
        shutil.rmtree(folder, ignore_errors=True)
    print("\ntest_jev_pii: " + str(RAN[0] - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
