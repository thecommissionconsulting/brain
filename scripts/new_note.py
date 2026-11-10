"""Create a wiki note from its template, with the frontmatter and map lines it needs.

Run from anywhere: python scripts/new_note.py <command> ... The wiki comes from wiki_root.

  client "<Name>" [--display NAME]           wiki/clients/<slug>/<slug>.md, name file entry
  engagement <client> "<Title>"              wiki/clients/<client>/engagements/<client>-<slug>.md
  meeting <client> "<Topic>" [--engagement S] wiki/clients/<client>/meetings/<date>-<client>-<slug>.md
  playbook "<Title>"                         wiki/internal/playbooks/<slug>.md
  retro <engagement-stem>                    wiki/internal/retrospectives/<stem>-retro.md
  timesheet                                  wiki/internal/timesheets/<date>-timesheet.md

Common: --date YYYY-MM-DD (default today), --owner NAME (default git user.name of the wiki),
--source TEXT (adds a source: line to the frontmatter).

Never overwrites: an existing path or an existing note with the same stem exits 1.
Runs the R-58 and R-59 checks from wiki_edit_gate on the text it is about to write. Exit 2
on an R-58 block. Keeps index.md section 9 true for every folder it creates.
"""
import argparse
import ast
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wiki_root  # noqa: E402
import wiki_edit_gate as wg  # noqa: E402

NAMES_REL = "_ai/client-names.json"
PATH_LINE = re.compile(r"`([^`]+/)`")
SLUG_OK = re.compile(r"[a-z0-9][a-z0-9-]*")
ANSWERS = {
    "client": "Who is the client? What do they need from us? What is still open?",
    "engagement": "What is in scope? What has been decided? What comes next?",
    "meeting": "What was discussed? What was decided? What must happen next?",
    "playbook": "When is it used? What are the steps? Where does it go wrong?",
    "timesheet": "Where did the hours go? Which hours are estimates? What is missing from the transcripts?",
}


def fail(msg, code=2):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def slug(text):
    """ASCII, lowercase, runs of other characters to a hyphen. Exit 2 if nothing is left."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    out = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not out:
        fail('name has no Latin letters: pass an ASCII name and --display "<name>"')
    return out


def required_fields():
    """check_frontmatter.REQUIRED, read with ast. The checker is not imported: it runs its lint on import."""
    tree = ast.parse((HERE / "check_frontmatter.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "REQUIRED" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("REQUIRED not found in check_frontmatter.py")


def yaml_value(value):
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./-]*", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def split_front(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ValueError("note has no frontmatter")
    return m.group(1), text[m.end():]


def set_fields(fm, fields, after="owner"):
    """Set each key's line; a missing key goes under `after:`, or at the end."""
    lines = fm.split("\n") if fm else []
    for key, value in fields.items():
        if value is None:
            continue
        new = f"{key}: {yaml_value(value)}"
        pat = re.compile(rf"^{re.escape(key)}:.*$")
        idx = next((i for i, line in enumerate(lines) if pat.match(line)), None)
        if idx is not None:
            lines[idx] = new
            continue
        at = next((i for i, line in enumerate(lines) if line.startswith(after + ":")), None)
        if at is None:
            lines.append(new)
        else:
            lines.insert(at + 1, new)
    return "\n".join(lines)


def add_answers(body, kind):
    if re.search(r"^> \*\*Answers:\*\*", body, re.M):
        return body
    lines = body.split("\n")
    i = next(i for i, line in enumerate(lines) if line.startswith("# "))
    lines[i + 1:i + 1] = ["", f"> **Answers:** {ANSWERS[kind]}"]
    return "\n".join(lines)


def compose(template, subs, fields, kind=None):
    fm, body = split_front(template)
    for key, value in subs.items():
        body = body.replace("{" + key + "}", value)
    if kind:
        body = add_answers(body, kind)
    return "---\n" + set_fields(fm, fields) + "\n---\n" + body


def read_template(wiki, name):
    return (wiki / "_ai" / "templates" / name).read_text(encoding="utf-8")


def h1_of(text):
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return None


def require_client(wiki, client):
    if not SLUG_OK.fullmatch(client):
        fail(f"client must be a slug such as otaki-water-co, not {client!r}")
    note = wiki / "wiki" / "clients" / client / f"{client}.md"
    if not note.is_file():
        fail(f'{client} is not in the wiki. Create it first: python scripts/new_note.py client "<Name>"')
    display = h1_of(note.read_text(encoding="utf-8"))
    if not display:
        fail(f"{client}'s client note has no H1 name")
    return display


