# syntax=docker/dockerfile:1

# ---- Builder: compile/resolve dependencies only, discarded after this stage
# so no compiler toolchain ends up in the final image. -------------------
FROM python:3.12-slim AS builder

# Safety net for any dependency in requirements.txt that doesn't ship a
# prebuilt wheel for this Python version and has to compile from source
# (e.g. cryptography, bcrypt). Almost everything here already has manylinux
# wheels, so this typically goes unused - it's here so a build never fails
# for lack of it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# Only requirements.txt is copied before the install step, so this layer -
# by far the slowest part of the build - is only invalidated when
# dependencies actually change, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ---- Final: minimal runtime image --------------------------------------
FROM python:3.12-slim AS final

RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# APP_VERSION mirrors what _resolve_app_version() in server.py already
# checks first (see Part 1) - .git isn't in this build context (backend/ is
# the context root; the repo's .git lives one level up), so the git-based
# fallback there can never resolve inside a container. Pass the real commit
# at build time instead:
#   docker build --build-arg APP_VERSION=$(git rev-parse --short HEAD) ...
# Left as "unknown" (the same fallback server.py itself uses) if omitted.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Only what the app actually imports at runtime - no tests/, tools/,
# venv/, or .env (secrets come from the platform's env at container start,
# never baked into the image).
COPY --chown=appuser:appuser server.py .
COPY --chown=appuser:appuser services/ ./services/

USER appuser

EXPOSE 8001

# Uses shell form (not exec-array form) so ${PORT:-8001} actually expands -
# Railway/most PaaS platforms inject a dynamic PORT the container must bind
# to; local `docker run`/docker-compose (no PORT set) falls back to 8001,
# matching how this already runs today. `exec` replaces the shell process
# (rather than running uvicorn as its child) so SIGTERM reaches uvicorn
# directly for a clean shutdown instead of being swallowed by the shell.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT','8001'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/health', timeout=3).status==200 else 1)"

CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}"]
