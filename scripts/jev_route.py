"""Route a Build to a superpowers skill with TypeSafe's Jev model (R-55).

At the start of a Build, Claude writes a short summary of the work and asks Jev which
superpowers skill should start it. Jev answers with one skill from SKILLS and a
confidence. Below THRESHOLD, or for a skill outside SKILLS, `ask_user` is true, and
Claude names its best pick and asks the owner instead of acting on it.

The summary is sent to TypeSafe. The owner approved that on 2026-11-07. So send a
short summary of the Build, never raw client material and never a secret. Every call
goes through jev_client (policy, PII scan, deadline, decision log); this file only
builds the questions and reads the answers.

The classify hook (`--hook`) also sends each user prompt, raw text and not a summary.
The owner approved that on 2026-11-07, which widens the approval above. The hook reads
a UserPromptSubmit JSON on stdin and prints a hint for Claude's context: Question, Task
or Build. Claude still decides, under CLAUDE.md "How Claude responds".
- Skipped, not sent: empty prompts, slash commands, any prompt the policy in
  _local/jev-policy.json does not allow (mode off), and any prompt the PII scan
  (scripts/patterns.py) flags. The scan fails closed: if it cannot load or run, nothing is sent.
- The `#pii-ok` override of prompt_gate.py does not apply here.
- Only the prompt text is sent. session_id, transcript_path and cwd never leave the machine.
- Fails open: a Jev error prints one line naming the error type, and the prompt proceeds.
- Names and client material without a detectable pattern are not caught by the scan.

The API key comes only from the TYPESAFE_API_KEY environment variable. It is never
printed, logged or written to a file. Error messages name the error type and the HTTP
status, never the key.

Usage, from the repo root:

  python scripts/jev_route.py --text "Add a CSV export to the reports page"
  python scripts/jev_route.py raw/output/build-summary.md

Exit codes: 0 routed, 2 bad input, no key, policy off or blocked by the PII scan,
3 the Jev call failed.

Enforces R-56 for Build routing: only a short summary of the Build is sent, and only through jev_client.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jev_client  # noqa: E402

ENDPOINT = jev_client.DEFAULT_ENDPOINT
load_policy = jev_client.load_policy
MODEL = "jev-latest"
THRESHOLD = 0.6
MAX_CHARS = 24000
HOOK_MAX_CHARS = 4000
HOOK_TIMEOUT = 4   # jev_client.send enforces this as a total deadline; the hook entry allows 15 s
BUILD_TIMEOUT = 30 # the Build route is not a hook, so it keeps the longer limit
KINDS = {
    "question": "The user wants an answer or an explanation; nothing is to be changed",
    "task": "A bounded change or action: fix, run, edit, move, check or configure something that exists",
    "build": "New behaviour, a feature, a tool or a multi-step change that needs a plan first",
}
SKILLS = {
    "brainstorming":
        "The idea or requirements are still unclear; a new feature or change needs design before any plan",
    "writing-plans":
        "Requirements are agreed; multi-step work needs a written implementation plan",
    "subagent-driven-development":
        "A written plan already exists and is ready to be carried out task by task",
    "test-driven-development":
        "A small, clear code change or feature to build test-first, with no plan needed",
    "systematic-debugging":
        "A bug, failing test, error or unexpected behaviour must be found and fixed",
    "requesting-code-review":
        "The work is written and needs a review before it is merged",
    "finishing-a-development-branch":
        "The work is done and tested; it needs a PR, merge or branch clean-up",
}


def build_request(text):
    """The Jev payload for one Build summary. Raises ValueError on empty text."""
    text = text.strip()
    if not text:
        raise ValueError("the Build summary is empty")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return {
        "state": text,
        "model": MODEL,
        "questions": {
            "skill": {
                "type": "choice",
                "instructions": "Which superpowers skill should start this Build",
                "criteria": dict(SKILLS),
            },
        },
    }


def build_classify_request(text):
    """The Jev payload that labels one prompt Question, Task or Build. Raises ValueError on empty text."""
    text = text.strip()
    if not text:
        raise ValueError("the prompt is empty")
    if len(text) > HOOK_MAX_CHARS:
        text = text[:HOOK_MAX_CHARS]
    return {
        "state": text,
        "model": MODEL,
        "questions": {
            "kind": {
                "type": "choice",
                "instructions": "Is this prompt a Question, a Task or a Build",
                "criteria": dict(KINDS),
            },
        },
    }


def parse_response(data):
    """Read Jev's answer to the skill question. Raises ValueError if it is malformed."""
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict) or "skill" not in answers:
        raise ValueError("the Jev response has no answers.skill")
    answer = answers["skill"]
    if not isinstance(answer, dict):
        raise ValueError("the Jev response has a malformed answers.skill")
    choice = answer.get("choice")
    try:
        confidence = float(answer.get("confidence", 0))
    except (TypeError, ValueError):
        raise ValueError("the Jev response has a non-numeric confidence")
    probabilities = answer.get("probabilities") or {}
    if choice not in SKILLS:
        choice = None
    return {
        "skill": choice,
        "confidence": confidence,
        "ask_user": choice is None or confidence < THRESHOLD,
        "probabilities": probabilities,
    }


