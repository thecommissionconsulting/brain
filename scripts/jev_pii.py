"""Review the Jev PII "yes" log: list the new entries, then mark them reviewed.

jev_client.log_pii writes one JSON line per prompt that Jev says still holds personal data
after masking (R-65). The lines sit in `_local/jev-pii/YYYY-MM-DD.jsonl`, and each line keeps
the masked text, so the folder is private and never leaves the machine.

An entry is new until its key, "<time> <sha256>", is a line in `.reviewed` in the same
folder. Keys rather than timestamps, so two prompts in the same second are never confused.
Bad JSON lines, and lines with no time or sha256, are skipped.

Modes:

  --list    Print the new entries, oldest first: time, confidence, tags and masked text.
  --done    Mark every current new entry reviewed. Prints how many it marked.

Enforces R-65: lists the Jev PII "yes" entries for Opus to draft a sweep pattern; the owner approves it.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jev_client  # noqa: E402

PII_DIR = jev_client.PII_DIR
MARKER = ".reviewed"


def entry_key(entry):
    return f"{entry['time']} {entry['sha256']}"


def reviewed_keys(log_dir):
    marker = pathlib.Path(log_dir) / MARKER
    if not marker.is_file():
        return set()
    lines = marker.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip()}


def all_entries(log_dir):
    """Every usable entry in log_dir, oldest first. A missing folder gives []."""
    folder = pathlib.Path(log_dir)
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or not entry.get("time") or not entry.get("sha256"):
                continue
            entries.append(entry)
    entries.sort(key=lambda e: str(e["time"]))
    return entries


def new_entries(log_dir=PII_DIR):
    """Entries whose key is not in the .reviewed marker, oldest first."""
    reviewed = reviewed_keys(log_dir)
    return [e for e in all_entries(log_dir) if entry_key(e) not in reviewed]


def mark_reviewed(log_dir=PII_DIR):
    """Append the key of each current new entry to .reviewed. Returns how many keys it added."""
    keys = []
    for entry in new_entries(log_dir):
        key = entry_key(entry)
        if key not in keys:
            keys.append(key)
    folder = pathlib.Path(log_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if keys:
        with (folder / MARKER).open("a", encoding="utf-8") as marker:
            marker.write("".join(key + "\n" for key in keys))
    return len(keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review the Jev PII yes log (R-65).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="print the new entries")
    mode.add_argument("--done", action="store_true", help="mark the new entries reviewed")
    args = parser.parse_args(argv)

    if args.list:
        entries = new_entries(PII_DIR)
        if not entries:
            print("no new PII entries")
        for entry in entries:
            tags = ", ".join(str(t) for t in entry.get("tags") or [])
            text = str(entry.get("text", "")).replace("\n", " ")
            print(f"{entry['time']}  {entry.get('confidence')}  {tags}  {text}")
    else:
        print(f"marked {mark_reviewed(PII_DIR)} reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
