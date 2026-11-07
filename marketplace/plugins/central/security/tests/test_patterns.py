import time
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
                     'see 3 Big Things st the end',
                     'password_hint = "remember"',
                     'secret_count = 3',
                     'token_type = "bearer_access"']:
            with self.subTest(text=text):
                self.assertEqual(labels(text), [])

    def test_luhn_valid_number_without_a_card_prefix(self):
        # 9000000000000001 passes Luhn; 1 in 10 random 16-digit IDs do.
        self.assertFalse(plausible_card("9000000000000001"))
        self.assertEqual(labels("customer_id,9000000000000001", OUTPUT), [])


class CardDetection(unittest.TestCase):
    def assert_one_card(self, text, digits):
        [(label, start, end)] = scan(text, OUTPUT)
        self.assertEqual(label, "card number")
        self.assertEqual(text[start:end].replace(" ", ""), digits)

    def test_card_after_date(self):
        self.assert_one_card("2026-10-07 " + s.VISA, "4111111111111111")

    def test_card_after_id(self):
        self.assert_one_card("id 12 " + s.VISA, "4111111111111111")

    def test_card_span_excludes_surrounding_digits(self):
        text = "id 12 " + s.VISA
        [(_, start, end)] = scan(text, OUTPUT)
        self.assertEqual(text[start:end], s.VISA)

    def test_mastercard(self):
        self.assert_one_card("card 5555 5555 5555 4444", "5555555555554444")

    def test_amex(self):
        self.assert_one_card("card 378282246310005", "378282246310005")

    def test_run_ending_against_a_letter_stops_at_its_last_separator(self):
        # The group touching the letter is not part of the run; the card before it is.
        self.assert_one_card("paid " + s.VISA + " 2222abc", "4111111111111111")
        self.assertEqual(labels("paid 4111 1111 1111 1111abc", OUTPUT), [])

    def test_non_card_runs_give_nothing(self):
        for text in ["customer_id,9000000000000001", "order 1234567890123456 shipped"]:
            with self.subTest(text=text):
                self.assertEqual(labels(text, OUTPUT), [])


class SecretAssignmentKeyword(unittest.TestCase):
    def assert_value_only(self, text, value):
        [(label, start, end)] = scan(text)
        self.assertEqual(label, "secret assignment")
        self.assertEqual(text[start:end], value)

    def test_prefixed_keywords(self):
        for key, value in [("OPENAI_API_KEY=", "abc123" + "def456ghi789"),
                           ("client_secret=", "Tr0ub4dor3" + "xK987654"),
                           ("GITHUB_TOKEN=", "a1b2c3d4" + "e5f6g7h8i9"),
                           ("access_token=", "MySecret" + "Token123456")]:
            with self.subTest(key=key):
                self.assert_value_only(key + value, value)

    def test_key_names_with_a_tail_after_the_keyword(self):
        # ~/.aws/credentials and Django settings: no fixed prefix for the token pattern.
        value = "wJalrXUtnFEMI/" + "K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        for key in ["AWS_SECRET_ACCESS_KEY=", "aws_secret_access_key = ", "SECRET_KEY="]:
            with self.subTest(key=key):
                self.assert_value_only(key + value, value)

    def test_no_letter_or_digit_straight_after_keyword(self):
        self.assertEqual(labels("tokens=abc123def456ghi"), [])

    def test_quoted_keys(self):
        self.assert_value_only('"password": "' + "Tr0ub4dor3" + 'xK"', "Tr0ub4dor3xK")
        self.assert_value_only("'api_key' = '" + "abc123" + "def456ghi'", "abc123def456ghi")

    def test_known_token_value_is_claimed_once_by_the_token_pattern(self):
        self.assertEqual(labels("api_key = " + s.GITHUB), ["API token"])


