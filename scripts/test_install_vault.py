"""Cases for install_vault.py, run from the repo root: python scripts/test_install_vault.py

Every case runs against a temporary config directory, never yours. The script
reads `$VAULT_CLAUDE_HOME` for exactly this reason, so no test here can touch the
real `~/.claude/settings.json`.

The cases that matter are the ones about somebody else's file. This is the only
part of the vault that edits a GLOBAL Claude Code setting, and a merge that drops
another hook, duplicates its own entry on a second run, or overwrites a file it
could not parse would break configuration the vault does not own. So: other hooks
survive, a second run is a no-op, a backup exists, and malformed JSON is left
exactly as it was found.
"""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install_vault", ROOT / "scripts" / "install_vault.py")
iv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iv)

FAILS = [0]
RAN = [0]


def case(name, got, want):
    ok = got == want
    RAN[0] += 1
    FAILS[0] += not ok
    print("  " + ("ok  " if ok else "FAIL") + "  " + name.ljust(46) +
          "want " + str(want)[:28].ljust(28) + " got " + str(got)[:28])


def home(tmp, settings=None):
    """Point the module at a temp config directory, optionally seeding settings.json."""
    path = pathlib.Path(tmp)
    os.environ["VAULT_CLAUDE_HOME"] = str(path)
    if settings is not None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "settings.json").write_text(settings, encoding="utf-8")
    return path


# ---- the wiki steps ----------------------------------------------------------
# Every case here runs against a temporary brain and a temporary wiki. ROOT is
# pointed at the temporary brain, so the real _local/ and .claude/settings.local.json
# are never written, and BRAIN_WIKI names a folder that does not exist, so the real
# wiki is never found by accident.

def make_wiki(tmp):
    wiki = pathlib.Path(tmp) / "wiki"
    (wiki / ".claude").mkdir(parents=True)
    (wiki / ".githooks").mkdir(parents=True)
    (wiki / "index.md").write_text("# index\n", encoding="utf-8")
    (wiki / ".claude" / "settings.json").write_text(json.dumps({"permissions": {
        "deny": ["Read(./raw/**)", "Read(./_local/**)", "Bash(rm -rf:*)"]}}),
        encoding="utf-8")
    for name in iv.WIKI_HOOK_NAMES:
        (wiki / ".githooks" / name).write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(wiki)], check=True)
    subprocess.run(["git", "-C", str(wiki), "add", "-A"], check=True)
    return wiki


