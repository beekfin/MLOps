# Точный digest базового образа подставляет scripts/setup.py и сохраняет images-lock.json.
ARG BASE_IMAGE=python:3.12.11-slim-bookworm
FROM ${BASE_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY src ./src
COPY scripts/client.py ./client.py
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "src.service"]
