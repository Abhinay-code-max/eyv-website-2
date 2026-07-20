"""
Sentry init for the FastAPI backend.

No-ops entirely (init() is never called) when SENTRY_DSN is unset, so local
dev and the test suite - which run without a DSN - are unaffected; every
sentry_sdk.capture_* call elsewhere in the codebase is always safe to call
regardless, since the SDK is a no-op client until init() runs.

Scrubbing: this project already redacts secrets from *logging* output (see
log_redaction.py - SerpApi's api_key travels as a URL query param with no
header alternative). Sentry's own instrumentation is a separate pipeline
that does NOT go through Python's logging module - the Starlette/FastAPI
integration reads request headers/cookies directly off the ASGI scope, and
httpx breadcrumbs read the request URL directly off the httpx request object
- so log_redaction's filter never sees any of it. before_send/before_breadcrumb
below are this project's only chance to scrub that data before it leaves the
process. send_default_pii=False keeps Sentry from attaching cookies/PII by
default, but request headers (Cookie, Authorization, Stripe-Signature) and
breadcrumb URLs/query strings are still scrubbed explicitly here rather than
relying on that flag alone.
"""
import logging
import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from .log_redaction import redact_secrets
from .request_id_middleware import request_id_var

_SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "stripe-signature", "x-api-key"}


def _scrub_headers(headers):
    if not isinstance(headers, dict):
        return headers
    return {
        k: ("<redacted>" if k.lower() in _SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def _scrub_breadcrumb(breadcrumb, hint):
    if isinstance(breadcrumb.get("message"), str):
        breadcrumb["message"] = redact_secrets(breadcrumb["message"])
    data = breadcrumb.get("data")
    if isinstance(data, dict):
        for key in ("url", "query_string", "message"):
            if isinstance(data.get(key), str):
                data[key] = redact_secrets(data[key])
        if isinstance(data.get("headers"), dict):
            data["headers"] = _scrub_headers(data["headers"])
    return breadcrumb


def _scrub_event(event, hint):
    request = event.get("request")
    if isinstance(request, dict):
        # send_default_pii=False already keeps cookies out in current SDK
        # versions, but drop the key outright too rather than depend on that.
        request.pop("cookies", None)
        if isinstance(request.get("headers"), dict):
            request["headers"] = _scrub_headers(request["headers"])
        for key in ("query_string", "url"):
            if isinstance(request.get(key), str):
                request[key] = redact_secrets(request[key])

    for exc in (event.get("exception", {}) or {}).get("values", []) or []:
        if isinstance(exc.get("value"), str):
            exc["value"] = redact_secrets(exc["value"])

    breadcrumbs = (event.get("breadcrumbs") or {})
    if isinstance(breadcrumbs, dict):
        for crumb in breadcrumbs.get("values", []) or []:
            _scrub_breadcrumb(crumb, None)

    request_id = request_id_var.get()
    if request_id != "-":
        event.setdefault("tags", {})["request_id"] = request_id

    return event


def init_sentry(app_version: str) -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "development"),
        release=app_version,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            # event_level=None: don't let every logger.error(...) call in this
            # 2900+ line server.py auto-become a Sentry event - that would
            # capture far more than "unhandled exceptions + the 4 named
            # providers" (e.g. GridFS storage errors, OAuth callback errors)
            # with no tagging to tell them apart. Unhandled exceptions are
            # still captured via the Starlette/FastAPI integration regardless
            # of this setting; the 4 named providers are captured by explicit,
            # tagged capture_exception() calls at their actual failure sites.
            # level=INFO still turns logger.info/.warning/.error into
            # breadcrumbs, so they show up as context on whatever event does
            # get captured.
            LoggingIntegration(level=logging.INFO, event_level=None),
        ],
        before_send=_scrub_event,
        before_breadcrumb=_scrub_breadcrumb,
    )