def stem_taken(wiki, stem):
    for dirpath, dirnames, filenames in os.walk(wiki):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("raw", "_local")]
        for name in filenames:
            if name.endswith(".md") and name[:-3] == stem:
                return True
    return False


def ensure_folder(wiki, rel):
    """Create the folder; keep index.md section 9: add a new leaf, drop a parent that is no longer one."""
    wiki = pathlib.Path(wiki)
    folder = wiki / rel
    folder.mkdir(parents=True, exist_ok=True)
    index = wiki / "index.md"
    if not index.is_file():
        return
    lines = index.read_text(encoding="utf-8").split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith("## 9.")), None)
    if start is None:
        print("index.md has no '## 9.' section; the vault map was not updated.", file=sys.stderr)
        return
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if PATH_LINE.fullmatch(lines[i].strip())]
    entries = {PATH_LINE.fullmatch(lines[i].strip()).group(1) for i in rows}

    def has_subdir(path):
        return path.is_dir() and any(child.is_dir() for child in path.iterdir())

    keep = set()
    for entry in entries:
        parent = entry.rstrip("/")
        if rel.startswith(parent + "/") and has_subdir(wiki / parent):
            continue
        keep.add(entry)
    if not has_subdir(folder):
        keep.add(rel.rstrip("/") + "/")
    block = [f"`{e}`" for e in sorted(keep)]

    if rows:
        first = rows[0]
        out = []
        for i, line in enumerate(lines):
            if i in rows:
                if i == first:
                    out.extend(block)
                continue
            out.append(line)
    else:
        last = max((i for i in range(start + 1, end) if lines[i].strip()), default=start)
        out = lines[:last + 1] + [""] + block + lines[last + 1:]
    if out != lines:
        with open(index, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out))


