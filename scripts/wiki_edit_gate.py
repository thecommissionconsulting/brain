"""PreToolUse gate for wiki edits: R-58 (client name): no other client's name. R-58 (AI text): no text aimed at an AI model.

Runs on Write, Edit and MultiEdit. It checks only the text the edit adds, never the
whole file, and it answers in well under a second. It makes no network call and sends
nothing off the machine; the only file it writes is a once-a-day marker in the wiki's
_local/ folder.

Client names come from the folders under wiki/clients/ plus the committed name file
_ai/client-names.json in the wiki. Every machine gets that file from git clone.

R-58 (client name): an edit under wiki/clients/<client>/ that names another client.
  A distinctive name (two or more words, or any name listed in the name file) is
  blocked. A single-word name taken from a folder only warns. Text inside the client's
  own name is not counted, so "Alpha Co Holdings" in alpha-co-holdings is fine.
  Stops accidents, not intent: Bash writes are not checked.

R-58 (AI text): an edit to a wiki/**/*.md file that holds text aimed at an AI model. It warns only.

Fail-open by design. Any error gives one systemMessage naming the exception type, and
the edit goes through. A missing wiki gives no output.

A systemMessage is shown to the owner, not to the model.
"""
import datetime
import json
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wiki_root  # noqa: E402

NAMES_FILE = "_ai/client-names.json"
MARKER = "client-names-warned.txt"
TOOLS = {"Write", "Edit", "MultiEdit"}

AI_TEXT = re.compile(
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions"
    r"|disregard\s+(all\s+)?(the\s+|your\s+)?(previous\s+|prior\s+|above\s+)?instructions"
    r"|you\s+are\s+(now\s+)?(an?\s+)?(ai\s+assistant|language\s+model|chatbot|claude|chatgpt)\b"
    r"|do\s+not\s+(tell|inform)\s+the\s+user"
    r"|<\s*/?\s*(system|assistant|instructions?)\s*>",
    re.IGNORECASE,
)

MALFORMED_TEXT = "R-58 (client name): _ai/client-names.json is malformed; its names are ignored."


def _hidden(name):
    return name.startswith("_") or name.startswith(".")


def client_of(rel, not_clients):
    """The client slug for a wiki-relative path under wiki/clients/, or None."""
    parts = rel.split("/")
    if len(parts) < 4 or parts[0] != "wiki" or parts[1] != "clients":
        return None
    folders = parts[2:-1]
    if not folders or _hidden(folders[0]):
        return None
    if folders[0] in not_clients:
        if len(folders) < 2 or _hidden(folders[1]) or folders[1] in not_clients:
            return None
        return folders[1]
    return folders[0]


def _client_folders(clients_dir, not_clients):
    """Client folder names, walked the same way client_of walks a path."""
    if not clients_dir.is_dir():
        return []
    out = []
    for child in sorted(clients_dir.iterdir()):
        if not child.is_dir() or _hidden(child.name):
            continue
        if child.name in not_clients:
            for grand in sorted(child.iterdir()):
                if grand.is_dir() and not _hidden(grand.name) and grand.name not in not_clients:
                    out.append(grand.name)
        else:
            out.append(child.name)
    return out


def clients(wiki, data):
    """Map each client slug to (name, listed) pairs. Short and ignored names are dropped."""
    not_clients = set(data.get("not_clients", []))
    ignore = {s.casefold() for s in data.get("ignore", [])}
    aliases = data.get("clients", {})
    slugs = set(_client_folders(pathlib.Path(wiki) / "wiki" / "clients", not_clients))
    slugs |= set(aliases)
    out = {}
    for slug in sorted(slugs):
        pairs = [(slug.replace("-", " ").replace("_", " "), False)]
        pairs += [(alias, True) for alias in aliases.get(slug, [])]
        kept = []
        for name, listed in pairs:
            name = name.strip()
            if len(name) < 3 or name.casefold() in ignore:
                continue
            kept.append((name, listed))
        out[slug] = kept
    return out


def distinctive(name, listed):
    return listed or len(name.split()) >= 2


