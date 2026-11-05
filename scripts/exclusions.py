"""The approved source-zone exclusions, as enforceable code.

Source of truth for the policy itself is strategy/directory-instructions.md,
"Hard-excluded source zones", approved 2026-09-08. This module exists so the
rule is applied by the import and the router rather than remembered.

Two severities, because the owner distinguished them on 2026-09-11:

  BLOCK  Hard-excluded source zones. Never imported, never quoted. A file under
         one of these paths cannot reach the vault by any route.

  WARN   Filename patterns (confidential, pricing, invoice, bank, visa,
         criminal). The written rule excludes these outright. The owner decided
         on 2026-09-11 to keep them where they sit inside an approved zone,
         on the grounds that a signed client confidentiality agreement is a
         legitimate engagement record. They are reported, not removed.

Not enforced here, and flagged in the source document as unresolved: content
level exclusions inside approved zones (HubSpot prospect lists, per-person
billable rates, client tenant GUIDs). Those need the note body, not the path.
"""

from __future__ import annotations

import re

# Paths are matched against a library-relative, forward-slash path.
BLOCKED_ZONES = (
    "Admin/",                      # per-person HR, visa, MOJ and ASB checks, payroll
    "Consultant CVS/",             # personal CVs
    "Account Setup/",              # deposit slips, incorporation certificate, NDA
    "Support/Invoices",
    "Marketing/Email lists",
    "Marketing/Budgets",
    "Slack/",                      # unvetted message exports
)

WARN_PATTERNS = re.compile(
    r"confidential|pricing|\blead[s]?\b|invoice|\bbank\b|\bvisa\b|criminal"
    r"|ratecard|rate card",
    re.I,
)


def blocked(rel: str) -> str | None:
    """Return the zone that bars this path, or None.

    `rel` is relative to the shared library root, forward slashes.
    """
    normalised = rel.replace("\\", "/").lstrip("/")
    for zone in BLOCKED_ZONES:
        if normalised == zone.rstrip("/") or normalised.startswith(zone):
            return zone
    return None


def flagged(rel: str) -> str | None:
    """Return the matched sensitive term, or None. Advisory only."""
    match = WARN_PATTERNS.search(rel.replace("\\", "/"))
    return match.group(0) if match else None


def admissible(rel: str) -> bool:
    """True when the path may enter the vault at all."""
    return blocked(rel) is None
