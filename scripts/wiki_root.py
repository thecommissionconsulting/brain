"""Find the wiki repo on this machine.

The brain holds config, rules and scripts. The wiki holds the knowledge base and is
a separate clone. Content scripts call wiki_root() to find it. Brain scripts keep
their own ROOT.

Lookup order, first set value wins:
  1. the BRAIN_WIKI environment variable
  2. "wiki" in _local/brain.json (written by install_vault.py --wiki PATH)
  3. the sibling folder ../wiki next to the brain

A candidate counts only if it is a folder holding index.md. A set but invalid
value returns None; it does not fall through to the next one. A missing or
malformed config file counts as unset.
"""
import json
import os
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
CONFIG = BRAIN / "_local" / "brain.json"
ENV_VAR = "BRAIN_WIKI"
MISSING = BRAIN / "_local" / "no-wiki"  # a path that never exists


def _is_wiki(path):
    return path.is_dir() and (path / "index.md").is_file()


def _resolve(value):
    return Path(value).expanduser().resolve()


def _config_wiki(config):
    try:
        data = json.loads(Path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("wiki")
    return value if isinstance(value, str) and value else None


def wiki_root(env=None, config=CONFIG):
    """Return the wiki folder, or None if this machine has no valid one."""
    if env is None:
        env = os.environ

    candidates = []
    env_value = env.get(ENV_VAR)
    if env_value:
        candidates = [_resolve(env_value)]
    else:
        cfg_value = _config_wiki(config)
        if cfg_value:
            candidates = [_resolve(cfg_value)]
        else:
            candidates = [(BRAIN.parent / "wiki").expanduser().resolve()]

    chosen = candidates[0]
    return chosen if _is_wiki(chosen) else None


def require_wiki(root=None):
    """Return root (or wiki_root() when root is None) if it is a wiki; else exit 2."""
    if root is None:
        root = wiki_root()
    if root is not None and _is_wiki(Path(root)):
        return Path(root)
    print(
        f"wiki not found. Run: python {BRAIN}/scripts/install_vault.py --wiki <path>",
        file=sys.stderr,
    )
    raise SystemExit(2)


def write_config(wiki, config=CONFIG):
    """Store the wiki path in the per-machine config file."""
    config = Path(config)
    config.parent.mkdir(parents=True, exist_ok=True)
    path = _resolve(wiki).as_posix()
    config.write_text(json.dumps({"wiki": path}, indent=2) + "\n", encoding="utf-8")
