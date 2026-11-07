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
import bisect
import itertools
import operator
import re

SECRET, FINANCIAL, IDENTIFIER, CONTACT = "secret", "financial", "identifier", "contact"
ALL = frozenset({SECRET, FINANCIAL, IDENTIFIER, CONTACT})
OUTPUT = frozenset({SECRET, FINANCIAL})

# The TLD must be alphabetic. `[\w.]{2,}` matched `foo@1.2.3`, so every npm or pip
# version pin read as an email address.
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")

# Runs of digits and single separators, for the card search. The lookahead skips
# runs too short to hold a card, in C. A run that ends against a word character
# is cut back to its last separator, which is what `\d+(?:[ -]\d+)*(?!\w)` does
# by backtracking; _card_runs does that cut, because the possessive `*+` that
# makes the regex about 15 times faster on long runs cannot backtrack. Python
# 3.10 has no possessive repeats, so it gets the backtracking form.
try:
    _CARD_RUN = re.compile(r"(?<!\w)(?=[\d -]{13})\d+(?:[ -]\d+)*+")
except re.error:
    _CARD_RUN = re.compile(r"(?<!\w)(?=[\d -]{13})\d+(?:[ -]\d+)*(?!\w)")
_WORD = re.compile(r"\w")

PATTERNS = (
    # The body is matched too: the header alone leaves the key itself in the
    # output. Up to the matching END line when there is one; for a truncated key,
    # the run of base64 that follows. The body class has no "-", so the fallback
    # cannot run on through a later header. The END search is bounded to 10,000
    # characters and tempered so it stops at the next "-----BEGIN ": without the
    # temper every header in 5 MB of headers searched 10,000 characters, about
    # 28 s, and a hook timeout passes the output through unredacted.
    ("private key", SECRET, re.compile(
        r"-----BEGIN ([A-Z ]*)PRIVATE KEY-----"
        r"(?:(?:[^-]|-(?!----BEGIN )){0,10000}?-----END \1PRIVATE KEY-----"
        r"|[A-Za-z0-9+/=\s:,]*)")),
    ("JWT", SECRET, re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}")),
    ("API token", SECRET, re.compile(
        r"\b(?:sk-ant-[\w-]{20,}|sk-[A-Za-z0-9]{32,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{36}"
        r"|github_pat_\w{22,}|AKIA[0-9A-Z]{16}|xox[baprs]-[\w-]{10,})")),
    # The value must carry a digit. Without that test the pattern fires on
    # ordinary code: `token = payload.get("user_input")` matched a plain length rule.
    # Uses (?<![A-Za-z0-9]) before and (?![A-Za-z0-9]) after the keyword so underscore and hyphen prefixes pass
    # (OPENAI_API_KEY=, client_secret=, etc.) and [\"']? after the keyword to allow
    # quoted keys ("password":, 'api_key'=, etc.). A key-name tail that starts
    # with "_" or "-" may follow the keyword (AWS_SECRET_ACCESS_KEY=, SECRET_KEY=),
    # but not a letter straight after it, so `tokens=` still passes.
    ("secret assignment", SECRET, re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:api[_-]?key|secret|passwd|password|token)"
        r"(?:[_-][A-Za-z0-9_-]{0,40})?(?![A-Za-z0-9])[\"']?\s*[:=]\s*[\"']?"
        r"(?P<value>(?=[^\s\"']*\d)[A-Za-z0-9_\-+/=!@#$%^&*.]{10,})")),
    ("email address", CONTACT, EMAIL),
    ("NZ bank account", FINANCIAL, re.compile(r"\b\d{2}-\d{4}-\d{6,7}-\d{2,3}\b")),
    ("card number", FINANCIAL, _CARD_RUN),  # digit runs; card_spans finds the cards in them
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


