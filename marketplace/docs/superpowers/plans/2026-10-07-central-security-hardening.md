# central Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep credentials and payment numbers out of the model's context and the session transcript. Four layers do this: deny rules for credential files, a PreToolUse gate, PostToolUse output redaction with salted per-session placeholders, and one detector module that the prompt gate and the vault's read gate both use.

**Architecture:** A new `plugins/central/security/` package holds everything that isn't a skill. `patterns.py` is the only copy of the detectors. `placeholders.py` turns a match into a stable, unguessable token. `pretool_gate.py` and `redact_output.py` are the two new command hooks. Plugins cannot ship permission rules, so `install_deny_rules.py` writes them into the user's own settings, and the PreToolUse gate covers what those rules miss. `answer-only/prompt_gate.py` imports the shared detectors instead of carrying its own. The vault's `scripts/pii_gate.py` loads the shared email detector from the installed plugin and falls back to a local copy.

**Tech Stack:** Python 3 standard library only (the machines run 3.14; pytest is not installed), `unittest`, Claude Code 2.1.292 command hooks, JSON.

**Spec:** No separate spec document. The requirements come from the 2026-10-07 review of honmoon's `packages/claude-plugin` and are restated in Global Constraints below. Facts about Claude Code were checked against these pages:
- https://code.claude.com/docs/en/plugins/manifest-reference.md: a plugin's `settings` keep only `agent` and `subagentStatusLine`, so permission rules can't ship in a plugin.
- https://code.claude.com/docs/en/permissions.md: `Read` deny rules also apply to Grep, Glob, and Bash file commands Claude Code recognises (`cat`, `head`, `tail`, `sed`, `tee`). They don't apply to `grep -r pattern .`, or to scripts that open files themselves.
- https://code.claude.com/docs/en/hooks-guide.md: the PreToolUse deny output shape. A hook that exits non-zero (other than 2) or times out lets the tool call proceed.
- **Not documented:** replacing tool output from a PostToolUse command hook. honmoon verified empirically on 2.1.263 that `hookSpecificOutput.updatedToolOutput` replaces the output and is what gets persisted to the transcript. Task 1 re-verifies this on 2.1.292 before anything depends on it.

## Global Constraints

- Python standard library only, with no third-party imports. Tests use `unittest` and run with `python -m unittest discover -s security/tests -t .` from `plugins/central`.
- Every hook fails open on its own error. It still exits 0, and it prints `{"systemMessage": "<what failed>; <what that means>"}` so the user sees the failure. Only the deny rules in `settings.json` have no code that can fail.
- Never quote a matched value anywhere: in deny reasons, system messages, additional context, logs, or test assertion messages. Name the label and the count only.
- Placeholder format, exactly: `<<redacted:<label-slug>:<8 lowercase hex>>>`, matched by `<<redacted:[a-z0-9-]+:[0-9a-f]{8}>>`.
- Output redaction covers the `secret` and `financial` categories only. `identifier` (IRD number, NHI number) and `contact` (email address, phone number, street address) are checked in prompts only, because vault notes and data files are full of them.
- Hook timeout: 10 seconds for every new hook entry.
- Test credentials are synthetic and built by string concatenation at runtime (`"gh" + "p_" + ...`), so the source never holds a literal that GitHub push protection or the vault's `hooks_guard.py` would flag.
- Files, commits and PR text are written in normal prose. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The plugin version goes from `1.2.0` to `1.3.0`, in both `plugins/central/.claude-plugin/plugin.json` and the README.

## Review Focus

1. **The model writes a placeholder back into a file.** It reads a config file whose secret came back redacted, then rewrites the whole file with `Write`, which silently replaces the real secret with `<<redacted:…>>`. Expected: the write is denied with a reason telling it to leave that line out. Pinned in Task 6.
2. **A data file holds long numeric IDs.** A 16-digit customer ID that passes Luhn by chance (1 in 10 do) must not be redacted as a card number, or analysis output is silently corrupted. Expected: a number without a real card prefix passes through untouched. Pinned in Task 2.
3. **Reading an image or PDF.** The tool response carries base64 bytes, and rewriting any of them corrupts the file the model sees. Expected: binary results pass through untouched. Pinned in Task 4.
4. **Very large Bash output**, such as a 5 MB log dump. Expected: redaction finishes well inside the 10-second hook timeout, because a timeout passes the output through unredacted. Pinned in Task 4: 5 MB in under 3 seconds.
5. **A hook gets malformed input or crashes.** Expected: the tool call proceeds, nothing is blocked, and the user sees a system message saying the check did not run. Pinned in Tasks 4 and 5.

---

## File Structure

All paths are relative to the skills repo root unless they say `C:\vault`.

| Path | Responsibility |
| --- | --- |
| `plugins/central/security/__init__.py` | Makes `security` importable as a package. Empty. |
| `plugins/central/security/patterns.py` | The detectors: labels, categories, regexes, Luhn and card-prefix checks, `scan()`. The only copy. |
| `plugins/central/security/placeholders.py` | Machine key, per-session salt, `token()`, `substitute()`, `PLACEHOLDER`. |
| `plugins/central/security/credential-files.json` | The credential file list, as data. Read by both the gate and the deny-rule installer. |
| `plugins/central/security/credential_paths.py` | `is_credential_path()` and `command_reads_credential()`. |
| `plugins/central/security/pretool_gate.py` | PreToolUse hook: denies credential-file reads and placeholder writes. |
| `plugins/central/security/redact_output.py` | PostToolUse hook: redacts tool output. |
| `plugins/central/security/install_deny_rules.py` | Merges the deny rules into a `settings.json`. Run by hand. |
| `plugins/central/security/tests/__init__.py` | Empty. Required for `unittest discover`. |
| `plugins/central/security/tests/secrets_fixture.py` | Synthetic credentials, built at runtime. |
| `plugins/central/security/tests/fixtures/*.json` | Real PostToolUse payloads captured in Task 1. |
| `plugins/central/security/tests/test_*.py` | One test file per module, plus `test_prompt_gate.py`. |
| `plugins/central/skills/answer-only/prompt_gate.py` | Modified to import from `security.patterns` and `security.placeholders`. |
| `plugins/central/hooks/hooks.json` | Modified to add the PreToolUse and PostToolUse entries. |
| `plugins/central/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md` | Version 1.3.0, descriptions, and a security section. |
| `C:\vault\scripts\pii_gate.py`, `C:\vault\scripts\test_pii_gate.py`, `C:\vault\scripts\test_prompt_gate.py` | Load the shared email detector and fix the plugin-version sort. |

---

### Task 1: Verify PostToolUse output replacement on 2.1.292 and capture payload fixtures

This is a spike. It produces no product code: it produces fixtures and a yes/no answer. **If the answer is no, stop after Step 6 and report.** Task 4 can't be built as written without it; the fallback is a function-hooks module, which needs a revised plan.

**Files:**
- Create (throwaway, outside the repo): `%TEMP%\spike\.claude-plugin\plugin.json`, `%TEMP%\spike\hooks\hooks.json`, `%TEMP%\spike\hooks\spike.py`
- Create: `plugins/central/security/tests/fixtures/post_read_text.json`, `post_read_image.json`, `post_bash.json`, `post_grep.json`, `post_webfetch.json`

**Interfaces:**
- Produces: the fixture files above. Each one is a full PostToolUse stdin payload, with `tool_response` exactly as Claude Code sent it. Task 4's tests load them.

- [ ] **Step 1: Write the spike plugin**

`%TEMP%\spike\.claude-plugin\plugin.json`:
```json
{ "name": "spike", "version": "0.0.1", "description": "Throwaway: checks PostToolUse output replacement." }
```

`%TEMP%\spike\hooks\hooks.json`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read|Bash|Grep|WebFetch",
        "hooks": [{ "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/spike.py\"", "timeout": 10 }]
      }
    ]
  }
}
```

`%TEMP%\spike\hooks\spike.py`:
```python
import json, os, pathlib, sys

payload = json.loads(sys.stdin.read())
out = pathlib.Path(os.environ["TEMP"]) / "spike" / "captured"
out.mkdir(exist_ok=True)
name = payload["tool_name"].lower()
if name == "read" and isinstance(payload.get("tool_response"), dict):
    name += "_" + str(payload["tool_response"].get("type"))
