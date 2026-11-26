# Genova installation

The release runs on a Linux x86_64 workstation or server with Docker Engine,
Docker Compose 2.30 or newer, a compatible NVIDIA GPU driver, and NVIDIA
Container Toolkit configured for Docker. Model dependencies, code, weights,
and tools are included in the application images. Node.js, Conda, local model
source directories, historical images, and build caches are not required.

The eight application images are backend, frontend, protein-preparation,
SurfGen, ECloudGen, EPSO, DELETE, and TarPass. PostgreSQL and Redis use official
images, bringing the total to ten images.
See `SURFGEN_COMPATIBILITY.md` for the tested GPU environment and limitations.
EPSO runs in its own worker and image. The image bundles ECloudGen model components
and the TarPass environment for optional GNINA affinity scoring. [EPSO deployment](EPSO.md#参数来源与部署)

## Configure

Keep the installation directory and Compose project name stable across restarts
and upgrades so that the same database and data volumes are used.

```bash
test ! -e .env && cp .env.example .env
chmod 600 .env
```

Generate three separate secrets with `openssl rand -hex 32` and enter them as
`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `JWT_SECRET` in `.env`.
Set `WEB_PORT` if port 18001 is already occupied. The template contains the
release's image repository and version; online installations must use the
publisher's actual repository. PostgreSQL and Redis do not expose host ports.

## Install from an offline release

The offline release includes all ten images. No registry access is required
to load and start them.

```bash
sha256sum -c SHA256SUMS
docker image load -i images.tar.gz
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

## Install from a registry

Use the configuration package for the same release and configure its published
repository in `.env`. PostgreSQL and Redis are pulled from their official
repositories.

```bash
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml pull
docker compose --env-file .env -f compose.yml up -d --no-build --wait
```

Open `http://localhost:18001/genova/`, or substitute the server address and
configured port. API requests and WebSockets use the same web entry point.

## Recover GPU access

Compare `nvidia-smi` on the host and in the affected worker. If the host passes,
run a temporary container from the exact same image with `--gpus all`. If the
temporary container passes, wait for active jobs on the affected worker to finish,
then recreate it from the local image. For example, to recover `worker-epso`, run
the following from the installation directory.

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps worker-epso
docker compose --env-file .env -f compose.yml exec -T worker-epso \
  /opt/conda/envs/ecloudgen/bin/python -c \
  'import torch; print(torch.ones(1, device="cuda").item())' </dev/null
```

On 2026-11-24, the EPSO and TarPass workers recovered CUDA access after
recreation from their existing images. The incident and TarPass CUDA test are
in the GPU troubleshooting section of `README.zh-CN.md` in the release package.

## Stop and migrate

`docker compose --env-file .env -f compose.yml stop` stops the services while
keeping their data. Do not use `down -v` on an installation whose data you need.
Migrating an existing installation requires separate backups of PostgreSQL,
the shared data volume, Redis state, and the original secret configuration.
Images alone contain no user accounts, uploaded datasets, or job results.

`image-ids.txt` and `image-manifest.jsonl` identify the packaged images; application
labels record the build version, source revision, and creation time. Registry
digests may be empty for locally built images until they are published.

Maintainers rebuild with `compose.build.yml` and the model build inputs described
in `README.md`. Those inputs are separate from the recipient's runtime needs.
