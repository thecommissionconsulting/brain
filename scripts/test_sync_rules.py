"""Cases for sync_rules.py, run from the repo root: python scripts/test_sync_rules.py

Each case builds a small brain, wiki and home in a temp directory and checks the result.
VAULT_CLAUDE_HOME points at a temp folder, so the real ~/.claude is never touched.
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sync_rules", ROOT / "scripts" / "sync_rules.py")
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(50) +
          "want " + str(want)[:40].ljust(40) + " got " + str(got)[:40])


def block(name, body):
    return ("<!-- block:%s:start -->\n" % name) + body + ("\n<!-- block:%s:end -->\n" % name)


RULES = (block("brain-guardrails", "BG-1") + block("response-contract", "RC-1") +
         block("build-flow-brain", "BF-1") + block("global-guardrails", "GG-1") +
         block("build-flow-global", "BFG-1") + block("wiki-guardrails", "WG-1"))

BRAIN_CLAUDE = (block("brain-guardrails", "BG-1") + "outside text\n" +
                block("response-contract", "RC-1") + block("build-flow-brain", "BF-1"))
BRAIN_SETUP = (block("global-guardrails", "GG-1") + block("response-contract", "RC-1") +
               block("build-flow-global", "BFG-1"))
WIKI_CLAUDE = block("wiki-guardrails", "WG-1")
HOME_CLAUDE = (block("global-guardrails", "GG-1") + block("response-contract", "RC-1") +
               block("build-flow-global", "BFG-1"))


def brain_files(**changes):
    files = {"_ai/rules.md": RULES, "CLAUDE.md": BRAIN_CLAUDE, "_ai/claude-setup.md": BRAIN_SETUP}
    files.update(changes)
    return files


def build(base, brain, wiki=None, home=None):
    """Write the three roots under base. A dict is a folder with those files; None is no folder."""
    base = pathlib.Path(base)
    paths = {}
    for key, files in (("brain", brain), ("wiki", wiki), ("home", home)):
        if files is None:
            paths[key] = None
            continue
        root = base / key
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        root.mkdir(parents=True, exist_ok=True)
        paths[key] = root
    return paths["brain"], paths["wiki"], paths["home"]


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def in_sync(base):
    """A fully synced world."""
    return build(base, brain_files(), {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})


def main():
    print("block parsing")
    case("blocks() reads a body without surrounding newlines",
         sr.blocks(block("x", "one\ntwo")), {"x": "one\ntwo"})
    case("a repeated block name counts as missing",
         "x" in sr.blocks(block("x", "a") + block("x", "b")), False)
    case("a start with no end counts as missing",
         "x" in sr.blocks("<!-- block:x:start -->\nbody\n"), False)
    case("replace() returns None when markers are missing",
         sr.replace("no markers here\n", "x", "y"), None)

    print("sync checks")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VAULT_CLAUDE_HOME"] = tmp
        case("claude_dir() honours VAULT_CLAUDE_HOME", str(sr.claude_dir()), tmp)

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = in_sync(tmp)
        problems, notes = sr.check(b, w, h)
        case("in_sync: problems == []", problems, [])

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": BRAIN_CLAUDE.replace("BG-1", "BG-OLD")}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        problems, _ = sr.check(b, w, h)
        case("drift: one edited body is reported",
             problems, ["drift: brain:CLAUDE.md brain-guardrails"])

    with tempfile.TemporaryDirectory() as tmp:
        broken = BRAIN_CLAUDE.replace("<!-- block:response-contract:start -->\n", "").replace(
            "\n<!-- block:response-contract:end -->\n", "\n")
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": broken}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        problems, _ = sr.check(b, w, h)
        case("missing_markers: reported as missing",
             problems, ["missing markers: brain:CLAUDE.md response-contract"])

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(), {"CLAUDE.md": WIKI_CLAUDE}, {})
        problems, notes = sr.check(b, w, h)
        case("absent_home_target: problems == []", problems, [])
        case("absent_home_target: note names the file",
             "skipped (absent): home:CLAUDE.md" in notes, True)

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(), {}, {"CLAUDE.md": HOME_CLAUDE})
        problems, notes = sr.check(b, w, h)
        case("absent_wiki_file: problems == []", problems, [])
        case("absent_wiki_file: note names the file",
             "skipped (absent): wiki:CLAUDE.md" in notes, True)

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(), None, {"CLAUDE.md": HOME_CLAUDE})
        problems, notes = sr.check(b, None, h)
        case("no_wiki: note says no wiki", "skipped (no wiki): wiki:CLAUDE.md" in notes, True)
        case("no_wiki: problems == []", problems, [])

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": BRAIN_CLAUDE.replace("\n", "\r\n")}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        problems, _ = sr.check(b, w, h)
        case("crlf_equal: CRLF target gives problems == []", problems, [])

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": BRAIN_CLAUDE.replace("BG-1", "BG-OLD")}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        changed = sr.write(b, w, h)
        case("write_fixes_drift: returns the changed label",
             changed, ["brain:CLAUDE.md"])
        problems, _ = sr.check(b, w, h)
        case("write_fixes_drift: check is then clean", problems, [])
        case("write_keeps_outside_text: outside line kept",
             "outside text\n" in read(b / "CLAUDE.md"), True)
        case("write_keeps_outside_text: file equals the synced text",
             read(b / "CLAUDE.md"), BRAIN_CLAUDE)

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": BRAIN_CLAUDE.replace("BG-1", "BG-OLD")}),
                        {"CLAUDE.md": WIKI_CLAUDE},
                        {"CLAUDE.md": HOME_CLAUDE.replace("GG-1", "GG-OLD")})
        drifted_brain = read(b / "CLAUDE.md")
        changed = sr.write(b, w, h, wheres=("home",))
        case("write_wheres_filter: returns only the home label",
             changed, ["home:CLAUDE.md"])
        case("write_wheres_filter: brain file unchanged",
             read(b / "CLAUDE.md"), drifted_brain)

    with tempfile.TemporaryDirectory() as tmp:
        broken = BRAIN_CLAUDE.replace("<!-- block:response-contract:start -->\n", "")
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": broken}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        before = read(b / "CLAUDE.md")
        changed = sr.write(b, w, h)
        case("write never adds markers: file left as it is", read(b / "CLAUDE.md"), before)
        case("write never adds markers: nothing reported", changed, [])

    with tempfile.TemporaryDirectory() as tmp:
        b, w, h = build(tmp, brain_files(**{"CLAUDE.md": BRAIN_CLAUDE.replace(
            "BG-1", "BG-OLD").replace("\n", "\r\n")}), {"CLAUDE.md": WIKI_CLAUDE},
            {"CLAUDE.md": HOME_CLAUDE})
        sr.write(b, w, h)
        case("write keeps CRLF line endings",
             read(b / "CLAUDE.md"), BRAIN_CLAUDE.replace("\n", "\r\n"))

    with tempfile.TemporaryDirectory() as tmp:
        no_block = RULES.replace(block("build-flow-global", "BFG-1"), "")
        b, w, h = build(tmp, brain_files(**{"_ai/rules.md": no_block}),
                        {"CLAUDE.md": WIKI_CLAUDE}, {"CLAUDE.md": HOME_CLAUDE})
        problems, _ = sr.check(b, w, h)
        case("unknown block: named by a target but absent from rules.md",
             "unknown block: build-flow-global" in problems, True)

    print(f"\ntest_sync_rules: {RAN[0] - FAILS[0]} passed, {FAILS[0]} failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