def fold(text):
    """ASCII and lowercase: accents dropped (Otaki matches Ōtaki), case ignored."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def name_pattern(name):
    """Words of the folded name, any run of non-alphanumerics between them, whole words only."""
    words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if w]
    if not words:
        return re.compile(r"(?!)")  # a name with no Latin letters matches nothing
    body = r"[^a-z0-9]+".join(re.escape(w) for w in words)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


def added_text(tool_name, tool_input):
    """The text an edit adds: content, new_string, or every new_string of a MultiEdit."""
    if tool_name == "Write":
        return str(tool_input.get("content") or "")
    if tool_name == "Edit":
        return str(tool_input.get("new_string") or "")
    if tool_name == "MultiEdit":
        return "\n".join(str(e.get("new_string") or "") for e in tool_input.get("edits") or [])
    return ""


def foreign_clients(text, own, names):
    """(block, warn): slugs of other clients named in text, sorted."""
    text = fold(text)
    own_spans = []
    for name, _listed in names.get(own, []) if own else []:
        own_spans += [m.span() for m in name_pattern(name).finditer(text)]
    hits = {}
    for slug in sorted(names):
        if slug == own:
            continue
        for name, listed in names[slug]:
            for m in name_pattern(name).finditer(text):
                if any(s <= m.start() and m.end() <= e for s, e in own_spans):
                    continue
                hits.setdefault(slug, []).append(distinctive(name, listed))
    block = sorted(s for s, flags in hits.items() if any(flags))
    warn = sorted(s for s, flags in hits.items() if not any(flags))
    return block, warn


def _load_names(wiki):
    """(data, malformed). Malformed or unreadable means empty data and a notice."""
    path = wiki / NAMES_FILE
    if not path.is_file():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        for key in ("not_clients", "ignore"):
            if key in data and not (isinstance(data[key], list)
                                    and all(isinstance(x, str) for x in data[key])):
                raise ValueError(key)
        if "clients" in data and not (isinstance(data["clients"], dict) and all(
                isinstance(v, list) and all(isinstance(x, str) for x in v)
                for v in data["clients"].values())):
            raise ValueError("clients")
        return data, False
    except (OSError, ValueError):
        return {}, True


def _malformed_notice(state_dir):
    """The malformed warning, shown once per day. A failed marker write is ignored."""
    today = datetime.date.today().isoformat()
    marker = pathlib.Path(state_dir) / MARKER
    try:
        if marker.read_text(encoding="utf-8").strip() == today:
            return None
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(today, encoding="utf-8")
    except OSError:
        pass
    return MALFORMED_TEXT


def _deny_reason(own, block):
    return (f"R-58 (client name): this edit to {own}'s notes names another client ({', '.join(block)}). "
            f"Remove it, or put shared material in wiki/internal/. If it is a vendor or a "
            f"common word, add it to ignore in _ai/client-names.json.")


def _client_mode(client, text, root, data, malformed, state_dir):
    """--client SLUG: every edit, any path, is checked against that client's name. R-58 (AI text) is off."""
    names = clients(root, data)
    if client not in names:
        return json.dumps({"systemMessage": f"R-58 (client name): client {client} is not in the wiki; check skipped."})
    block, warn = foreign_clients(text, client, names)
    out = {}
    messages = []
    if block:
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"R-58 (client name): this edit in {client}'s repo names another client ({', '.join(block)}). "
                f"Remove it, or keep shared material out of this repo. If it is a vendor or a "
                f"common word, add it to ignore in _ai/client-names.json."),
        }
    if warn:
        messages.append(f"R-58 (client name): this edit in {client}'s repo may name another client "
                        f"({', '.join(warn)}). Not blocked.")
    if malformed:
        notice = _malformed_notice(state_dir)
        if notice:
            messages.append(notice)
    if messages:
        out["systemMessage"] = " ".join(messages)
    return json.dumps(out) if out else ""


def _run(stdin_text, env, state_dir, client=None):
    payload = json.loads(stdin_text)
    tool = payload.get("tool_name", "")
    if tool not in TOOLS:
        return ""
    ti = payload.get("tool_input") or {}
    root = wiki_root.wiki_root(env)
    if root is None:
        return ""
    file_path = str(ti.get("file_path") or "").replace("\\", "/")
    if not file_path:
        return ""
    if client is not None:
        data, malformed = _load_names(root)
        return _client_mode(client, added_text(tool, ti), root, data, malformed, state_dir)
    try:
        rel = pathlib.Path(file_path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return ""

    data, malformed = _load_names(root)
    names = clients(root, data)
    own = client_of(rel, set(data.get("not_clients", [])))
    text = added_text(tool, ti)

    block, warn = ([], [])
    if own:
        block, warn = foreign_clients(text, own, names)

    out = {}
    messages = []
    ai_match = AI_TEXT.search(text) if rel.startswith("wiki/") and rel.endswith(".md") else None
    r59 = None
    if ai_match:
        r59 = f'R-58 (AI text): this edit holds text aimed at an AI model ("{ai_match.group(0)}"). Not blocked.'

    if block:
        reason = _deny_reason(own, block)
        if r59:
            reason += " " + r59
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    elif r59:
        messages.append(r59)
    if warn:
        messages.insert(0, f"R-58 (client name): this edit to {own}'s notes may name another client "
                           f"({', '.join(warn)}). Not blocked.")
    if malformed:
        notice = _malformed_notice(state_dir)
        if notice:
            messages.append(notice)
    if messages:
        out["systemMessage"] = " ".join(messages)
    return json.dumps(out) if out else ""


def run_hook(stdin_text, env=None, state_dir=None, client=None):
    """The JSON to print for one hook call, or "". Fails open with a systemMessage.

    client: a slug, checks every edit against that client's names (--client mode).
    """
    try:
        root = wiki_root.wiki_root(env)
        if state_dir is None:
            state_dir = root / "_local" if root is not None else pathlib.Path(".")
        return _run(stdin_text, env, state_dir, client)
    except Exception as err:
        return json.dumps({"systemMessage": f"wiki edit gate failed: {type(err).__name__}"})


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    client = None
    if "--client" in argv:
        i = argv.index("--client")
        value = argv[i + 1] if i + 1 < len(argv) else ""
        if not value or value.startswith("--"):
            sys.stdout.write(json.dumps({"systemMessage": (
                "R-58 (client name): --client needs a client slug, for example --client alpha-co; check skipped.")})
                + "\n")
            return 0
        client = value
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        out = run_hook(raw, client=client)
    except Exception as err:
        out = json.dumps({"systemMessage": f"wiki edit gate failed: {type(err).__name__}"})
    if out:
        sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
