ARG EPSO_MODEL_IMAGE=ecloudgen
ARG EPSO_DOCKING_IMAGE=tarpass
FROM ${EPSO_MODEL_IMAGE} AS model
FROM ${EPSO_DOCKING_IMAGE}

COPY --from=model /opt/conda/envs/ecloudgen /opt/conda/envs/ecloudgen
COPY --from=model /app/models /app/models
COPY --from=model /app/utils /app/utils
COPY --from=model /app/ecloud_utils /app/ecloud_utils
COPY --from=model /app/configs /app/configs
COPY --from=model /app/ckpt/ecloudgen_decipher_ckpt /app/ckpt/ecloudgen_decipher_ckpt
COPY genova_runtime /platform/genova_runtime
COPY tarpass /app/tarpass

ENV PATH=/opt/conda/envs/ecloudgen/bin:$PATH \
    PYTHONPATH=/platform:/app ECLOUDGEN_ROOT=/app \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /platform
CMD ["python", "-m", "genova_runtime.queue_worker", "--task", "epso"]