# The card search runs over every run of digits in the text at once, as byte
# masks held in big integers, so its cost is a few C-level passes over the digits
# whatever the text looks like. A per-group Python loop took 5 to 12 seconds on
# 5 MB of input such as "4-4-4-..." and the hook times out at 10, which passes
# the output through unredacted.
#
# ds is the digits of every run, joined by "x" so no card can span two runs.
# A digit outside ASCII becomes "y": it can start or end no card window (the old
# per-group check ran Luhn over its UTF-8 bytes, which is not a card checksum).
# Mask bytes are 0 or 1, one per position of ds; big-endian, so `x << 8 * j`
# moves the byte for position k + j to position k.
_CARD_LENGTHS = (13, 15, 16, 19)  # ascending: each prefix's lengths are tried in this order
_NOT_ASCII = re.compile(r"[^\x00-\x7f]")
_DOUBLE = bytes.maketrans(b"0123456789", b"0246813579")
_MARK = bytes.maketrans(b"0123456789y-", b"00000000000 ")  # digits to "0", separators to " "
_VALUE = bytes.maketrans(b"0123456789", bytes(range(10)))  # other bytes are masked out later
_DOUBLED = bytes.maketrans(b"0123456789", bytes([0, 2, 4, 6, 8, 1, 3, 5, 7, 9]))
_IS_ZERO = bytes([1] + [0] * 255)
_VECTOR_MIN = 64  # below this many candidate starts (plus 1 per 32 digits), Luhn each one directly


def _in(ds, chars):
    """Mask of the positions of ds holding one of `chars`."""
    table = bytes(1 if chr(i) in chars else 0 for i in range(256))
    return int.from_bytes(ds.translate(table), "big")


def _luhn_bytes(b):
    """Luhn over a bytes string of ASCII digits."""
    odd, even = b[-1::-2], b[-2::-2].translate(_DOUBLE)
    return (sum(odd) + sum(even) - 48 * len(b)) % 10 == 0


def _prefix_sums_mod10(values):
    """Bytes P with P[k] = sum(values[:k]) % 10, one longer than values."""
    return bytes(map(operator.mod, itertools.accumulate(values, initial=0), itertools.repeat(10)))


def _luhn_masks(ds, size):
    """{n: mask of the starts k where ds[k:k + n] passes Luhn}, garbage where it is not all digits."""
    value, doubled = ds.translate(_VALUE), ds.translate(_DOUBLED)
    even_raw, odd_raw = bytearray(value), bytearray(doubled)
    even_raw[1::2] = doubled[1::2]  # undoubled at even positions
    odd_raw[1::2] = value[1::2]  # undoubled at odd positions
    sums = (_prefix_sums_mod10(even_raw), _prefix_sums_mod10(odd_raw))
    masks = {}
    for n in _CARD_LENGTHS:
        # A window passes when the prefix sums at its two ends are equal mod 10.
        eq = []
        for p in sums:
            diff = int.from_bytes(p[:size], "big") ^ int.from_bytes(p[n:] + bytes(n - 1), "big")
            eq.append(diff.to_bytes(size, "big").translate(_IS_ZERO))
        # The last digit k + n - 1 is undoubled; use the sums for its parity.
        mask = bytearray(eq[1])
        mask[(n + 1) % 2::2] = eq[0][(n + 1) % 2::2]
        masks[n] = int.from_bytes(mask, "big")
    return masks


