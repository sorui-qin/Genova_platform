ARG ECLOUDGEN_BASE_IMAGE=ecloudgen:latest
FROM ${ECLOUDGEN_BASE_IMAGE} AS source
RUN python -m pip install --no-cache-dir redis==5.3.1
RUN find /opt/conda/envs/ecloudgen -type d -name __pycache__ -prune -exec rm -rf '{}' +

FROM nvidia/cuda:12.1.1-base-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=source /opt/conda/envs/ecloudgen /opt/conda/envs/ecloudgen
ENV PATH=/opt/conda/envs/ecloudgen/bin:$PATH \
    PYTHONPATH=/platform:/app ECLOUDGEN_ROOT=/app \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY ECloudGen_official/generate_from_pdb.py /app/generate_from_pdb.py
COPY ECloudGen_official/configs /app/configs
COPY ECloudGen_official/models /app/models
COPY ECloudGen_official/utils /app/utils
COPY ECloudGen_official/ecloud_utils /app/ecloud_utils
COPY deploy/ecloudgen-runtime-patch.py /tmp/ecloudgen-runtime-patch.py
RUN python /tmp/ecloudgen-runtime-patch.py && rm /tmp/ecloudgen-runtime-patch.py
COPY ECloudGen_official/ckpt /app/ckpt
COPY VERSE/genova_runtime /platform/genova_runtime
COPY VERSE/builtin_datasets /app/builtin_datasets
WORKDIR /platform
ENTRYPOINT []
CMD ["python", "-m", "genova_runtime.queue_worker", "--task", "ecloudgen"]