def write_note(wiki, rel, text):
    path = wiki / rel
    ensure_folder(wiki, pathlib.PurePosixPath(rel).parent.as_posix())
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def update_names(wiki, slug_, display):
    """Add the display name under clients[slug] in the name file. A malformed file is left alone."""
    path = wiki / NAMES_REL
    data = {"clients": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            clients = data.setdefault("clients", {})
            if not isinstance(clients, dict):
                raise ValueError("clients")
            names = clients.setdefault(slug_, [])
            if not (isinstance(names, list) and all(isinstance(x, str) for x in names)):
                raise ValueError("entry")
        except (OSError, ValueError):
            print(f"R-58: {NAMES_REL} is malformed; left alone. Add {display!r} to it by hand.",
                  file=sys.stderr)
            return
    names = data["clients"].setdefault(slug_, [])
    if display not in names:
        names.append(display)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def set_last_touch(path, day):
    fm, body = split_front(path.read_text(encoding="utf-8"))
    fm = set_fields(fm, {"last_touch": day})
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("---\n" + fm + "\n---\n" + body)


def gate_text(text, own, names):
    """R-58 blocks (exit 2); R-58 warnings and R-59 hits are printed, and the note is written.

    R-58 applies only to a note that belongs to a client, as in the edit gate: a note under
    wiki/internal/ with no client (a playbook, a timesheet) may name clients."""
    block, warn = wg.foreign_clients(text, own, names) if own else ([], [])
    if block:
        fail(f"R-58: this note names another client ({', '.join(block)}). Remove that name, or put "
             f"shared material in wiki/internal/. The note was not written.")
    if warn:
        print(f"R-58: this note may name another client ({', '.join(warn)}). Written anyway.",
              file=sys.stderr)
    hit = wg.AI_TEXT.search(text)
    if hit:
        print(f'R-59: this note holds text aimed at an AI model ("{hit.group(0)}"). Written anyway.',
              file=sys.stderr)


def git_user(wiki):
    try:
        proc = subprocess.run(["git", "-C", str(wiki), "config", "user.name"],
                              capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def build(cmd, args, wiki, owner, day):
    """(rel path, note text, own client or None, after-write action or None)."""
    if cmd == "client":
        s = slug(args.name)
        display = args.display or args.name
        rel = f"wiki/clients/{s}/{s}.md"
        text = compose(read_template(wiki, "client.md"), {"Client Name": display},
                       {"client_id": s, "owner": owner, "created": day, "source": args.source}, "client")
        return rel, text, s, lambda: update_names(wiki, s, display)

    if cmd == "engagement":
        display = require_client(wiki, args.client)
        t = slug(args.title)
        stem = f"{args.client}-{t}"
        rel = f"wiki/clients/{args.client}/engagements/{stem}.md"
        text = compose(read_template(wiki, "engagement.md"),
                       {"Client": display, "engagement name": args.title},
                       {"client": f"[[{args.client}]]", "client_id": args.client, "owner": owner,
                        "created": day, "started": day, "source": args.source}, "engagement")
        return rel, text, args.client, None

    if cmd == "meeting":
        display = require_client(wiki, args.client)
        t = slug(args.topic)
        stem = f"{day}-{args.client}-{t}"
        rel = f"wiki/clients/{args.client}/meetings/{stem}.md"
        after = None
        if args.engagement:
            if not SLUG_OK.fullmatch(args.engagement):
                fail(f"engagement must be a stem, not {args.engagement!r}")
            eng = wiki / "wiki" / "clients" / args.client / "engagements" / f"{args.engagement}.md"
            if not eng.is_file():
                fail(f"engagement {args.engagement} is not under {args.client}; nothing written")
            after = lambda: set_last_touch(eng, day)  # noqa: E731
        text = compose(read_template(wiki, "meeting.md"),
                       {"Client": display, "topic": args.topic, "date": day},
                       {"client": f"[[{args.client}]]", "client_id": args.client, "owner": owner,
                        "created": day, "source": args.source}, "meeting")
        return rel, text, args.client, after

    if cmd == "playbook":
        s = slug(args.title)
        rel = f"wiki/internal/playbooks/{s}.md"
        text = compose(read_template(wiki, "playbook.md"), {"Job name": args.title},
                       {"owner": owner, "created": day, "source": args.source}, "playbook")
        return rel, text, None, None

    if cmd == "retro":
        if not SLUG_OK.fullmatch(args.stem):
            fail(f"engagement stem must be a slug, not {args.stem!r}")
        found = sorted(wiki.glob(f"wiki/clients/*/engagements/{args.stem}.md"))
        if len(found) != 1:
            fail(f"engagement note {args.stem} not found; create it with new_note.py engagement first")
        eng = found[0]
        client = eng.parent.parent.name
        display = require_client(wiki, client)
        h1 = h1_of(eng.read_text(encoding="utf-8")) or ""
        prefix = display + " — "
        if h1.startswith(prefix):
            title = h1[len(prefix):]
        elif " — " in h1:
            title = h1.split(" — ", 1)[1]
        else:
            title = args.stem
        rel = f"wiki/internal/retrospectives/{args.stem}-retro.md"
        text = compose(read_template(wiki, "retrospective.md"),
                       {"Client": display, "Engagement": title},
                       {"owner": owner, "created": day, "client": f"[[{client}]]",
                        "client_id": client, "engagement": f"[[{args.stem}]]",
                        "source": args.source})
        return rel, text, client, None

    if cmd == "timesheet":
        rel = f"wiki/internal/timesheets/{day}-timesheet.md"
        fm = (f"type: note\nstatus: active\nowner: {yaml_value(owner)}\ncreated: {day}\n"
              f"tags:\n  - timesheet")
        if args.source:
            fm = set_fields(fm, {"source": args.source})
        body = add_answers(f"\n# Timesheet {day}\n\n## Hours\n", "timesheet")
        return rel, "---\n" + fm + "\n---\n" + body, None, None

    raise AssertionError(cmd)


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", default=None)
    common.add_argument("--owner", default=None)
    common.add_argument("--source", default=None)
    p = argparse.ArgumentParser(prog="new_note.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("client", parents=[common])
    c.add_argument("name")
    c.add_argument("--display", default=None)
    e = sub.add_parser("engagement", parents=[common])
    e.add_argument("client")
    e.add_argument("title")
    m = sub.add_parser("meeting", parents=[common])
    m.add_argument("client")
    m.add_argument("topic")
    m.add_argument("--engagement", default=None)
    pb = sub.add_parser("playbook", parents=[common])
    pb.add_argument("title")
    r = sub.add_parser("retro", parents=[common])
    r.add_argument("stem")
    sub.add_parser("timesheet", parents=[common])
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)

    day = args.date or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        fail(f"--date must be YYYY-MM-DD, not {day!r}")
    if args.source is not None and ("\n" in args.source or "\r" in args.source or not args.source.strip()):
        fail("--source must be one line of text")

    wiki = wiki_root.require_wiki()
    owner = (args.owner or git_user(wiki)).strip()
    if not owner:
        fail("owner unknown: pass --owner NAME")

    data, malformed = wg._load_names(wiki)
    if malformed:
        print(wg.MALFORMED_TEXT, file=sys.stderr)
    names = wg.clients(wiki, data)

    rel, text, own, after = build(args.cmd, args, wiki, owner, day)
    stem = pathlib.PurePosixPath(rel).stem
    if (wiki / rel).exists() or stem_taken(wiki, stem):
        fail(f"{rel} or a note named {stem} already exists; nothing written", 1)

    gate_text(text, own, names)
    write_note(wiki, rel, text)
    if after:
        after()
    print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
