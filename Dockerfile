# CLEARCUT — single container: FastAPI serves both the API and the UI.
# The frontend is dependency-free vanilla, so there is no build stage.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    # Cloud Run's filesystem is read-only apart from /tmp, so all runtime
    # state (model cache, research cache, clearance ledger) lives there.
    CLEARCUT_DATA_DIR=/tmp/clearcut

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY assets/ ./assets/

RUN useradd --create-home --uid 1001 clearcut \
    && mkdir -p /tmp/clearcut \
    && chown -R clearcut:clearcut /app /tmp/clearcut
USER clearcut

# Cloud Run injects PORT; default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn clearcut.api:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 620
