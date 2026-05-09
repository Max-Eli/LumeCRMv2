# syntax=docker/dockerfile:1.7
#
# Lumè CRM backend image.
#
# Two-stage build:
#   1. `builder` — compiles wheels into a venv we can copy verbatim.
#      Anything build-only (gcc, libpq-dev) lives here and never makes
#      the runtime layer, keeping the final image small + auditable.
#   2. `runtime` — `python:3.12-slim-bookworm` with the venv copied in,
#      a non-root `app` user, and gunicorn as PID 1. No shell access,
#      no apt cache, no build tools.
#
# Why slim-bookworm: Debian 12 (current stable) gets security patches,
# `slim` drops 80 MB of unused tooling, Python 3.12 matches local dev.
# Stick with this — switching base distros (Alpine, distroless) breaks
# psycopg's libpq linkage in nonobvious ways.
#
# Why gunicorn (not uvicorn): no async views in the Django codebase, no
# Channels yet. gunicorn with sync workers is simpler, well-understood,
# and matches the deployment model AWS Fargate + ALB expects.
#
# The image expects DJANGO_SETTINGS_MODULE=lume_crm.settings.prod at
# runtime. Local dev with this image: pass `-e
# DJANGO_SETTINGS_MODULE=lume_crm.settings.dev`.

ARG PYTHON_VERSION=3.12

# ── Builder ─────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# psycopg3 ships a `binary` wheel; we still install build-essential so
# any package that *isn't* prebuilt for linux/arm64 (Fargate Graviton)
# can compile from source. The cost (~30 sec build, zero runtime) is
# worth the resilience.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Build into an isolated venv so we can `COPY --from=builder /opt/venv`
# in one shot. Keeps the runtime stage hermetic.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Layer caching: copy reqs first so app-source changes don't
# invalidate the wheel install layer.
COPY requirements.txt requirements-prod.txt ./
RUN pip install --upgrade pip wheel \
    && pip install -r requirements.txt -r requirements-prod.txt

# ── Runtime ─────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=lume_crm.settings.prod

# libpq5 (runtime), curl for HEALTHCHECK, tini for proper PID-1 signal
# handling (gunicorn alone doesn't reap zombies cleanly under SIGTERM
# from ECS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app /app/staticfiles \
    && chown -R app:app /app

# Copy the venv from the builder; nothing else from that stage.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Source last so unrelated reqs changes still hit the cached venv layer.
COPY --chown=app:app . /app

# Collectstatic at build time -- the admin + DRF browsable API need
# their assets served. WhiteNoise reads from STATIC_ROOT in the runtime
# image, so we pre-build them here.
#
# `prod.py` reads several env vars at module-load time (for S3
# storage, SES, etc.), so we set ALL of them to dummy values for the
# build. None of these are read by `collectstatic` itself; they only
# need to be SET so `prod.py` imports cleanly. They're cleared after
# the RUN step so they can't leak into the runtime image.
ENV SECRET_KEY=build-time-dummy-not-used-at-runtime \
    DEBUG=0 \
    ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgres://nobody@localhost:5432/nobody \
    AWS_STORAGE_BUCKET_NAME=build-time-dummy \
    AWS_S3_KMS_KEY_ID=build-time-dummy \
    DEFAULT_FROM_EMAIL=build@dummy.local
RUN python manage.py collectstatic --noinput --clear
ENV SECRET_KEY="" DEBUG="" ALLOWED_HOSTS="" DATABASE_URL="" \
    AWS_STORAGE_BUCKET_NAME="" AWS_S3_KMS_KEY_ID="" DEFAULT_FROM_EMAIL=""

USER app

EXPOSE 8000

# /healthz is wired up in lume_crm/urls.py and returns 200 when the
# DB is reachable. ECS uses ALB health checks instead of the Docker
# HEALTHCHECK in production; this directive is for `docker run` parity
# during local-prod testing.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:${PORT}/healthz || exit 1

# tini → gunicorn. Workers count is set in the entrypoint script so
# Fargate task-size changes don't require a rebuild. Sync workers; if
# we add Channels later, switch to uvicorn workers in a separate
# revision.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec gunicorn lume_crm.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers ${GUNICORN_WORKERS:-3} \
    --threads ${GUNICORN_THREADS:-2} \
    --worker-tmp-dir /dev/shm \
    --access-logfile - \
    --error-logfile - \
    --log-level info"]
