"""Tests for the pure classification and naming logic of the OneDrive migration.

    uv run --with pytest python -m pytest scripts/tests -q
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

# The script's filename is hyphenated, so it is loaded by path rather than name.
_spec = importlib.util.spec_from_file_location(
    "onedrive_to_vault", Path(__file__).resolve().parent.parent / "onedrive-to-vault.py"
)
otv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(otv)


# --- markdown_name ---------------------------------------------------------

def test_markdown_name_puts_type_after_a_space():
    assert otv.markdown_name("Terms of Service", "pdf") == "Terms of Service pdf.md"


def test_markdown_name_keeps_same_named_siblings_apart():
    stem = "Company - General Terms and Conditions of Service"
    assert otv.markdown_name(stem, "pdf") != otv.markdown_name(stem, "docx")


def test_markdown_name_without_extension():
    assert otv.markdown_name("Statement of Work", "") == "Statement of Work.md"


def test_markdown_name_preserves_dots_in_the_stem():
    assert otv.markdown_name("v1.2 Report", "docx") == "v1.2 Report docx.md"


# --- split_name ------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("report.PDF", ("report", "pdf")),
    ("archive.tar.gz", ("archive.tar", "gz")),
    ("Statement of Work Template", ("Statement of Work Template", "")),
    (".gitignore", (".gitignore", "")),
])
def test_split_name(name, expected):
    assert otv.split_name(name) == expected


# --- is_noise --------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Thumbs.db",
    "desktop.ini",
    "~$Budget.xlsx",
    ".849C9593-D756-4E56-8D6E-42412F2A707B",
])
def test_is_noise_true(name):
    assert otv.is_noise(name) is True


@pytest.mark.parametrize("name", ["Budget.xlsx", "notes.md", "DepositSlip.pdf"])
def test_is_noise_false(name):
    assert otv.is_noise(name) is False


# --- classify --------------------------------------------------------------

def test_classify_document(tmp_path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 stub")
    assert otv.classify(target) == ("convert", "pdf")


def test_classify_legacy_doc_is_copied_not_converted(tmp_path):
    """markitdown registers no converter for .doc, so it must travel verbatim."""
    target = tmp_path / "memo.doc"
    target.write_bytes(b"\xd0\xcf\x11\xe0stub")
    assert otv.classify(target) == ("copy", "doc")


@pytest.mark.parametrize("name", ["photo.jpg", "clip.mp4", "model.yxmd", "query.sql"])
def test_classify_non_documents_are_copied(tmp_path, name):
    target = tmp_path / name
    target.write_bytes(b"stub")
    action, _ = otv.classify(target)
    assert action == "copy"


def test_classify_zip_is_copied_intact(tmp_path):
    target = tmp_path / "bundle.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("inner.txt", "hello")
    assert otv.classify(target) == ("copy", "zip")


def test_classify_noise_is_skipped(tmp_path):
    target = tmp_path / "Thumbs.db"
    target.write_bytes(b"stub")
    assert otv.classify(target) == ("skip", "")


# --- extensionless sniffing ------------------------------------------------

def test_sniff_extensionless_pdf(tmp_path):
    target = tmp_path / "Some Contract"
    target.write_bytes(b"%PDF-1.7\n stub")
    assert otv.classify(target) == ("convert", "pdf")


def _write_ooxml(path: Path, part: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(part, "stub")


@pytest.mark.parametrize("part,expected", [
    ("word/document.xml", "docx"),
    ("xl/workbook.xml", "xlsx"),
    ("ppt/presentation.xml", "pptx"),
])
def test_sniff_extensionless_ooxml(tmp_path, part, expected):
    target = tmp_path / "Statement of Work Template"
    _write_ooxml(target, part)
    assert otv.classify(target) == ("convert", expected)


def test_sniff_unrecognised_extensionless_falls_back_to_copy(tmp_path):
    target = tmp_path / "mystery"
    target.write_bytes(b"\x00\x01\x02\x03random")
    assert otv.classify(target) == ("copy", "")


def test_sniff_legacy_ole2_extensionless_falls_back_to_copy(tmp_path):
    target = tmp_path / "old memo"
    target.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
    assert otv.classify(target) == ("copy", "")


# --- manifest resume -------------------------------------------------------

def test_load_done_collects_finished_and_ignores_failures(tmp_path):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text(
        '{"src": "a.pdf", "status": "ok"}\n'
        '{"src": "b.doc", "status": "fallback"}\n'
        '{"src": "c.db", "status": "skipped"}\n'
        '{"src": "d.pdf", "status": "failed"}\n',
        encoding="utf-8",
    )
    assert otv.load_done(manifest) == {"a.pdf", "b.doc", "c.db"}


def test_load_done_survives_a_torn_final_line(tmp_path):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text(
        '{"src": "a.pdf", "status": "ok"}\n{"src": "b.pdf", "sta',
        encoding="utf-8",
    )
    assert otv.load_done(manifest) == {"a.pdf"}


def test_load_done_lets_a_later_failure_reopen_a_file(tmp_path):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text(
        '{"src": "a.pdf", "status": "ok"}\n{"src": "a.pdf", "status": "failed"}\n',
        encoding="utf-8",
    )
    assert otv.load_done(manifest) == set()


def test_load_done_on_missing_manifest():
    assert otv.load_done(Path("no-such-manifest.jsonl")) == set()


# --- asset index must be portable ------------------------------------------

def test_index_path_is_relative_and_posix(tmp_path):
    """Index entries must resolve on any machine, not just the one that wrote them."""
    src = tmp_path / "Admin" / "Drivers" / "odbc.msi"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"stub")
    row = otv.index_row(src, Path("Admin/Drivers/odbc.msi"), "msi", "asset")
    assert row["path"] == "Admin/Drivers/odbc.msi"
    assert "\\" not in row["path"]


def test_index_row_carries_no_absolute_path(tmp_path):
    """No field may leak a local root - that is what makes the index portable."""
    src = tmp_path / "Sales" / "deck.pptx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"stub")
    row = otv.index_row(src, Path("Sales/deck.pptx"), "pptx", "asset")
    blob = json.dumps(row)
    assert "C:" not in blob
    assert str(tmp_path) not in blob
    assert "Users" not in blob


def test_index_row_records_size_and_kind(tmp_path):
    src = tmp_path / "big.zip"
    src.write_bytes(b"x" * 1234)
    row = otv.index_row(src, Path("Photos/big.zip"), "zip", "asset")
    assert row["bytes"] == 1234
    assert row["kind"] == "asset"
    assert row["modified"].endswith("+00:00")


def test_index_row_survives_a_missing_file(tmp_path):
    row = otv.index_row(tmp_path / "gone.bin", Path("a/gone.bin"), "bin", "asset")
    assert row["path"] == "a/gone.bin"
    assert row["bytes"] is None
