import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
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


class Utf8(unittest.TestCase):
    """Claude Code sends UTF-8. Decoding it as the Windows code page garbles macrons.

    The payload goes in as UTF-8 bytes: text=True would encode it with the same
    code page the hook decodes with, and the round trip would hide the bug.
    """

    def test_non_ascii_text_survives_a_redaction(self):
        payload = fixture("post_bash.json")
        payload["tool_response"] = {"stdout": f"Māori token {s.GITHUB} café “ok”\n",
                                    "stderr": ""}
        p = subprocess.run([sys.executable, str(HOOK)],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        stdout = json.loads(p.stdout.decode("utf-8"))["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        self.assertTrue(stdout.startswith("Māori token <<redacted:api-token:"), "text before the placeholder garbled")
        self.assertTrue(stdout.endswith(">> café “ok”\n"), "text after the placeholder garbled")


class Rulings(unittest.TestCase):
    def test_powershell_output_is_redacted(self):
        payload = fixture("post_bash.json")
        payload["tool_name"] = "PowerShell"
        payload["tool_response"] = {"stdout": f"api_key = {s.GITHUB}\n", "stderr": ""}
        code, out = run(payload)
        self.assertEqual(code, 0)
        updated = out["hookSpecificOutput"]["updatedToolOutput"]
        self.assertNotIn(s.GITHUB, json.dumps(updated))
        self.assertIn("<<redacted:api-token:", updated["stdout"])

    def test_hooks_json_matcher_includes_powershell(self):
        hooks = json.loads((HERE.parents[1] / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        matcher = hooks["hooks"]["PostToolUse"][0]["matcher"]
        for tool in ["Read", "Bash", "PowerShell", "Grep", "WebFetch"]:
            self.assertIn(tool, matcher.split("|"))

    def test_missing_session_id_still_redacts_and_says_unstable(self):
        for sid in (None, ""):
            with self.subTest(session_id=sid):
                payload = fixture("post_bash.json")
                payload.pop("session_id", None)
                if sid is not None:
                    payload["session_id"] = sid
                payload["tool_response"] = {"stdout": f"api_key = {s.GITHUB}\n", "stderr": ""}
                code, out = run(payload)
                self.assertEqual(code, 0)
                self.assertNotIn(s.GITHUB, json.dumps(out["hookSpecificOutput"]["updatedToolOutput"]))
                self.assertIn("not stable", out["systemMessage"])

    def test_broken_import_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            lone = pathlib.Path(tmp) / "redact_output.py"
            shutil.copy(HOOK, lone)
            p = subprocess.run([sys.executable, str(lone)], input=json.dumps(fixture("post_bash.json")),
                               capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("failed", json.loads(p.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
