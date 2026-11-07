"""Route a Build to a superpowers skill with TypeSafe's Jev model (R-55).

At the start of a Build, Claude writes a short summary of the work and asks Jev which
superpowers skill should start it. Jev answers with one skill from SKILLS and a
confidence. Below THRESHOLD, or for a skill outside SKILLS, `ask_user` is true, and
Claude names its best pick and asks the owner instead of acting on it.

The summary is sent to TypeSafe. The owner approved that on 2026-11-07. So send a
short summary of the Build, never raw client material and never a secret.

The API key comes only from the TYPESAFE_API_KEY environment variable. It is never
printed, logged or written to a file. Error messages name the error type and the HTTP
status, never the key.

Usage, from the repo root:

  python scripts/jev_route.py --text "Add a CSV export to the reports page"
  python scripts/jev_route.py raw/output/build-summary.md

Exit codes: 0 routed, 2 bad input or no key, 3 the Jev call failed.
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
THRESHOLD = 0.6
MAX_CHARS = 24000
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


def call_jev(payload, key, timeout=30):
    """POST the payload to Jev and return the parsed JSON. The key is never in an error."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask Jev which superpowers skill starts a Build.")
    parser.add_argument("file", nargs="?", help="a plan or summary file to send")
    parser.add_argument("--text", help="the Build summary as a string")
    args = parser.parse_args(argv)

    if (args.file is None) == (args.text is None):
        print("Give exactly one of a file path or --text.", file=sys.stderr)
        return 2
    try:
        raw = args.text if args.text is not None else pathlib.Path(args.file).read_text(encoding="utf-8")
        payload = build_request(raw)
    except (OSError, ValueError) as err:
        print("Bad input: " + str(err), file=sys.stderr)
        return 2

    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        print("TYPESAFE_API_KEY is not set. Set it in your shell; never put it in a file.", file=sys.stderr)
        return 2

    try:
        result = parse_response(call_jev(payload, key))
    except (urllib.error.URLError, OSError, ValueError) as err:
        # Name the type and the HTTP status only. str(err) is never printed.
        status = getattr(err, "code", None)
        label = type(err).__name__ + (" " + str(status) if status is not None else "")
        print("Jev call failed: " + label, file=sys.stderr)
        return 3

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
