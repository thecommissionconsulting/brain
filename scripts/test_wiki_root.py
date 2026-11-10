"""Cases for wiki_root.py, run from the repo root: python scripts/test_wiki_root.py

Every case uses temp folders only. BRAIN is pointed at a temp brain for the
sibling-folder case, so no test reads or writes the real _local/brain.json or
the real ~/wiki. The config file, when a case needs one, is a temp file.
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import wiki_root  # noqa: E402


def make_wiki(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.md").write_text("# index\n", encoding="utf-8")
    return path


def case(name, got, want, fails):
    fails[1] += 1
    ok = got == want
    if not ok:
        fails[0] += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))


def main():
    fails = [0, 0]  # [failed, total]
    tmp = pathlib.Path(tempfile.mkdtemp())
    real_brain = wiki_root.BRAIN
    real_home = os.environ.get("HOME")
    try:
        # A temp brain, so the sibling-folder fallback looks in temp, not in the real checkout.
        brain = tmp / "brain"
        brain.mkdir()
        wiki_root.BRAIN = brain

        env_wiki = make_wiki(tmp / "env-wiki")
        cfg_wiki = make_wiki(tmp / "cfg-wiki")
        sib_wiki = make_wiki(tmp / "wiki")  # sibling of the temp brain

        config = tmp / "brain.json"
        config.write_text(json.dumps({"wiki": str(cfg_wiki)}), encoding="utf-8")
        missing_config = tmp / "absent" / "brain.json"

        # 1. env wins over config
        got = wiki_root.wiki_root(env={wiki_root.ENV_VAR: str(env_wiki)}, config=config)
        case("env wins over config", got, env_wiki.resolve(), fails)

        # 2. config used when env unset
        got = wiki_root.wiki_root(env={}, config=config)
        case("config used when env unset", got, cfg_wiki.resolve(), fails)

        # 3. sibling used when env and config are both unset
        got = wiki_root.wiki_root(env={}, config=missing_config)
        case("sibling used when both unset", got, sib_wiki.resolve(), fails)

        # 4. env set to a missing folder returns None (no fall-through to config)
        got = wiki_root.wiki_root(env={wiki_root.ENV_VAR: str(tmp / "nowhere")}, config=config)
        case("env set to missing folder returns None", got, None, fails)

        # 5. malformed config, no env, no sibling -> None
        shutil.rmtree(sib_wiki)
        bad = tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        got = wiki_root.wiki_root(env={}, config=bad)
        case("malformed config and no sibling returns None", got, None, fails)

        # 6. "~" in config expands
        fake_home = tmp / "home"
        make_wiki(fake_home / "vault")
        os.environ["HOME"] = str(fake_home)
        tilde = tmp / "tilde.json"
        tilde.write_text(json.dumps({"wiki": "~/vault"}), encoding="utf-8")
        got = wiki_root.wiki_root(env={}, config=tilde)
        case("~ in config expands", got, (fake_home / "vault").resolve(), fails)
        if real_home is not None:
            os.environ["HOME"] = real_home

        # 7. require_wiki on the missing sentinel exits 2 with the exact message
        err = io.StringIO()
        code = None
        with contextlib.redirect_stderr(err):
            try:
                wiki_root.require_wiki(wiki_root.MISSING)
            except SystemExit as exc:
                code = exc.code
        expected = f"wiki not found. Run: python {wiki_root.BRAIN}/scripts/install_vault.py --wiki <path>"
        case("require_wiki(MISSING) exits 2", code, 2, fails)
        case("require_wiki prints the exact message", err.getvalue().strip(), expected, fails)

        # 8. require_wiki returns a real wiki folder unchanged
        case("require_wiki returns a real wiki", wiki_root.require_wiki(cfg_wiki), cfg_wiki, fails)

        # 9. write_config then wiki_root round-trips
        out = tmp / "written" / "brain.json"
        wiki_root.write_config(cfg_wiki, config=out)
        written = json.loads(out.read_text(encoding="utf-8"))
        case("write_config stores absolute posix path", written, {"wiki": cfg_wiki.resolve().as_posix()}, fails)
        got = wiki_root.wiki_root(env={}, config=out)
        case("write_config round-trips through wiki_root", got, cfg_wiki.resolve(), fails)
    finally:
        wiki_root.BRAIN = real_brain
        if real_home is not None:
            os.environ["HOME"] = real_home
        shutil.rmtree(tmp, ignore_errors=True)

    total = fails[1]
    print(f"\ntest_wiki_root: {total - fails[0]} passed, {fails[0]} failed.")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
