ARG SURFGEN_BASE_IMAGE
FROM ${SURFGEN_BASE_IMAGE} AS source
RUN sed -i '/^pool.finished = pool.finished\[:config.sample.num_samples\]$/d; /^# save the generation results/a pool.finished = pool.finished[:config.sample.num_samples]' /app/gen.py
RUN sed -i '/^seed_all(config.sample.seed)$/d; /^print.*sample_seed:/d; s/^from utils.misc import load_config$/from utils.misc import load_config, seed_all/; /^config = load_config(args.config)$/a seed_all(config.sample.seed)\nprint("sample_seed:", config.sample.seed, flush=True)' /app/gen.py \
    && sed -i '/^  mask_init:/d' /app/configs/sample.yml
RUN rm -rf /opt/conda/pkgs /root/.cache \
    && find /opt/conda /opt/pdb2pqr /app -type d -name __pycache__ -prune -exec rm -rf '{}' +

FROM nvidia/cuda:12.1.1-base-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends libapbs3=3.0.0+dfsg1-3build2 libopenmpi3 ca-certificates libgomp1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=source /opt/conda /opt/conda
COPY --from=source /opt/pdb2pqr /opt/pdb2pqr
COPY --from=source /usr/local/bin/msms /usr/local/bin/msms
COPY --from=source /usr/bin/apbs /usr/bin/apbs
COPY --from=source /usr/lib/apbs /usr/lib/apbs
COPY --from=source /usr/share/doc/apbs /usr/share/doc/apbs
RUN ln -s /opt/pdb2pqr/bin/pdb2pqr /usr/bin/pdb2pqr
COPY --from=source /app/gen.py /app/surface_cli.py /app/LICENSE /app/
COPY --from=source /app/models /app/models
COPY --from=source /app/utils /app/utils
COPY --from=source /app/configs /app/configs
COPY --from=source /app/ckpt /app/ckpt
COPY surfgen-runtime-patch.py /tmp/surfgen-runtime-patch.py
RUN /opt/conda/envs/surfgen/bin/python /tmp/surfgen-runtime-patch.py && rm /tmp/surfgen-runtime-patch.py
ENV PATH=/opt/conda/bin:$PATH \
    PYTHONPATH=/platform SURFGEN_ROOT=/app \
    SURFGEN_MSMS_BIN=/usr/local/bin/msms \
    SURFGEN_APBS_BIN=/usr/bin/apbs \
    SURFGEN_PDB2PQR_BIN=/usr/bin/pdb2pqr \
    SURFGEN_MULTIVALUE_BIN=/usr/lib/apbs/tools/bin/bin/multivalue \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /platform
COPY genova_runtime /platform/genova_runtime
COPY builtin_datasets /app/builtin_datasets
RUN sed -i 's/liten_runtime.pdb2pqr_compat/genova_runtime.pdb2pqr_compat/g' /app/utils/masif/computeAPBS.py
CMD ["/opt/conda/envs/surfgen/bin/python", "-m", "genova_runtime.queue_worker", "--task", "surfgen"]
