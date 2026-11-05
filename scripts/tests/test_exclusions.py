"""Tests for the approved source-zone exclusions.

These encode the policy in strategy/directory-instructions.md. A failure here
means the vault would ingest something the owner approved excluding.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "exclusions", Path(__file__).resolve().parent.parent / "exclusions.py"
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)


@pytest.mark.parametrize("rel", [
    "Admin/ASB Checks/2023/Arathi Rajeev/Photo ID-Passport.pdf",
    "Admin/Employees/naveen@example.nz/contract.docx",
    "Admin/Accredited Employee Visa/Constance Termoz/Application Fee.pdf",
    "Admin/Policies/Company Limited Company Handbook.docx",
    "Consultant CVS/Consultant CVS/someone.docx",
    "Account Setup/Company Certificate of Incorporation.pdf",
    "Account Setup/DepositSlip.pdf",
    "Support/Invoices/2024/inv-001.pdf",
    "Marketing/Email lists/newsletter.xlsx",
    "Marketing/Budgets/fy26.xlsx",
    "Slack/Slack export Apr 27 2017 - Aug 19 2024/channel.json",
])
def test_blocked_zones_are_barred(rel):
    assert ex.blocked(rel) is not None
    assert ex.admissible(rel) is False


@pytest.mark.parametrize("rel", [
    "Customers/Fonterra/SOW/20250716 - Fonterra Consultancy SOW.pdf",
    "Services/2025 Graduate Programme/Case Study.pptx",
    "Marketing/Advertising/2022/overview.pptx",
    "Partners/Tableau/Starters/template.xlsx",
    "Customers/AA Life/Contracts & Agreements/agreement.docx",
])
def test_approved_zones_pass(rel):
    assert ex.blocked(rel) is None
    assert ex.admissible(rel) is True


def test_marketing_subfolders_are_surgical():
    """Only Email lists and Budgets are barred, not all of Marketing."""
    assert ex.blocked("Marketing/Budgets/fy26.xlsx") is not None
    assert ex.blocked("Marketing/Advertising/2022/deck.pptx") is None


def test_a_prefix_collision_does_not_over_block():
    """'Administration' is not 'Admin/'."""
    assert ex.blocked("Administration Notes/guide.pdf") is None


def test_backslash_paths_are_normalised():
    assert ex.blocked("Admin\\ASB Checks\\x.pdf") is not None


@pytest.mark.parametrize("rel,term", [
    ("Customers/AA Life/CONFIDENTIALITY AGREEMENT.docx", "CONFIDENTIALITY"),
    ("Customers/Westpac/Company 2026 - Ratecard.xlsx", "Ratecard"),
    ("Customers/X/2024 invoice.pdf", "invoice"),
])
def test_patterns_are_flagged(rel, term):
    assert ex.flagged(rel) is not None


def test_flagged_files_remain_admissible():
    """Owner decision 2026-09-11: pattern matches are reported, not removed."""
    rel = "Customers/AA Life/Contracts & Agreements/CONFIDENTIALITY AGREEMENT.docx"
    assert ex.flagged(rel) is not None
    assert ex.admissible(rel) is True


def test_ordinary_client_documents_are_not_flagged():
    assert ex.flagged("Customers/Fonterra/SOW/Consultancy SOW.pdf") is None
