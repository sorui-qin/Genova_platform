ARG DELETE_SOURCE_IMAGE=genova/delete:v1
FROM ${DELETE_SOURCE_IMAGE} AS source
COPY VERSE/delete-image-clean.py /tmp/delete-image-clean.py
RUN python3 /tmp/delete-image-clean.py

# No source-image layers are inherited by the final image.
FROM nvidia/cuda:11.3.1-runtime-ubuntu20.04@sha256:e8e94e51bb63ab09d698764aac45611c4370995947e59afc3ead508518e86e91
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 libgomp1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=source /clean/ /
COPY VERSE/delete-runtime-patch.py /tmp/delete-runtime-patch.py
RUN python3 /tmp/delete-runtime-patch.py && rm /tmp/delete-runtime-patch.py
COPY VERSE/genova_runtime /platform/genova_runtime
COPY VERSE/builtin_datasets /app/builtin_datasets
RUN apt-get update && apt-get install -y --no-install-recommends python3-pkg-resources \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/platform:/code:/code/components/Delete \
    DELETE_CHECKPOINT=/opt/delete/delete.pt \
    DATA_ROOT=/app/data \
    LD_LIBRARY_PATH=/code/components/Delete/delete_input/src/inputs/APBS-3.0.0.Linux/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
WORKDIR /platform
CMD ["python3", "-m", "genova_runtime.queue_worker", "--task", "delete"]