(out / f"post_{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mark(v):
    if isinstance(v, str):
        return v.replace("SPIKE-ORIGINAL", "SPIKE-REPLACED")
    if isinstance(v, list):
        return [mark(x) for x in v]
    if isinstance(v, dict):
        return {k: mark(x) for k, x in v.items()}
    return v


json.dump({"hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "updatedToolOutput": mark(payload.get("tool_response")),
    "additionalContext": "SPIKE-CONTEXT-NOTE",
}}, sys.stdout)
```

- [ ] **Step 2: Create the inputs**

```bash
mkdir -p "$TEMP/spike/work" && cd "$TEMP/spike/work" && printf 'line one SPIKE-ORIGINAL\n' > probe.txt && python -c "import base64,pathlib;pathlib.Path('dot.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='))"
```

- [ ] **Step 3: Run one headless session per tool**

Run each command from `$TEMP/spike/work`:
```bash
claude -p --plugin-dir "$TEMP/spike" --allowedTools "Read" "Read probe.txt with the Read tool. Reply with its first line verbatim, then on a new line any note you were given about the tool output, verbatim."
```
```bash
claude -p --plugin-dir "$TEMP/spike" --allowedTools "Bash" "Run: echo SPIKE-ORIGINAL. Reply with the exact output."
```
```bash
claude -p --plugin-dir "$TEMP/spike" --allowedTools "Grep" "Use the Grep tool with output mode content to search for SPIKE in this directory. Reply with the matching line verbatim."
```
```bash
claude -p --plugin-dir "$TEMP/spike" --allowedTools "Read" "Read dot.png with the Read tool and say what colour it is."
```
```bash
claude -p --plugin-dir "$TEMP/spike" --allowedTools "WebFetch" "Fetch https://example.com with WebFetch and reply with the page heading."
```

Expected: the Read, Bash and Grep replies contain `SPIKE-REPLACED` and not `SPIKE-ORIGINAL`, and the Read reply repeats `SPIKE-CONTEXT-NOTE`. The image reply describes the image normally, because the spike leaves bytes without the marker alone.

- [ ] **Step 4: Check what the transcript stored**

```bash
grep -rl "SPIKE-ORIGINAL" ~/.claude/projects/*spike-work*/ ; grep -rl "SPIKE-REPLACED" ~/.claude/projects/*spike-work*/
```
Expected: the first command prints nothing except lines where the prompt itself names the marker (the Bash prompt does); no tool result holds it. The second command lists the session files. Open one session file and confirm that the `toolUseResult` for the Read call holds `SPIKE-REPLACED`.

- [ ] **Step 5: Copy the captured payloads into the repo as fixtures**

```bash
cd ~/Documents/skills/plugins/central && mkdir -p security/tests/fixtures && cp "$TEMP/spike/captured/post_read_text.json" "$TEMP/spike/captured/post_read_image.json" "$TEMP/spike/captured/post_bash.json" "$TEMP/spike/captured/post_grep.json" "$TEMP/spike/captured/post_webfetch.json" security/tests/fixtures/
```
Open each file and replace `session_id`, `transcript_path` and `cwd` with `"fixture-session"`, `"fixture.jsonl"` and `"C:/fixture"`. In `post_read_image.json`, shorten the base64 string to its first 40 characters. Note in which key `"type": "image"` appears: Task 4's binary check reads `tool_response["type"]`. If it sits elsewhere, Task 4 Step 3 changes that one line to the path seen here.

- [ ] **Step 6: Record the result and commit**

Add a file `plugins/central/security/tests/fixtures/README.md` with this content, filling in yes or no from Steps 3 and 4:
```markdown
Captured from Claude Code 2.1.292 on 2026-10-07 with a throwaway plugin whose PostToolUse hook
replaced a marker string via `hookSpecificOutput.updatedToolOutput`.

- Model saw the replaced output (Read, Bash, Grep): yes/no
- Model saw `additionalContext` from PostToolUse: yes/no
- Transcript stored the replaced output: yes/no

Session ids, paths and the image bytes are scrubbed. Re-capture after a Claude Code upgrade
that changes tool result shapes.
```
```bash
git add plugins/central/security/tests/fixtures
git commit -m "Capture PostToolUse payloads from Claude Code 2.1.292

Real stdin payloads for Read (text and image), Bash, Grep and WebFetch, and a
note recording that updatedToolOutput replaces what the model sees and what the
transcript stores on this version.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
If any answer is "no", stop here and report it. Do not start Task 4.

---

### Task 2: Shared detector module

**Files:**
- Create: `plugins/central/security/__init__.py`, `plugins/central/security/patterns.py`
- Create: `plugins/central/security/tests/__init__.py`, `plugins/central/security/tests/secrets_fixture.py`, `plugins/central/security/tests/test_patterns.py`

**Interfaces:**
- Produces:
  - `security.patterns.EMAIL: re.Pattern`
  - the category constants `SECRET`, `FINANCIAL`, `IDENTIFIER`, `CONTACT: str`, and `ALL`, `OUTPUT: frozenset[str]`
  - `PATTERNS: tuple[tuple[str, str, re.Pattern], ...]` of (label, category, regex)
  - `luhn(text: str) -> bool`
  - `plausible_card(text: str) -> bool`
  - `scan(text: str, categories: frozenset[str] = ALL) -> list[tuple[str, int, int]]`: (label, start, end), sorted by start and non-overlapping. When a regex has a named group `value`, the span is that group's.
  - `security.tests.secrets_fixture`: `ANTHROPIC`, `GITHUB`, `AWS`, `JWT`, `PRIVATE_KEY`, `VISA: str`

- [ ] **Step 1: Write the synthetic credentials**

`security/tests/secrets_fixture.py`:
```python
"""Synthetic credentials for tests, assembled at import so no source line holds one.

None of these authenticate anything. The AWS key id is the example from AWS's own
documentation, the JWT is the jwt.io specimen, the rest are invented. Building them
from pieces keeps GitHub push protection and the vault's hooks_guard.py from
flagging this file, which is the same reason the vault's test_prompt_gate.py
carries allowlist pragmas.
"""
ANTHROPIC = "sk-" + "ant-api03-" + "AbCdEf0123456789xyzQrStUvW"
GITHUB = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
JWT = ("ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "."
       + "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk")
PRIVATE_KEY = ("-----BEGIN " + "RSA PRIVATE KEY-----\n"
               "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
               "KUpRKfFLfRYC9AIKjbJTWit+CqvjWYzvQwECAwEAAQ==\n"
               "-----END " + "RSA PRIVATE KEY-----")
VISA = "4111 1111 " + "1111 1111"
```

Create `security/__init__.py` and `security/tests/__init__.py` as empty files.

- [ ] **Step 2: Write the failing tests**

`security/tests/test_patterns.py`:
```python
import unittest

from security import patterns
from security.patterns import ALL, OUTPUT, plausible_card, scan
from security.tests import secrets_fixture as s


def labels(text, categories=ALL):
    return [label for label, _, _ in scan(text, categories)]


class Detects(unittest.TestCase):
    def test_credentials(self):
        for value, label in [(s.ANTHROPIC, "API token"), (s.GITHUB, "API token"),
                             (s.AWS, "API token"), (s.JWT, "JWT"),
                             (s.PRIVATE_KEY, "private key")]:
            with self.subTest(label=label):
                self.assertEqual(labels(f"use {value} here"), [label])

    def test_private_key_span_covers_the_body(self):
        text = f"before\n{s.PRIVATE_KEY}\nafter"
        [(label, start, end)] = scan(text)
        self.assertEqual(text[start:end].strip(), s.PRIVATE_KEY)

    def test_secret_assignment_span_is_the_value_only(self):
        text = "set password: Tr0ub4dor3xK in the config"
        [(label, start, end)] = scan(text)
        self.assertEqual(label, "secret assignment")
        self.assertEqual(text[:start], "set password: ")

    def test_payment_and_identity(self):
        cases = [(f"card {s.VISA}", "card number"),
                 ("pay into 01-0123-0123456-00 please", "NZ bank account"),
                 ("his IRD is 123-456-789", "IRD number"),
                 ("patient ABC1234 was admitted", "NHI number"),
                 ("mail sarah.jones@example.co.nz", "email address"),
                 ("call her on 021 555 1234", "NZ phone"),
                 ("drop it at 12 Queen Street", "street address")]
        for text, label in cases:
            with self.subTest(label=label):
                self.assertEqual(labels(text), [label])


class Ignores(unittest.TestCase):
    """Known false positives. Each one cost a resend before the pattern was fixed."""

    def test_ordinary_text(self):
        for text in ['pin it at foo@1.2.3',
                     'token = payload.get("user_input")',
                     'order 1234567890123456 shipped',
                     'see 3 Big Things st the end']:
            with self.subTest(text=text):
                self.assertEqual(labels(text), [])

    def test_luhn_valid_number_without_a_card_prefix(self):
        # 9000000000000001 passes Luhn; 1 in 10 random 16-digit IDs do.
        self.assertFalse(plausible_card("9000000000000001"))
        self.assertEqual(labels("customer_id,9000000000000001", OUTPUT), [])


class Categories(unittest.TestCase):
    def test_output_set_skips_contact_and_identifier(self):
        text = "mail a@example.com, IRD 123-456-789, key " + s.GITHUB
        self.assertEqual(labels(text, OUTPUT), ["API token"])

    def test_every_pattern_has_a_known_category(self):
        for label, category, _ in patterns.PATTERNS:
            self.assertIn(category, ALL, label)

    def test_email_is_exported_for_the_vault(self):
        self.assertTrue(patterns.EMAIL.search("x a.b@example.nz y"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd plugins/central && python -m unittest discover -s security/tests -t .`
