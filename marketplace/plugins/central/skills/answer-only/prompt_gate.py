"""UserPromptSubmit gate: keep personal data out of the prompt, keep padding out
of the reply. Installed globally -- see SKILL.md in this directory.

Two things happen on the way past, and they are here together because they share
a trigger: both are things nobody remembers to ask for. A reply's packaging is
invisible until you count tokens. A pasted address is invisible until it is
already in the context window, at which point nothing downstream can take it
back, which is why the check has to sit in front of the prompt rather than after
it.

`scripts/pii_gate.py` in the vault guards the other entrance, file reads, and its
docstring states the gap this fills: it "cannot help with anything pasted into
the prompt by hand."

Two modes, one constant:

  block    exit 2, which erases the prompt and hands back the reason. You edit
           and resend. Default.
  redact   rewrite the prompt through the hook's `updatedInput` field, replacing each match with a <<redacted:...>> placeholder (see security/placeholders.py). The prompt still runs.

Either way the data stays out of the model's context. The message names the
pattern and the character offsets and NEVER quotes what matched -- quoting it
would put the data back into the context this exists to keep it out of.

Names are not detected. A name is not reliably distinguishable from any other
capitalised word, and the vault owner's name is in every Windows path in the
repo, so a name check would block every prompt.

`#pii-ok` anywhere in the prompt skips the scan for that prompt. That escape
hatch is load-bearing. A gate with no way past it gets switched off within a
week, and a gate that is switched off protects nothing.

Fail-open by design, for the same reason `pii_gate.py` is: if this script itself
errors the prompt proceeds. A crashed gate that silently bricks every prompt
would be uninstalled within the hour.

The detectors live in security/patterns.py, shared with the output redaction and the vault's read gate. Change them there.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
# The security.* imports live inside the functions that use them, so a missing or
# broken module lands in the fail-open handler below instead of a bare traceback.

MODE = "block"          # "block" or "redact"
OVERRIDE = "#pii-ok"
SKILL = pathlib.Path(__file__).resolve().parent / "SKILL.md"
FENCE = re.compile(r"<!-- INJECT:START -->\n(.*?)\n<!-- INJECT:END -->", re.S)


def report(hits):
    """A block message that identifies each match without reproducing it."""
    by_label = {}
    for label, start, end in hits:
        by_label.setdefault(label, []).append(f"{start}-{end}")
    width = max(len(l) for l in by_label)
    lines = [f"  {l.ljust(width)}  x{len(s)}  (chars {', '.join(s)})"
             for l, s in by_label.items()]
    return ("Blocked by the answer-only prompt gate. The prompt was not sent, so "
            "nothing below reached the model:\n\n" + "\n".join(lines) +
            f"\n\nRedact those and resend. To send the prompt as it stands, add "
            f"{OVERRIDE} to it.")


def redact(text, hits, session_id):
    import secrets
    from security.placeholders import session_salt, substitute
    # No session id: use a random salt so sessionless prompts never share one.
    salt = session_salt(session_id)[0] if session_id else secrets.token_bytes(32)
    return substitute(text, hits, salt)


def contract():
    """The reply contract, read from SKILL.md so this file holds no second copy."""
    try:
        m = FENCE.search(SKILL.read_text(encoding="utf-8"))
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def emit(**fields):
    fields["hookEventName"] = "UserPromptSubmit"
    json.dump({"hookSpecificOutput": fields}, sys.stdout)
    sys.stdout.write("\n")


def main():
    from security.patterns import scan
    # UTF-8 whatever the code page: Claude Code sends UTF-8, and Windows would
    # decode it as cp1252. Output stays ASCII-escaped JSON (json.dump default).
    raw = sys.stdin.buffer.read().decode("utf-8")
    if not raw.strip():
        return
    payload = json.loads(raw)
    prompt = payload.get("user_input") or payload.get("prompt") or ""

    hits = [] if OVERRIDE in prompt else scan(prompt)
    rules = contract()

    if hits and MODE == "block":
        sys.stderr.write(report(hits) + "\n")
        sys.exit(2)
    if hits:
        emit(updatedInput=redact(prompt, hits, payload.get("session_id") or ""), additionalContext=rules,
             systemMessage=f"Prompt gate redacted {len(hits)} match(es) before sending.")
        return
    if rules:
        emit(additionalContext=rules)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        # Fail open, and say so: see the module docstring.
        json.dump({"systemMessage": f"answer-only prompt gate failed ({type(exc).__name__}); "
                                    f"the prompt was sent unchecked."}, sys.stdout)
        sys.stdout.write("\n")
