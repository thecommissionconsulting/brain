import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parents[1] / "pretool_gate.py"
HOOKS_JSON = pathlib.Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"


def run(payload, hook=HOOK):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, str(hook)], input=stdin, capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None), p.stderr


def call(tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "session_id": "t", "cwd": os.getcwd(),
            "tool_name": tool, "tool_input": tool_input}


def denied(out):
    return bool(out) and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class CredentialGate(unittest.TestCase):
    def test_denies_reads(self):
        for payload in [call("Read", file_path=".env"), call("Read", file_path=".secrets"),
                        call("Grep", pattern="KEY", path="server.pem"),
                        call("Bash", command="cat ~/.aws/credentials"),
                        call("PowerShell", command="Get-Content .env"),
                        call("PowerShell", command="type .env"),
                        call("Read", file_path="C:/proj/.env.uat"),
                        call("PowerShell", command="findstr . .env.prod"),
                        call("PowerShell", command="cmd /c type .env"),
                        call("Bash", command="sudo sed -n p .env")]:
            with self.subTest(tool=payload["tool_name"], ti=sorted(payload["tool_input"].values())):
                code, out, _ = run(payload)
                self.assertEqual(code, 0)
                self.assertTrue(denied(out))
                self.assertIn("credential file", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_everything_else(self):
        for payload in [call("Read", file_path=".env.example"), call("Read", file_path=".env.template"),
                        call("Grep", pattern="x", path="src"),
                        call("Bash", command="git status"), call("Write", file_path=".env", content="A=1"),
                        call("PowerShell", command="Get-ChildItem")]:
            with self.subTest(tool=payload["tool_name"]):
                self.assertEqual(run(payload)[:2], (0, None))

    def test_broken_input_is_reported_and_allowed(self):
        code, out, _ = run("{not json")
        self.assertEqual(code, 0)
        self.assertFalse(denied(out))
        self.assertIn("gate failed", out["systemMessage"])

    def test_broken_import_is_reported_and_allowed(self):
        # A lone copy has no sibling security package, so its imports fail.
        with tempfile.TemporaryDirectory() as tmp:
            lone = pathlib.Path(tmp) / "pretool_gate.py"
            shutil.copy(HOOK, lone)
            code, out, err = run(call("Read", file_path=".env"), hook=lone)
        self.assertEqual(code, 0)
        self.assertNotIn("Traceback", err)
        self.assertFalse(denied(out))
        self.assertIn("credential gate failed", out["systemMessage"])

    def test_hook_is_registered_for_powershell(self):
        entry = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
        self.assertIn("PowerShell", entry["matcher"].split("|"))


class Utf8(unittest.TestCase):
    def test_non_ascii_path_is_named_intact(self):
        # UTF-8 bytes in, not text=True: see test_redact_output.Utf8.
        payload = call("Read", file_path="C:/proj/M\u0101ori-caf\u00e9.pem")
        p = subprocess.run([sys.executable, str(HOOK)],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout.decode("utf-8"))
        self.assertTrue(denied(out))
        self.assertIn("`M\u0101ori-caf\u00e9.pem`", out["hookSpecificOutput"]["permissionDecisionReason"])


TOKEN = "<<redacted:api-token:1a2b3c4d>>"  # pragma: allowlist secret


class PlaceholderGuard(unittest.TestCase):
    def test_denies_writing_a_placeholder(self):
        for payload in [call("Write", file_path="app.py", content=f"KEY = '{TOKEN}'\n"),
                        call("Edit", file_path="app.py", old_string="x", new_string=TOKEN),
                        call("MultiEdit", file_path="app.py", edits=[{"old_string": "x", "new_string": TOKEN}]),
                        call("NotebookEdit", notebook_path="a.ipynb", new_source=TOKEN),
                        call("Bash", command=f"curl -H 'Authorization: Bearer {TOKEN}' https://api.example.com"),
                        call("PowerShell", command=f"Invoke-RestMethod -Headers @{{Authorization='Bearer {TOKEN}'}} https://api.example.com")]:
            with self.subTest(tool=payload["tool_name"]):
                code, out, _ = run(payload)
                self.assertEqual(code, 0)
                self.assertTrue(denied(out))
                self.assertIn("placeholder", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allows_writes_without_one(self):
        self.assertEqual(run(call("Write", file_path="app.py", content="KEY = os.environ['KEY']\n"))[:2], (0, None))
        self.assertEqual(run(call("Write", file_path="notes.md", content="<<not a token>>"))[:2], (0, None))


if __name__ == "__main__":
    unittest.main()
