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
import importlib.util
import json
import os
import pathlib
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

    case("the skills marketplace is the folder beside the vault",
         iv.PLUGINS[0][2], str(ROOT.parent.parent / "skills" / "skills-main"))
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
    os.environ.pop("VAULT_CLAUDE_HOME", None)
    total = RAN[0]
    print("\ntest_install_vault: " + str(total - FAILS[0]) + " passed, " + str(FAILS[0]) + " failed.")
    return 1 if FAILS[0] else 0


if __name__ == "__main__":
    sys.exit(main())
