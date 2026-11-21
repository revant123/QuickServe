# QuickServe API image. See docs/docker.md for a line-by-line explanation.
#
#   docker build -t quickserve-api:dev .
#   docker run --rm -p 8001:8000 -e DATABASE_URL=... quickserve-api:dev

# ---------- Stage 1: builder ----------
# Installs the Python dependencies into a virtual environment. Nothing from this
# stage reaches the final image except that finished /opt/venv folder.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the lock file first. Docker caches each step, so as long as this
# file is unchanged, the slow install below is reused on the next build even
# when the app code changes.
# requirements.lock (not requirements.txt) pins every sub-dependency too, so
# building the same commit next month gives the same packages the tests passed with.
COPY requirements.lock .
RUN pip install -r requirements.lock


# ---------- Stage 2: runtime ----------
# A fresh, clean base. It gets the ready-made venv and our code, nothing else.
FROM python:3.11-slim AS runtime

# PYTHONDONTWRITEBYTECODE: don't write .pyc files into the image.
# PYTHONUNBUFFERED: print logs immediately, so `docker logs` shows them live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# A normal user with no special rights. If someone ever breaks into the app,
# they get this user's (very limited) powers, not root's.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /srv/quickserve

COPY --from=builder /opt/venv /opt/venv

# Only what the API needs at runtime. Files are owned by root and read-only to
# the app user, so the running app cannot modify its own code.
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Phase 16: which commit is this? CI passes --build-arg GIT_SHA=<commit> and
# /health reports it. It comes last, so a new commit only rebuilds this one tiny
# layer, and all the layers above stay cached.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

USER app

EXPOSE 8000

# Docker calls /health every 30s and marks the container "unhealthy" after 3
# failures. The slim image has no curl, so Python's built-in urllib does it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Exec form (a JSON list) makes uvicorn process 1 in the container, so it gets
# Docker's stop signal directly and shuts down cleanly. No --reload: that is a
# development convenience that watches files, which a container never edits.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
