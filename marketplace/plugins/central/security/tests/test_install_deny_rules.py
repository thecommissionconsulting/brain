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
        self.assertIn("Read(**/.env.uat)", r)  # stages the gate matches generically
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

    def test_accepts_a_bom_and_writes_without_one(self):
        # Windows PowerShell 5.1 writes UTF-8 with a BOM.
        self.settings.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus", "permissions": {"allow": ["Read(src/**)"]}}')
        self.assertEqual(quiet(["--settings", str(self.settings)]), 0)
        raw = self.settings.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        written = json.loads(raw.decode("utf-8"))
        self.assertEqual(written["model"], "opus")
        self.assertEqual(written["permissions"]["allow"], ["Read(src/**)"])
        self.assertEqual(written["permissions"]["deny"], rules())

    def test_dry_run_writes_nothing(self):
        quiet(["--settings", str(self.settings), "--dry-run"])
        self.assertFalse(self.settings.exists())

    def test_refuses_to_overwrite_invalid_json(self):
        self.settings.write_text("{broken")
        self.assertEqual(quiet(["--settings", str(self.settings)]), 1)
        self.assertEqual(self.settings.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
