"""Is this path, or this shell command, a read of a credential file?

The list is data, in credential-files.json, shared with install_deny_rules.py.
This module covers what the permission deny rules miss: PowerShell's `type` and
`Get-Content`, `$HOME`-style paths, and any machine where the rules were never
installed.

The Bash test is the one pii_gate.py in the vault arrived at after two false
positives. A command must have a reading verb in command position AND name a
credential path. Matching a bare mention blocked writing .gitignore, and matching
the verb anywhere blocked commit messages containing "more" or "less".
"""
import json
import os
import pathlib
import re

DATA = json.loads(pathlib.Path(__file__).with_name("credential-files.json").read_text(encoding="utf-8"))
NAMES = frozenset(n.lower() for n in DATA["names"])
SUFFIXES = tuple(s.lower() for s in DATA["suffixes"])

# Any .env.<stage> file is a credential unless it is a template. The names list in
# credential-files.json still enumerates the common stages, because
# install_deny_rules.py builds Read() deny rules from it, and a deny rule such as
# Read(**/.env.*) could not be carved back out for .env.example. So the generic
# match lives only here, in the PreToolUse gate.
ENV_PREFIX = ".env."
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")

# A reading verb in command position, optionally behind `sudo` (with its flags,
# and the argument of -u/-g) or `cmd /c` (whose `type` reads a file). The two
# sudo flag forms must not overlap: an argument may not start with "-", or
# `sudo -u -u -u ...` backtracks exponentially.
READS_A_FILE = re.compile(
    r"(?:^|[|;&`(]|&&|\|\|)\s*\(?\s*"
    r"(?:sudo(?:\s+-[ug]\s+[^\s-]\S*|\s+-\S+)*\s+)?"
    r"(?:cmd(?:\.exe)?\s+/[ck]\s+[\"']?)?"
    r"(cat|bat|head|tail|less|more|nl|strings|xxd|od|type|sed|awk|sort|tac|base64|"
    r"grep|rg|ag|ack|findstr|Get-Content|gc|Select-String)\b",
    re.MULTILINE | re.IGNORECASE)
TOKEN = re.compile(r"[^\s|;&<>()'\"`]+")
PS_PARAMETER = re.compile(r"-[A-Za-z]+:")  # -Path:.env, PowerShell's joined form
HOME_VARS = ("${HOME}", "$HOME", "$env:USERPROFILE", "%USERPROFILE%")


def _home(home):
    return home or os.path.expanduser("~")


def _norm(path, cwd, home):
    p = str(path)
    for var in HOME_VARS:
        if p.lower().startswith(var.lower()):
            p = _home(home) + p[len(var):]
    if p.startswith("~"):
        p = _home(home) + p[1:]
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    # abspath, not normpath: on Windows a drive-less path such as \home\dev is not
    # absolute, and only abspath roots both sides of a comparison the same way.
    return os.path.normcase(os.path.abspath(p))


def is_credential_path(path, cwd=None, home=None):
    if not path:
        return False
    name = re.split(r"[\\/]", str(path).rstrip("\\/"))[-1].lower()
    if name in NAMES or name.endswith(SUFFIXES):
        return True
    if name.startswith(ENV_PREFIX) and not name.endswith(TEMPLATE_SUFFIXES):
        return True
    target = _norm(path, cwd, home)
    return any(target == _norm(os.path.join(_home(home), rel), None, home) for rel in DATA["home_paths"])


def command_reads_credential(command, cwd=None, home=None):
    if not READS_A_FILE.search(command or ""):
        return None
    for tok in TOKEN.findall(command):
        if tok.startswith("-"):
            m = PS_PARAMETER.match(tok)
            if not m:
                continue
            tok = tok[m.end():]
        if is_credential_path(tok, cwd, home):
            return re.split(r"[\\/]", tok.rstrip("\\/"))[-1]
    return None