def capture(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = iv.main(argv)
    return code, buf.getvalue()


def wiki_cases():
    saved_root, saved_env = iv.ROOT, os.environ.get("BRAIN_WIKI")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            home(base)
            brain = base / "brain"
            (brain / "_local").mkdir(parents=True)
            (brain / ".claude").mkdir()
            wiki = make_wiki(base)
            wiki_p = wiki.resolve().as_posix()
            iv.ROOT = brain
            os.environ["BRAIN_WIKI"] = str(base / "no-such-wiki")

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--dry-run"])
            case("dry-run exits 0", code, 0)
            case("dry-run lists the six wiki steps", out.count("PENDING"), 6)
            case("dry-run writes nothing", (brain / "_local" / "brain.json").exists(), False)

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--check"])
            case("check on a bare wiki exits 1", code, 1)
            case("check names the wiki it found", "wiki: " + wiki_p in out, True)

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--yes"])
            case("apply exits 0", code, 0)
            cfg = json.loads((brain / "_local" / "brain.json").read_text(encoding="utf-8"))
            case("step 1 records the wiki path", cfg["wiki"], wiki_p)
            case("step 2 imports the brain CLAUDE.md by absolute path",
                 (wiki / "_local" / "brain.md").read_text(encoding="utf-8"),
                 "@" + (brain / "CLAUDE.md").as_posix() + "\n")

            wl_path = wiki / ".claude" / "settings.local.json"
            bl_path = brain / ".claude" / "settings.local.json"
            wl = json.loads(wl_path.read_text(encoding="utf-8"))
            cmds = [h["command"] for ev in wl["hooks"].values() for g in ev for h in g["hooks"]]
            case("step 3 wires four gates", len(cmds), 4)
            pre = wl["hooks"]["PreToolUse"]
            case("step 3 wires two PreToolUse groups, PII then the edit gate",
                 [g["matcher"] for g in pre], [iv.PII_MATCHER, iv.EDIT_MATCHER])
            case("the edit gate has a 5 second timeout and names the wiki gate",
                 pre[1]["hooks"][0].get("timeout") == 5
                 and "wiki_edit_gate.py" in pre[1]["hooks"][0]["command"], True)
            case("step 3 wires the session gate",
                 any("session_gate.py" in c for c in cmds), True)
            case("step 3 passes --root to the review gate",
                 any("review_output.py" in c and f'--root "{wiki_p}"' in c for c in cmds), True)
            case("step 3 adds the brain as an extra directory",
                 wl["permissions"]["additionalDirectories"], [brain.as_posix()])

            bl = json.loads(bl_path.read_text(encoding="utf-8"))
            case("step 4 adds the wiki as an extra directory",
                 bl["permissions"]["additionalDirectories"], [wiki_p])
            case("step 4 makes the Read rules absolute, drops the others",
                 bl["permissions"]["deny"],
                 ["Read(/" + wiki_p + "/raw/**)", "Read(/" + wiki_p + "/_local/**)"])

            def git_out(*args):
                return subprocess.run(["git", "-C", str(wiki)] + list(args),
                                      capture_output=True, text=True).stdout
            case("step 5 sets brain.root", git_out("config", "--get", "brain.root").strip(),
                 brain.as_posix())
            case("step 5 sets core.hooksPath",
                 git_out("config", "--get", "core.hooksPath").strip(), ".githooks")
            case("step 5 marks the three hooks executable in git",
                 sum(1 for l in git_out("ls-files", "-s").splitlines()
                     if l.startswith("100755") and ".githooks/" in l), 3)
            case("step 5 makes the hooks executable on disk",
                 os.name == "nt" or all(os.access(wiki / ".githooks" / n, os.X_OK)
                                        for n in iv.WIKI_HOOK_NAMES), True)

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--check"])
            case("check after apply exits 0", code, 0)
            case("check after apply says fully installed", "fully installed" in out, True)

            # Entries the owner added by hand survive, and a second run changes nothing.
            wl["hooks"].setdefault("PostToolUse", []).append(
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hand"}]})
            wl_path.write_text(json.dumps(wl), encoding="utf-8")
            bl["permissions"]["deny"].append("Read(//home/someone/private/**)")
            bl_path.write_text(json.dumps(bl), encoding="utf-8")
            before = {p: p.read_bytes() for p in (wl_path, bl_path, brain / "_local" / "brain.json",
                                                  wiki / "_local" / "brain.md")}
            baks = len(list(base.rglob("*.bak-*")))
            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--yes"])
            case("a second run exits 0", code, 0)
            case("a second run says nothing to do", "nothing to do" in out, True)
            case("a second run rewrites no file",
                 {p: p.read_bytes() for p in before} == before, True)
            case("a second run makes no backup", len(list(base.rglob("*.bak-*"))), baks)
            case("a hand-added hook survives",
                 "echo hand" in wl_path.read_text(encoding="utf-8"), True)
            case("a hand-added deny rule survives",
                 "Read(//home/someone/private/**)" in bl_path.read_text(encoding="utf-8"), True)
            case("our session gate is not duplicated",
                 wl_path.read_text(encoding="utf-8").count("session_gate.py"), 1)

            # A malformed file is refused and left alone, and the other steps still apply.
            bl_path.write_text("{not json", encoding="utf-8")
            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--yes"])
            case("malformed brain settings exit 1", code, 1)
            case("malformed brain settings are left alone",
                 bl_path.read_text(encoding="utf-8"), "{not json")
            case("and the failure is named", "FAILED  brain for wiki" in out, True)

            code, out = capture(["--wiki", str(base / "nope"), "--wiki-only", "--check"])
            case("a folder with no index.md is refused", code, 2)

            os.environ["BRAIN_WIKI"] = str(base / "no-such-wiki")
            code, out = capture(["--wiki-only", "--check"])
            case("no wiki: the report says not configured", "wiki: not configured" in out, True)
            case("no wiki: wiki-only exits 2", code, 2)

        # Pure helpers: a Windows path with spaces, and the two import forms.
        win_brain, win_wiki = "C:/Users/Daru Broodryk/brain", "C:/Users/Daru Broodryk/wiki"
        entries = iv.wiki_hook_entries(win_brain, win_wiki)
        case("a path with spaces keeps the hook JSON valid",
             json.loads(json.dumps(entries)), entries)
        case("the review gate quotes the wiki path",
             f'--root "{win_wiki}"' in entries["Stop"][0]["hooks"][0]["command"], True)
        case("the session gate quotes the brain path",
             f'python "{win_brain}/scripts/session_gate.py"'
             in entries["SessionStart"][0]["hooks"][0]["command"], True)
        case("a drive-letter deny rule is absolute",
             iv.absolute_read(win_wiki, "raw/**"),
             "Read(//c/Users/Daru Broodryk/wiki/raw/**)")
        case("a POSIX deny rule is absolute",
             iv.absolute_read("/home/x/wiki", "raw/**"), "Read(//home/x/wiki/raw/**)")
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            line, warn = iv.brain_import_line(base / "brain", home=base)
            case("a brain under home uses the ~ import", line, "@~/brain/CLAUDE.md")
            case("and needs no warning", warn, "")
            line, warn = iv.brain_import_line(base / "my brain", home=base / "elsewhere")
            case("a brain outside home is an absolute import",
                 line, "@" + (base / "my brain" / "CLAUDE.md").as_posix())
            case("a space in that path is warned about", "space" in warn, True)
    finally:
        iv.ROOT = saved_root
        if saved_env is None:
            os.environ.pop("BRAIN_WIKI", None)
        else:
            os.environ["BRAIN_WIKI"] = saved_env


def launcher_cases():
    """The wiki's scripts/new_note.py launcher: written, ignored, idempotent, never over a tracked file."""
    saved_root, saved_env = iv.ROOT, os.environ.get("BRAIN_WIKI")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            home(base)
            brain = base / "brain"
            (brain / "_local").mkdir(parents=True)
            (brain / ".claude").mkdir()
            wiki = make_wiki(base)
            git_run("-C", str(wiki), "-c", "user.name=Test", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "fixture")
            iv.ROOT = brain
            os.environ["BRAIN_WIKI"] = str(base / "no-such-wiki")
            launcher = wiki / "scripts" / "new_note.py"

            label, state, apply_step = next(s for s in iv.WIKI_STEPS if s[0] == "new_note launcher")
            done, _ = state(wiki, iv.wiki_snapshot(wiki))
            case("launcher step is pending on a bare wiki", done, False)
            ok, _ = apply_step(wiki, iv.wiki_snapshot(wiki))
            case("launcher apply succeeds", ok, True)
            case("launcher file is written", launcher.is_file(), True)
            case("launcher names the brain's new_note.py",
                 brain.as_posix() + "/scripts" in launcher.read_text(encoding="utf-8")
                 or repr(brain.as_posix()) in launcher.read_text(encoding="utf-8"), True)
            case("scripts/ is ignored through info/exclude",
                 git_run("-C", str(wiki), "check-ignore", "-q", "--", "scripts/new_note.py").returncode,
                 0)
            case("the committed .gitignore is not edited",
                 (wiki / ".gitignore").exists(), False)
            case("the wiki stays clean after the launcher",
                 git_run("-C", str(wiki), "status", "--porcelain").stdout.strip(), "")
            done, _ = state(wiki, iv.wiki_snapshot(wiki))
            case("launcher step is done after apply", done, True)
            apply_step(wiki, iv.wiki_snapshot(wiki))
            case("a second apply adds one scripts/ line only",
                 exclude_text(wiki).splitlines().count("scripts/"), 1)
            iv.ROOT = ROOT
            apply_step(wiki, iv.wiki_snapshot(wiki))
            iv.ROOT = brain
            res = subprocess.run([sys.executable, str(launcher), "--help"], cwd=str(wiki),
                                 capture_output=True, text=True, encoding="utf-8",
                                 env=dict(os.environ, BRAIN_WIKI=str(wiki)))
            case("the launcher runs new_note.py (--help exits 0)", res.returncode, 0)
            if res.returncode != 0:
                print(res.stdout + res.stderr)

            launcher.write_text("print('someone else')\n", encoding="utf-8")
            done, _ = state(wiki, iv.wiki_snapshot(wiki))
            case("a stale launcher is pending", done, False)
            apply_step(wiki, iv.wiki_snapshot(wiki))
            case("apply rewrites a stale launcher",
                 "someone else" in launcher.read_text(encoding="utf-8"), False)

            git_run("-C", str(wiki), "add", "-f", "--", "scripts/new_note.py")
            git_run("-C", str(wiki), "-c", "user.name=Test", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "tracked")
            ok, detail = apply_step(wiki, iv.wiki_snapshot(wiki))
            case("a tracked launcher is never overwritten", ok, False)
    finally:
        iv.ROOT = saved_root
        if saved_env is None:
            os.environ.pop("BRAIN_WIKI", None)
        else:
            os.environ["BRAIN_WIKI"] = saved_env


# ---- the midnight schedule ------------------------------------------------------
# Every case passes its own runner, so no test runs systemctl or schtasks. The unit files
# go to a temporary folder and the Windows XML to a temporary brain's _local/.

class Recorder:
    """A runner that records each argv and answers from a table keyed by its verb (systemctl's or schtasks')."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        key = argv[2] if argv[0] == "systemctl" else argv[1]
        rc, out = self.answers.get(key, (0, ""))
        return subprocess.CompletedProcess(argv, rc, out, "")


def nightly_cases():
    import xml.etree.ElementTree as ET
    print("\nnightly schedule")
    brain = pathlib.Path("/home/x/my brain")
    wiki = pathlib.Path("/home/x/my wiki")
    service = iv.nightly_service_text("/opt/my python/bin/python3", brain.as_posix(), wiki.as_posix(),
                                      "/usr/bin:/opt/a b/bin")
    case("service: ExecStart quotes python and the script",
         'ExecStart="/opt/my python/bin/python3" "/home/x/my brain/scripts/nightly_digest.py"'
         in service, True)
    case("service: runs in the wiki", "WorkingDirectory=/home/x/my wiki" in service, True)
    case("service: PATH is passed in quoted", 'Environment="PATH=/usr/bin:/opt/a b/bin"' in service, True)
    case("service: oneshot", "Type=oneshot" in service, True)
    pct = iv.nightly_service_text("/p/python", "/b/100%", "/w", "/usr/bin")
    case("service: a percent sign is escaped for systemd", "/b/100%%/scripts" in pct, True)
    timer = iv.nightly_timer_text()
    case("timer: midnight in Pacific/Auckland",
         "OnCalendar=*-*-* 00:00:00 Pacific/Auckland" in timer, True)
    case("timer: runs a missed day on next boot", "Persistent=true" in timer, True)
    case("timer: wanted by timers.target", "WantedBy=timers.target" in timer, True)

    xml_text = iv.nightly_task_xml(r"C:\Program Files\Python\python.exe", r"C:\my brain",
                                   r"C:\my wiki")
    root = ET.fromstring(xml_text)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    case("windows XML: starts when available",
         root.find("t:Settings/t:StartWhenAvailable", ns).text, "true")
    case("windows XML: daily at 00:00",
         root.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", ns).text[-8:], "00:00:00")
    case("windows XML: runs python on the script",
         root.find("t:Actions/t:Exec/t:Command", ns).text, r"C:\Program Files\Python\python.exe")
    case("windows XML: arguments quote the script path",
         root.find("t:Actions/t:Exec/t:Arguments", ns).text, '"C:\\my brain\\scripts\\nightly_digest.py"')
    case("windows XML: works in the wiki",
         root.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text, r"C:\my wiki")
    saved_mode = iv.nightly_mode
    iv.nightly_mode = lambda args: 7
    try:
        case("main dispatches --nightly to its mode", iv.main(["--nightly", "--check"]), 7)
    finally:
        iv.nightly_mode = saved_mode
    case("schtasks create argv is exact",
         iv.schtasks_create_argv(r"C:\x\task.xml"),
         ["schtasks", "/Create", "/F", "/TN", "brain-nightly-digest", "/XML", r"C:\x\task.xml"])
    shown = ET.tostring(root, encoding="unicode")
    case("parse: a query naming this brain's script is found",
         iv.task_query_points_at(shown, r"C:\my brain"), True)
    case("parse: a query for another brain is not",
         iv.task_query_points_at(shown, r"C:\other brain"), False)

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp).resolve()
        home(base)
        brain_dir = base / "brain"
        (brain_dir / "_local").mkdir(parents=True)
        wiki_dir = base / "wiki"
        (wiki_dir / "index.md").parent.mkdir(parents=True)
        (wiki_dir / "index.md").write_text("# i\n", encoding="utf-8")
        real_root = iv.ROOT
        iv.ROOT = brain_dir
        try:
            units = base / "units"
            rec = Recorder({"is-enabled": (1, "disabled\n")})
            rows = iv.nightly_rows(wiki_dir, rec, windows=False, unit_dir=units)
            case("linux: one row, pending on a bare machine", [r[1] for r in rows], [False])
            ok, _ = rows[0][4]()
            case("linux: apply succeeds", ok, True)
            case("linux: the service file is written",
                 (units / "brain-nightly-digest.service").is_file(), True)
            case("linux: the timer file is written", (units / "brain-nightly-digest.timer").is_file(), True)
            case("linux: apply reloads then enables the timer now",
                 rec.calls[-2:], [["systemctl", "--user", "daemon-reload"],
                                  ["systemctl", "--user", "enable", "--now", "brain-nightly-digest.timer"]])
            rec2 = Recorder({"is-enabled": (0, "enabled\n")})
            rows2 = iv.nightly_rows(wiki_dir, rec2, windows=False, unit_dir=units)
            case("linux: a second check with files and enable in place is done", rows2[0][1], True)
            (units / "brain-nightly-digest.timer").write_text("stale\n", encoding="utf-8")
            rows3 = iv.nightly_rows(wiki_dir, rec2, windows=False, unit_dir=units)
            case("linux: a stale timer file is pending", rows3[0][1], False)

            rec_w = Recorder({"/Query": (1, "")})
            rows_w = iv.nightly_rows(wiki_dir, rec_w, windows=True, unit_dir=units)
            case("windows: one row, pending when the task is missing", rows_w[0][1], False)
            ok, _ = rows_w[0][4]()
            case("windows: apply reports success", ok, True)
            xml_file = brain_dir / "_local" / "nightly-digest-task.xml"
            case("windows: apply writes the XML in _local", xml_file.is_file(), True)
            case("windows: the XML file is UTF-16 with a byte order mark",
                 xml_file.read_bytes()[:2], b"\xff\xfe")
            case("windows: apply runs schtasks create",
                 rec_w.calls[-1], iv.schtasks_create_argv(str(xml_file)))
            rec_ok = Recorder({"/Query": (0, iv.nightly_task_xml(sys.executable, brain_dir.as_posix(),
                                                                 wiki_dir.as_posix()))})
            rows_ok = iv.nightly_rows(wiki_dir, rec_ok, windows=True, unit_dir=units)
            case("windows: a task pointing at this brain is done", rows_ok[0][1], True)
            rec_other = Recorder({"/Query": (0, "<Command>other</Command>")})
            rows_other = iv.nightly_rows(wiki_dir, rec_other, windows=True, unit_dir=units)
            case("windows: a task pointing elsewhere is pending", rows_other[0][1], False)
        finally:
            iv.ROOT = real_root


def stale_cases():
    """Old paths the installer wrote are removed; the owner's own paths stay.

    The old brain, old wiki, and old brain.root are set up as they were before, and
    the apply must read them before it rewrites the pointer and git's brain.root.
    """
    saved_root, saved_env = iv.ROOT, os.environ.get("BRAIN_WIKI")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            home(base)
            brain = base / "brain"
            (brain / "_local").mkdir(parents=True)
            (brain / ".claude").mkdir()
            wiki = make_wiki(base)
            wiki_p = wiki.resolve().as_posix()
            iv.ROOT = brain
            os.environ["BRAIN_WIKI"] = str(base / "no-such-wiki")

            old_brain = base / "old-brain"             # exists, holds the old wiki_root.py
            (old_brain / "scripts").mkdir(parents=True)
            (old_brain / "scripts" / "wiki_root.py").write_text("", encoding="utf-8")
            old_wiki = base / "old-wiki"               # exists, holds the old brain.md
            (old_wiki / "_local").mkdir(parents=True)
            (old_wiki / "_local" / "brain.md").write_text("", encoding="utf-8")
            gone_brain = base / "gone-brain"           # missing: the old brain.root
            gone_wiki = base / "gone-wiki"             # missing: the old configured wiki
            hand_missing = base / "hand-missing"       # missing, never written by us
            keep = base / "keep-me"                    # exists, owner's folder
            keep.mkdir()

            (brain / "_local" / "brain.json").write_text(
                json.dumps({"wiki": gone_wiki.as_posix()}), encoding="utf-8")
            subprocess.run(["git", "-C", str(wiki), "config", "brain.root",
                            gone_brain.as_posix()], check=True)
            wl_path = wiki / ".claude" / "settings.local.json"
            wl_path.write_text(json.dumps({
                "permissions": {"additionalDirectories": [
                    old_brain.as_posix(), gone_brain.as_posix(),
                    hand_missing.as_posix(), keep.as_posix()]},
                "hooks": {"PreToolUse": [
                    {"matcher": "Write", "hooks": [{"type": "command",
                        "command": 'python "/old/scripts/pii_gate.py"'}]},
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hand"}]}]},
            }), encoding="utf-8")
            bl_path = brain / ".claude" / "settings.local.json"
            bl_path.write_text(json.dumps({"permissions": {
                "additionalDirectories": [old_wiki.as_posix(), gone_wiki.as_posix(),
                                          keep.as_posix()],
                "deny": ["Read(//c/Users/Old/wiki/raw/**)",
                         "Read(//c/Users/Old/wiki/_local/**)",
                         "Read(//home/someone/private/**)"]}}), encoding="utf-8")

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--check"])
            case("stale paths: check reports pending", code, 1)
            case("stale paths: the brain step is not ok",
                 iv.step_brain_for_wiki(wiki, iv.wiki_snapshot(wiki))[0], False)
            case("stale paths: the wiki hooks step is not ok",
                 iv.step_wiki_hooks(wiki, iv.wiki_snapshot(wiki))[0], False)

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--yes"])
            case("stale paths: apply exits 0", code, 0)
            wl = json.loads(wl_path.read_text(encoding="utf-8"))
            case("the old brain and the missing old brain.root leave the wiki's list",
                 wl["permissions"]["additionalDirectories"],
                 [hand_missing.as_posix(), keep.as_posix(), brain.as_posix()])
            case("a missing folder the owner added stays in the wiki's list",
                 hand_missing.as_posix() in wl["permissions"]["additionalDirectories"], True)
            pre = wl["hooks"]["PreToolUse"]
            case("the old gate is replaced; the owner's hook keeps its place after ours",
                 [g["matcher"] for g in pre], [iv.PII_MATCHER, iv.EDIT_MATCHER, "Bash"])
            case("the old pii_gate command is gone",
                 "/old/scripts" in wl_path.read_text(encoding="utf-8"), False)

            bl = json.loads(bl_path.read_text(encoding="utf-8"))
            case("the old wiki and the missing old wiki leave the brain's list",
                 bl["permissions"]["additionalDirectories"], [keep.as_posix(), wiki_p])
            case("the old drive-form deny rules are replaced, the owner's rule stays",
                 bl["permissions"]["deny"],
                 ["Read(//home/someone/private/**)",
                  "Read(/" + wiki_p + "/raw/**)", "Read(/" + wiki_p + "/_local/**)"])
            case("the pointer is rewritten to the new wiki",
                 json.loads((brain / "_local" / "brain.json").read_text(encoding="utf-8"))["wiki"],
                 wiki_p)
            case("git brain.root is rewritten to the new brain",
                 subprocess.run(["git", "-C", str(wiki), "config", "--get", "brain.root"],
                                capture_output=True, text=True).stdout.strip(),
                 brain.as_posix())

            code, out = capture(["--wiki", str(wiki), "--wiki-only", "--check"])
            case("stale paths: check after apply is ok", code, 0)
            case("stale paths: a second apply changes nothing",
                 "nothing to do" in capture(["--wiki", str(wiki), "--wiki-only", "--yes"])[1], True)

            # Pure: the deny rule matcher, the merge's shape, and a second merge.
            wanted = iv.wiki_hook_entries(brain.as_posix(), wiki_p)
            case("the wiki hook entries are lists per event",
                 all(isinstance(v, list) for v in wanted.values()), True)
            settings = {"hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo a"}]},
                {"matcher": "Write", "hooks": [{"type": "command",
                    "command": 'python "/x/pii_gate.py"'}, {"type": "command", "command": "echo keep"}]}]}}
            once = iv.merge_hooks(settings, {"PreToolUse": wanted["PreToolUse"]})
            case("merge: ours are replaced, others keep order, a kept hook stays in its group",
                 [g["matcher"] for g in once["hooks"]["PreToolUse"]],
                 ["Bash", iv.PII_MATCHER, iv.EDIT_MATCHER, "Write"])
            case("merge: the group that held ours keeps the hand-added hook",
                 once["hooks"]["PreToolUse"][3]["hooks"], [{"type": "command", "command": "echo keep"}])
            case("merge: a second merge is a no-op", iv.merge_hooks(once, {"PreToolUse": wanted["PreToolUse"]}), once)
            case("stale deny: a drive-form rule of an old wiki is stale",
                 iv.stale_deny(["Read(//c/Users/Old Wiki/raw/**)", "Read(./raw/**)",
                                "Read(//c/x/private/**)"], pathlib.Path("/home/x/wiki"), ["raw/**"]),
                 ["Read(//c/Users/Old Wiki/raw/**)"])
            case("stale deny: the current rule is not stale",
                 iv.stale_deny(["Read(//home/x/wiki/raw/**)"], pathlib.Path("/home/x/wiki"),
                               ["raw/**"]), [])
    finally:
        iv.ROOT = saved_root
        if saved_env is None:
            os.environ.pop("BRAIN_WIKI", None)
        else:
            os.environ["BRAIN_WIKI"] = saved_env


def verify_cases():
    spec = importlib.util.spec_from_file_location(
        "verify_install", ROOT / "scripts" / "verify_install.py")
    vi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vi)
    vi.results.clear()
    vi.wiki_suites(None)
    skipped = [r for r in vi.results if r[2] == "SKIP"]
    case("no wiki: the wiki suites are skipped", len(skipped), 3)
    case("and the reason is named", all(r[3] == "wiki not configured" for r in skipped), True)

    saved_root = vi.ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            wiki = base / "wiki"
            (wiki / "_local").mkdir(parents=True)
            vi.ROOT = base / "brain"
            case("no brain.md: the import check fails",
                 vi.brain_import_check(wiki)[0], "FAIL")
            (wiki / "_local" / "brain.md").write_text(
                iv.brain_import_line(vi.ROOT)[0] + "\n", encoding="utf-8")
            case("brain.md imports this brain: the import check passes",
                 vi.brain_import_check(wiki)[0], "PASS")
    finally:
        vi.ROOT = saved_root


# ---- the Jev policy file, the key line and the duplicate prompt hook -------
# The policy lives in the brain's _local/, which is machine-local and gitignored.
# Every case points ROOT at a temporary brain, so the real _local/ is never written.

def jev_cases():
    saved_root = iv.ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            home(base)
            brain = base / "brain"
            (brain / "_local").mkdir(parents=True)
            iv.ROOT = brain
            path = brain / "_local" / "jev-policy.json"

            done, (detail, what) = iv.step_jev_policy(None)
            case("jev: no file and no flag is pending", done, False)
            case("jev: the pending detail says missing", "missing" in detail, True)
            ok, _ = iv.apply_jev_policy(None)
            case("jev: apply with no flag creates the file", ok, True)
            case("jev: the new file holds mode off only", json.loads(path.read_text(encoding="utf-8")),
                 {"mode": "off"})
            case("jev: an existing file with no flag is done", iv.step_jev_policy(None)[0], True)

            path.write_text(json.dumps({"mode": "meta"}), encoding="utf-8")
            case("jev: no flag leaves an existing mode alone", iv.step_jev_policy(None)[0], True)
            iv.apply_jev_policy(None)
            case("jev: apply with no flag keeps the mode", json.loads(path.read_text(encoding="utf-8")),
                 {"mode": "meta"})

            case("jev: a flag that differs is pending", iv.step_jev_policy("off")[0], False)
            ok, _ = iv.apply_jev_policy("off")
            case("jev: the flag sets the mode", json.loads(path.read_text(encoding="utf-8")), {"mode": "off"})
            backups = list(path.parent.glob("jev-policy.json.bak-*"))
            case("jev: the replaced file is backed up", len(backups), 1)
            case("jev: the same flag again is done", iv.step_jev_policy("off")[0], True)

            path.write_text("{not json", encoding="utf-8")
            done, (detail, what) = iv.step_jev_policy("meta")
            case("jev: a malformed file is not done", done, False)
            case("jev: a malformed file is reported", "not valid JSON" in detail, True)
            ok, _ = iv.apply_jev_policy("meta")
            case("jev: a malformed file is never overwritten", (ok, path.read_text(encoding="utf-8")),
                 (False, "{not json"))

            case("jev: the policy line for a malformed file", iv.jev_policy_line(), "jev policy: malformed")
            path.unlink()
            case("jev: the policy line says missing", iv.jev_policy_line(), "jev policy: missing")
            path.write_text(json.dumps({"mode": "meta"}), encoding="utf-8")
            case("jev: the policy line shows the mode", iv.jev_policy_line(), "jev policy: meta")

            case("jev: the key line says yes when set", iv.jev_key_line({"TYPESAFE_API_KEY": "test-key"}),
                 "TYPESAFE_API_KEY set: yes")
            case("jev: the key line says no when unset", iv.jev_key_line({}), "TYPESAFE_API_KEY set: no")
            case("jev: a blank key counts as unset", iv.jev_key_line({"TYPESAFE_API_KEY": "  "}),
                 "TYPESAFE_API_KEY set: no")
            case("jev: the key line never shows the value",
                 "test-key" in iv.jev_key_line({"TYPESAFE_API_KEY": "test-key"}), False)

            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    iv.main(["--jev-mode", "max", "--check"])
                exited = None
            except SystemExit as stop:
                exited = stop.code
            case("jev: an unknown mode is refused", exited, 2)
    finally:
        iv.ROOT = saved_root

    jev_one = {"hooks": {"UserPromptSubmit": [{"hooks": [
        {"command": 'python "x/scripts/jev_route.py" --hook'}]}]}}
    jev_two = {"hooks": {"UserPromptSubmit": [{"hooks": [
        {"command": 'python "x/scripts/jev_route.py" --hook'},
        {"command": 'python "y/scripts/jev_route.py" --hook'}]}]}}
    labels = lambda found: [c["label"] for c in found]
    case("jev: one global Jev prompt hook is not a conflict",
         [l for l in labels(iv.conflicts(jev_one, ".githooks", [])) if "Jev" in l], [])
    dup = iv.conflicts(jev_one, ".githooks", [], jev_one)
    case("jev: a global and a project Jev hook are a duplicate",
         [l for l in labels(dup) if "Jev" in l], ["a second Jev prompt hook is registered"])
    case("jev: the duplicate is left for the owner", [c["fix"] for c in dup if "Jev" in c["label"]], ["report"])
    case("jev: two copies in one file are a duplicate",
         [l for l in labels(iv.conflicts(jev_two, ".githooks", [])) if "Jev" in l],
         ["a second Jev prompt hook is registered"])
    case("jev: a Jev hook is not reported as another prompt hook",
         any("another UserPromptSubmit" in l for l in labels(iv.conflicts(jev_one, ".githooks", []))), False)
    case("jev: a foreign prompt hook is still reported",
         any("another UserPromptSubmit" in l for l in labels(iv.conflicts(
             {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "someone-else"}]}]}},
             ".githooks", []))), True)


def matcher_cases():
    """MultiEdit is an edit tool, so the PII gate must see it on every path the installer and the brain wire."""
    case("the installer's PII matcher covers MultiEdit", "MultiEdit" in iv.PII_MATCHER, True)
    case("the installer's PII matcher keeps the Edit tools",
         all(t in iv.PII_MATCHER.split("|") for t in ("Edit", "Write", "NotebookEdit")), True)
    brain = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pii = [g["matcher"] for g in brain["hooks"]["PreToolUse"] if "pii_gate.py" in
           json.dumps(g["hooks"])]
    case("the brain's PII matcher covers MultiEdit", [("MultiEdit" in m) for m in pii], [True])
    case("the brain's PII matcher is the installer's", pii, [iv.PII_MATCHER])


# ---- client repos ------------------------------------------------------------
# Every case builds a temporary brain, a temporary wiki and temporary git repos.
# ROOT is the temporary brain and BRAIN_WIKI names the temporary wiki, so the real
# _local/, the real wiki and any real repo are never written.

def git_run(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def commit_repo(path, add=()):
    """A git repo with one commit; add lists paths to commit, forced (for tracked-file cases)."""
    path = pathlib.Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git_run("init", "-q", str(path))
    for rel in add:
        git_run("-C", str(path), "add", "-f", "--", rel)
    git_run("-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-q", "--allow-empty", "-m", "init")


def exclude_text(repo):
    out = git_run("-C", str(repo), "rev-parse", "--git-path", "info/exclude").stdout.strip()
    path = pathlib.Path(out)
    if not path.is_absolute():
        path = pathlib.Path(repo) / path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def ignored(repo, rel):
    return git_run("-C", str(repo), "check-ignore", "-q", "--", rel).returncode == 0


def client_repo_cases():
    saved_root, saved_env = iv.ROOT, os.environ.get("BRAIN_WIKI")
    saved_git = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "XDG_CONFIG_HOME")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            home(base)
            # The owner's global ignore file (~/.config/git/ignore) may already ignore the
            # settings file, which would hide the exclude step. Git reads empty config here.
            gitcfg = base / "gitconfig"
            gitcfg.write_text("", encoding="utf-8")
            os.environ["GIT_CONFIG_GLOBAL"] = str(gitcfg)
            os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
            os.environ["XDG_CONFIG_HOME"] = str(base / "xdg")
            brain = base / "brain"
            (brain / "_local").mkdir(parents=True)
            (brain / ".claude").mkdir()
            wiki = base / "wiki"
            (wiki / "wiki" / "clients" / "alpha-co").mkdir(parents=True)
            (wiki / "index.md").write_text("# index\n", encoding="utf-8")
            iv.ROOT = brain
            os.environ["BRAIN_WIKI"] = str(wiki)
            registry = brain / "_local" / "client-repos.json"

            print("client repo: the group")
            group = iv.client_repo_group("C:/Users/Daru Broodryk/brain", "alpha-co")
            back = json.loads(json.dumps(group))
            case("the group matches the edit tools", back["matcher"], "Write|Edit|MultiEdit")
            case("the group has a 5 second timeout", back["hooks"][0]["timeout"], 5)
            case("a path with spaces is quoted and survives JSON",
                 back["hooks"][0]["command"],
                 'python "C:/Users/Daru Broodryk/brain/scripts/wiki_edit_gate.py" --client alpha-co')

            print("client repo: apply")
            repo = base / "work" / "acme-app"
            commit_repo(repo)
            settings = repo / ".claude" / "settings.local.json"
            code, out = capture(["--client-repo", str(repo), "--client", "alpha-co", "--check"])
            case("check on a fresh repo exits 1", code, 1)
            case("check shows three pending steps", out.count("PENDING"), 3)
            case("check writes nothing", settings.exists() or registry.exists(), False)

            code, out = capture(["--client-repo", str(repo), "--client", "alpha-co", "--yes"])
            case("apply exits 0", code, 0)
            pre = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
            case("apply writes one PreToolUse group", len(pre), 1)
            want = 'python "' + brain.as_posix() + '/scripts/wiki_edit_gate.py" --client alpha-co'
            case("the group runs the gate for this client", pre[0]["hooks"][0]["command"], want)
            case("settings.local.json is ignored by git", ignored(repo, ".claude/settings.local.json"), True)
            case("the exclude file holds the line once",
                 exclude_text(repo).splitlines().count(".claude/settings.local.json"), 1)
            case("the registry maps the repo to the client",
                 json.loads(registry.read_text(encoding="utf-8")),
                 {repo.resolve().as_posix(): "alpha-co"})
            code, out = capture(["--client-repo", str(repo), "--client", "alpha-co", "--check"])
            case("check after apply exits 0", code, 0)
            case("check after apply says fully installed", "fully installed." in out, True)

            print("client repo: second run")
            before = settings.read_bytes()
            code, out = capture(["--client-repo", str(repo), "--client", "alpha-co", "--yes"])
            case("a second apply exits 0", code, 0)
            case("a second apply says nothing to do", "nothing to do." in out, True)
            case("a second apply leaves the settings file as it was", settings.read_bytes(), before)
            case("a second apply does not repeat the exclude line",
                 exclude_text(repo).splitlines().count(".claude/settings.local.json"), 1)

            print("client repo: other people's settings")
            kept = base / "work" / "kept-app"
            commit_repo(kept)
            hand = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
            old = {"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "timeout": 5,
                   "command": 'python "old/scripts/wiki_edit_gate.py" --client beta-ltd'}]}
            kept_settings = kept / ".claude" / "settings.local.json"
            kept_settings.parent.mkdir(parents=True)
            kept_settings.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [hand, old]}}),
                                     encoding="utf-8")
            code, _ = capture(["--client-repo", str(kept), "--client", "alpha-co", "--yes"])
            data = json.loads(kept_settings.read_text(encoding="utf-8"))
            case("apply keeps a hand-added group", data["hooks"]["PreToolUse"][0], hand)
            case("apply replaces our old group for another client",
                 [g["hooks"][0]["command"].endswith("--client alpha-co") for g in data["hooks"]["PreToolUse"][1:]],
                 [True])
            case("apply keeps other settings", data["model"], "opus")
            case("apply exits 0 with a hand-added group", code, 0)

            print("client repo: refusals")
            code, out = capture(["--client-repo", str(base / "work" / "nope"), "--client", "alpha-co", "--yes"])
            case("a path that is not a repo exits 2", code, 2)
            plain = base / "plain"
            plain.mkdir()
            code, out = capture(["--client-repo", str(plain), "--client", "alpha-co", "--yes"])
            case("a folder outside any repo exits 2", code, 2)
            sub = repo / "src"
            sub.mkdir()
            code, out = capture(["--client-repo", str(sub), "--client", "alpha-co", "--yes"])
            case("a subfolder of a repo exits 2", code, 2)
            case("the subfolder refusal says it is not the top", "top" in out, True)
            unknown = base / "work" / "unknown-app"
            commit_repo(unknown)
            code, out = capture(["--client-repo", str(unknown), "--client", "no-such", "--yes"])
            case("an unknown client exits 2", code, 2)
            case("an unknown client writes no settings",
                 (unknown / ".claude" / "settings.local.json").exists(), False)
            case("an unknown client names the wiki check", "not in the wiki" in out, True)
            try:
                code, out = capture(["--client-repo", str(repo), "--client-repo-typo"])
            except SystemExit as err:
                code = err.code
            case("an unknown flag exits 2", code, 2)
            code, out = capture(["--client-repo", str(repo)])
            case("--client-repo without --client exits 2", code, 2)

            print("client repo: git worktree")
            wt = base / "work" / "acme-wt"
            git_run("-C", str(repo), "worktree", "add", "-q", "-b", "wt-branch", str(wt))
            code, out = capture(["--client-repo", str(wt), "--client", "alpha-co", "--yes"])
            case("a worktree can be guarded", code, 0)
            case("the worktree's settings file is written",
                 (wt / ".claude" / "settings.local.json").is_file(), True)
            case("the exclude line is written to the shared exclude file",
                 ".claude/settings.local.json" in exclude_text(repo).splitlines(), True)
            case("the registry keys the worktree path",
                 wt.resolve().as_posix() in json.loads(registry.read_text(encoding="utf-8")), True)

            print("client repo: a committed settings file")
            tracked = base / "work" / "tracked-app"
            commit_repo(tracked)
            (tracked / ".claude").mkdir()
            (tracked / ".claude" / "settings.local.json").write_text('{"hooks": {}}\n', encoding="utf-8")
            git_run("-C", str(tracked), "add", "-f", "--", ".claude/settings.local.json")
            git_run("-C", str(tracked), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-q", "-m", "track settings")
            before = (tracked / ".claude" / "settings.local.json").read_bytes()
            code, out = capture(["--client-repo", str(tracked), "--client", "alpha-co", "--yes"])
            case("a committed settings file exits 1", code, 1)
            case("a committed settings file is left as it was",
                 (tracked / ".claude" / "settings.local.json").read_bytes(), before)

            print("client repo: already ignored by git")
            seen = base / "work" / "seen-app"
            commit_repo(seen)
            ignore_file = base / "global-ignore"
            ignore_file.write_text(".claude/settings.local.json\n", encoding="utf-8")
            gitcfg.write_text("[core]\n\texcludesFile = " + ignore_file.as_posix() + "\n", encoding="utf-8")
            code, out = capture(["--client-repo", str(seen), "--client", "alpha-co", "--yes"])
            case("apply exits 0 when git already ignores the file", code, 0)
            case("no exclude line is added when git already ignores it",
                 ".claude/settings.local.json" in exclude_text(seen).splitlines(), False)
            case("the settings file is still written",
                 (seen / ".claude" / "settings.local.json").is_file(), True)
            gitcfg.write_text("", encoding="utf-8")

            print("client repo: malformed files")
            bad = base / "work" / "bad-app"
            commit_repo(bad)
            (bad / ".claude").mkdir()
            (bad / ".claude" / "settings.local.json").write_text("{bad", encoding="utf-8")
            code, out = capture(["--client-repo", str(bad), "--client", "alpha-co", "--yes"])
            case("malformed settings exit 1", code, 1)
            case("malformed settings are left alone",
                 (bad / ".claude" / "settings.local.json").read_text(encoding="utf-8"), "{bad")
            registry.write_text("{bad", encoding="utf-8")
            fresh = base / "work" / "fresh-app"
            commit_repo(fresh)
            code, out = capture(["--client-repo", str(fresh), "--client", "alpha-co", "--yes"])
            case("a malformed registry exits 1", code, 1)
            case("a malformed registry is left alone", registry.read_text(encoding="utf-8"), "{bad")
    finally:
        iv.ROOT = saved_root
        if saved_env is None:
            os.environ.pop("BRAIN_WIKI", None)
        else:
            os.environ["BRAIN_WIKI"] = saved_env
        for name, value in saved_git.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ---- the Jev hook, the global rules and the session files ---------------------
# Every case runs against a temporary config directory and a temporary brain.
# The real ~/.claude and the real brain's _local/ are never touched.

UNMARKED_HOME = (
    "## Mine\n\nkeep me\n\n"
    "## Guardrails — apply every session\n\nold guard text\n\n"
    "## How Claude responds\n\nold response text\n\n"
    "## Build flow — only for a request you identify as a Build\n\nold build text\n"
)

OLD_JEV_SETTINGS = {"hooks": {
    "UserPromptSubmit": [{"hooks": [
        {"type": "command", "timeout": 20,
         "command": '/usr/bin/python3 "$HOME/.claude/scripts/jev_route.py" --hook'},
        {"type": "command", "command": "echo other"}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
}}


def prompt_commands(claude):
    data = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    return [h["command"] for g in data["hooks"]["UserPromptSubmit"] for h in g["hooks"]]


def wiring_brain(base):
    brain = base / "brain"
    (brain / "_local").mkdir(parents=True)
    (brain / "_ai").mkdir()
    (brain / "scripts").mkdir()
    shutil.copy(ROOT / "_ai" / "rules.md", brain / "_ai" / "rules.md")
    (brain / "scripts" / "jev_route.py").write_text("# stub\n", encoding="utf-8")
    iv.ROOT = brain
    return brain


def installer_wiring_cases():
    saved_root, saved_env = iv.ROOT, os.environ.get("BRAIN_WIKI")
    real_symlink = os.symlink
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp).resolve()
            brain = wiring_brain(base)
            os.environ["BRAIN_WIKI"] = str(base / "no-such-wiki")
            target = brain / "scripts" / "jev_route.py"
            cmd_start = '"' + sys.executable + '"'

            # ---- jev hook ----
            claude = base / "claude"
            home(claude)
            case("jev_hook_missing: not ok with no settings", iv.step_jev_hook()[0], False)
            home(claude, json.dumps(OLD_JEV_SETTINGS))
            case("jev_hook_missing: not ok with the old python3 hook", iv.step_jev_hook()[0], False)
            ok, _ = iv.apply_jev_hook()
            case("jev_hook_applied: apply ok", ok, True)
            case("jev_hook_applied: step ok after apply", iv.step_jev_hook()[0], True)
            cmds = prompt_commands(claude)
            jev = [c for c in cmds if c.endswith('jev_route.py" --hook')]
            case("jev_hook_applied: one jev command", len(jev), 1)
            case("jev_hook_applied: command starts with the quoted interpreter",
                 jev[0].startswith(cmd_start), True)
            link = claude / "scripts" / "jev_route.py"
            case("jev_hook_applied: the script resolves to the brain copy",
                 link.resolve() == target.resolve(), True)
            case("jev_hook_replaces_usr_bin: the old unquoted python3 entry is gone",
                 '/usr/bin/python3 "$HOME/.claude/scripts/jev_route.py" --hook' in cmds, False)
            case("jev_hook_replaces_usr_bin: the other hook is kept", "echo other" in cmds, True)
            data = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
            case("jev_hook_replaces_usr_bin: timeout kept on the jev hook",
                 data["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("timeout"), 20)
            case("jev_hook_replaces_usr_bin: PreToolUse kept",
                 data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "echo pre")
            case("jev_hook_replaces_usr_bin: a backup of the old settings exists",
                 len(list(claude.glob("settings.json.bak-*"))), 1)

            home(claude, "{not json")
            case("jev_hook: malformed settings are not ok", iv.step_jev_hook()[0], False)
            ok, _ = iv.apply_jev_hook()
            case("jev_hook: malformed settings are left untouched and fail",
                 (ok, (claude / "settings.json").read_text(encoding="utf-8")), (False, "{not json"))

            claude2 = base / "claude2"
            home(claude2, json.dumps(OLD_JEV_SETTINGS))

            def no_symlinks(src, dst, *args, **kwargs):
                raise OSError("no symlink rights")
            os.symlink = no_symlinks
            try:
                ok, _ = iv.apply_jev_hook()
            finally:
                os.symlink = real_symlink
            launcher = claude2 / "scripts" / "jev_route.py"
            case("jev_launcher_fallback: apply ok", ok, True)
            case("jev_launcher_fallback: a launcher file, not a link",
                 launcher.is_file() and not launcher.is_symlink(), True)
            case("jev_launcher_fallback: the launcher runs the brain script with runpy",
                 "runpy" in launcher.read_text(encoding="utf-8"), True)
            case("jev_launcher_fallback: step ok with the launcher", iv.step_jev_hook()[0], True)

            # ---- global rules ----
            claude3 = base / "claude3"
            claude3.mkdir()
            (claude3 / "CLAUDE.md").write_text(UNMARKED_HOME, encoding="utf-8")
            (brain / "CLAUDE.md").write_text("brain text\n", encoding="utf-8")
            home(claude3)
            case("global_rules_adopts_unmarked: not ok before apply",
                 iv.step_global_rules()[0], False)
            ok, _ = iv.apply_global_rules()
            text = (claude3 / "CLAUDE.md").read_text(encoding="utf-8")
            case("global_rules_adopts_unmarked: apply ok", ok, True)
            case("global_rules_adopts_unmarked: the Mine section is still there",
                 "## Mine\n\nkeep me" in text, True)
            case("global_rules_adopts_unmarked: the old bodies are gone",
                 any(s in text for s in ("old guard text", "old response text", "old build text")),
                 False)
            case("global_rules_adopts_unmarked: the file ends with the build-flow marker",
                 text.rstrip("\n").endswith("<!-- block:build-flow-global:end -->"), True)
            case("global_rules_adopts_unmarked: all three blocks are marked",
                 all(f"<!-- block:{n}:start -->" in text and f"<!-- block:{n}:end -->" in text
                     for n in ("global-guardrails", "response-contract", "build-flow-global")), True)
            case("global_rules_adopts_unmarked: step ok after apply",
                 iv.step_global_rules()[0], True)
            case("global_rules: the brain CLAUDE.md is never written",
                 (brain / "CLAUDE.md").read_text(encoding="utf-8"), "brain text\n")

            # ---- session files ----
            session = brain / "_local" / "CLAUDE.md"
            case("session_files_created: not ok before apply", iv.step_session_files()[0], False)
            ok, _ = iv.apply_session_files()
            case("session_files_created: apply ok", ok, True)
            case("session_files_created: the one comment line",
                 session.read_text(encoding="utf-8"),
                 "<!-- machine-local additions; may stay empty -->\n")
            case("session_files_created: step ok after apply", iv.step_session_files()[0], True)

            # ---- ordering and restart ----
            labels = [s[0] for s in iv.STEPS]
            case("the three wiring steps follow hook runtimes",
                 labels[labels.index("hook runtimes") + 1:],
                 ["jev hook", "global rules", "session files"])
            case("the three wiring steps need a restart",
                 all(x in iv.NEEDS_RESTART for x in ("jev hook", "global rules", "session files")),
                 True)
    finally:
        os.symlink = real_symlink
        iv.ROOT = saved_root
        if saved_env is None:
            os.environ.pop("BRAIN_WIKI", None)
        else:
            os.environ["BRAIN_WIKI"] = saved_env


def main():
    # No case may reach GitHub. Cases that need the private marketplace's answer
    # set it themselves.
    real_access = iv.repo_access
    iv.repo_access = lambda: (True, "")
    real_remote = iv.remote_head
    iv.remote_head = lambda: ""
    case("empty settings have no gate", iv.gate_registered({}), False)
    stale = {"hooks": {"UserPromptSubmit": [
        {"hooks": [{"command": 'python "x/prompt_gate.py"'}]}]}}
    case("a stale gate hook is seen", iv.gate_registered(stale), True)

    existing = {"model": "opus", "hooks": {
        "SessionStart": [{"hooks": [{"command": "a"}]}],
        "UserPromptSubmit": [{"hooks": [
            {"command": 'python "x/prompt_gate.py"'},
            {"command": "someone-elses-hook"}]}]}}
    dropped = iv.drop_gate_hooks(existing)
    case("dropping the gate keeps other settings", dropped["model"], "opus")
    case("dropping the gate keeps other hook events", "SessionStart" in dropped["hooks"], True)
    case("dropping the gate keeps another prompt hook",
         dropped["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"], "someone-elses-hook")
    case("the gate itself is gone", iv.gate_registered(dropped), False)
    case("dropping does not mutate the original", iv.gate_registered(existing), True)
    only_gate = iv.drop_gate_hooks(
        {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "a/prompt_gate.py"}]}]}})
    case("an emptied event is removed", "UserPromptSubmit" in only_gate.get("hooks", {}), False)

    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        ok, detail = iv.apply_gate()
        case("a machine with no settings file needs nothing", ok, True)
        case("and says there is nothing to do", "nothing to do" in detail, True)
        case("and no settings file is created", (path / "settings.json").exists(), False)

    with tempfile.TemporaryDirectory() as tmp:
        stale = {"hooks": {
            "SessionStart": [{"hooks": [{"command": "keep me"}]}],
            "UserPromptSubmit": [{"hooks": [{"command": 'python "~/.claude/skills/answer-only/prompt_gate.py"'}]}]},
            "theme": "dark"}
        path = home(tmp, json.dumps(stale))
        ok, detail = iv.apply_gate()
        settings = json.loads((path / "settings.json").read_text(encoding="utf-8"))
        case("the stale hook is removed", iv.gate_registered(settings), False)
        case("and it says so", "stale hook removed" in detail, True)
        case("existing hooks survive", settings["hooks"]["SessionStart"][0]["hooks"][0]["command"], "keep me")
        case("unrelated settings survive", settings.get("theme"), "dark")
        case("the old file is backed up", len(list(path.glob("settings.json.bak-*"))), 1)

        ok, detail = iv.apply_gate()
        case("a second run has nothing left to do", "nothing to do" in detail, True)

    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp, "{not json at all")
        ok, _ = iv.apply_gate()
        case("malformed settings are refused", ok, False)
        case("malformed settings are left alone",
             (path / "settings.json").read_text(encoding="utf-8"), "{not json at all")
        case("step_gate reports rather than raising", iv.step_gate()[0], False)

    case("detect answers every field", sorted(iv.detect()) == sorted(iv.FIELDS), True)
    case("a plain identifier survives safe()", iv.safe("ACME_DEV"), "ACME_DEV")
    case("a token is dropped by safe()", iv.safe("ghp_secret_value"), "")
    case("an overlong value is dropped by safe()", iv.safe("x" * 81), "")

    filled = iv.render({"git_name": "A Person", "git_email": "a@example.nz"})
    case("render places a detected value", "A Person <a@example.nz>" in filled["cli-bindings.md"], True)
    case("render names what is still blank", "Still blank:" in filled["cli-bindings.md"], True)
    full = iv.render({k: "x" for k in iv.FIELDS})
    case("nothing is blank when every field is set",
         "Still blank:" in full["workspace-bindings.md"], False)

    with tempfile.TemporaryDirectory() as tmp:
        local = pathlib.Path(tmp) / "_local"
        written = iv.write_bindings(local, {"vault_clone": "/one"})
        case("writes both binding files", len(written), 2)
        case("the written file carries the value",
             "/one" in (local / "workspace-bindings.md").read_text(encoding="utf-8"), True)

        (local / "cli-bindings.md").write_text("mine", encoding="utf-8")
        again = iv.write_bindings(local, {})
        case("never overwrites a binding file by default", again, [])
        case("the edited file is untouched",
             (local / "cli-bindings.md").read_text(encoding="utf-8"), "mine")

        iv.write_bindings(local, {"vault_clone": "/two"}, force=True)
        case("force rewrites the file",
             "/two" in (local / "workspace-bindings.md").read_text(encoding="utf-8"), True)
        case("force backs the old file up first",
             len(list(local.glob("cli-bindings.md.bak-*"))), 1)

    # A machine that has never seen Claude Code installs cleanly. A machine that
    # has one already is where this went wrong: a personal skill of the same
    # name, a hooks path pointing somewhere else, a global switch that turns
    # every hook off. Each of those leaves the install looking successful and
    # behaving as though it never ran.
    case("a clean setup has no conflicts", iv.conflicts({}, ".githooks", []), [])

    off = iv.conflicts({"disableAllHooks": True}, ".githooks", [])
    case("disableAllHooks is a conflict", len(off), 1)
    case("disableAllHooks is ours to override", off[0]["fix"], "override")

    ours = {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "python x/prompt_gate.py"}]}]}}
    case("our own prompt gate is not a conflict", iv.conflicts(ours, ".githooks", []), [])

    foreign = {"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "python recall.py"}]}]}}
    found = iv.conflicts(foreign, ".githooks", [])
    case("a foreign prompt hook is a conflict", len(found), 1)
    case("a foreign prompt hook is reported, not overridden", found[0]["fix"], "report")

    path = iv.conflicts({}, ".husky", [])
    case("a foreign hooks path is a conflict", len(path), 1)
    case("a foreign hooks path is ours to override", path[0]["fix"], "override")
    case("an unset hooks path is not a conflict", iv.conflicts({}, "", []), [])

    skills = iv.conflicts({}, ".githooks", ["humanizer", "migration"])
    case("a leftover skill copy is a conflict", len(skills), 1)
    case("a leftover copy is ours to take", skills[0]["fix"], "override")
    case("the conflict names the skills", "humanizer" in skills[0]["detail"], True)

    # The plugin step. Nothing here runs the claude CLI: `apply_plugins` shells
    # out, and a case that did would clone a private marketplace into whatever
    # config directory it found. What is worth pinning is the reading of the two
    # halves, because they go missing independently and the apply step must do
    # only the half that is absent.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        gaps = iv.plugin_gaps({})
        case("a bare machine is missing every plugin", len(gaps), len(iv.PLUGINS))
        case("and is missing their marketplaces too",
             all(g["marketplace_missing"] for g in gaps), True)

        # exist_ok because several plugins can come from one marketplace:
        # central and humanizer both ship from skills.
        for _, marketplace, _ in iv.PLUGINS:
            (path / "plugins" / "marketplaces" / marketplace).mkdir(parents=True, exist_ok=True)
        gaps = iv.plugin_gaps({})
        case("a cloned marketplace is not re-added",
             any(g["marketplace_missing"] for g in gaps), False)
        case("but an uninstalled plugin is still a gap", len(gaps), len(iv.PLUGINS))

        enabled = {"enabledPlugins": {n + "@" + m: True for n, m, _ in iv.PLUGINS}}
        case("a fully installed machine has no gaps", iv.plugin_gaps(enabled), [])
        case("a disabled plugin is a gap", len(iv.plugin_gaps(
            {"enabledPlugins": {n + "@" + m: False for n, m, _ in iv.PLUGINS}})),
            len(iv.PLUGINS))

        first = iv.PLUGINS[0]
        partial = {"enabledPlugins": {first[0] + "@" + first[1]: True}}
        case("only the missing plugin is reported",
             [g["name"] for g in iv.plugin_gaps(partial)],
             [n for n, _, _ in iv.PLUGINS[1:]])

        # A machine whose global settings will not parse must not read as fully
        # installed: that is the gate step's failure to report, not a pass here.
        home(tmp, "{not json at all")
        case("unreadable settings leave every plugin pending",
             len(iv.plugin_gaps(iv.plugin_settings())), len(iv.PLUGINS))

    case("the skills marketplace is marketplace/ in the vault",
         iv.PLUGINS[0][2], str(ROOT / "marketplace"))
    case("token-weather-usage installs from the skills marketplace",
         ("token-weather-usage", "skills", iv.SKILLS_SOURCE) in iv.PLUGINS,
         True)
    # cache-handoff left the marketplace in skills#6. Listing it here would
    # make the plugin step fail on every machine.
    case("cache-handoff is not expected",
         any(name == "cache-handoff" for name, _, _ in iv.PLUGINS), False)

    class Result:
        def __init__(self, out, err="", code=1):
            self.stdout, self.stderr, self.returncode = out, err, code

    case("tail reads the last thing the CLI said",
         iv.tail(Result("cloning\nfailed: repository not found\n")),
         "failed: repository not found")
    case("tail falls back to the exit code", iv.tail(Result("", "", 128)), "exit 128")

    # Without the CLI the step reports and installs nothing, rather than raising
    # and taking the other four steps down with it.
    real_cli = iv.claude_cli
    iv.claude_cli = lambda: ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home(tmp)
            done, (detail, _) = iv.step_plugins()
            case("no CLI means the step is pending", done, False)
            case("and says why", "not on PATH" in detail, True)
            ok, detail = iv.apply_plugins()
            case("applying without the CLI fails cleanly", ok, False)
            case("and installs nothing", "nothing installed" in detail, True)
    finally:
        iv.claude_cli = real_cli

    cleared = iv.clear_hook_blocks({"disableAllHooks": True, "theme": "dark"})
    case("clear_hook_blocks turns the switch off", cleared.get("disableAllHooks"), False)
    case("clear_hook_blocks leaves other settings alone", cleared.get("theme"), "dark")

    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp, json.dumps({"disableAllHooks": True}))
        iv.apply_gate()
        settings = json.loads((path / "settings.json").read_text(encoding="utf-8"))
        case("clearing the gate also un-disables hooks",
             settings.get("disableAllHooks"), False)
        case("and leaves no stale gate hook behind", iv.gate_registered(settings), False)

    # Every skill is a plugin now, so a directory under ~/.claude/skills/ is a
    # leftover copy shadowing the plugin's. Finding them is the seam.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        for name in ("humanizer", "caveman"):
            d = path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nname: " + name + "\n---\n", encoding="utf-8")
        (path / "skills" / "synced").mkdir(parents=True, exist_ok=True)
        (path / "skills" / "half-installed").mkdir(parents=True)
        mine = path / "skills" / "my-own-skill"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: my-own-skill\n---\n", encoding="utf-8")
        case("finds the leftover copies", iv.stale_skill_copies(), ["caveman", "humanizer"])
        case("a person's own skill is not a leftover",
             "my-own-skill" in iv.stale_skill_copies(), False)

        ok, detail = iv.apply_skills()
        case("without --force the copies stay", ok, False)
        case("and are still there", (path / "skills" / "caveman").is_dir(), True)
        ok, detail = iv.apply_skills(force=True)
        case("with --force the copies are moved", ok, True)
        case("nothing is left to shadow the plugin", iv.stale_skill_copies(), [])
        backups = list(path.glob("skills-backup-*"))
        case("they land in one backup folder", len(backups), 1)
        case("outside skills/, where they would still load",
             backups[0].parent == path, True)
        case("the moved copy keeps its file",
             (backups[0] / "humanizer" / "SKILL.md").exists(), True)
        case("a person's own skill stays put", mine.is_dir(), True)
        case("synced stays put", (path / "skills" / "synced").is_dir(), True)
        case("a second run has nothing to move", iv.apply_skills(force=True), (True, "none left"))
    with tempfile.TemporaryDirectory() as tmp:
        home(tmp)
        case("a clean machine has none", iv.stale_skill_copies(), [])

    lines = iv.conflict_report(iv.conflicts({"disableAllHooks": True}, ".husky", ["humanizer"]))
    case("the report covers every conflict", len(lines), 3)
    case("an override says it will be taken",
         any("--force" in line for line in lines), True)
    case("leftover copies are taken with --force",
         sum("--force" in line for line in lines), 3)
    case("a clean machine reports nothing", iv.conflict_report([]), [])

    # The whole point, rehearsed end to end: a machine still holding a copied
    # skill from the old layout, with hooks switched off globally on top.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp, json.dumps({"disableAllHooks": True}))
        mine = path / "skills" / "humanizer"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: humanizer\n---\nmine\n", encoding="utf-8")
        found = iv.machine_conflicts()
        labels = [c["label"] for c in found]
        case("a real pre-existing setup is detected", len(found) >= 2, True)
        case("it sees the leftover skill copy",
             any("not plugins" in label for label in labels), True)
        case("it sees hooks switched off",
             any("switched off" in label for label in labels), True)
        case("the switch and the copy are both ours to take",
             sorted(c["fix"] for c in found), ["override", "override"])


    # A machine installed before a plugin was retired still carries it.
    # It is found in either the settings or the CLI's install record.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        case("a clean machine has no retired plugins", iv.retired_plugins({}), [])
        case("an enabled retired plugin is found",
             iv.retired_plugins({"enabledPlugins": {"engineering@skills": True}}),
             ["engineering@skills"])
        case("a disabled one is found too",
             iv.retired_plugins({"enabledPlugins": {"engineering@skills": False}}),
             ["engineering@skills"])
        (path / "plugins").mkdir(parents=True)
        (path / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"claude-mem@skills": [{"scope": "project"}]}}),
            encoding="utf-8")
        case("one installed at project scope is found",
             iv.retired_plugins({}), ["claude-mem@skills"])
        case("cache-handoff is retired in favour of token-weather-usage",
             iv.RETIRED_PLUGINS.get("cache-handoff@skills"),
             "token-weather-usage@skills")
        case("every replacement is a skills plugin or nothing",
             all(v is None or v.endswith("@skills") for v in iv.RETIRED_PLUGINS.values()),
             True)
        case("claude-mem is removed without installing session-memory",
             iv.RETIRED_PLUGINS.get("claude-mem@skills"), None)
        case("gsd-core is retired", "gsd-core@skills" in iv.RETIRED_PLUGINS, True)
        case("central and humanizer are retired with no replacement",
             [iv.RETIRED_PLUGINS.get(p, "absent") for p in ("central@skills", "humanizer@skills")],
             [None, None])
        case("neither is installed any more",
             [n for n, _, _ in iv.PLUGINS if n in ("central", "humanizer")], [])

    # The plugin step against a stubbed CLI: what matters is the order of calls.
    class Ran:
        def __init__(self):
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return Result("", "", 0)

    real_cli, real_run = iv.claude_cli, iv.run_claude
    iv.claude_cli = lambda: "claude"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = home(tmp)
            for _, marketplace, _ in iv.PLUGINS:
                (path / "plugins" / "marketplaces" / marketplace).mkdir(parents=True, exist_ok=True)
            iv.run_claude = ran = Ran()
            ok, _ = iv.apply_plugins()
            updates = [c for c in ran.calls if c[:3] == ("plugin", "marketplace", "update")]
            case("an existing clone is updated before installing", ok, True)
            case("once per marketplace", len(updates),
                 len({m for _, m, _ in iv.PLUGINS}))
            first_install = next(i for i, c in enumerate(ran.calls) if c[1] == "install")
            case("and the update comes first",
                 ran.calls.index(updates[0]) < first_install, True)

            home(tmp, json.dumps({"enabledPlugins": {"cache-handoff@skills": True}}))
            iv.run_claude = ran = Ran()
            ok, detail = iv.apply_retired()
            case("a retired plugin is uninstalled", ("plugin", "uninstall",
                 "cache-handoff@skills") in ran.calls, True)
            case("and its replacement installed", ("plugin", "install",
                 "token-weather-usage@skills") in ran.calls, True)
            case("the replacement goes in before the old one comes out",
                 ran.calls.index(("plugin", "install", "token-weather-usage@skills")) <
                 ran.calls.index(("plugin", "uninstall", "cache-handoff@skills")), True)

            class Fails(Ran):
                def __call__(self, *args):
                    self.calls.append(args)
                    return Result("", "boom", 1)

            iv.run_claude = ran = Fails()
            ok, detail = iv.apply_retired()
            case("a failed replacement keeps the old plugin", ok, False)
            case("and nothing is uninstalled",
                 any(c[1] == "uninstall" for c in ran.calls), False)

            home(tmp, "{}")
            iv.run_claude = ran = Fails()
            iv.apply_plugins()
            case("a marketplace that fails to update is tried once",
                 sum(c[:2] == ("plugin", "marketplace") for c in ran.calls),
                 len({m for _, m, _ in iv.PLUGINS}))
            case("and nothing installs from it",
                 any(c[1] == "install" for c in ran.calls), False)
    finally:
        iv.claude_cli, iv.run_claude = real_cli, real_run

    # Auto-update. Third-party marketplaces are off by default, which is how a
    # machine ends up on the plugin versions it first installed.
    case("auto-update is a gap with no entry", iv.auto_update_gaps({}), ["skills"])
    case("and with the switch off", iv.auto_update_gaps(
        {"extraKnownMarketplaces": {"skills": {"autoUpdate": False}}}), ["skills"])
    on = iv.with_auto_update({"theme": "dark", "extraKnownMarketplaces": {
        "skills": {"source": {"source": "github", "repo": "elsewhere/fork"}},
        "other": {"source": {"source": "github", "repo": "x/y"}}}})
    case("turning it on closes the gap", iv.auto_update_gaps(on), [])
    case("an existing source is kept",
         on["extraKnownMarketplaces"]["skills"]["source"]["repo"], "elsewhere/fork")
    case("other marketplaces are left alone",
         "autoUpdate" in on["extraKnownMarketplaces"]["other"], False)
    case("unrelated settings survive", on["theme"], "dark")
    case("a missing entry gets the company source", iv.with_auto_update({})
         ["extraKnownMarketplaces"]["skills"]["source"],
         {"source": "directory", "path": iv.SKILLS_SOURCE})

    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp, json.dumps({"model": "opus"}))
        ok, _ = iv.apply_auto_update()
        settings = json.loads((path / "settings.json").read_text(encoding="utf-8"))
        case("apply turns auto-update on", iv.auto_update_gaps(settings), [])
        case("and keeps the rest", settings.get("model"), "opus")
        case("and backs the file up", len(list(path.glob("settings.json.bak-*"))), 1)
        case("a second run changes nothing", iv.apply_auto_update(), (True, "already on"))
        home(tmp, "{not json at all")
        case("malformed settings are refused here too", iv.apply_auto_update()[0], False)

    case("the deny rules step left with central",
         "deny rules" in [s[0] for s in iv.STEPS], False)

    # Hook runtimes. A plugin whose hooks start node fails on every event when
    # node is missing; the step must find it and name the fix, never apply one.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        plugins = path / "plugins"

        def plugin(name, commands):
            root = plugins / "cache" / "skills" / name / "1.0.0"
            (root / "hooks").mkdir(parents=True)
            (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": c}
                                          for c in commands]}]}}), encoding="utf-8")
            return root

        js = plugin("context-mode", ['node "${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.mjs"'])
        py = plugin("central", ['python "${CLAUDE_PLUGIN_ROOT}/x.py"'])
        nvm = plugin("session-memory", [
            'export PATH="$HOME/.nvm/versions/node/v1/bin:$PATH"; node "$_P/run.js" hook'])
        sneaky = plugin("other", ['echo nodes; python nodejs.py'])
        case("a node hook is found", iv.hook_runtimes(js), {"node"})
        case("a python hook needs python", iv.hook_runtimes(py), {"python"})
        case("node after a PATH export is found", iv.hook_runtimes(nvm), {"node"})
        case("node inside a path or word is not a call",
             "node" in iv.hook_runtimes(sneaky), False)
        case("a plugin with no hooks file needs nothing",
             iv.hook_runtimes(path / "nowhere"), set())

        (plugins / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "context-mode@skills": [{"scope": "user", "installPath": str(js)}],
            "central@skills": [{"scope": "user", "installPath": str(py)}],
            "session-memory@skills": [{"scope": "user", "installPath": str(nvm)}]}}),
            encoding="utf-8")
        settings = {"enabledPlugins": {"context-mode@skills": True,
                                       "central@skills": True,
                                       "session-memory@skills": False}}
        roots = iv.active_plugin_roots(settings)
        case("an enabled plugin is active", "context-mode@skills" in roots, True)
        case("a disabled plugin is not", "session-memory@skills" in roots, False)

        real_which, real_probe, real_vault = iv.shutil.which, iv.probe, iv.vault_hook_runtimes
        try:
            iv.vault_hook_runtimes = lambda: {"python"}
            iv.shutil.which = lambda name: None
            missing = iv.missing_runtimes(settings)
            case("missing node names the plugin that needs it",
                 missing.get("node"), ["context-mode@skills"])
            case("missing python names central and the vault's hooks",
                 missing.get("python"), ["central@skills", "this vault's hooks"])
            py_fix = iv.runtime_fix("python", missing["python"])
            case("python is never fixed by removing a plugin",
                 "claude plugin uninstall" in py_fix, False)
            case("and says the gates stop working", "PII and credential gates" in py_fix, True)
            fix = iv.runtime_fix("node", missing["node"])
            case("the fix offers to remove the plugin",
                 "claude plugin uninstall context-mode@skills" in fix, True)
            case("and to install node", "node" in fix and "restart Claude Code" in fix, True)
            home(tmp, json.dumps(settings))
            done, _ = iv.step_runtimes()
            case("missing node leaves the step pending", done, False)
            ok, detail = iv.apply_runtimes()
            case("applying never fixes it", ok, False)
            case("it says what to do instead", "claude plugin uninstall" in detail, True)
            iv.shutil.which = lambda name: "/usr/bin/" + name
            iv.probe = lambda *a: Result("3\n", "", 0)
            case("with node and python 3 nothing is missing", iv.missing_runtimes(settings), {})
            case("and the step is done", iv.step_runtimes()[0], True)

            # On PATH is not enough: the Store alias prints a message and fails,
            # and an old machine's python can be Python 2.
            iv.probe = lambda *a: Result("", "Python was not found", 9009)
            case("the Store alias does not count as python", iv.hook_python(), "")
            iv.probe = lambda *a: Result("2\n", "", 0)
            case("Python 2 does not count either", iv.hook_python(), "")
            iv.probe = lambda *a: None
            case("a python that cannot start does not count", iv.hook_python(), "")
            iv.probe = lambda *a: Result("3\n", "", 0)
            case("a working Python 3 counts", iv.hook_python(), "/usr/bin/python")

            # Optional tools are reported, never pending.
            iv.shutil.which = lambda name: None if name == "uv" else "/usr/bin/" + name
            iv.probe = lambda *a: Result("3\n" if "sys" in a[-1] else "", "",
                                         1 if a[-1] == "import yaml" else 0)
            gaps = [g[0] for g in iv.optional_gaps()]
            case("missing uv is reported", "uv" in gaps, True)
            case("missing PyYAML is reported", "PyYAML" in gaps, True)
            case("tzdata present is not reported", "tzdata" in gaps, False)
            case("the report names the install command",
                 any("pip install --user pyyaml" in line
                     for line in iv.optional_report(iv.optional_gaps())), True)
            case("optional gaps never make the runtime step pending",
                 iv.step_runtimes()[0], True)
        finally:
            iv.shutil.which, iv.probe, iv.vault_hook_runtimes = real_which, real_probe, real_vault

    # Nothing the installer suggests may need an administrator: every Windows
    # install is per user, pip installs go to the user's site-packages, and no
    # command elevates.
    commands = [c for platforms in iv.RUNTIME_INSTALL.values() for c in platforms.values()]
    commands += [c for _, platforms in iv.OPTIONAL_TOOLS.values() for c in platforms.values()]
    case("every winget install is per user",
         all("--scope user" in c for c in commands if c.startswith("winget")), True)
    case("every pip install is per user",
         all("--user" in c for c in commands if "pip install" in c), True)
    case("no install command elevates",
         any(word in c.lower() for c in commands
             for word in ("sudo", "runas", "-verb", "/usr/local/bin")), False)

    # Without the claude CLI, the fix is the per-user installer, never an admin one.
    fix = iv.claude_cli_fix()
    case("the CLI fix names the official installer", "claude.ai/install" in fix, True)
    case("on Windows it says not as administrator",
         "not as administrator" in fix or sys.platform != "win32", True)
    real_cli = iv.claude_cli
    iv.claude_cli = lambda: ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home(tmp)
            done, (detail, what) = iv.step_plugins()
            case("no CLI: the plan says how to install it", "claude.ai/install" in what, True)
            ok, detail = iv.apply_plugins()
            case("no CLI: applying says how too", "claude.ai/install" in detail, True)
            home(tmp, json.dumps({"enabledPlugins": {"gsd-core@skills": True}}))
            ok, detail = iv.apply_retired()
            case("no CLI: the retired step says how too", "claude.ai/install" in detail, True)
    finally:
        iv.claude_cli = real_cli

    # Without access to the private marketplace, nothing tries to clone it, and the
    # fix is a git sign-in that works with or without gh.
    iv.claude_cli = lambda: "claude"
    real_run = iv.run_claude
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home(tmp)
            iv.repo_access = lambda: (False, "Authentication failed")
            done, (detail, what) = iv.step_plugins()
            case("no access: the plugin step is pending", done, False)
            case("no access: the plan names the cause", "not readable" in detail, True)
            case("no access: the fix names the folder", iv.SKILLS_SOURCE in what, True)
            case("no access: the folder can be overridden", "VAULT_SKILLS_DIR" in what, True)
            calls = []
            iv.run_claude = lambda *a: calls.append(a) or Result("", "", 0)
            ok, detail = iv.apply_plugins()
            case("no access: applying fails", ok, False)
            case("no access: skills is never cloned",
                 any("skills" in " ".join(c) for c in calls), False)
            case("no access: the public marketplace still installs",
                 any("superpowers@claude-plugins-official" in c for c in calls), True)
            iv.repo_access = lambda: (True, "")
            done, (detail, what) = iv.step_plugins()
            case("with access: the plan installs", "clone the marketplaces" in what, True)
    finally:
        iv.claude_cli, iv.run_claude = real_cli, real_run
        iv.repo_access = lambda: (True, "")

    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        folder = pathlib.Path(tmp) / "elsewhere"
        folder.mkdir()
        (path / "plugins").mkdir(parents=True, exist_ok=True)
        (path / "plugins" / "known_marketplaces.json").write_text(json.dumps(
            {"skills": {"installLocation": str(folder)}}), encoding="utf-8")
        case("a folder marketplace is found without a clone",
             iv.marketplace_location("skills"), folder)
        case("and does not read as missing",
             [g["marketplace_missing"] for g in iv.plugin_gaps({}) if g["name"] == "flightdeck"],
             [False])

    case("flightdeck installs everywhere",
         ("flightdeck", "skills", iv.SKILLS_SOURCE) in iv.PLUGINS, True)
    case("next-steps installs everywhere",
         ("next-steps", "skills", iv.SKILLS_SOURCE) in iv.PLUGINS, True)

    # Plugin updates: pull the clone when GitHub is ahead, then update each
    # installed plugin the clone offers a different version of.
    with tempfile.TemporaryDirectory() as tmp:
        path = home(tmp)
        market = path / "plugins" / "marketplaces" / "skills"
        (market / ".claude-plugin").mkdir(parents=True)
        (market / ".git").mkdir()
        (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [
            {"name": "central", "source": "./plugins/central"},
            {"name": "flightdeck", "source": "./plugins/flightdeck"},
            {"name": "humanizer", "source": {"source": "url", "sha": "new"}},
            {"name": "context-mode", "source": {"source": "url", "sha": "x"}}]}),
            encoding="utf-8")
        for name, version in (("central", "1.4.0"), ("flightdeck", "0.3.2")):
            d = market / "plugins" / name / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "plugin.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (path / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {
            "central@skills": [{"scope": "user", "version": "1.3.1"}],
            "flightdeck@skills": [{"scope": "user", "version": "0.3.2"}],
            "humanizer@skills": [{"scope": "user", "version": "3.0.0",
                                       "gitCommitSha": "old"}]}}), encoding="utf-8")

        case("an older version is outdated, a matching one is not, an uninstalled one is skipped",
             iv.outdated_plugins(), ["central@skills", "humanizer@skills"])

        real_local, real_cli, real_run = iv.local_head, iv.claude_cli, iv.run_claude
        try:
            iv.claude_cli = lambda: "claude"
            iv.local_head = lambda: "aaa"
            iv.remote_head = lambda: "bbb"
            done, (detail, _) = iv.step_updates()
            case("a clone behind GitHub is pending", done, False)
            case("and says so", "behind GitHub" in detail, True)
            calls = []
            iv.run_claude = lambda *a: calls.append(a) or Result("", "", 0)
            ok, detail = iv.apply_updates()
            case("applying pulls the marketplace first",
                 calls[0], ("plugin", "marketplace", "update", "skills"))
            case("then updates each outdated plugin",
                 [c for c in calls if c[1] == "update"],
                 [("plugin", "update", "central@skills"),
                  ("plugin", "update", "humanizer@skills")])
            case("and reports it", ok and "updated central@skills" in detail, True)

            iv.remote_head = lambda: ""
            calls.clear()
            iv.apply_updates()
            case("without access the clone is not pulled",
                 any(c[1] == "marketplace" for c in calls), False)

            iv.remote_head = lambda: "aaa"
            (market / "plugins" / "central" / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": "1.3.1"}), encoding="utf-8")
            (path / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {
                "central@skills": [{"scope": "user", "version": "1.3.1"}]}}),
                encoding="utf-8")
            case("a current machine has nothing to update", iv.step_updates()[0], True)
            iv.local_head = lambda: ""
            case("with no clone the plugins step handles it", iv.step_updates()[0], True)
        finally:
            iv.local_head, iv.claude_cli, iv.run_claude = real_local, real_cli, real_run
            iv.remote_head = lambda: ""

    case("every forced step exists", all(f in [s[0] for s in iv.STEPS] for f in iv.FORCED), True)
    case("plugins come before what depends on them",
         [s[0] for s in iv.STEPS].index("plugins") < [s[0] for s in iv.STEPS].index("retired plugins"),
         True)

    iv.repo_access, iv.remote_head = real_access, real_remote
    wiki_cases()
    launcher_cases()
    stale_cases()
    verify_cases()
    jev_cases()
    matcher_cases()
    client_repo_cases()
    nightly_cases()
    installer_wiring_cases()
    os.environ.pop("VAULT_CLAUDE_HOME", None)
    total = RAN[0]
    print("\ntest_install_vault: " + str(total - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