class Overlap(unittest.TestCase):
    def test_ird_shaped_run_inside_bank_account_is_reported_once(self):
        text = "account 12-3456-1234567-123 ok"
        hits = scan(text)
        self.assertEqual([h[0] for h in hits], ["NZ bank account"])
        self.assertEqual(text[hits[0][1]:hits[0][2]], "12-3456-1234567-123")

    def test_claimed_span_is_not_offered_to_a_later_pattern(self):
        # The IRD pattern matches 123-456-789 in the raw text; the earlier
        # pattern's claim must hide it.
        from security.patterns import PATTERNS
        import re
        ird = next(p for l, _, p in PATTERNS if l == "IRD number")
        text = "123-456-789"
        self.assertTrue(ird.search(text))
        patterns.PATTERNS, saved = (("API token", "secret", re.compile(r"\d{3}-\d{3}-\d{3}")),) + PATTERNS, PATTERNS
        try:
            self.assertEqual(labels(text), ["API token"])
        finally:
            patterns.PATTERNS = saved

    def test_two_secrets_in_text_order(self):
        text = f"a {s.GITHUB} then {s.ANTHROPIC}"
        hits = scan(text)
        self.assertEqual([h[0] for h in hits], ["API token", "API token"])
        self.assertEqual([text[h[1]:h[2]] for h in hits], [s.GITHUB, s.ANTHROPIC])

    def test_private_key_without_end_line(self):
        text = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34Gkx"
        self.assertEqual(labels(text), ["private key"])


class Bounds(unittest.TestCase):
    """5 MB of private-key headers with no END line, the Speed class's bar.

    The bounded body once tried 10,000 characters after every header, about 28 s
    on this input, and a hook timeout passes the whole output through unredacted.
    """

    def assert_fast(self, block):
        text = block * (5_000_000 // len(block))
        t0 = time.perf_counter()
        hits = scan(text)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 3.0, f"took {elapsed:.2f}s")
        return hits

    def test_many_begin_lines_without_end_scan_fast(self):
        header = "-----BEGIN " + "PRIVATE KEY-----\n"
        hits = self.assert_fast(header)
        self.assertEqual(len(hits), 5_000_000 // len(header))

    def test_many_headers_with_short_bodies_scan_fast(self):
        block = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34Gkx\n"
        hits = self.assert_fast(block)
        self.assertEqual({h[0] for h in hits}, {"private key"})

    def test_key_after_an_unterminated_header_is_still_covered_to_its_end(self):
        text = "-----BEGIN " + "PRIVATE KEY-----\n-- note --\n" + s.PRIVATE_KEY + "\nafter"
        self.assertTrue(any(text[a:b].endswith("-----END " + "RSA PRIVATE KEY-----")
                            for _, a, b in scan(text)))


class Speed(unittest.TestCase):
    """5 MB of output must scan in under 3 s; the hook's timeout passes it unredacted.

    Each shape once beat a per-group card search: every group starts like a card.
    """

    def assert_fast(self, text):
        t0 = time.perf_counter()
        hits = scan(text, OUTPUT)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 3.0, f"took {elapsed:.2f}s")
        return hits

    def test_csv_rows(self):
        row = "2026-10-07,1234567890123456,000123,98.40\n"
        text = row * (5_000_000 // len(row)) + "paid " + s.VISA
        hits = self.assert_fast(text)
        self.assertEqual([h[0] for h in hits], ["card number"])
        self.assertEqual(text[hits[0][1]:hits[0][2]], s.VISA)

    def test_single_digits_joined_by_dashes(self):
        self.assertEqual(self.assert_fast("4-" * 2_500_000), [])

    def test_single_digits_joined_by_spaces(self):
        self.assertEqual(self.assert_fast("5 " * 2_500_000), [])

    def test_single_digits_joined_by_commas(self):
        self.assertEqual(self.assert_fast("4," * 2_500_000), [])

    def test_four_digit_groups(self):
        self.assertEqual(self.assert_fast("4111 " * 1_000_000), [])

    def test_repeated_spaced_card(self):
        hits = self.assert_fast("4111 2222 3333 4444 " * 250_000)
        self.assertEqual(len(hits), 125_000)

    def test_one_long_digit_run(self):
        self.assertEqual(self.assert_fast("1" * 5_000_000), [])


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
