FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home app
COPY --chown=app:app catalog ./catalog
COPY --chown=app:app tests ./tests
USER app
CMD ["uvicorn", "catalog.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM python:3.12-slim AS test
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY catalog ./catalog
COPY tests ./tests
COPY pyproject.toml ./
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
