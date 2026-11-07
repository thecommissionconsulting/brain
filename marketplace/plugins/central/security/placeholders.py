"""Stable, unguessable stand-ins for redacted values.

A placeholder is `<<redacted:<label>:<8 hex>>>`. The hex is HMAC-SHA256 of the value
under a per-session salt, so within one session the same secret always gets the
same token. The model can then tell "the same key in two files" from "two
different keys". Across sessions the tokens differ, so a transcript never lets
anyone line one session's tokens up against another's.

The salt is HMAC(machine key, session id). The machine key is 32 random bytes in
~/.claude/central/placeholder.key, made on first use. If the key can't be
read or made, a random salt is used for this call alone: the output is still
redacted, only the tokens stop being stable, and the caller says so.
"""
import hashlib
import hmac
import os
import pathlib
import re
import secrets

KEY_PATH = pathlib.Path.home() / ".claude" / "central" / "placeholder.key"
PLACEHOLDER = re.compile(r"<<redacted:[a-z0-9-]+:[0-9a-f]{8}>>")


def machine_key(path=None):
    path = pathlib.Path(path or KEY_PATH)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            pass  # another hook made it first; read theirs
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("placeholder key is not 32 bytes")
    return key


def session_salt(session_id, key_path=None):
    """(salt, stable). `stable` is False when the machine key was unavailable."""
    try:
        key = machine_key(key_path)
    except (OSError, ValueError):
        return secrets.token_bytes(32), False
    return hmac.new(key, session_id.encode("utf-8"), hashlib.sha256).digest(), True


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def token(label, value, salt):
    digest = hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"<<redacted:{slug(label)}:{digest}>>"


def substitute(text, hits, salt):
    """`text` with each (label, start, end) span replaced by its token."""
    out, cursor = [], 0
    for label, start, end in hits:
        out.append(text[cursor:start])
        out.append(token(label, text[start:end], salt))
        cursor = end
    out.append(text[cursor:])
    return "".join(out)