def _card_digit_spans(ds, starts):
    """[(k, n)]: card windows ds[k:k + n], found greedily left to right.

    `starts` marks with b"1" the positions of ds where a digit group starts. Only
    those are tried, only with the lengths their card prefix allows, shortest
    first, and the search resumes after each card found.
    """
    size = len(ds)
    full = (1 << 8 * size) - 1

    def sh(mask, j):
        return (mask << 8 * j) & full

    d = {c: _in(ds, c) for c in "01234567"}
    is_digit = _in(ds, "0123456789")
    clean = {1: is_digit}  # clean[w][k]: ds[k:k + w] is all ASCII digits
    for w in (2, 4, 8, 16):
        clean[w] = clean[w // 2] & sh(clean[w // 2], w // 2)
    window = {13: clean[8] & sh(clean[8], 5), 15: clean[8] & sh(clean[8], 7),
              16: clean[16], 19: clean[16] & sh(clean[16], 3)}
    discover = d["6"] & (sh(d["5"], 1) | (sh(d["0"], 1) & sh(d["1"], 2) & sh(d["1"], 3)))
    two_range = d["2"] & (  # 2221 to 2720
        (sh(d["2"], 1) & sh(d["2"], 2) & sh(_in(ds, "123456789"), 3))
        | (sh(d["2"], 1) & sh(_in(ds, "3456789"), 2))
        | sh(_in(ds, "3456"), 1)
        | (sh(d["7"], 1) & sh(_in(ds, "01"), 2))
        | (sh(d["7"], 1) & sh(d["2"], 2) & sh(d["0"], 3)))
    prefix = {13: d["4"],
              15: d["3"] & sh(_in(ds, "47"), 1),
              16: d["4"] | (d["5"] & sh(_in(ds, "12345"), 1)) | two_range | discover,
              19: d["4"] | discover}
    group = int.from_bytes(starts.translate(bytes.maketrans(b"01x", bytes([0, 1, 0]))), "big")
    cand = {n: group & prefix[n] & window[n] for n in _CARD_LENGTHS}
    union = 0
    for n in _CARD_LENGTHS:
        union |= cand[n]
    if not union:
        return []
    union_b = union.to_bytes(size, "big")
    direct = union_b.count(1) < _VECTOR_MIN + size // 32
    if not direct:  # many candidates: Luhn for every window at once
        luhn_ok = _luhn_masks(ds, size)
        cand = {n: cand[n] & luhn_ok[n] for n in _CARD_LENGTHS}
        union = 0
        for n in _CARD_LENGTHS:
            union |= cand[n]
        union_b = union.to_bytes(size, "big")
    cand_b = [(n, cand[n].to_bytes(size, "big")) for n in _CARD_LENGTHS]
    found, k = [], union_b.find(1)
    while k >= 0:
        for n, mask in cand_b:
            if mask[k] and (not direct or _luhn_bytes(ds[k:k + n])):
                found.append((k, n))
                k = union_b.find(1, k + n)
                break
        else:
            k = union_b.find(1, k + 1)
    return found


def _card_runs(text, pattern):
    """[(start, end)] of the runs `pattern` finds, each cut back as `(?!\\w)` would."""
    runs, size = [], len(text)
    for m in pattern.finditer(text):
        start, end = m.span()
        if end < size and _WORD.match(text, end):
            end = max(text.rfind(" ", start, end), text.rfind("-", start, end))
            if end < 0:
                continue
        runs.append((start, end))
    return runs


def card_spans(text, runs):
    """Plausible card spans inside the runs of digits and separators at `runs`.

    A run such as `2026-10-07 4111 1111 1111 1111` fails plausible_card as a
    whole, so every digit-group start with a real card prefix is tried, with the
    lengths that prefix allows, and only the card digits are reported.
    """
    if not runs:
        return []
    joined = "x".join(text[s:e] for s, e in runs)
    if not joined.isascii():
        joined = _NOT_ASCII.sub("y", joined)
    joined = joined.encode("ascii")
    ds = joined.replace(b" ", b"").replace(b"-", b"")
    # "1" where a digit group starts: after a separator, or first in its run
    starts = (b" " + joined.translate(_MARK)).replace(b" 0", b"1").replace(b"x0", b"x1")
    big_start, pos = [], 0  # offset in `joined` where each run starts
    for s, e in runs:
        big_start.append(pos)
        pos += e - s + 1

    ones = xs = upto = 0  # group starts and run joins in ds[:upto]

    def text_pos(i):  # text offset of digit ds[i]; called with i ascending
        nonlocal ones, xs, upto
        ones += starts.count(b"1", upto, i + 1)
        xs += ds.count(b"x", upto, i + 1)
        upto = i + 1
        joined_pos = i + ones - xs - 1  # one separator before each group but a run's first
        return runs[xs][0] + joined_pos - big_start[xs]

    spans = []
    for k, n in _card_digit_spans(ds, starts):
        start = text_pos(k)
        spans.append((start, text_pos(k + n - 1) + 1))
    return spans


def scan(text, categories=ALL):
    """[(label, start, end)] for every match in `categories`, non-overlapping, in text order."""
    hits, starts, ends = [], [], []  # starts/ends: claimed spans, sorted, disjoint

    def claim(label, start, end):
        i = bisect.bisect_left(starts, start)
        if (i and ends[i - 1] > start) or (i < len(starts) and starts[i] < end):
            return
        starts.insert(i, start)
        ends.insert(i, end)
        hits.append((label, start, end))

    for label, category, pattern in PATTERNS:
        if category not in categories:
            continue
        if label == "card number":
            for start, end in card_spans(text, _card_runs(text, pattern)):
                claim(label, start, end)
            continue
        for m in pattern.finditer(text):
            start, end = m.span("value") if "value" in pattern.groupindex else m.span()
            claim(label, start, end)
    return sorted(hits, key=lambda h: h[1])
