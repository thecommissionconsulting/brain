import os
import time
import unittest

from security.credential_paths import command_reads_credential, is_credential_path

HOME = os.path.join(os.sep, "home", "dev")


class Paths(unittest.TestCase):
    def test_credential_files(self):
        for p in [".env", "app/.env.production", r"C:\proj\.env.local", "certs/server.pem",
                  "keys/deploy.KEY", "~/.ssh/id_ed25519", "vault.kdbx", ".secrets"]:
            with self.subTest(p=p):
                self.assertTrue(is_credential_path(p, cwd=HOME, home=HOME))

    def test_home_paths(self):
        self.assertTrue(is_credential_path(os.path.join(HOME, ".aws", "credentials"), home=HOME))
        self.assertTrue(is_credential_path(".dbt/profiles.yml", cwd=HOME, home=HOME))

    def test_home_variables_are_case_insensitive(self):
        win_home = r"C:\Users\x"
        for p, home in [("$env:userprofile/.aws/credentials", HOME),
                        (r"$ENV:USERPROFILE\.aws\credentials", HOME),
                        (r"%USERPROFILE%\.aws\credentials", HOME),
                        (r"C:\Users\x\.ssh\id_rsa", win_home)]:
            with self.subTest(p=p):
                self.assertTrue(is_credential_path(p, cwd=home, home=home))
        self.assertIsNotNone(command_reads_credential(
            r"Get-Content $env:userprofile\.aws\credentials", home=HOME))

    def test_any_env_stage_file(self):
        # Matched generically, not from the names list: .env.<anything> but templates.
        for p in [".env.prod", ".env.uat", "app/.env.ci", r"C:\proj\.env.qa-2", ".env.example.local"]:
            with self.subTest(p=p):
                self.assertTrue(is_credential_path(p, cwd=HOME, home=HOME))

    def test_templates_and_lookalikes_are_readable(self):
        for p in [".env.example", ".env.sample", ".env.template", ".env.dist", "app/.env.local.example",
                  ".envrc.md", "id_ed25519.pub", "keyboard.md",
                  "models/profiles.yml", "credentials.md", None, ""]:
            with self.subTest(p=p):
                self.assertFalse(is_credential_path(p, cwd=HOME, home=HOME))


class Commands(unittest.TestCase):
    def test_reading_commands(self):
        for cmd in ["cat .env", "head -5 ~/.ssh/id_rsa", "git log && type .env.local",
                    "Get-Content $HOME/.aws/credentials", "grep KEY certs/server.pem"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(command_reads_credential(cmd, cwd=HOME, home=HOME))

    def test_more_readers_and_prefixes(self):
        for cmd in ["sed -n p .env", "awk 1 .env", "sort .env", "tac .env", "base64 .env",
                    "findstr . .env", "cmd /c type .env", 'cmd /c "type .env"', "cmd.exe /C type .env",
                    "sudo cat .env", "sudo -u root cat /srv/app/.env", "gc .env.prod", "cat .env.uat",
                    "Get-Content -Path:.env", "git status; sudo tail -n 5 .env.ci"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(command_reads_credential(cmd, cwd=HOME, home=HOME))

    def test_many_sudo_flags_scan_fast(self):
        # Overlapping flag alternatives once made this exponential.
        for cmd in ["sudo " + "-u " * 60 + "x", "sudo " + "-uX " * 60 + "x"]:
            t0 = time.perf_counter()
            self.assertIsNone(command_reads_credential(cmd, cwd=HOME, home=HOME))
            self.assertLess(time.perf_counter() - t0, 0.5)

    def test_commands_that_only_mention_a_path(self):
        # Learned in the vault's pii_gate.py: a gate that blocks its own setup gets switched off.
        for cmd in ["echo '.env' >> .gitignore", "git add .env.example", "cp .env.example .env",
                    "cp .env.template .env.uat", "echo .env.prod >> .gitignore", "sort .env.dist",
                    "grep --exclude=.env -r TODO src", "sudo apt install less",
                    "git commit -m 'do not cat .env, read more docs'", "cat .env.example"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(command_reads_credential(cmd, cwd=HOME, home=HOME))

    def test_reports_the_name_only(self):
        self.assertEqual(command_reads_credential("cat /srv/app/.env", home=HOME), ".env")


if __name__ == "__main__":
    unittest.main()