Expected: ERROR with `ModuleNotFoundError: No module named 'security.patterns'`.

- [ ] **Step 4: Write `security/patterns.py`**

```python
"""The detectors every central gate uses. This file is the only copy.

`answer-only/prompt_gate.py` checks prompts against all of them. `redact_output.py`
checks tool output against the `secret` and `financial` categories only, because
vault notes and data files are full of contact details and identifiers that are
the work itself. The vault's `scripts/pii_gate.py` imports `EMAIL` from the
installed copy of this file.

Patterns are ordered longest and most specific first. A span claimed by an
earlier pattern is not offered to a later one, so an IRD-shaped run inside a bank
account number is reported once, as the bank account.

A pattern with a named group `value` reports that group's span. Redaction then
replaces `Tr0ub4dor3xK` in `password: Tr0ub4dor3xK` and leaves `password: `
readable, so the model can still see what the line is.
"""
import re

SECRET, FINANCIAL, IDENTIFIER, CONTACT = "secret", "financial", "identifier", "contact"
ALL = frozenset({SECRET, FINANCIAL, IDENTIFIER, CONTACT})
OUTPUT = frozenset({SECRET, FINANCIAL})

# The TLD must be alphabetic. `[\w.]{2,}` matched `foo@1.2.3`, so every npm or pip
# version pin read as an email address.
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")

PATTERNS = (
    # The body is matched too: the header alone leaves the key itself in the
    # output. Up to the matching END line when there is one; for a truncated key,
    # the run of base64 that follows. The body class has no "-", so the fallback
    # cannot run on through a later header.
    ("private key", SECRET, re.compile(
        r"-----BEGIN ([A-Z ]*)PRIVATE KEY-----"
        r"(?:[\s\S]*?-----END \1PRIVATE KEY-----|[A-Za-z0-9+/=\s:,]*)")),
    ("JWT", SECRET, re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}")),
    ("API token", SECRET, re.compile(
        r"\b(?:sk-ant-[\w-]{20,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{36}"
        r"|github_pat_\w{22,}|AKIA[0-9A-Z]{16}|xox[baprs]-[\w-]{10,})")),
    # The value must carry a digit. Without that test the pattern fires on
    # ordinary code: `token = payload.get("user_input")` matched a plain length rule.
    ("secret assignment", SECRET, re.compile(
        r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*[\"']?"
        r"(?P<value>(?=[^\s\"']*\d)[A-Za-z0-9_\-+/=!@#$%^&*.]{10,})")),
    ("email address", CONTACT, EMAIL),
    ("NZ bank account", FINANCIAL, re.compile(r"\b\d{2}-\d{4}-\d{6,7}-\d{2,3}\b")),
    ("card number", FINANCIAL, re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),  # plausible_card below
    ("IRD number", IDENTIFIER, re.compile(r"\b\d{2,3}-\d{3}-\d{3}\b")),
    ("NHI number", IDENTIFIER, re.compile(r"\b[A-HJ-NP-Z]{3}(?:\d{4}|\d{2}[A-HJ-NP-Z]{2})\b")),
    ("NZ phone", CONTACT, re.compile(
        r"(?<![\w.])(?:\+64[-\s]?|0)(?:2\d{1,2}|[34679])[-\s]?\d{3}[-\s]?\d{3,4}\b")),
    # Case-sensitive on purpose. Under `(?i)` any digit followed by two words
    # ending in "st" or "dr" matched.
    ("street address", CONTACT, re.compile(
        r"\b\d+[A-Za-z]?(?:[/-]\d+)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
        r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Lane|Ln|Place|Pl|Terrace|Tce"
        r"|Crescent|Cres|Way|Quay|Parade|Pde)\b")),
)


def luhn(text):
    """True if the digits in `text` pass the Luhn checksum."""
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def plausible_card(text):
    """Luhn plus a real card prefix and length.

    Luhn alone passes 1 in 10 random digit runs, and our data files are full of
    16-digit IDs. Redacting those would corrupt analysis output silently, so a
    number must also start like Visa, Mastercard, Amex or Discover.
    """
    digits = "".join(c for c in text if c.isdigit())
    if not luhn(digits):
        return False
    n, two, four = len(digits), int(digits[:2]), int(digits[:4])
    if digits[0] == "4":
        return n in (13, 16, 19)
    if 51 <= two <= 55 or 2221 <= four <= 2720:
        return n == 16
    if two in (34, 37):
        return n == 15
    if digits.startswith("6011") or two == 65:
        return n in (16, 19)
    return False


def scan(text, categories=ALL):
    """[(label, start, end)] for every match in `categories`, non-overlapping, in text order."""
    hits, claimed = [], []
    for label, category, pattern in PATTERNS:
        if category not in categories:
            continue
        for m in pattern.finditer(text):
            if label == "card number" and not plausible_card(m.group()):
                continue
            start, end = m.span("value") if "value" in pattern.groupindex else m.span()
            if any(start < e and s < end for s, e in claimed):
                continue
            claimed.append((start, end))
            hits.append((label, start, end))
    return sorted(hits, key=lambda h: h[1])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd plugins/central && python -m unittest discover -s security/tests -t . -v`
Expected: all tests in `test_patterns` pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/central/security
git commit -m "Add the shared detector module for central's gates

security/patterns.py now holds every detector, tagged by category, so the prompt
gate, the output redaction and the vault's read gate can share one copy. Card
numbers need a real card prefix as well as Luhn, private keys match their body,
and secret assignments report only the value.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Salted per-session placeholders, and the prompt gate on the shared module

**Files:**
- Create: `plugins/central/security/placeholders.py`, `plugins/central/security/tests/test_placeholders.py`, `plugins/central/security/tests/test_prompt_gate.py`
- Modify: `plugins/central/skills/answer-only/prompt_gate.py`. Delete the `PATTERNS`, `luhn` and `scan` definitions (lines 52-139 in the 1.2.0 file), and replace `redact` and the `except Exception` branch.

**Interfaces:**
- Consumes: `security.patterns.scan`, `ALL`
- Produces:
  - `security.placeholders.KEY_PATH: pathlib.Path` (`~/.claude/central/placeholder.key`)
  - `PLACEHOLDER: re.Pattern`
  - `machine_key(path: pathlib.Path | None = None) -> bytes`: 32 bytes, created on first use
  - `session_salt(session_id: str, key_path=None) -> tuple[bytes, bool]`: (salt, stable)
  - `slug(label: str) -> str`
  - `token(label: str, value: str, salt: bytes) -> str`
  - `substitute(text: str, hits: list[tuple[str, int, int]], salt: bytes) -> str`

- [ ] **Step 1: Write the failing placeholder tests**