def parse_classify_response(data):
    """Read Jev's answer to the kind question. Raises ValueError if it is malformed."""
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict) or "kind" not in answers:
        raise ValueError("the Jev response has no answers.kind")
    answer = answers["kind"]
    if not isinstance(answer, dict):
        raise ValueError("the Jev response has a malformed answers.kind")
    choice = answer.get("choice")
    try:
        confidence = float(answer.get("confidence", 0))
    except (TypeError, ValueError):
        raise ValueError("the Jev response has a non-numeric confidence")
    if choice not in KINDS:
        choice = None
    return {
        "kind": choice,
        "confidence": confidence,
        "ask_user": choice is None or confidence < THRESHOLD,
    }


def hook_context(result):
    """The text the hook adds to Claude's context: a hint, never an instruction."""
    if result["kind"] is None:
        return "Jev gave no usable label for this prompt. Classify it yourself."
    kind = result["kind"].capitalize()
    confidence = f"{result['confidence']:.2f}"
    if result["ask_user"]:
        return f"Jev is unsure about this prompt (best guess: {kind}, confidence {confidence}). Classify it yourself."
    return f"Jev labels this prompt a {kind} (confidence {confidence}). Treat it as a hint; you decide."


def should_send(prompt, scan=None, policy=None):
    """(send, reason). Empty and slash-command prompts are never sent. The rest goes
    through jev_client.may_send for zone "meta": policy, then the PII scan, fail-closed."""
    if not prompt.strip():
        return False, "empty"
    if prompt.lstrip().startswith("/"):
        return False, "slash command"
    if policy is None:
        policy = load_policy()
    return jev_client.may_send(prompt, "meta", policy, scan)


def adapt(call):
    """jev_client.send passes endpoint=; the wrappers here take only the timeout."""
    def send_call(payload, key, timeout=30, endpoint=None):
        return call(payload, key, timeout=timeout)
    return send_call


def run_hook(stdin_text, env, call=None, scan=None, policy=None):
    """The UserPromptSubmit hook. Returns the JSON to print, or "" to print nothing.

    Never blocks the prompt. Only the prompt text is sent to Jev; the rest of the
    hook input (session id, transcript path, working directory) stays here.
    """
    call = call or call_jev
    hook_input = json.loads(stdin_text)
    prompt = hook_input.get("prompt") or hook_input.get("user_input") or ""
    ok, _ = should_send(prompt, scan, policy)
    if not ok:
        return ""
    key = env.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        return ""
    cut = len(prompt.strip()) > HOOK_MAX_CHARS
    answers = {}
    ms = None
    started = None
    try:
        request = build_classify_request(prompt)
        started = time.monotonic()
        data = jev_client.send(request, env, timeout=HOOK_TIMEOUT, call=adapt(call))
        ms = int((time.monotonic() - started) * 1000)
        if isinstance(data, dict) and isinstance(data.get("answers"), dict):
            answers = data["answers"]
        result = parse_classify_response(data)
    except Exception as err:
        if ms is None and started is not None:
            ms = int((time.monotonic() - started) * 1000)
        jev_client.log_decision("prompt", prompt, answers, cut, ms=ms)
        # Name the type and the HTTP status only: never the key, str(err) or the prompt.
        return json.dumps({"systemMessage": "Jev classify failed: " + jev_client.error_label(err)})
    jev_client.log_decision("prompt", prompt, answers, cut, ms=ms)
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                              "additionalContext": hook_context(result)}})


def call_jev(payload, key, timeout=30):
    """POST the payload to Jev through jev_client and return the parsed JSON."""
    return jev_client.post_json(payload, key, timeout, ENDPOINT)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask Jev which superpowers skill starts a Build.")
    parser.add_argument("file", nargs="?", help="a plan or summary file to send")
    parser.add_argument("--text", help="the Build summary as a string")
    parser.add_argument("--hook", action="store_true", help="run as the UserPromptSubmit hook, reading stdin")
    args = parser.parse_args(argv)

    if args.hook:
        if args.file is not None or args.text is not None:
            print("--hook takes no file or --text.", file=sys.stderr)
            return 2
        try:
            text = sys.stdin.buffer.read().decode("utf-8")
            output = run_hook(text, os.environ)
            if output:
                print(output)
            return 0
        except Exception:
            # Fail open, and print nothing: a broken hook must never block a prompt.
            return 0

    if (args.file is None) == (args.text is None):
        print("Give exactly one of a file path or --text.", file=sys.stderr)
        return 2

    policy = load_policy()
    if policy["mode"] == "off":
        print("Jev disabled by policy (_local/jev-policy.json)", file=sys.stderr)
        return 2

    try:
        raw = args.text if args.text is not None else pathlib.Path(args.file).read_text(encoding="utf-8")
        payload = build_request(raw)
    except (OSError, ValueError) as err:
        print("Bad input: " + str(err), file=sys.stderr)
        return 2

    allowed, reason = jev_client.may_send(raw, "meta", policy)
    if not allowed:
        print("Jev not called: " + reason, file=sys.stderr)
        return 2

    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        print("TYPESAFE_API_KEY is not set. Set it in your shell; never put it in a file.", file=sys.stderr)
        return 2

    cut = len(raw.strip()) > MAX_CHARS
    answers = {}
    try:
        data = jev_client.send(payload, os.environ, timeout=BUILD_TIMEOUT, call=adapt(call_jev))
        if isinstance(data, dict) and isinstance(data.get("answers"), dict):
            answers = data["answers"]
        result = parse_response(data)
    except (urllib.error.URLError, OSError, ValueError) as err:
        jev_client.log_decision("build", raw, answers, cut)
        # Name the type and the HTTP status only. str(err) is never printed.
        print("Jev call failed: " + jev_client.error_label(err), file=sys.stderr)
        return 3

    jev_client.log_decision("build", raw, answers, cut)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
