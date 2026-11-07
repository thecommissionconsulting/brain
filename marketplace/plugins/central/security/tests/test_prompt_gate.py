"""The prompt gate, driven through its real stdin/stdout/exit-code contract."""
import json
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
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
                     'what does token = payload.get("user_input") do',
                     'why is password_hint = "remember" here', 'set secret_count = 3']:
            with self.subTest(text=text):
                self.assertEqual(prompt(text).returncode, 0)

    def test_override(self):
        self.assertEqual(prompt(f"use {s.AWS} #pii-ok").returncode, 0)

    def test_broken_input_is_reported_and_passes(self):
        p = run("{not json")
        self.assertEqual(p.returncode, 0)
        self.assertIn("prompt gate failed", json.loads(p.stdout)["systemMessage"])


class Utf8(unittest.TestCase):
    def test_offsets_count_characters_of_a_non_ascii_prompt(self):
        # UTF-8 bytes in, not text=True: see test_redact_output.Utf8.
        text = f"Māori café: use {s.GITHUB} now"
        start = text.index(s.GITHUB)
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": text}
        p = subprocess.run([sys.executable, str(GATE)],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn(f"chars {start}-{start + len(s.GITHUB)}", p.stderr.decode("utf-8"))


class GateRulings(unittest.TestCase):
    def test_broken_import_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            lone = pathlib.Path(tmp) / "prompt_gate.py"
            shutil.copy(GATE, lone)
            p = subprocess.run([sys.executable, str(lone)],
                               input=json.dumps({"session_id": "t", "prompt": "hello"}),
                               capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("failed", json.loads(p.stdout)["systemMessage"])

    def test_redact_without_session_id_does_not_share_a_salt(self):
        spec = importlib.util.spec_from_file_location("prompt_gate_under_test", GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = f"use {s.GITHUB}"
        from security.patterns import scan
        hits = scan(text)
        self.assertNotEqual(mod.redact(text, hits, ""), mod.redact(text, hits, ""))
        self.assertEqual(mod.redact(text, hits, "abc"), mod.redact(text, hits, "abc"))


if __name__ == "__main__":
    unittest.main()
