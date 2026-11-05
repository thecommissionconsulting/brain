"""Tests for the vault routing rules.

    uv run --with pytest python -m pytest scripts/tests -q
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "route_vault", Path(__file__).resolve().parent.parent / "route-vault.py"
)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def route(rel: str):
    """Return (bucket, destination-as-posix) for a raw-relative path."""
    decision = rv.plan_destination(Path(rel))
    if decision is None:
        return None
    bucket, dest = decision
    return bucket, dest.as_posix()


# --- personal material wins over every other rule ---------------------------

@pytest.mark.parametrize("rel", [
    "Admin/ASB Checks/2023/Arathi Rajeev/Photo ID-Passport pdf.md",
    "Admin/Employees/Archived/naveen@example.nz/contract docx.md",
    "Admin/Accredited Employee Visa/Constance Termoz/Application Fee pdf.md",
])
def test_personal_material_routes_private(rel):
    bucket, _ = route(rel)
    assert bucket == "private"


def test_a_passport_image_never_reaches_assets():
    """Non-markdown under a private rule must stay private, not fall to assets."""
    bucket, dest = route("Admin/ASB Checks/2024/Michael ASB check/passport.jpg")
    assert bucket == "private"
    assert dest.startswith(".confluence-private/asb-checks/")
    assert dest.endswith("passport.jpg")


def test_private_keeps_original_filenames():
    _, dest = route("Admin/ASB Checks/2023/Arathi Rajeev/Photo ID-Passport pdf.md")
    assert dest == ".confluence-private/asb-checks/2023/Arathi Rajeev/Photo ID-Passport pdf.md"


# --- wiki routing and naming ------------------------------------------------

def test_markdown_routes_to_mapped_wiki_folder():
    assert route("Admin/Asset Registry/Card Audit xlsx.md") == (
        "wiki", "wiki/company/ops/asset-registry/card-audit.md"
    )


def test_wiki_names_are_kebab_cased_and_lose_the_type_marker():
    _, dest = route("Admin/Admin Set up Instructions/1. Google Workspace Set up Instructions pdf.md")
    assert dest == (
        "wiki/company/ops/instructions-user-guides/"
        "1-google-workspace-set-up-instructions.md"
    )


def test_wiki_subdirectories_are_kebab_cased_too():
    _, dest = route("Admin/Cathedral House/Contracts/18052017080352-0001 pdf.md")
    assert dest == "wiki/company/ops/contracts/18052017080352-0001.md"


def test_longest_prefix_wins():
    """'Admin Set up Instructions' must not be shadowed by a broader 'Admin' rule."""
    bucket, dest = route("Admin/Admin Set up Instructions/x pdf.md")
    assert dest.startswith("wiki/company/ops/instructions-user-guides/")


def test_unmapped_markdown_stays_in_raw():
    assert route("Sales/Some Deck pptx.md") is None


# --- scripts vs vendored packages ------------------------------------------

def test_vendored_r_library_goes_to_assets_not_scripts():
    bucket, dest = route(
        "Admin/Employees/x/R/win-library/4.4/Rcpp/include/Rcpp.h"
    )
    # Under Employees this is private; check the vendoring rule in isolation too.
    assert bucket == "private"


def test_vendored_code_outside_a_private_folder_goes_to_assets():
    bucket, dest = route("Analytics Forum/R/win-library/4.4/Rcpp/include/Rcpp.h")
    assert bucket == "assets"
    assert dest.startswith("assets/")


def test_genuine_code_goes_to_scripts():
    bucket, dest = route("Data Sets/refresh_customers.sql")
    assert bucket == "scripts"
    assert dest == "scripts/Data Sets/refresh_customers.sql"


@pytest.mark.parametrize("rel", [
    "Analytics Forum/node_modules/left-pad/index.js",
    "Analytics Forum/.venv/Lib/site-packages/thing.py",
])
def test_dependency_trees_are_not_scripts(rel):
    bucket, _ = route(rel)
    assert bucket == "assets"


# --- assets catch-all -------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "Admin/Drivers/snowflake64_odbc-3.10.0.msi",
    "Admin/David St Georgo Photographs 2023-2024/Office.zip",
    "Admin/Computers/photo.png",
])
def test_leftovers_mirror_into_assets(rel):
    bucket, dest = route(rel)
    assert bucket == "assets"
    assert dest == "assets/" + rel


def test_nothing_is_dropped():
    """Every non-markdown file lands somewhere; none return None."""
    for rel in ["a/b.msi", "a/b.zip", "a/b.bak", "a/b.lnk", "a/b.rdb"]:
        assert route(rel) is not None


# --- kebab helper -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Card Audit", "card-audit"),
    ("Health & Safety", "health-and-safety"),
    ("1. Google Workspace", "1-google-workspace"),
    ("Photo ID-Passport ", "photo-id-passport"),
    ("Company  --  Terms", "company-terms"),
])
def test_kebab(raw, expected):
    assert rv.kebab(raw) == expected


@pytest.mark.parametrize("stem,expected", [
    ("Card Audit xlsx", ("Card Audit", "xlsx")),
    ("Resident Visa-Right to work pdf pdf", ("Resident Visa-Right to work pdf", "pdf")),
    ("Quarterly Report", ("Quarterly Report", "")),
])
def test_strip_type_marker(stem, expected):
    assert rv.strip_type_marker(stem) == expected


def test_wiki_filename_can_keep_the_type_for_collisions():
    assert rv.wiki_filename("Terms docx.md", keep_type=True) == "terms-docx.md"
    assert rv.wiki_filename("Terms pdf.md", keep_type=True) == "terms-pdf.md"
