FROM python:3.12-slim AS builder
ENV PATH="/opt/venv/bin:$PATH"
ENV HF_HOME=/app/.hf_cache
WORKDIR /app
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY . .

FROM python:3.12-slim AS runner
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN useradd --system -m --shell /bin/false appuser
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
WORKDIR /app
COPY entrypoint.sh .
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
ENV HF_HOME=/app/.hf_cache
ENV PATH="/opt/venv/bin:$PATH"
RUN chmod +x entrypoint.sh && chown -R appuser:appuser /app
USER appuser
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-"]
