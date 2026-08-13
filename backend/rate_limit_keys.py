"""Shared rate-limit key functions used by server.py's general-purpose
`limiter` and by internal_tickets_api.py/internal_analytics_api.py/
internal_jarvis_api.py's own Limiters. Centralized here - rather than
duplicated per-module, or imported from one of the internal_*_api.py
modules directly - so each internal_*_api.py file stays a standalone,
independently-reviewable unit with no cross-imports between them (see
internal_analytics_api.py's own module docstring for that discipline).
Copied into the Docker image the same way db_models.py is (see
backend/Dockerfile).

Background: every Limiter in this app used to key on slowapi's
get_remote_address, which reads request.client.host - the address of
whatever opened the raw TCP connection to uvicorn. Behind Railway's edge
that's an internal proxy hop, not the real client, and (confirmed via a
temporary TEMP_IP_DEBUG logging pass against production, since removed)
it varies request-to-request rather than staying stable - so every per-IP
rate limit in this app silently never accumulated. This module's
get_trusted_client_ip replaces get_remote_address as the default key_func
everywhere; get_bearer_token_key is an additional, narrower per-route
override for the three internal APIs (see its own docstring for why it
must NOT be used for their auth-gate limits).
"""

from starlette.requests import Request


def get_trusted_client_ip(request: Request) -> str:
    """Rate-limit key: the real client IP, read from X-Real-IP.

    Trusting this header is safe ONLY because it was confirmed, via a
    deliberate spoofing test against the live Railway deployment (send
    X-Real-IP: <forged value>, inspect what the app actually received in
    TEMP_IP_DEBUG logs), that Railway's edge overwrites this header with
    the real connecting client's IP rather than passing through whatever
    the client sent - i.e. Railway itself is the only thing that can ever
    set the value this function sees. See test_rate_limit_keys.py's
    spoofing test, which pins this exact trust decision (not just the
    fallback below) - if this app is ever deployed somewhere other than
    Railway, or Railway changes this behavior, that test is what should
    catch it before a forged header can be used to bypass rate limiting
    the same way the old request.client.host bug silently disabled it.

    Falls back to request.client.host (get_remote_address's own behavior)
    when X-Real-IP is absent - local dev / CI / any environment with no
    proxy in front, where request.client.host IS the real peer.
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if not request.client or not request.client.host:
        return "127.0.0.1"
    return request.client.host


def get_bearer_token_key(request: Request) -> str:
    """Rate-limit key for internal_tickets_api.py/internal_analytics_api.py/
    internal_jarvis_api.py's per-route limits (e.g. TICKET_API_RATE_LIMIT,
    ANALYTICS_API_RATE_LIMIT, JARVIS_QUEUE_API_RATE_LIMIT) ONLY - never for
    their AUTH_GATE_RATE_LIMIT, which must keep using get_trusted_client_ip.

    Each of these routers' auth dependency (require_*_token) runs as a
    FastAPI router-level dependency, which FastAPI resolves before the
    endpoint function - the one this key_func's @_limiter.limit(...)
    decorator wraps - is ever called. So by the time this function runs,
    require_*_token has already verified the provided value is that
    router's one real, correct static token; a request with a wrong or
    missing token never reaches here at all (it's rejected with 401 inside
    the dependency first). Keying on the token here means "N/minute total
    for whoever holds this token" - a more meaningful bound than IP ever
    was for a single known trusted automated caller (eyv_poller and
    friends - there is exactly one legitimate holder of each token).

    This is NOT safe to use for AUTH_GATE_RATE_LIMIT: that limit exists
    specifically to bound requests that have NOT yet been authenticated,
    including wrong/missing tokens - keying on the attacker-supplied token
    value there would let an attacker trivially bypass it by sending a
    different garbage token on every request, the exact "trust
    attacker-controlled input" mistake this whole fix is meant to close,
    just moved from IP to token instead of fixed.
    """
    auth_header = request.headers.get("Authorization", "")
    return auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
