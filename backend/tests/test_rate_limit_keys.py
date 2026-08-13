"""
Unit tests for rate_limit_keys.py's key_funcs, plus an integration test
proving the auth-gate limiters (internal_tickets_api.py's/
internal_analytics_api.py's/internal_jarvis_api.py's AUTH_GATE_RATE_LIMIT)
can't be bypassed by varying the one input a pre-auth caller fully
controls: the bearer token itself.

get_trusted_client_ip's X-Real-IP trust is NOT something these tests (or
any test running against server.app in-process) can verify end to end -
that trust is only safe because Railway's edge was manually confirmed (a
live spoofing test against the actual deployed proxy: sent
X-Real-IP: 6.6.6.6, observed the app receive the real caller's IP instead)
to overwrite this header before this app ever sees it. No test running
locally/in CI has a Railway edge in front of it, so
test_trusted_client_ip_prefers_x_real_ip_header below documents/pins that
the CODE trusts the header - it cannot and does not prove that trust is
safe. If this app is ever redeployed off Railway, or Railway's proxying
changes, that manual verification (not this file) is what must be redone
before get_trusted_client_ip can be trusted again - see its own docstring
in rate_limit_keys.py.
"""
import os
import sys
import uuid

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from rate_limit_keys import get_bearer_token_key, get_trusted_client_ip

from conftest import client  # noqa: E402,F401  (fixture import)


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Minimal duck-typed stand-in - get_trusted_client_ip/get_bearer_token_key
    only ever touch .headers.get(...) and .client.host, so a real
    starlette.requests.Request (which needs a full ASGI scope) is more
    machinery than these unit tests need."""

    def __init__(self, headers=None, client_host="203.0.113.1"):
        self.headers = headers or {}
        self.client = _FakeClient(client_host) if client_host is not None else None


# ═══════════════ get_trusted_client_ip ═══════════════

def test_trusted_client_ip_prefers_x_real_ip_header():
    """Pins the current trust decision: X-Real-IP wins over
    request.client.host whenever present. This is a documentation/
    regression pin, NOT proof the header is safe to trust - see this
    file's module docstring."""
    req = _FakeRequest(headers={"X-Real-IP": "198.51.100.7"}, client_host="10.0.0.5")
    assert get_trusted_client_ip(req) == "198.51.100.7"


def test_trusted_client_ip_falls_back_to_client_host_without_header():
    req = _FakeRequest(headers={}, client_host="10.0.0.5")
    assert get_trusted_client_ip(req) == "10.0.0.5"


def test_trusted_client_ip_falls_back_to_loopback_when_client_missing():
    req = _FakeRequest(headers={}, client_host=None)
    assert get_trusted_client_ip(req) == "127.0.0.1"


# ═══════════════ get_bearer_token_key ═══════════════

def test_bearer_token_key_reads_authorization_header():
    req = _FakeRequest(headers={"Authorization": "Bearer abc123"})
    assert get_bearer_token_key(req) == "abc123"


def test_bearer_token_key_empty_when_not_bearer_scheme():
    req = _FakeRequest(headers={"Authorization": "Basic abc123"})
    assert get_bearer_token_key(req) == ""


def test_bearer_token_key_empty_when_header_missing():
    req = _FakeRequest(headers={})
    assert get_bearer_token_key(req) == ""


# ═══ Integration: forged X-Real-IP + wrong token still hit one bucket ═════
# LAST in the file, deliberately - see test_internal_jarvis_api.py's own
# trailing rate-limit tests for why (shared Limiter state across tests
# sharing one TestClient/process).

def test_forged_headers_do_not_defeat_auth_gate_rate_limit(client):
    """The layered defense this fix relies on: AUTH_GATE_RATE_LIMIT (used
    by all three internal APIs) is keyed by get_trusted_client_ip, never by
    get_bearer_token_key - that key_func is only ever wired to the
    post-auth per-route limits (see rate_limit_keys.py's own docstrings for
    why keying the auth gate on an attacker-supplied token would be
    unsafe). So even though this test varies BOTH the wrong token AND sends
    a forged X-Real-IP on every single request - the two inputs a pre-auth
    caller fully controls - the requests still share one bucket (same
    forged IP every time) and the caller still gets rate-limited.

    This does NOT prove an attacker can't defeat the auth gate by varying
    X-Real-IP itself - in this test environment (no Railway edge in front
    of TestClient), a *varying* forged X-Real-IP absolutely would spread
    across buckets, because get_trusted_client_ip trusts whatever value
    it's given. This app's only defense against that is Railway's edge
    overwriting X-Real-IP before this code ever runs (see this file's
    module docstring) - not anything a unit/integration test can exercise.
    """
    statuses = []
    for _ in range(150):
        r = client.get(
            "/jarvis/queue",
            headers={
                "Authorization": f"Bearer still-the-wrong-token-{uuid.uuid4().hex}",
                "X-Real-IP": "203.0.113.99",  # same forged IP every request
            },
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        f"expected a 429 within 150 wrong-token requests sharing one forged "
        f"X-Real-IP once AUTH_GATE_RATE_LIMIT was exhausted, got: "
        f"{sorted(set(statuses))}"
    )