`security/tests/test_placeholders.py`:
```python
import pathlib
import tempfile
import unittest

from security.patterns import scan
from security.placeholders import PLACEHOLDER, machine_key, session_salt, slug, substitute, token
from security.tests import secrets_fixture as s


class Tokens(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.key = pathlib.Path(self.dir.name) / "sub" / "placeholder.key"

    def tearDown(self):
        self.dir.cleanup()

    def test_shape(self):
        salt, _ = session_salt("s1", self.key)
        t = token("API token", s.GITHUB, salt)
        self.assertRegex(t, r"^<<redacted:api-token:[0-9a-f]{8}>>$")
        self.assertTrue(PLACEHOLDER.fullmatch(t))

    def test_same_value_same_session_same_token(self):
        salt, _ = session_salt("s1", self.key)
        self.assertEqual(token("JWT", s.JWT, salt), token("JWT", s.JWT, salt))

    def test_other_session_other_token(self):
        a, _ = session_salt("s1", self.key)
        b, _ = session_salt("s2", self.key)
        self.assertNotEqual(token("JWT", s.JWT, a), token("JWT", s.JWT, b))

    def test_key_is_made_once_and_reused(self):
        first = machine_key(self.key)
        self.assertEqual(len(first), 32)
        self.assertEqual(machine_key(self.key), first)

    def test_unreadable_key_still_redacts(self):
        self.key.parent.mkdir(parents=True)
        self.key.write_bytes(b"short")
        salt, stable = session_salt("s1", self.key)
        self.assertFalse(stable)
        self.assertEqual(len(salt), 32)

    def test_substitute_replaces_only_the_spans_and_never_keeps_the_value(self):
        salt, _ = session_salt("s1", self.key)
        text = f"a {s.GITHUB} b password: Tr0ub4dor3xK c"
        out = substitute(text, scan(text), salt)
        self.assertNotIn(s.GITHUB, out)
        self.assertNotIn("Tr0ub4dor3xK", out)
        self.assertTrue(out.startswith("a <<redacted:api-token:"))
        self.assertIn(" b password: <<redacted:secret-assignment:", out)

    def test_redacted_text_has_nothing_left_to_find(self):
        salt, _ = session_salt("s1", self.key)
        text = f"{s.AWS} and {s.JWT}"
        once = substitute(text, scan(text), salt)
        self.assertEqual(scan(once), [])

    def test_slug(self):
        self.assertEqual(slug("NZ bank account"), "nz-bank-account")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_placeholders`
Expected: ERROR with `ModuleNotFoundError: No module named 'security.placeholders'`.

- [ ] **Step 3: Write `security/placeholders.py`**

```python
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
```

- [ ] **Step 4: Run the placeholder tests to verify they pass**

Run: `cd plugins/central && python -m unittest security.tests.test_placeholders -v`
Expected: 8 tests pass.

- [ ] **Step 5: Write the failing prompt-gate tests**

`security/tests/test_prompt_gate.py`:
```python
"""The prompt gate, driven through its real stdin/stdout/exit-code contract."""
import json
import pathlib
import subprocess
import sys
import unittest

from security.tests import secrets_fixture as s

GATE = pathlib.Path(__file__).resolve().parents[2] / "skills" / "answer-only" / "prompt_gate.py"


def run(stdin):
    return subprocess.run([sys.executable, str(GATE)], input=stdin, capture_output=True, text=True)


def prompt(text):
    return run(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": text}))


class PromptGate(unittest.TestCase):
    def test_blocks_a_credential_without_quoting_it(self):
        p = prompt(f"use {s.ANTHROPIC} for this")
        self.assertEqual(p.returncode, 2)
        self.assertIn("API token", p.stderr)
        self.assertNotIn(s.ANTHROPIC, p.stderr)

    def test_blocks_contact_details(self):
        self.assertEqual(prompt("mail the summary to sarah.jones@example.co.nz").returncode, 2)

    def test_passes_ordinary_prompts(self):
        for text in ["pin it at foo@1.2.3", "order 1234567890123456 shipped",
                     'what does token = payload.get("user_input") do']:
            with self.subTest(text=text):
                self.assertEqual(prompt(text).returncode, 0)

    def test_override(self):
        self.assertEqual(prompt(f"use {s.AWS} #pii-ok").returncode, 0)

    def test_broken_input_is_reported_and_passes(self):
        p = run("{not json")
        self.assertEqual(p.returncode, 0)
        self.assertIn("prompt gate failed", json.loads(p.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run them to verify the new case fails**

Run: `cd plugins/central && python -m unittest security.tests.test_prompt_gate -v`
Expected: `test_broken_input_is_reported_and_passes` FAILS, because the 1.2.0 gate prints nothing on error. The other four pass already.

- [ ] **Step 7: Move the prompt gate onto the shared modules**

In `skills/answer-only/prompt_gate.py`, replace everything from `import json` down to the end of the `scan` function with the block below. That covers the imports, the constants, the `PATTERNS` tuple, `luhn` and `scan`; `report`, `redact`, `contract`, `emit` and `main` stay.
```python
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from security.patterns import scan  # noqa: E402  (path set up above)
from security.placeholders import session_salt, substitute  # noqa: E402

MODE = "block"          # "block" or "redact"
OVERRIDE = "#pii-ok"
SKILL = pathlib.Path(__file__).resolve().parent / "SKILL.md"
FENCE = re.compile(r"<!-- INJECT:START -->\n(.*?)\n<!-- INJECT:END -->", re.S)
```

Replace the `redact` function with:
```python
def redact(text, hits, session_id):
    salt, _ = session_salt(session_id)
    return substitute(text, hits, salt)
```

In `main()`, change the redact call to `redact(prompt, hits, payload.get("session_id") or "")`.

Replace the bottom block with:
```python
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
```

In the module docstring, change the `redact` mode line to: `redact    rewrite the prompt through the hook's updatedInput field, replacing each match with a <<redacted:...>> placeholder (see security/placeholders.py). The prompt still runs.` Add one paragraph at the end of the docstring: `The detectors live in security/patterns.py, shared with the output redaction and the vault's read gate. Change them there.`

- [ ] **Step 8: Run the whole suite**

Run: `cd plugins/central && python -m unittest discover -s security/tests -t . -v`
Expected: every test passes, including all five prompt-gate tests.

- [ ] **Step 9: Commit**

```bash
git add plugins/central/security plugins/central/skills/answer-only/prompt_gate.py
git commit -m "Add salted per-session placeholders and move the prompt gate onto the shared modules

placeholders.py turns a match into <<redacted:label:hex>>, where the hex is an HMAC under
a per-session salt derived from a machine key, so tokens are stable within a session
and unlinkable across sessions. The prompt gate now imports its detectors, uses the
placeholders in redact mode, and reports its own failure instead of failing open in
silence.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: PostToolUse output redaction

Start only if Task 1 recorded "yes" for all three answers.

**Files:**
- Create: `plugins/central/security/redact_output.py`, `plugins/central/security/tests/test_redact_output.py`
- Modify: `plugins/central/hooks/hooks.json`

**Interfaces:**
- Consumes: `security.patterns.scan`, `OUTPUT`; `security.placeholders.session_salt`, `substitute`; the fixtures from Task 1
- Produces:
  - `security.redact_output.redact_value(value, salt: bytes, counter: list[int])`: the same shape, with string leaves redacted; `counter[0]` is incremented per match
  - `note(count: int) -> str`
  - Hook contract: stdin is a PostToolUse payload. Stdout is empty (nothing to redact), or `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": ..., "additionalContext": ...}}` with an optional top-level `systemMessage`. Exit 0 always.

- [ ] **Step 1: Write the failing tests**

`security/tests/test_redact_output.py`:
```python
import json
import pathlib
import subprocess
import sys
import time
import unittest

from security.tests import secrets_fixture as s

HERE = pathlib.Path(__file__).resolve().parent
HOOK = HERE.parent / "redact_output.py"
FIXTURES = HERE / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def plant(value, text, key=None):
    """Append `text` to every string leaf of a tool_response, keeping its shape.

    `type` fields are left alone: they say what the record is ("text", "image"),
    and changing one would turn an image result into something the hook rewrites.
    """
    if isinstance(value, str):
        return value if key == "type" else f"{value}\n{text}\n"
    if isinstance(value, list):
        return [plant(v, text) for v in value]
    if isinstance(value, dict):
        return {k: plant(v, text, k) for k, v in value.items()}
    return value


def run(payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None)


class RedactsEachTool(unittest.TestCase):
    def test_real_payload_shapes(self):
        secret = s.GITHUB
        for name in ["post_read_text.json", "post_bash.json", "post_grep.json", "post_webfetch.json"]:
            with self.subTest(fixture=name):
                payload = fixture(name)
                payload["tool_response"] = plant(payload["tool_response"], f"api_key = {secret}")
                code, out = run(payload)
                self.assertEqual(code, 0)
                updated = out["hookSpecificOutput"]["updatedToolOutput"]
                self.assertNotIn(secret, json.dumps(updated))
                self.assertIn("<<redacted:api-token:", json.dumps(updated))
                self.assertEqual(type(updated), type(payload["tool_response"]))
                self.assertIn("opaque", out["hookSpecificOutput"]["additionalContext"])


class LeavesAlone(unittest.TestCase):
    def test_nothing_to_redact_prints_nothing(self):
        payload = fixture("post_bash.json")
        self.assertEqual(run(payload), (0, None))

    def test_contact_details_stay(self):
        payload = fixture("post_bash.json")
        payload["tool_response"] = plant(payload["tool_response"],
                                         "mail sarah.jones@example.co.nz, IRD 123-456-789")
        self.assertEqual(run(payload), (0, None))

    def test_image_bytes_are_never_touched(self):
        payload = fixture("post_read_image.json")
        payload["tool_response"] = plant(payload["tool_response"], f"api_key = {s.GITHUB}")
        self.assertEqual(run(payload), (0, None))

    def test_data_ids_that_pass_luhn(self):
        payload = fixture("post_bash.json")
        payload["tool_response"] = plant(payload["tool_response"], "customer_id,9000000000000001")
        self.assertEqual(run(payload), (0, None))


class Robust(unittest.TestCase):
    def test_broken_input_is_reported_and_passes(self):
        code, out = run("{not json")
        self.assertEqual(code, 0)
        self.assertIn("NOT redacted", out["systemMessage"])

    def test_five_megabytes_in_under_three_seconds(self):
        line = "2026-10-07 INFO request id=4821 path=/api/v1/orders status=200 ms=12\n"
        payload = fixture("post_bash.json")
        payload["tool_response"] = {"stdout": line * (5_000_000 // len(line)) + s.AWS, "stderr": ""}
        started = time.perf_counter()
        code, out = run(payload)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertNotIn(s.AWS, out["hookSpecificOutput"]["updatedToolOutput"]["stdout"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_redact_output`
