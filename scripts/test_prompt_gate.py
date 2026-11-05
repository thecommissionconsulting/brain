"""Cases for the answer-only prompt gate, run from the repo root:

    python scripts/test_prompt_gate.py

The gate itself is not in this repo. It ships with the `answer-only` skill inside
the `central` plugin, so these tests run against the installed copy under
`~/.claude/plugins/cache/`. With no plugin installed there is nothing to test and
the run says so rather than failing every case. The tests stay in `scripts/` with
the vault's others, because the rules they encode are the vault's.

Half these cases are PASS cases, and those are the ones that matter. This gate
blocks on a match, so a false positive costs a resend on a prompt that was never
a problem. Every gate that gets uninstalled is uninstalled over a false positive,
not over a miss. Four of the PASS cases below are real false positives found
while writing the patterns: an npm version pin reading as an email address, a
dict lookup reading as a secret assignment, a long order number reading as a card
number, and two capitalised words after a digit reading as a street address.

The one deliberate miss is RFC1234, which has the shape of an NHI number and
blocks. `#pii-ok` is the answer to that, and the last case proves it works.

The credential fixtures carry `# pragma: allowlist secret` because
`hooks_guard.py` scans added lines for exactly the patterns this gate detects
and refused the commit under R-30 -- correctly. Every one of them is synthetic:
the AWS key id is the example value from AWS's own documentation, the JWT is the
specimen from jwt.io, and the rest are invented. None authenticates anything.
The literals are not repeated here, because a line of prose quoting one trips
the same guard.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def find_gate():
    """The installed plugin's copy of the gate, newest version first.

    `claude plugin install` unpacks to ~/.claude/plugins/cache/<market>/<plugin>/
    <version>/, so a version bump changes the path. Globbing beats hard-coding it.
    """
    cache = pathlib.Path.home() / ".claude" / "plugins" / "cache"
    found = sorted(cache.glob("*/central/*/skills/answer-only/prompt_gate.py"))
    return found[-1] if found else None


GATE = find_gate()


def verdict(prompt):
    p = subprocess.run([sys.executable, str(GATE)], cwd=str(ROOT), text=True,
                       capture_output=True,
                       input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                         "user_input": prompt}))
    if p.returncode == 2:
        return "BLOCK", p.stderr
    return "PASS", p.stdout


CASES = [
    # --- must block -------------------------------------------------------
    ("email address",      "mail the summary to sarah.jones@example.co.nz", "BLOCK"),
    ("Anthropic key",      "use sk-ant-api03-AbCdEf0123456789xyzQrStUvW for this", "BLOCK"),  # pragma: allowlist secret
    ("github token",       "auth with ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "BLOCK"),  # pragma: allowlist secret
    ("AWS key id",         "the id is AKIAIOSFODNN7EXAMPLE", "BLOCK"),  # pragma: allowlist secret
    ("JWT",                "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk", "BLOCK"),  # pragma: allowlist secret
    ("password assignment","set password: Tr0ub4dor3xK in the config", "BLOCK"),
    ("IRD number",         "his IRD is 123-456-789", "BLOCK"),
    ("bank account",       "pay into 01-0123-0123456-00 please", "BLOCK"),  # pragma: allowlist secret
    ("NHI number",         "patient ABC1234 was admitted", "BLOCK"),
    ("mobile number",      "call her on 021 555 1234", "BLOCK"),
    ("landline",           "the office is 09-123-4567", "BLOCK"),
    ("+64 form",           "reach me at +64 21 555 1234", "BLOCK"),
    ("street address",     "the invoice goes to 12 Queen Street", "BLOCK"),
    ("card number",        "card 4111 1111 1111 1111 declined", "BLOCK"),
    ("private key",        "-----BEGIN RSA PRIVATE KEY-----", "BLOCK"),  # pragma: allowlist secret
    ("two at once",        "a@b.co.nz and 021 555 1234", "BLOCK"),

    # --- must pass --------------------------------------------------------
    ("plain question",     "which clients have an active engagement?", "PASS"),
    ("windows path",       r"open C:\Users\DaruBroodryk\Documents\vault\index.md", "PASS"),
    ("repo path",          "read wiki/clients/aa-life/aa-life.md", "PASS"),
    ("npm version pin",    "install foo@1.2.3 and @types/node@18.0.0", "PASS"),
    ("dict lookup",        'token = payload.get("user_input") or ""', "PASS"),
    ("env lookup",         "api_key = os.environ.get(KEY)", "PASS"),
    ("git sha",            "revert f5b76b2 and 63fc506", "PASS"),
    ("semver",             "bump from 1.2.3 to 10.4.11", "PASS"),
    ("iso date",           "the scan ran 2026-09-17 and again 2026-09-22", "PASS"),
    ("localhost port",     "the server is on localhost:8080", "PASS"),
    ("order number",       "order 1234567890123456 has not shipped", "PASS"),
    ("prose with digit",   "3 Pull Requests are open and 2 Data Files changed", "PASS"),
    ("quantity phrasing",  "any note with 10 or more addresses is denied", "PASS"),
    ("skill reference",    "explain what scripts/pii_gate.py blocks", "PASS"),
    ("iso standard",       "does it follow ISO8601 for timestamps?", "PASS"),
    ("override honoured",  "mail sarah.jones@example.co.nz #pii-ok", "PASS"),
]


def main():
    if GATE is None:
        print("test_prompt_gate: the central plugin is not installed, so the gate "
              "cannot be tested.\n  Run `python scripts/install_vault.py` to install it.")
        return 0
    print("test_prompt_gate: testing " + str(GATE))
    failed = []
    for name, prompt, want in CASES:
        got, detail = verdict(prompt)
        if got != want:
            failed.append((name, want, got, detail.strip()[:200]))
        print(f"{'ok  ' if got == want else 'FAIL'}  {want:<5}  {name}")

    print(f"\n{len(CASES) - len(failed)}/{len(CASES)} passed")
    for name, want, got, detail in failed:
        print(f"\n  {name}: wanted {want}, got {got}\n  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
