# Multi-platform production container for Trust Fall Arena API
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    USE_MOCKS=1 \
    PORT=8000

WORKDIR /app

# Create unprivileged application user
RUN useradd -m -u 1000 appuser

# Install Python requirements
COPY requirements/base.txt requirements/arena_api.txt requirements/
RUN pip install --no-cache-dir -r requirements/base.txt -r requirements/arena_api.txt

# Copy application code
COPY . /app
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
