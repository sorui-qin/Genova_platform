FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openbabel \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install -r /tmp/backend-requirements.txt

COPY backend /app/backend
COPY genova_runtime /app/genova_runtime
COPY tarpass /app/tarpass
COPY builtin_datasets /app/builtin_datasets

EXPOSE 18000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "18000"]
