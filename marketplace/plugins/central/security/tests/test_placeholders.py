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
