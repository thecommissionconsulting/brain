"""PostToolUse hook: take secrets and payment numbers out of tool output.

Runs after Read, Bash, PowerShell, Grep and WebFetch. Every string in the tool's response is
checked against the `secret` and `financial` detectors in patterns.py; each match
is replaced by a <<redacted:...>> placeholder, and the rewritten response goes back
through `hookSpecificOutput.updatedToolOutput`. On Claude Code 2.1.292 that is
what the model reads and what the transcript stores (tests/fixtures/README.md),
so the raw value never reaches either.

Contact details and identifiers are left alone on purpose. Vault notes and client
data are full of them and they are the work; the prompt gate still blocks them
when they are pasted in.

Image and PDF results carry base64 bytes and are never rewritten.

Fails open, and says so: an error lets the output through unredacted with a
system message, because a redactor that blocks every tool call gets switched off.
The security.* imports sit inside main() so that a missing or broken module takes
the same path. What this cannot see: a script that reads a file itself and prints
only a summary.
"""
import json
import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BINARY_TYPES = {"image", "pdf"}


def redact_value(value, salt, counter):
    from security.patterns import OUTPUT, scan
    from security.placeholders import substitute
    if isinstance(value, str):
        hits = scan(value, OUTPUT)
        if not hits:
            return value
        counter[0] += len(hits)
        return substitute(value, hits, salt)
    if isinstance(value, list):
        return [redact_value(v, salt, counter) for v in value]
    if isinstance(value, dict):
        return {k: redact_value(v, salt, counter) for k, v in value.items()}
    return value


def note(count):
    return (f"central redacted {count} value(s) in this tool output as <<redacted:...>> "
            f"placeholders. They are opaque: do not guess the value, and never write a "
            f"placeholder into a file or a command. If you need the real value, ask the user.")


def main():
    from security.placeholders import session_salt
    # UTF-8 whatever the code page: Claude Code sends UTF-8, and Windows would
    # decode it as cp1252. Output stays ASCII-escaped JSON (json.dump default).
    raw = sys.stdin.buffer.read().decode("utf-8")
    if not raw.strip():
        return
    payload = json.loads(raw)
    response = payload.get("tool_response")
    if isinstance(response, dict) and response.get("type") in BINARY_TYPES:
        return
    session_id = payload.get("session_id")
    if session_id:
        salt, stable = session_salt(session_id)
    else:
        # No session id: a random salt, so sessionless payloads never share one.
        salt, stable = secrets.token_bytes(32), False
    counter = [0]
    updated = redact_value(response, salt, counter)
    if not counter[0]:
        return
    out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                  "updatedToolOutput": updated,
                                  "additionalContext": note(counter[0])}}
    if not stable:
        out["systemMessage"] = ("central: the placeholder key is unavailable, so "
                                "placeholders in this output are not stable across calls.")
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        json.dump({"systemMessage": f"central output redaction failed "
                                    f"({type(exc).__name__}); this tool output was NOT redacted."},
                  sys.stdout)
        sys.stdout.write("\n")
