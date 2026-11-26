FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/platform

RUN apt-get update \
    && apt-get install -y --no-install-recommends openbabel \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    pdbfixer==1.12.0 openmm==8.4.0 pdb2pqr==3.6.2 \
    rdkit==2025.3.5 biopython==1.85 redis==5.3.1

WORKDIR /platform
COPY genova_runtime /platform/genova_runtime
COPY builtin_datasets /app/builtin_datasets
