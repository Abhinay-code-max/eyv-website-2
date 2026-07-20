"""
Per-request correlation ID: generated (or forwarded, if the caller/proxy
already set one) at the very edge of the ASGI stack, stored in a contextvar
so every log line and error response emitted while handling that request can
carry it, and echoed back as the X-Request-ID response header.

Implemented as a plain ASGI middleware class rather than Starlette's
BaseHTTPMiddleware - this app streams chat responses via StreamingResponse
(see /api/chat/stream in server.py), and BaseHTTPMiddleware wraps the whole
response in a way that has historically buffered/broken streaming bodies.
A raw ASGI middleware passes `send` straight through (wrapped only to inject
one header), so it never touches the response body.
"""
import contextvars
import logging
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIDLogFilter(logging.Filter):
    """Attaches the current request's ID to every LogRecord so the JSON log
    formatter can include it. Records emitted outside a request (startup/
    shutdown, background tasks not tied to a request) get "-"."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        request_id = incoming.decode("latin-1") if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = message.setdefault("headers", [])
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
