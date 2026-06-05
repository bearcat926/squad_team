FROM python:3.11-slim

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

COPY pyproject.toml .
COPY squad_runtime/ squad_runtime/

RUN pip install --no-cache-dir .

RUN mkdir -p /app/.squad && chown -R appuser:appuser /app

USER appuser

EXPOSE 8765

ENTRYPOINT ["squad"]
CMD ["start", "--host", "0.0.0.0", "--port", "8765"]
