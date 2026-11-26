FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV MAMBA_ROOT_PREFIX=/opt/conda \
    PATH=/opt/conda/envs/tarpass/bin:/usr/local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget bzip2 libgomp1 && rm -rf /var/lib/apt/lists/*
RUN wget -qO- https://micro.mamba.pm/api/micromamba/linux-64/2.0.5 | tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba
COPY tarpass/environment.yml /tmp/environment.yml
RUN micromamba create -y -f /tmp/environment.yml && micromamba clean --all --yes
RUN python -m pip install --no-cache-dir --no-build-isolation --no-deps plip==2.4.0
ARG GNINA_URL=https://github.com/gnina/gnina/releases/download/v1.3/gnina
RUN wget --timeout=60 --tries=3 -q "${GNINA_URL}" -O /usr/local/bin/gnina && chmod 755 /usr/local/bin/gnina && gnina --version
WORKDIR /app
COPY tarpass /app/tarpass
COPY genova_runtime /app/genova_runtime
COPY builtin_datasets /app/builtin_datasets
CMD ["python", "-m", "genova_runtime.queue_worker", "--task", "tarpass"]
