"""Tests for scripts/setup_vault.py.

The question flow is a pure function over an IO facade, so the whole interview
can be replayed from a list of canned answers and the resulting decisions
asserted exactly. That is what makes the script's questions deterministic in
the sense that matters: the same answers always produce the same plan.

Nothing here may touch the real machine. The Obsidian registry tests write to
tmp_path; no test runs git, winget, or brew.

    python -m pytest scripts/test_setup_vault.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import setup_vault as sv


# --------------------------------------------------------------------------
# The interview
# --------------------------------------------------------------------------

def _io(*answers):
    return sv.ScriptedIO(list(answers))


def test_interview_collects_the_four_answers():
    io = _io("C:/work", "Ada Lovelace", "ada@example.nz", "y", "n")
    a = sv.ask(io, sv.Detected())
    assert a.workspace == Path("C:/work")
    assert a.git_name == "Ada Lovelace"
    assert a.git_email == "ada@example.nz"
    assert a.install_obsidian is True
    assert a.build_index is False


def test_workspace_default_is_the_root_of_c_on_windows():
    """On Windows the vault lands at C:\vault. On Linux and macOS - and
    WSL, which reports itself as Linux - ~/workspace is the convention, and on WSL
    ~/Documents usually does not exist at all."""
    assert sv.default_workspace("windows") == Path("C:/")
    assert sv.default_workspace("windows") / sv.VAULT_DIR == Path("C:/vault")
    assert sv.default_workspace("linux") == Path.home() / "workspace"
    assert sv.default_workspace("macos") == Path.home() / "workspace"


def test_wsl_is_announced_before_the_workspace_question(monkeypatch):
    """The default changes on WSL, so say why - otherwise a Linux-side path
    reads as a bug to someone expecting the documented C:\vault."""
    io = _io("", "Ada Lovelace", "ada@example.nz", "", "")
    sv.ask(io, sv.Detected(wsl=True))
    assert any("WSL" in line for line in io.output)

    quiet = _io("", "Ada Lovelace", "ada@example.nz", "", "")
    sv.ask(quiet, sv.Detected(wsl=False))
    assert not any("WSL" in line for line in quiet.output)


def test_blank_answers_take_the_documented_defaults():
    io = _io("", "Ada Lovelace", "ada@example.nz", "", "")
    a = sv.ask(io, sv.Detected())
    assert a.workspace == sv.DEFAULT_WORKSPACE
    # Obsidian defaults to yes (it is how you read the vault); the index
    # defaults to NO because it is a ~100 minute job.
    assert a.install_obsidian is True
    assert a.build_index is False


def test_index_question_is_asked_and_can_be_accepted():
    io = _io("C:/work", "Ada", "ada@example.nz", "n", "y")
    a = sv.ask(io, sv.Detected())
    assert a.build_index is True


def test_obsidian_question_is_skipped_when_already_installed():
    """Do not offer to install something that is already here."""
    io = _io("C:/work", "Ada", "ada@example.nz", "n")
    a = sv.ask(io, sv.Detected(obsidian_exe=Path("C:/Obsidian/Obsidian.exe")))
    assert a.install_obsidian is False
    assert a.build_index is False
    # Four prompts, not five: the Obsidian question was never put.
    assert not any("install obsidian" in p.lower() for p in io.output)


def test_git_identity_is_prefilled_from_existing_config():
    io = _io("C:/work", "", "", "n", "n")
    a = sv.ask(io, sv.Detected(git_name="Existing Name", git_email="e@example.nz"))
    assert a.git_name == "Existing Name"
    assert a.git_email == "e@example.nz"


def test_the_same_answers_always_produce_the_same_plan():
    answers = ("C:/work", "Ada", "ada@example.nz", "y", "n")
    first = sv.plan(sv.ask(_io(*answers), sv.Detected()), sv.Detected())
    second = sv.plan(sv.ask(_io(*answers), sv.Detected()), sv.Detected())
    assert first == second


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------

def test_plan_clones_both_repos_on_a_bare_machine():
    a = sv.ask(_io("C:/work", "Ada", "ada@example.nz", "n", "n"), sv.Detected())
    steps = sv.plan(a, sv.Detected())
    joined = " ".join(steps)
    assert "vault" in joined
    assert "rag" in joined


def test_plan_skips_a_repo_that_is_already_cloned(tmp_path):
    (tmp_path / "vault" / ".git").mkdir(parents=True)
    a = sv.ask(_io(str(tmp_path), "Ada", "ada@example.nz", "n", "n"), sv.Detected())
    steps = sv.plan(a, sv.Detected())
    assert not any("clone" in s and "vault" in s for s in steps)
    assert any("clone" in s and "rag" in s for s in steps)


def test_plan_mentions_the_index_cost_when_building():
    a = sv.ask(_io("C:/work", "Ada", "ada@example.nz", "n", "y"), sv.Detected())
    steps = sv.plan(a, sv.Detected())
    assert any("100" in s for s in steps), "the ~100 minute cost must be stated"


def test_plan_is_empty_of_actions_on_a_fully_configured_machine(tmp_path):
    for repo in ("vault", "rag"):
        (tmp_path / repo / ".git").mkdir(parents=True)
    (tmp_path / "rag" / ".venv").mkdir()
    detected = sv.Detected(
        obsidian_exe=Path("C:/Obsidian.exe"),
        git_name="Ada", git_email="ada@example.nz",
        vault_registered=True,
    )
    a = sv.ask(_io(str(tmp_path), "", "", "n"), detected)
    assert sv.plan(a, detected) == []


# --------------------------------------------------------------------------
# Obsidian vault registration — the part that can destroy someone's setup
# --------------------------------------------------------------------------

def _registry(tmp_path, payload):
    p = tmp_path / "obsidian.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_registering_adds_the_vault_and_keeps_existing_entries(tmp_path):
    reg = _registry(tmp_path, {"vaults": {"abc123": {"path": "C:\\old", "ts": 1}}})
    ok, msg = sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    assert ok, msg
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert "abc123" in data["vaults"], "existing vaults must survive"
    paths = [v["path"] for v in data["vaults"].values()]
    assert "C:\\work\\vault" in paths


def test_registering_is_idempotent(tmp_path):
    reg = _registry(tmp_path, {"vaults": {}})
    sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert len(data["vaults"]) == 1


def test_registering_refuses_while_obsidian_is_running(tmp_path):
    """Obsidian rewrites this file on exit, silently discarding our edit."""
    reg = _registry(tmp_path, {"vaults": {}})
    before = reg.read_text(encoding="utf-8")
    ok, msg = sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=True)
    assert not ok
    assert "running" in msg.lower()
    assert reg.read_text(encoding="utf-8") == before, "file must be untouched"


def test_registering_refuses_an_unfamiliar_file_rather_than_guessing(tmp_path):
    """The format is undocumented. If it changes, do not improvise on it."""
    reg = _registry(tmp_path, {"somethingElse": 1})
    before = reg.read_text(encoding="utf-8")
    ok, msg = sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    assert not ok
    assert reg.read_text(encoding="utf-8") == before


def test_registering_refuses_unparseable_json_rather_than_overwriting(tmp_path):
    reg = tmp_path / "obsidian.json"
    reg.write_text("{not json", encoding="utf-8")
    ok, msg = sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    assert not ok
    assert reg.read_text(encoding="utf-8") == "{not json"


def test_registering_backs_up_before_writing(tmp_path):
    reg = _registry(tmp_path, {"vaults": {"abc123": {"path": "C:\\old", "ts": 1}}})
    sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    backups = list(tmp_path.glob("obsidian.json.bak*"))
    assert backups, "a backup must exist before the registry is modified"
    assert "abc123" in backups[0].read_text(encoding="utf-8")


def test_registering_creates_the_file_when_absent(tmp_path):
    reg = tmp_path / "nested" / "obsidian.json"
    ok, msg = sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    assert ok, msg
    assert json.loads(reg.read_text(encoding="utf-8"))["vaults"]


def test_vault_id_is_sixteen_hex_characters(tmp_path):
    """Matches the ids Obsidian generates itself."""
    reg = _registry(tmp_path, {"vaults": {}})
    sv.register_vault(reg, Path("C:/work/vault"), obsidian_running=False)
    (vid,) = json.loads(reg.read_text(encoding="utf-8"))["vaults"]
    assert len(vid) == 16
    int(vid, 16)


# --------------------------------------------------------------------------
# Generated RAG config — this is what stops the installer path being hardcoded
# --------------------------------------------------------------------------

def test_rag_config_points_at_the_cloned_vault(tmp_path):
    cfg = sv.rag_config(tmp_path / "vault")
    roots = [v["path"] for v in cfg["obsidian"]["vaults"]]
    assert str((tmp_path / "vault" / "wiki").as_posix()) in roots
    assert cfg["embedding"]["model"] == "BAAI/bge-small-en-v1.5"
    assert cfg["privacy"]["local_only"] is True
    assert cfg["schedule"]["enabled"] is False, "a schedule was never asked for"


def test_rag_config_carries_the_calibrated_floors():
    cfg = sv.rag_config(Path("C:/work/vault"))
    assert cfg["retrieval"]["min_similarity"] == 0.60
    assert cfg["retrieval"]["min_top_similarity"] == 0.60


def test_rag_config_uses_forward_slashes(tmp_path):
    """Backslashes in JSON need escaping and are an easy way to break this."""
    cfg = sv.rag_config(tmp_path / "vault")
    for v in cfg["obsidian"]["vaults"]:
        assert "\\" not in v["path"]


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------

def test_dry_run_plans_but_never_applies(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(sv, "run", lambda *a, **k: called.append(a))
    io = _io(str(tmp_path), "Ada", "ada@example.nz", "y", "y")
    sv.main(["--dry-run"], io=io)
    assert called == [], "dry run must not execute anything"


def test_winget_invocation_is_non_interactive():
    """winget blocks on source agreements without these flags."""
    cmd = " ".join(sv.obsidian_install_command("windows"))
    assert "--accept-source-agreements" in cmd
    assert "--accept-package-agreements" in cmd
    assert "--disable-interactivity" in cmd


def test_winget_installs_for_the_current_user():
    """A machine-wide install raises a UAC prompt; nothing here needs admin."""
    assert "--scope user" in " ".join(sv.obsidian_install_command("windows"))


def test_linux_reports_rather_than_installing():
    assert sv.obsidian_install_command("linux") is None


def test_plan_does_not_offer_to_register_an_already_known_vault(tmp_path):
    """detect() runs before the workspace is known, so main() must re-check."""
    reg = tmp_path / "obsidian.json"
    vault = tmp_path / "ws" / sv.VAULT_DIR
    reg.write_text(json.dumps({"vaults": {"a1": {"path": str(vault), "ts": 1}}}),
                   encoding="utf-8")
    assert sv.vault_is_registered(reg, vault) is True
    assert sv.vault_is_registered(reg, tmp_path / "ws" / "other") is False

    detected = sv.Detected(vault_registered=True)
    a = sv.ask(_io(str(tmp_path / "ws"), "Ada", "ada@example.nz", "n", "n"), detected)
    assert not any("register" in s for s in sv.plan(a, detected))


def test_installer_repo_is_rag():
    assert sv.INSTALLER_REPO.endswith("<owner>/rag.git")
    assert sv.INSTALLER_DIR == "rag"


def test_installer_path_is_recorded_under_local_which_is_gitignored():
    """R-31: absolute machine paths live in _local/, never in a synced note."""
    assert sv.INSTALLER_PATH_FILE.startswith("_local/")