Expected: errors, because `redact_output.py` does not exist (subprocess stderr shows `can't open file`, and `json.loads` fails on empty output).

- [ ] **Step 3: Write `security/redact_output.py`**

```python
"""PostToolUse hook: take secrets and payment numbers out of tool output.

Runs after Read, Bash, Grep and WebFetch. Every string in the tool's response is
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
What this cannot see: a script that reads a file itself and prints only a summary.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from security.patterns import OUTPUT, scan  # noqa: E402
from security.placeholders import session_salt, substitute  # noqa: E402

BINARY_TYPES = {"image", "pdf"}


def redact_value(value, salt, counter):
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
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)
    response = payload.get("tool_response")
    if isinstance(response, dict) and response.get("type") in BINARY_TYPES:
        return
    salt, stable = session_salt(payload.get("session_id") or "")
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/central && python -m unittest security.tests.test_redact_output -v`
Expected: 7 tests pass. If the 5 MB test is over 3 s, profile with `python -X importtime` and `cProfile` before touching the patterns. The card regex on digit-heavy text is the likely cost; do not loosen a detector to pass a timing test.

- [ ] **Step 5: Register the hook**

Replace `plugins/central/hooks/hooks.json` with:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/skills/answer-only/prompt_gate.py\"",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read|Bash|Grep|WebFetch",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/security/redact_output.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Run: `claude plugin validate plugins/central`
Expected: `✔ Validation passed`.

- [ ] **Step 6: Commit**

```bash
git add plugins/central/security plugins/central/hooks/hooks.json
git commit -m "Redact secrets and payment numbers from tool output

A PostToolUse hook on Read, Bash, Grep and WebFetch replaces every secret and
plausible card or bank number in the tool's response with a session placeholder,
through updatedToolOutput, and tells the model the placeholders are opaque. Image
and PDF results pass through untouched. A failure lets the output through and says so.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Credential-file gate

**Files:**
- Create: `plugins/central/security/credential-files.json`, `plugins/central/security/credential_paths.py`, `plugins/central/security/pretool_gate.py`, `plugins/central/security/tests/test_credential_paths.py`, `plugins/central/security/tests/test_pretool_gate.py`
- Modify: `plugins/central/hooks/hooks.json`

**Interfaces:**
- Produces:
  - `credential-files.json`: `{"names": [str], "suffixes": [str], "home_paths": [str]}`, the one list Task 7 also reads
  - `security.credential_paths.DATA: dict`
  - `is_credential_path(path: str | None, cwd: str | None = None, home: str | None = None) -> bool`
  - `command_reads_credential(command: str, cwd=None, home=None) -> str | None`: the basename of the first credential file the command reads, or None
  - `security.pretool_gate.check(payload: dict) -> str | None`: a deny reason, or None. Task 6 extends it.
  - Hook contract: stdout is empty to allow, or the PreToolUse deny JSON. Exit 0 always.

- [ ] **Step 1: Write the credential list**

`security/credential-files.json`:
```json
{
  "names": [
    ".env", ".env.local", ".env.development", ".env.development.local",
    ".env.test", ".env.test.local", ".env.staging", ".env.production", ".env.production.local",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", "_netrc", ".git-credentials", ".pypirc"
  ],
  "suffixes": [".pem", ".key", ".p12", ".pfx", ".kdbx"],
  "home_paths": [
    ".aws/credentials",
    ".azure/accessTokens.json", ".azure/msal_token_cache.json", ".azure/msal_token_cache.bin",
    ".kube/config", ".docker/config.json",
    ".dbt/profiles.yml", ".snowflake/connections.toml"
  ]
}
```
The `.env` variants are listed one by one rather than as `.env.*`. A permission deny rule always beats an allow rule, so `.env.*` could never be carved back open for `.env.example`, which the model needs to read.

- [ ] **Step 2: Write the failing tests for the path checks**

`security/tests/test_credential_paths.py`:
```python
import os
import unittest

from security.credential_paths import command_reads_credential, is_credential_path

HOME = os.path.join(os.sep, "home", "dev")


class Paths(unittest.TestCase):
    def test_credential_files(self):
        for p in [".env", "app/.env.production", "C:\\proj\\.env.local", "certs/server.pem",
                  "keys/deploy.KEY", "~/.ssh/id_ed25519", "vault.kdbx"]:
            with self.subTest(p=p):
                self.assertTrue(is_credential_path(p, cwd=HOME, home=HOME))

    def test_home_paths(self):
        self.assertTrue(is_credential_path(os.path.join(HOME, ".aws", "credentials"), home=HOME))
        self.assertTrue(is_credential_path(".dbt/profiles.yml", cwd=HOME, home=HOME))

    def test_templates_and_lookalikes_are_readable(self):
        for p in [".env.example", ".env.sample", "id_ed25519.pub", "keyboard.md",
                  "models/profiles.yml", "credentials.md", None, ""]:
            with self.subTest(p=p):
                self.assertFalse(is_credential_path(p, cwd=HOME, home=HOME))


