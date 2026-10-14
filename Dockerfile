FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY voxa ./voxa
RUN pip install --no-cache-dir .
COPY data ./data
COPY web ./web
RUN useradd -m voxa && mkdir -p /app/data/memory && chown -R voxa /app
USER voxa
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "voxa.server:app", "--host", "0.0.0.0", "--port", "8000"]
