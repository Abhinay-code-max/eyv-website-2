"""
Redacts secrets that travel as URL query parameters from log records before
they reach any handler (console, file, or otherwise), regardless of the log
level in effect.

Why this exists: SerpApi's own official client (serpapi-python's HTTPClient)
puts `api_key` in the request's query params - confirmed via SerpApi's docs
and client source, there is no header-based alternative. httpx logs the full
request URL (query string included) via logging.getLogger("httpx").info(...)
on every request/response (see httpx/_client.py) - so any INFO-level httpx
logging leaks the key in plaintext. httpcore's DEBUG-level connection tracing
does not currently leak it (httpcore.Request.__repr__ deliberately omits the
URL and headers), but its logger names are covered here too in case that
changes in a future version - see _LOGGERS_TO_REDACT below.

Ignav authenticates via the X-Api-Key request *header* rather than a query
param (see ignav_service.py's _headers()), and neither httpx nor httpcore
logs headers anywhere in the current versions pinned by this project
(confirmed by reading both packages' source), so there is nothing for Ignav
to redact today - it's covered by the same filter as a no-op safety net.

Implementation note: Python's logging only consults the *originating*
logger's filters during propagation - a filter added to a parent logger
(e.g. "httpcore") is never applied when a child logger like
"httpcore.http11" emits a record; only that child's own filters run, plus
each handler's filters along the propagation chain (see
logging.Logger.handle()/callHandlers() in cpython). So the filter below is
attached directly to every concrete logger name httpx/httpcore actually log
through, not just their top-level namespaces.
"""
import logging
import re

_SENSITIVE_QUERY_PARAMS = ("api_key", "apikey", "access_token", "token", "key")

_REDACT_PATTERN = re.compile(
    r'(?i)\b(' + '|'.join(_SENSITIVE_QUERY_PARAMS) + r')=([^&\s\'"]+)'
)

# Every logger name httpx/httpcore currently log request/connection info
# through (confirmed via their installed source in this project's venv).
_LOGGERS_TO_REDACT = (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


def redact_secrets(text: str) -> str:
    """Replace any `<sensitive-param>=<value>` query param with a redacted
    placeholder. Safe to call on text that contains no secret - it's a no-op."""
    return _REDACT_PATTERN.sub(r'\1=<redacted>', text)


class _SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            # Collapse to a plain string now that args have been consumed -
            # record.args would otherwise be re-applied to the (now
            # unrelated) redacted message by the formatter.
            record.msg = redacted
            record.args = ()
        return True


_installed = False


def install_secret_redaction() -> None:
    """Attach the redaction filter to every known httpx/httpcore logger.
    Idempotent - safe to call multiple times (e.g. across uvicorn --reload
    re-imports of server.py)."""
    global _installed
    if _installed:
        return
    f = _SecretRedactionFilter()
    for name in _LOGGERS_TO_REDACT:
        logging.getLogger(name).addFilter(f)
    _installed = True
