FROM python:3.11-slim

ARG ADAPTER

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY pyproject.toml LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir ".[$ADAPTER]"

RUN mkdir -p /app/.dbt && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

CMD ["uvicorn", "metricflow_server.main:app", "--host", "0.0.0.0", "--port", "8080"]
