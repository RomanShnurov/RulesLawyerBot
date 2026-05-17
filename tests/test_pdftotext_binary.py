"""The PDF text cache must use the configured (poppler) pdftotext binary,
and a non-poppler binary must warn loudly instead of silently degrading
every answer.

poppler and the legacy xpdf-4.00 build extract the SAME PDF into
materially different text; the whole pipeline (cache, ugrep, the
document_is_unreadable guard) is calibrated for poppler, so the active
extractor must be both pinnable and self-verifying.
"""
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter

from src.rules_lawyer_bot.agent.tools import (
    _get_pdf_text_cache,
    _verify_poppler_pdftotext,
)

_POPPLER_BANNER = (
    "pdftotext version 24.02.0\n"
    "Copyright 2005-2024 The Poppler Developers - "
    "http://poppler.freedesktop.org\n"
)
_XPDF_BANNER = (
    "pdftotext version 4.00\nCopyright 1996-2017 Glyph & Cog, LLC\n"
)


def _make_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)


def test_cache_invokes_configured_pdftotext_path(mock_settings, monkeypatch):
    """_get_pdf_text_cache must call settings.pdftotext_path, not a
    hard-coded bare 'pdftotext' resolved from PATH."""
    monkeypatch.setattr(mock_settings, "pdftotext_path", "/opt/poppler/pdftotext")

    pdf_path = Path(mock_settings.pdf_storage_path) / "x.pdf"
    _make_pdf(pdf_path)

    with patch(
        "src.rules_lawyer_bot.agent.tools._verify_poppler_pdftotext"
    ), patch(
        "src.rules_lawyer_bot.agent.tools.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        _get_pdf_text_cache(pdf_path)

    argv = mock_run.call_args[0][0]
    assert argv[0] == "/opt/poppler/pdftotext"
    assert argv[1] == "-layout"


def test_poppler_binary_is_accepted_without_warning(caplog):
    _verify_poppler_pdftotext.cache_clear()
    with patch(
        "src.rules_lawyer_bot.agent.tools.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr=_POPPLER_BANNER)
        with caplog.at_level(logging.WARNING):
            assert _verify_poppler_pdftotext("pdftotext") is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_xpdf_binary_is_rejected_with_warning(caplog):
    """The legacy xpdf build (the silent-divergence root cause) must
    return False and emit a WARNING naming the binary."""
    _verify_poppler_pdftotext.cache_clear()
    with patch(
        "src.rules_lawyer_bot.agent.tools.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr=_XPDF_BANNER)
        with caplog.at_level(logging.WARNING):
            assert _verify_poppler_pdftotext("pdftotext") is False
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings
    assert "NOT poppler" in warnings[0].getMessage()


def test_probe_failure_is_non_fatal(caplog):
    """A missing/broken pdftotext must warn but never raise — extraction
    still proceeds best-effort."""
    _verify_poppler_pdftotext.cache_clear()
    with patch(
        "src.rules_lawyer_bot.agent.tools.subprocess.run",
        side_effect=OSError("not found"),
    ):
        with caplog.at_level(logging.WARNING):
            assert _verify_poppler_pdftotext("missing-binary") is False
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_probe_result_is_cached_per_binary():
    """lru_cache: the binary is probed once, not on every cache miss."""
    _verify_poppler_pdftotext.cache_clear()
    with patch(
        "src.rules_lawyer_bot.agent.tools.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr=_POPPLER_BANNER)
        _verify_poppler_pdftotext("pdftotext")
        _verify_poppler_pdftotext("pdftotext")
    assert mock_run.call_count == 1
