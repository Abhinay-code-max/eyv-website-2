"""
Regression tests for the SerpApi-key-in-logs leak.

Root cause: SerpApi's api_key travels as a URL query param (confirmed - no
header alternative exists, see services/log_redaction.py's docstring), and
httpx logs full request URLs via logging.getLogger("httpx").info(...) on
every request. These tests simulate httpx's/httpcore's exact internal log
call shapes (rather than making real network calls) so they're fast,
network-free, and never need a real secret to prove the redaction works.
"""
import logging
import os
import sys

import pytest
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
load_dotenv(os.path.join(BACKEND_DIR, '.env'))  # so the live test below has SERPAPI_KEY, matching server.py's own startup

from services.log_redaction import redact_secrets, install_secret_redaction  # noqa: E402


# ---------- redact_secrets(): pure function ----------

def test_redacts_serpapi_style_api_key():
    text = (
        'HTTP Request: GET https://serpapi.com/search?engine=google_hotels'
        '&q=hotels+in+Goa&api_key=NOT_A_REAL_KEY_fixture_0000 "HTTP/1.1 200 OK"'
    )
    redacted = redact_secrets(text)
    assert 'NOT_A_REAL_KEY_fixture_0000' not in redacted
    assert 'api_key=<redacted>' in redacted


def test_redacts_key_regardless_of_position_in_query_string():
    text = 'https://serpapi.com/search?api_key=SECRET123&engine=google_hotels'
    redacted = redact_secrets(text)
    assert 'SECRET123' not in redacted
    assert 'api_key=<redacted>' in redacted


def test_redacts_case_insensitively():
    text = 'https://example.com/x?API_KEY=SECRET123'
    redacted = redact_secrets(text)
    assert 'SECRET123' not in redacted


def test_ignav_style_url_has_nothing_to_redact():
    # Ignav's key travels as an X-Api-Key header, never in the URL - this
    # must be a no-op, not an accidental corruption of an unrelated URL.
    text = 'HTTP Request: POST https://ignav.com/api/fares/one-way "HTTP/1.1 200 OK"'
    assert redact_secrets(text) == text


def test_non_matching_text_is_unchanged():
    text = 'Application startup complete.'
    assert redact_secrets(text) == text


def test_multiple_sensitive_params_all_redacted():
    text = 'https://example.com/x?token=AAA&api_key=BBB&q=hotels'
    redacted = redact_secrets(text)
    assert 'AAA' not in redacted
    assert 'BBB' not in redacted


# ---------- Installed as a logging.Filter: simulates real httpx/httpcore calls ----------

@pytest.fixture(autouse=True)
def _ensure_filter_installed():
    install_secret_redaction()


def test_httpx_style_info_log_does_not_leak_key(caplog):
    """Reproduces httpx/_client.py's exact call shape:
    logger.info('HTTP Request: %s %s "%s %d %s"', method, url, ...)."""
    fake_key = "LIVE_LOOKING_SECRET_7f3a9c"
    url = f"https://serpapi.com/search?engine=google_hotels&q=hotels&api_key={fake_key}&currency=INR"
    httpx_logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        httpx_logger.info('HTTP Request: %s %s "%s %d %s"', "GET", url, "HTTP/1.1", 200, "OK")
    assert fake_key not in caplog.text
    assert "<redacted>" in caplog.text


def test_httpcore_debug_style_log_does_not_leak_key(caplog):
    """Defense-in-depth: even though httpcore's current Request.__repr__
    doesn't include the URL, confirm the filter would catch it on any
    logger httpcore might emit a key-bearing message through."""
    fake_key = "LIVE_LOOKING_SECRET_9d1e2b"
    core_logger = logging.getLogger("httpcore.http11")
    with caplog.at_level(logging.DEBUG, logger="httpcore.http11"):
        core_logger.debug(f"send_request_headers.started request=<url with api_key={fake_key}>")
    assert fake_key not in caplog.text
    assert "<redacted>" in caplog.text


def test_install_is_idempotent_no_duplicate_redaction():
    """Calling install twice must not double-add the filter (which would
    otherwise be harmless here since redaction is idempotent, but a
    duplicate filter is still a bug worth catching)."""
    from services.log_redaction import _LOGGERS_TO_REDACT
    install_secret_redaction()
    install_secret_redaction()
    for name in _LOGGERS_TO_REDACT:
        filters = logging.getLogger(name).filters
        assert len(filters) == 1, f"{name} has {len(filters)} redaction filters, expected 1"


# ---------- Live: exercises the real serpapi_hotels_service integration ----------

@pytest.mark.timeout(30)
def test_live_serpapi_request_does_not_leak_real_key_in_logs(caplog):
    """End-to-end: makes one real SerpApi call through the actual service
    module and confirms the real key (read from the environment, never
    printed by this test) is absent from everything captured at INFO."""
    import asyncio
    from services import serpapi_hotels_service

    real_key = os.environ.get("SERPAPI_KEY")
    if not real_key:
        pytest.skip("SERPAPI_KEY not configured in this environment")

    with caplog.at_level(logging.INFO):
        asyncio.run(serpapi_hotels_service.search_hotels("Goa", "2026-09-01", "2026-09-04", travelers=2))

    assert real_key not in caplog.text
