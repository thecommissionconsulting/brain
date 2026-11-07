"""PreToolUse hook: stop credential files reaching the model.

Denies Read and Grep calls aimed at a credential file, and Bash or PowerShell
commands that read one (credential_paths.py). This is the second layer: the first
is the permission deny rules that install_deny_rules.py writes into settings.json,
which have no code to fail. This layer covers PowerShell readers, `$HOME` paths,
and machines where the rules were never installed.

Fails open, and says so: an error, including a broken import, allows the call with
a system message. The security.* imports therefore live inside check().

It also refuses any write, edit or command that carries a <<redacted:...>> placeholder.
Without that, a model that read a redacted config file and rewrote it whole would
silently replace the real secret with the token.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _name(path):
    return str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def credential_reason(name):
    return (f"Blocked by central: `{name}` is a credential file, and reading it would put "
            f"the secret into the prompt and the session transcript. Ask the user for the "
            f"specific value you need, or read the matching .example template.")


WRITE_FIELDS = ("content", "new_string", "old_string", "new_source", "command")

PLACEHOLDER_REASON = (
    "Blocked by central: this would write a <<redacted:...>> redaction placeholder, which "
    "stands in for a secret you were never shown. Writing it would replace the real value "
    "with the placeholder. Leave that line out of the change, or ask the user for the value.")


def carries_placeholder(tool_input, placeholder):
    texts = [tool_input.get(f) for f in WRITE_FIELDS]
    for edit in tool_input.get("edits") or []:
        texts += [edit.get("old_string"), edit.get("new_string")]
    return any(isinstance(t, str) and placeholder.search(t) for t in texts)


def check(payload):
    """A deny reason, or None to allow."""
    from security.credential_paths import command_reads_credential, is_credential_path
    from security.placeholders import PLACEHOLDER
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    if (tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell")
            and carries_placeholder(ti, PLACEHOLDER)):
        return PLACEHOLDER_REASON
    if tool in ("Read", "Grep"):
        target = ti.get("file_path") if tool == "Read" else ti.get("path")
        if is_credential_path(target, cwd):
            return credential_reason(_name(target))
    if tool in ("Bash", "PowerShell"):
        name = command_reads_credential(ti.get("command") or "", cwd)
        if name:
            return credential_reason(name)
    return None


def main():
    # UTF-8 whatever the code page: Claude Code sends UTF-8, and Windows would
    # decode it as cp1252. Output stays ASCII-escaped JSON (json.dump default).
    raw = sys.stdin.buffer.read().decode("utf-8")
    if not raw.strip():
        return
    reason = check(json.loads(raw))
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": reason}}, sys.stdout)
        sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        json.dump({"systemMessage": f"central credential gate failed ({type(exc).__name__}); "
                                    f"the tool call was allowed unchecked."}, sys.stdout)
        sys.stdout.write("\n")