class Commands(unittest.TestCase):
    def test_reading_commands(self):
        for cmd in ["cat .env", "head -5 ~/.ssh/id_rsa", "git log && type .env.local",
                    "Get-Content $HOME/.aws/credentials", "grep KEY certs/server.pem"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(command_reads_credential(cmd, cwd=HOME, home=HOME))

    def test_commands_that_only_mention_a_path(self):
        # Learned in the vault's pii_gate.py: a gate that blocks its own setup gets switched off.
        for cmd in ["echo '.env' >> .gitignore", "git add .env.example", "cp .env.example .env",
                    "git commit -m 'do not cat .env, read more docs'", "cat .env.example"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(command_reads_credential(cmd, cwd=HOME, home=HOME))

    def test_reports_the_name_only(self):
        self.assertEqual(command_reads_credential("cat /srv/app/.env", home=HOME), ".env")


if __name__ == "__main__":
    unittest.main()
```

The commit-message case relies on the vault's command-position rule: `cat` follows `do not`, not a separator, so it isn't a command.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_credential_paths`
Expected: ERROR with `No module named 'security.credential_paths'`.

- [ ] **Step 4: Write `security/credential_paths.py`**

```python
"""Is this path, or this shell command, a read of a credential file?

The list is data, in credential-files.json, shared with install_deny_rules.py.
This module covers what the permission deny rules miss: PowerShell's `type` and
`Get-Content`, `$HOME`-style paths, and any machine where the rules were never
installed.

The Bash test is the one pii_gate.py in the vault arrived at after two false
positives. A command must have a reading verb in command position AND name a
credential path. Matching a bare mention blocked writing .gitignore, and matching
the verb anywhere blocked commit messages containing "more" or "less".
"""
import json
import os
import pathlib
import re

DATA = json.loads(pathlib.Path(__file__).with_name("credential-files.json").read_text(encoding="utf-8"))
NAMES = frozenset(n.lower() for n in DATA["names"])
SUFFIXES = tuple(s.lower() for s in DATA["suffixes"])

READS_A_FILE = re.compile(
    r"(?:^|[|;&`(]|&&|\|\|)\s*\(?\s*"
    r"(cat|bat|head|tail|less|more|nl|strings|xxd|od|type|"
    r"grep|rg|ag|ack|Get-Content|gc|Select-String)\b",
    re.MULTILINE | re.IGNORECASE)
TOKEN = re.compile(r"[^\s|;&<>()'\"`]+")
HOME_VARS = ("${HOME}", "$HOME", "$env:USERPROFILE", "%USERPROFILE%")


def _home(home):
    return home or os.path.expanduser("~")


def _norm(path, cwd, home):
    p = str(path)
    for var in HOME_VARS:
        if p.startswith(var):
            p = _home(home) + p[len(var):]
    if p.startswith("~"):
        p = _home(home) + p[1:]
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    # abspath, not normpath: on Windows a drive-less path such as \home\dev is not
    # absolute, and only abspath roots both sides of a comparison the same way.
    return os.path.normcase(os.path.abspath(p))


def is_credential_path(path, cwd=None, home=None):
    if not path:
        return False
    name = re.split(r"[\\/]", str(path).rstrip("\\/"))[-1].lower()
    if name in NAMES or name.endswith(SUFFIXES):
        return True
    target = _norm(path, cwd, home)
    return any(target == _norm(os.path.join(_home(home), rel), None, home) for rel in DATA["home_paths"])


def command_reads_credential(command, cwd=None, home=None):
    if not READS_A_FILE.search(command or ""):
        return None
    for tok in TOKEN.findall(command):
        if tok.startswith("-"):
            continue
        if is_credential_path(tok, cwd, home):
            return re.split(r"[\\/]", tok.rstrip("\\/"))[-1]
    return None
```

- [ ] **Step 5: Run the path tests to verify they pass**

Run: `cd plugins/central && python -m unittest security.tests.test_credential_paths -v`
Expected: all pass. `cp .env.example .env` passes because `cp` isn't a reading verb.

- [ ] **Step 6: Write the failing hook tests**

`security/tests/test_pretool_gate.py`:
```python
import json
import os
import pathlib
import subprocess
import sys
import unittest

HOOK = pathlib.Path(__file__).resolve().parents[1] / "pretool_gate.py"


def run(payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None)


def call(tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "session_id": "t", "cwd": os.getcwd(),
            "tool_name": tool, "tool_input": tool_input}


def denied(out):
    return bool(out) and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class CredentialGate(unittest.TestCase):
    def test_denies_reads(self):
        for payload in [call("Read", file_path=".env"), call("Grep", pattern="KEY", path="server.pem"),
                        call("Bash", command="cat ~/.aws/credentials")]:
            with self.subTest(tool=payload["tool_name"]):
                code, out = run(payload)
                self.assertEqual(code, 0)
                self.assertTrue(denied(out))
                self.assertIn("credential file", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_everything_else(self):
        for payload in [call("Read", file_path=".env.example"), call("Grep", pattern="x", path="src"),
                        call("Bash", command="git status"), call("Write", file_path=".env", content="A=1")]:
            with self.subTest(tool=payload["tool_name"]):
                self.assertEqual(run(payload), (0, None))

    def test_broken_input_is_reported_and_allowed(self):
        code, out = run("{not json")
        self.assertEqual(code, 0)
        self.assertFalse(denied(out))
        self.assertIn("gate failed", out["systemMessage"])


if __name__ == "__main__":
    unittest.main()
```

`Write` to `.env` is allowed on purpose: writing a file is not reading it. The model often creates a `.env` from a template with values the user dictated.

- [ ] **Step 7: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_pretool_gate`
Expected: failures, because `pretool_gate.py` doesn't exist.

- [ ] **Step 8: Write `security/pretool_gate.py`**

```python
"""PreToolUse hook: stop credential files reaching the model.

Denies Read and Grep calls aimed at a credential file, and Bash commands that read
one (credential_paths.py). This is the second layer: the first is the permission
deny rules that install_deny_rules.py writes into settings.json, which have no
code to fail. This layer covers PowerShell readers, `$HOME` paths, and machines
where the rules were never installed.

Fails open, and says so: an error allows the call with a system message.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from security.credential_paths import command_reads_credential, is_credential_path  # noqa: E402


def _name(path):
    return str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def credential_reason(name):
    return (f"Blocked by central: `{name}` is a credential file, and reading it would put "
            f"the secret into the prompt and the session transcript. Ask the user for the "
            f"specific value you need, or read the matching .example template.")


def check(payload):
    """A deny reason, or None to allow."""
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    if tool in ("Read", "Grep"):
        target = ti.get("file_path") if tool == "Read" else ti.get("path")
        if is_credential_path(target, cwd):
            return credential_reason(_name(target))
    if tool == "Bash":
        name = command_reads_credential(ti.get("command") or "", cwd)
        if name:
            return credential_reason(name)
    return None


def main():
    raw = sys.stdin.read()
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
```

- [ ] **Step 9: Run the tests, register the hook, and validate**

Run: `cd plugins/central && python -m unittest discover -s security/tests -t . -v`
Expected: all pass.

In `hooks/hooks.json`, add this entry to the `"hooks"` object, between `UserPromptSubmit` and `PostToolUse`:
```json
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Bash|Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/security/pretool_gate.py\"",
            "timeout": 10
          }
        ]
      }
    ],
```
The write tools are in the matcher already, for Task 6.

Run: `claude plugin validate plugins/central`
Expected: `✔ Validation passed`.

- [ ] **Step 10: Commit**

```bash
git add plugins/central/security plugins/central/hooks/hooks.json
git commit -m "Deny reads of credential files before they open

A PreToolUse hook denies Read, Grep and Bash calls that would read a .env file, a
private key, a key store or a cloud, Kubernetes, Docker, dbt or Snowflake credential
file. Templates such as .env.example stay readable. The file list is data, shared with
the deny-rule installer.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Refuse to write placeholders back

**Files:**
- Modify: `plugins/central/security/pretool_gate.py`, `plugins/central/security/tests/test_pretool_gate.py`

**Interfaces:**
- Consumes: `security.placeholders.PLACEHOLDER`, `security.pretool_gate.check`
- Produces: `check()` also returns a reason when a Write, Edit, MultiEdit, NotebookEdit or Bash call carries a placeholder.

- [ ] **Step 1: Add the failing tests**

Append to `security/tests/test_pretool_gate.py`, above the `if __name__` line:
```python
TOKEN = "<<redacted:api-token:1a2b3c4d>>"  # pragma: allowlist secret


class PlaceholderGuard(unittest.TestCase):
    def test_denies_writing_a_placeholder(self):
        for payload in [call("Write", file_path="app.py", content=f"KEY = '{TOKEN}'\n"),
                        call("Edit", file_path="app.py", old_string="x", new_string=TOKEN),
                        call("MultiEdit", file_path="app.py", edits=[{"old_string": "x", "new_string": TOKEN}]),
                        call("NotebookEdit", notebook_path="a.ipynb", new_source=TOKEN),
                        call("Bash", command=f"curl -H 'Authorization: Bearer {TOKEN}' https://api.example.com")]:
            with self.subTest(tool=payload["tool_name"]):
                code, out = run(payload)
                self.assertTrue(denied(out))
                self.assertIn("placeholder", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_writes_without_one(self):
        self.assertEqual(run(call("Write", file_path="app.py", content="KEY = os.environ['KEY']\n")), (0, None))
        self.assertEqual(run(call("Write", file_path="notes.md", content="<<not a token>>")), (0, None))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_pretool_gate -v`
Expected: `test_denies_writing_a_placeholder` FAILS for every subtest. `test_allows_writes_without_one` passes.

- [ ] **Step 3: Add the guard to `security/pretool_gate.py`**

Add to the imports:
```python
from security.placeholders import PLACEHOLDER  # noqa: E402
```

Add above `check`:
```python
WRITE_FIELDS = ("content", "new_string", "old_string", "new_source", "command")

PLACEHOLDER_REASON = (
    "Blocked by central: this would write a <<redacted:...>> redaction placeholder, which "
    "stands in for a secret you were never shown. Writing it would replace the real value "
    "with the placeholder. Leave that line out of the change, or ask the user for the value.")


def carries_placeholder(tool_input):
    texts = [tool_input.get(f) for f in WRITE_FIELDS]
    for edit in tool_input.get("edits") or []:
        texts += [edit.get("old_string"), edit.get("new_string")]
    return any(isinstance(t, str) and PLACEHOLDER.search(t) for t in texts)
```

At the top of `check`, after `cwd = payload.get("cwd")`, add:
```python
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash") and carries_placeholder(ti):
        return PLACEHOLDER_REASON
```

Add to the module docstring: `It also refuses any write, edit or command that carries a <<redacted:...>> placeholder. Without that, a model that read a redacted config file and rewrote it whole would silently replace the real secret with the token.`

- [ ] **Step 4: Run the whole suite**

Run: `cd plugins/central && python -m unittest discover -s security/tests -t . -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/central/security
git commit -m "Refuse writes and commands that carry a redaction placeholder

A model that reads a redacted file and writes it back whole would replace the real
secret with <<redacted:...>>. The PreToolUse gate now denies any Write, Edit, MultiEdit,
NotebookEdit or Bash call that carries a placeholder, and says why.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Deny-rule installer

**Files:**
- Create: `plugins/central/security/install_deny_rules.py`, `plugins/central/security/tests/test_install_deny_rules.py`

**Interfaces:**
- Consumes: `credential-files.json`
- Produces:
  - `security.install_deny_rules.rules() -> list[str]`
  - `merge(settings: dict, new: list[str]) -> list[str]`: the rules it added
  - `main(argv: list[str] | None = None) -> int`
  - CLI: `python install_deny_rules.py [--settings PATH] [--dry-run]`

- [ ] **Step 1: Write the failing tests**

`security/tests/test_install_deny_rules.py`:
```python
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from security.install_deny_rules import main, merge, rules


def quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return main(argv)


class Rules(unittest.TestCase):
    def test_shape(self):
        r = rules()
        self.assertIn("Read(**/.env)", r)
        self.assertIn("Read(**/*.pem)", r)
        self.assertIn("Read(~/.aws/credentials)", r)
        self.assertNotIn("Read(**/.env.example)", r)
        self.assertEqual(len(r), len(set(r)))

    def test_merge_keeps_existing_rules_and_order(self):
        settings = {"permissions": {"deny": ["Bash(rm -rf:*)"], "allow": ["Read(src/**)"]}}
        added = merge(settings, ["Read(**/.env)"])
        self.assertEqual(settings["permissions"]["deny"], ["Bash(rm -rf:*)", "Read(**/.env)"])
        self.assertEqual(settings["permissions"]["allow"], ["Read(src/**)"])
        self.assertEqual(added, ["Read(**/.env)"])


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.settings = pathlib.Path(self.dir.name) / "settings.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_creates_settings_when_missing(self):
        self.assertEqual(quiet(["--settings", str(self.settings)]), 0)
        self.assertEqual(json.loads(self.settings.read_text())["permissions"]["deny"], rules())

    def test_second_run_changes_nothing_and_makes_no_backup(self):
        quiet(["--settings", str(self.settings)])
        before = self.settings.read_text()
        quiet(["--settings", str(self.settings)])
        self.assertEqual(self.settings.read_text(), before)
        self.assertEqual(list(self.settings.parent.glob("settings.json.bak-*")), [])

    def test_backs_up_before_changing(self):
        self.settings.write_text('{"model": "opus"}')
        quiet(["--settings", str(self.settings)])
        [backup] = self.settings.parent.glob("settings.json.bak-*")
        self.assertEqual(backup.read_text(), '{"model": "opus"}')
        self.assertEqual(json.loads(self.settings.read_text())["model"], "opus")

    def test_dry_run_writes_nothing(self):
        quiet(["--settings", str(self.settings), "--dry-run"])
        self.assertFalse(self.settings.exists())

    def test_refuses_to_overwrite_invalid_json(self):
        self.settings.write_text("{broken")
        self.assertEqual(quiet(["--settings", str(self.settings)]), 1)
        self.assertEqual(self.settings.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/central && python -m unittest security.tests.test_install_deny_rules`
Expected: ERROR with `No module named 'security.install_deny_rules'`.

- [ ] **Step 3: Write `security/install_deny_rules.py`**

```python
"""Add central's credential-file deny rules to a Claude Code settings file.

A plugin cannot ship permission rules: Claude Code drops every plugin setting
except `agent` and `subagentStatusLine`
(https://code.claude.com/docs/en/plugins/manifest-reference.md). So the rules
go into the user's own settings, by this script, run once per machine:

    python install_deny_rules.py                 # ~/.claude/settings.json
    python install_deny_rules.py --dry-run       # show what would be added
    python install_deny_rules.py --settings PATH # another file, e.g. managed settings

`Read` deny rules also cover Grep, Glob and the Bash file commands Claude Code
recognises, and unlike the PreToolUse gate they have no code that can fail
(https://code.claude.com/docs/en/permissions.md). The rules are added to
whatever is there and never replace it. The file is backed up first, and a
second run changes nothing.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
DATA = json.loads((HERE / "credential-files.json").read_text(encoding="utf-8"))
DEFAULT = pathlib.Path.home() / ".claude" / "settings.json"


def rules():
    return ([f"Read(**/{n})" for n in DATA["names"]]
            + [f"Read(**/*{s})" for s in DATA["suffixes"]]
            + [f"Read(~/{p})" for p in DATA["home_paths"]])


def merge(settings, new):
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    added = [r for r in new if r not in deny]
    deny.extend(added)
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--settings", type=pathlib.Path, default=DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    try:
        settings = json.loads(a.settings.read_text(encoding="utf-8")) if a.settings.exists() else {}
    except json.JSONDecodeError as exc:
        print(f"{a.settings} is not valid JSON ({exc.msg}, line {exc.lineno}); fix it first. Nothing changed.")
        return 1

    added = merge(settings, rules())
    if not added:
        print("All rules are already present. Nothing changed.")
        return 0
    for r in added:
        print(f"add     {r}")
    if a.dry_run:
        return 0
    if a.settings.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        backup = a.settings.with_name(f"{a.settings.name}.bak-{stamp}")
        shutil.copy2(a.settings, backup)
        print(f"backup  {backup}")
    else:
        a.settings.parent.mkdir(parents=True, exist_ok=True)
    a.settings.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"wrote   {a.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/central && python -m unittest security.tests.test_install_deny_rules -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/central/security
git commit -m "Add an installer for the credential-file deny rules

Plugins can't ship permission rules, so install_deny_rules.py merges Read deny
rules for every file in credential-files.json into the user's settings.json. It
backs the file up first, never removes a rule, refuses to touch invalid JSON, and
changes nothing on a second run.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Release central 1.3.0, end to end

**Files:**
- Modify: `plugins/central/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`, `plugins/central/skills/answer-only/SKILL.md`

**Interfaces:**
- Consumes: everything above.
- Produces: central 1.3.0 on a PR. Task 9 needs it installed.

- [ ] **Step 1: Bump the version and descriptions**

In `plugins/central/.claude-plugin/plugin.json`, set `"version": "1.3.0"` and change the description to:
`"In-house skills: answer-only replies with a PII prompt gate, security hooks that keep credentials out of the model's context, the caveman token-compression suite, document conversion, method skills for scoping and executing code changes, a data-model audit, and the vault tooling."`
Add `"security"` to its `keywords`. Make the same description and keyword change to the `central` entry in `.claude-plugin/marketplace.json`.

- [ ] **Step 2: Document it**

In `README.md`, add this section after the central skills tables and before the next `###` heading:
````markdown
### central security hooks

Three hooks keep credentials out of the model's context and the session transcript.
None of them needs invoking.

- **Prompt gate** (`UserPromptSubmit`, part of answer-only) blocks a prompt that carries a
  credential or personal data.
- **Credential gate** (`PreToolUse`) denies Read, Grep and Bash calls that would read a
  `.env` file, a private key or a cloud credential file (the list is
  `plugins/central/security/credential-files.json`). It also refuses any write that
  carries a redaction placeholder.
- **Output redaction** (`PostToolUse`) replaces secrets and card or bank numbers in Read,
  Bash, Grep and WebFetch output with placeholders like `<<redacted:api-token:1a2b3c4d>>`. The
  same value gets the same placeholder for the whole session. Contact details are left in
  tool output on purpose.

Each hook lets the call through if it fails, and shows a message saying it did.

A plugin can't ship permission rules, so run this once per machine to add matching
`Read` deny rules to your own `~/.claude/settings.json`. They have no code that can fail:

```sh
python ~/.claude/plugins/cache/skills/central/1.3.0/security/install_deny_rules.py
```

Add `--dry-run` to see the rules first. To roll them out to the whole team, put the same
rules in managed settings instead.

What these don't stop: a script that opens a file itself, or `grep -r` across a folder
holding a credential file. Output redaction is the backstop there, for the patterns it
knows.

Run the tests with:

```sh
cd plugins/central && python -m unittest discover -s security/tests -t .
```
````
Change the `central` row in the README's plugin table to say `In-house skills: answer-only replies with a PII prompt gate, security hooks for credentials, the caveman ...`, leaving the rest of the row unchanged.

In `skills/answer-only/SKILL.md`, outside the INJECT markers, add one paragraph after "Why a hook and not a skill call": `The detectors live in plugins/central/security/patterns.py, shared with the output redaction and the vault's read gate. Change them there, not in prompt_gate.py.`

- [ ] **Step 3: Run everything**

Run:
```bash
cd ~/Documents/skills && claude plugin validate . && claude plugin validate plugins/central && (cd plugins/central && python -m unittest discover -s security/tests -t .)
```
Expected: both validations pass and every unit test passes.

- [ ] **Step 4: Check it live in a real session**

```bash
cd "$TEMP" && mkdir -p e2e && cd e2e && printf 'API_KEY=%s\n' "$(python -c "print('gh'+'p_'+'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8')")" > .env && cp .env config.txt && printf 'API_KEY=\n' > .env.example
```
```bash
claude -p --plugin-dir ~/Documents/skills/plugins/central --allowedTools "Read Write" "Read .env, then config.txt, then .env.example. For each, say what you saw. Then write config.txt back exactly as you read it."
```
Expected: the .env read is denied with the credential-file reason. config.txt comes back with `<<redacted:api-token:...>>` and not the token. .env.example reads normally. The write of config.txt is denied with the placeholder reason. Then confirm the token isn't in the transcript, and that config.txt is unchanged:
```bash
grep -rl "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8" ~/.claude/projects/*e2e*/ ; cat config.txt | cut -c1-12
```
Expected: no file listed, and `API_KEY=ghp_` printed (the file still holds the real value).

- [ ] **Step 5: Commit and open the PR**

```bash
git add README.md .claude-plugin/marketplace.json plugins/central
git commit -m "Release central 1.3.0 with security hooks

Documents the credential gate, output redaction and deny-rule installer, and bumps
the version so installs pick up the new hooks.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin security-hardening
gh pr create -R <owner>/skills --base main --head security-hardening --title "central 1.3.0: security hooks" --body "Adds a credential-file gate, PostToolUse output redaction with salted per-session placeholders, a shared detector module, and an installer for permission deny rules. Plan: docs/superpowers/plans/2026-10-07-central-security-hardening.md. Unit tests and a live headless session check are in the plan's Task 8.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

After the PR is merged, refresh the marketplace and update the installed plugin. Task 9 needs 1.3.0 installed.
```bash
claude plugin marketplace update skills
```
```bash
claude plugin update central@skills
```

---

### Task 9: The vault's read gate uses the shared email detector

This task is in a different repo, `C:\vault`. That checkout is on `internal/install-cache-handoff` with uncommitted changes to `_ai/setup.md` and `index.md`. Leave them alone, and work in a separate worktree off `main`. That branch also installs cache-handoff, which has since been removed from skills; flag it to the user rather than fixing it here.

**Files:**
- Modify: `C:\vault\scripts\pii_gate.py` (the `EMAIL = re.compile(...)` line near the top)
- Modify: `C:\vault\scripts\test_pii_gate.py`, `C:\vault\scripts\test_prompt_gate.py` (`find_gate`)

**Interfaces:**
- Consumes: `EMAIL` from the installed `security/patterns.py`, found under `~/.claude/plugins/cache/*/central/<version>/`
- Produces: `pii_gate.newest(paths: list[pathlib.Path]) -> pathlib.Path | None`, picking the highest plugin version numerically

- [ ] **Step 1: Make a worktree**

```bash
cd /c/vault && git fetch origin && git worktree add ../vault-shared-email -b internal/pii-gate-shared-email origin/main
```

- [ ] **Step 2: Add the failing cases to `scripts/test_pii_gate.py`**

Add above `CASES`:
```python
import importlib.util
import tempfile

_spec = importlib.util.spec_from_file_location("pii_gate", GATE)
pii_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pii_gate)

_pins = pathlib.Path(tempfile.mkdtemp()) / "requirements-notes.md"
_pins.write_text("\n".join(f"pin pkg{i}@1.2.3" for i in range(12)), encoding="utf-8")
```
Add to the end of `CASES`:
```python
    ("Version pins are not addresses",     read(str(_pins)), "ALLOW"),
```
Add before the summary `print`:
```python
cache = pathlib.Path("/c") / "x" / "cache"
paths = [cache / "m" / "central" / v / "security" / "patterns.py" for v in ("1.9.0", "1.10.0", "1.2.0")]
newest = pii_gate.newest(paths)
ok = newest is not None and newest.parts[-3] == "1.10.0"
print(f"{'ok  ' if ok else 'FAIL'}  newest plugin version sorts numerically")
fails += 0 if ok else 1
total += 1
```
Read the existing loop first: if its counters aren't named `fails` and `total`, use the names it uses.

- [ ] **Step 3: Run it to verify it fails**

Run: `cd ../vault-shared-email && python scripts/test_pii_gate.py`
Expected: "Version pins are not addresses" fails (the old regex counts 12 distinct addresses and denies), and the version check raises `AttributeError: module 'pii_gate' has no attribute 'newest'`.

- [ ] **Step 4: Load the shared detector in `scripts/pii_gate.py`**

Add `import importlib.util` to the imports. Replace the `EMAIL = re.compile(...)` line with:
```python
def newest(paths):
    """The path under the highest plugin version. Plain sorting puts 1.10.0 before 1.9.0."""
    def version(p):
        return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", p.parts[-3]))
    return max(paths, key=version, default=None)


def shared_email():
    """EMAIL from the installed central plugin, the one copy every gate shares.

    The local copy below is the fallback for a machine without the plugin. It is
    kept identical, so a missing plugin changes nothing but where the pattern lives.
    """
    cache = pathlib.Path.home() / ".claude" / "plugins" / "cache"
    found = newest(list(cache.glob("*/central/*/security/patterns.py")))
    if found is None:
        return None
    spec = importlib.util.spec_from_file_location("shared_patterns", found)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EMAIL


# The TLD must be alphabetic: `[\w.]{2,}` read every `pkg@1.2.3` pin as an address.
EMAIL = shared_email() or re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
```
`shared_email()` runs at import. If the plugin file is broken, the exception reaches the `except Exception` at the bottom of the script, which already fails open.

In `scripts/test_prompt_gate.py`, change `find_gate` to use the same numeric sort:
```python
def find_gate():
    cache = pathlib.Path.home() / ".claude" / "plugins" / "cache"
    found = list(cache.glob("*/central/*/skills/answer-only/prompt_gate.py"))
    return max(found, key=lambda p: tuple(int(x) if x.isdigit() else 0
                                          for x in p.parts[-4].split(".")), default=None)
```
Keep its docstring, adding one sentence: `Versions are compared as numbers, so 1.10.0 beats 1.9.0.`

- [ ] **Step 5: Run the vault's gate tests**

Run: `cd ../vault-shared-email && python scripts/test_pii_gate.py && python scripts/test_prompt_gate.py`
Expected: every case passes in both, now against central 1.3.0. If a `test_prompt_gate.py` card or address case changes result, the 1.3.0 detectors changed it (card prefixes, value-only spans). Fix the case only if the new result is right, and say so in the commit.

- [ ] **Step 6: Commit and open the PR**

```bash
git add scripts/pii_gate.py scripts/test_pii_gate.py scripts/test_prompt_gate.py
git commit -m "Use central's shared email detector in the PII read gate

pii_gate.py loads EMAIL from the installed central plugin, so the read gate,
the prompt gate and the output redaction share one detector. It keeps an identical
local copy for machines without the plugin. The shared pattern requires an
alphabetic TLD, so version pins no longer count towards the bulk-address limit.
Plugin versions are now compared numerically in both gate scripts.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin internal/pii-gate-shared-email
gh pr create -R <owner>/vault --base main --head internal/pii-gate-shared-email --title "PII read gate: use central's shared email detector" --body "Needs central 1.3.0 installed. Loads EMAIL from the plugin's security/patterns.py, with an identical local fallback, and fixes the plugin-version sort. python scripts/test_pii_gate.py and python scripts/test_prompt_gate.py both pass.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
