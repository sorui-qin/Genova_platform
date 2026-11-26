# Genova

Protein preparation, SurfGen / ECloudGen molecule generation, DELETE / EPSO lead optimization, and
TarPass postprocessing on a shared authentication, dataset, job, and results platform.

[中文安装与迁移说明](README.zh-CN.md) · [Release maintenance](deploy/README.md)

## 1. What is distributed

The repository contains the frontend, backend, runtime adapters, protein preparation,
built-in examples, and deployment files. SurfGen, ECloudGen, and DELETE model code,
weights, and dependencies are supplied in images. The upstream [SurfGen license](licenses/SurfGen.LICENSE) is retained.

ECloudGen produces valid, unique 2D molecules and a SMILES CSV for a target count
(1,000 by default). Its sampling budget is based on measured yields, with top-ups by
default up to three times the initial budget; any shortfall is reported. Advanced settings
include noise (default 0.1), inverse temperature, cloud count, decodes per cloud, and seed.

EPSO uses a separate worker and supports optional GNINA affinity scoring. See
[EPSO integration](deploy/EPSO.md), or `EPSO.md` in the offline package.

The eight application images share one repository, with tags `backend-1.0.2`,
`frontend-1.0.2`, `protein-preparation-1.0.2`, `surfgen-1.0.2`,
`ecloudgen-1.0.2`, `epso-1.0.2`, `delete-1.0.2`, and `tarpass-1.0.2`.
PostgreSQL and Redis use `postgres:16-alpine` and `redis:7-alpine`. Images and Git
do not contain instance accounts, uploaded files, historical jobs, or the database.

## 2. Requirements

Use Linux x86_64 with Docker Engine, Docker Compose 2.30+, an NVIDIA GPU and driver,
Git, and OpenSSL. Configure the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
for Docker. Node.js, Conda, and a host CUDA toolkit are not required for image deployment.

SurfGen, ECloudGen, and EPSO use PyTorch 2.2.2 built for CUDA 12.1. DELETE uses
PyTorch 1.10.1 and CUDA 11.3. TarPass uses the CUDA 12.1 runtime.
Your GPU must support these environments; a newer GPU may require rebuilt model images.
The current deployment assumes one shared GPU. Reserve space for pulled images,
unpacked layers, and growing database/results volumes; the existing compressed
release archive alone is about 11 GB.

```bash
docker compose version
nvidia-smi
```

For Windows, first complete section 5, then run the Linux commands inside Ubuntu.

## 3. Clone and install from the registry

```bash
git clone https://github.com/sorui-qin/generation_platform.git
cd generation_platform
```

Private repositories require authorized Git access. Keep the intended release's
Git revision and image version together. Do not build the model directories.

For a **new installation**, create a private configuration:

```bash
cd deploy
test ! -e .env && cp .env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Edit `.env`: replace the image address with the actual repository supplied by the
publisher and put a different generated value into each secret:

```dotenv
IMAGE_REPOSITORY=registry.example.com/your-namespace/genova
PLATFORM_VERSION=1.0.2
POSTGRES_PASSWORD=replace_with_first_generated_value
REDIS_PASSWORD=replace_with_second_generated_value
JWT_SECRET=replace_with_third_generated_value
```

Keep other template settings. The registry address is a placeholder, not a hosted
public service. For a private registry, log in using the registry **hostname**:

```bash
docker login registry.example.com
docker compose --env-file .env -f compose.yml config --images
docker compose --env-file .env -f compose.yml pull
docker compose --env-file .env -f compose.yml up -d --no-build --wait
docker compose --env-file .env -f compose.yml ps
```

At startup, the Agent backend installs the bundled SurfGen/TarPass protocol documents
into PostgreSQL; missing or mismatched documents cause startup to fail. Release deployments
use prebuilt images, so pulling code alone does not update services. See the
[build instructions](deploy/README.md).

Open `http://localhost:18001/genova/`, or use the server address for remote
access. `WEB_PORT` changes the published port. Only the frontend port is published;
API and WebSocket traffic pass through Nginx. Public HTTPS is configured separately;
if it adds a reverse proxy in front of port 18001, set `set_real_ip_from` in
`genova_frontend/nginx.conf` to that proxy's address so sign-in limits stay per user.
If Docker Hub is unreachable, import the two official images offline or mirror them
and change their `image` entries in `compose.yml`.

The release uses named volumes `pgdata` and `data`, with shared files mounted at
`/app/data`. Keep the Compose project name/directory stable on subsequent runs.
Do not use `down -v` when you need to preserve data.

## 4. Verify the installation

Run from `deploy/`:

```bash
docker compose --env-file .env -f compose.yml exec -T backend-api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:18000/healthz').read().decode())"
docker compose --env-file .env -f compose.yml exec -T worker-surfgen \
  /opt/conda/envs/surfgen/bin/python -c \
  "import torch; assert torch.cuda.is_available(); print(torch.ones(1, device='cuda').cpu())"
docker compose --env-file .env -f compose.yml exec -T worker-delete \
  python3 -c "import torch; assert torch.cuda.is_available(); print(torch.ones(1, device='cuda').cpu())"
docker compose --env-file .env -f compose.yml exec -T worker-tarpass gnina --version
```

Create an account. Upload `VERSE/builtin_datasets/3cl.pdb` and
`VERSE/builtin_datasets/3cl_ligand.sdf` from the checkout, prepare the protein,
generate one SurfGen molecule, and run TarPass on its result. Also test DELETE
with the built-in `2VT4` inputs. Check successful jobs, valid SMILES, and CSV/SDF
downloads. GPU detection alone does not establish full inference compatibility.

```bash
docker compose --env-file .env -f compose.yml logs --tail=100
```

DELETE can retry indefinitely for some selected growth sites, holding the GPU
lock. Cancel the Job, then recreate only its worker to stop the actual computation:

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps worker-delete
```

Cancellation alone updates job status; it does not terminate model execution.

### GPU troubleshooting after a system upgrade

If a worker reports `Failed to initialize NVML: Unknown Error`, `CUDA_ERROR_NO_DEVICE`,
or `No CUDA GPUs are available`, check the host, the running worker, and a temporary
container from the exact same image. Run these commands from the release installation
directory. For source development, run from the repository root and replace the Compose
prefix with `docker compose -f VERSE/docker-compose.yml`. Set `worker` to the affected service.

```bash
worker=worker-epso
nvidia-smi
docker compose --env-file .env -f compose.yml exec -T "$worker" nvidia-smi </dev/null
container_id=$(docker compose --env-file .env -f compose.yml ps -q "$worker")
image_id=$(docker inspect --format '{{.Image}}' "$container_id")
docker run --rm --pull never --network none --gpus all --entrypoint nvidia-smi "$image_id"
```

- If the host check fails, check the NVIDIA driver and kernel modules, then complete
  any reboot required by a driver or kernel upgrade and rerun `nvidia-smi` on the host.
- If the host passes and the temporary container fails, repeat the test with a known-good
  CUDA base image. If it also fails, check Docker GPU configuration and NVIDIA Container
  Toolkit. If it passes, check the application image and service GPU settings. [Docker GPU access](https://docs.docker.com/engine/containers/gpu/)
- If the temporary container passes and the running worker fails, check GPU device
  access in the existing container. With systemd-managed cgroups, updates such as
  `systemctl daemon-reload` can cause running containers to lose GPU access. Check the
  cgroup driver with `docker info --format '{{.CgroupDriver}}'` and review system logs. [NVIDIA troubleshooting](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html#containers-losing-access-to-gpus-with-error-failed-to-initialize-nvml-unknown-error)

Once the affected worker has finished running tasks, recreate it from the local image.

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps "$worker"
```

Verify a CUDA operation in the worker's own runtime. EPSO and ECloudGen use
`/opt/conda/envs/ecloudgen/bin/python`, SurfGen uses `/opt/conda/envs/surfgen/bin/python`,
and DELETE uses `python3`. For TarPass, use its Python environment to check CUDA memory allocation.

```bash
docker compose --env-file .env -f compose.yml exec -T worker-epso \
  /opt/conda/envs/ecloudgen/bin/python -c \
  'import torch; print(torch.ones(1, device="cuda").item())' </dev/null
docker compose --env-file .env -f compose.yml exec -T worker-tarpass python - <<'PY'
import ctypes

cuda = ctypes.CDLL("libcudart.so.12")
buffer = ctypes.c_void_p()
status = cuda.cudaMalloc(ctypes.byref(buffer), ctypes.c_size_t(16))
if status:
    raise SystemExit(f"cudaMalloc failed: {status}")
status = cuda.cudaFree(buffer)
if status:
    raise SystemExit(f"cudaFree failed: {status}")
print("TarPass CUDA OK")
PY
```

If `nvidia-smi` passes but computation fails, check `CUDA_VISIBLE_DEVICES`, the
framework's CUDA build, and whether the failing operation supports the GPU architecture.
Resubmit GPU-related failed jobs after the CUDA check passes.

On 2026-11-24, the local EPSO and TarPass containers lost GPU access while temporary
containers from the same images worked. A systemd reload had occurred after the affected
containers started; the exact trigger is unconfirmed. Recreating both workers restored
CUDA operations. Business inference and docking were not tested in this incident.
[Local incident details](README.zh-CN.md#2026-11-24-本机排障记录)

## 5. Windows / WSL 2

Use Windows with a supported NVIDIA GPU and the Windows NVIDIA driver.
In administrator PowerShell:

```powershell
wsl --install -d Ubuntu
wsl --update
wsl -l -v
```

Confirm Ubuntu uses version 2. Install Docker Desktop, enable **Use the WSL 2 based
engine**, and enable Ubuntu under **Resources → WSL Integration**. Use Linux
containers. With Docker Desktop integration, do not install a second Docker daemon
inside Ubuntu. Do not install a Linux NVIDIA display driver inside WSL.

Clone into the Ubuntu filesystem, such as `~/generation_platform`, then follow
sections 3–4 in Ubuntu. Open `http://localhost:18001/genova/` in Windows.
Linux images are reused unchanged. WSL deployment has not been end-to-end validated
for this release; verify each model on your actual GPU.

References: [Docker WSL backend](https://docs.docker.com/desktop/features/wsl/),
[Docker GPU support](https://docs.docker.com/desktop/features/gpu/),
[NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/).

## 6. Move images to an offline machine

On the connected publisher machine, pull all release images first. From the
repository root, export using the **same repository address** as the pulled images:

```bash
bash deploy/export.sh deploy/dist/genova-1.0.2-single-repo 1.0.2 \
  registry.example.com/your-namespace/genova
```

The script exports eight unique images, Compose, documentation, a blank-secret
configuration template, image IDs, and checksums. Transfer only this output
folder, not the whole `deploy/dist/` tree, which may contain private backups.
The destination does not need Git or model source to run this package.

Inside the transferred folder:

```bash
sha256sum -c SHA256SUMS
docker image load -i images.tar.gz
test ! -e .env && cp .env.example .env
chmod 600 .env
```

Fill the three secrets for a fresh installation, then:

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

Keep each archive's accompanying Compose and template together. The earlier
`genova-1.0.2` archive uses the old multi-repository tags; do not mix its files
with the new single-repository deployment files.

## 7. Migrate accounts, jobs, and files

Image transfer alone creates no backup of business data. Use the **same application
version** for a host migration; schema upgrades are a separate operation.
Block new submissions, let queued/running jobs finish, then stop application
writers. Redis queues persist in the `redisdata` volume, but running model
processes cannot resume on another host. Drain all work before migration.

### Source: current image deployment

Run inside its deployment directory. Choose a new, private backup directory:

```bash
umask 077
mkdir -p ~/genova-backup
docker compose --env-file .env -f compose.yml stop \
  frontend backend-api backend-worker workflow-worker dispatcher worker-protein-preparation \
  worker-surfgen worker-ecloudgen worker-epso worker-delete worker-tarpass
docker compose --env-file .env -f compose.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > ~/genova-backup/database.dump
docker compose --env-file .env -f compose.yml run --rm --no-deps -T \
  --entrypoint tar backend-api -C /app/data -czf - . > ~/genova-backup/data.tar.gz
cp .env ~/genova-backup/instance.env
(cd ~/genova-backup && sha256sum database.dump data.tar.gz instance.env > SHA256SUMS)
```

Check command exit status and transfer this private backup securely. Keep the
source stopped during cutover to avoid diverging writes. If only testing the
backup, resume it with `docker compose --env-file .env -f compose.yml up -d --no-build`.

### Source: earlier source-mounted deployment

For `VERSE/docker-compose.yml`, stop its application services in the same way,
using `docker compose -f VERSE/docker-compose.yml` from the repository root.
Dump its PostgreSQL with that Compose command. Archive **the contents** of
`VERSE/data/` with `tar -C VERSE/data -czf /path/to/private-backup/data.tar.gz .`.
Save `VERSE/.env` privately. On the destination, use the release template and
transfer matching database settings and `JWT_SECRET`; do not blindly replace it
with the development `.env`. Keep database/file paths under `/app/data`.

### Destination: empty deployment only

Prepare matching images and Compose first. Check the backup's `SHA256SUMS`.
Restore the source release `.env` (or map development settings as above), keeping
its secrets private. Do not restore into an already initialized platform database.
From the destination deployment directory:

```bash
docker compose --env-file .env -f compose.yml up -d --wait postgres redis
docker compose --env-file .env -f compose.yml exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < ~/genova-backup/database.dump
docker compose --env-file .env -f compose.yml run --rm --no-deps -T \
  --entrypoint tar backend-api -C /app/data -xzf - < ~/genova-backup/data.tar.gz
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

Verify an existing account, historical job, and artifact download before retiring
the source. Never merge unrelated destination data into the restored volumes.

## 8. Development and subsequent releases

Deployment uses `deploy/compose.yml`; `VERSE/docker-compose.yml` is the separate
source-development entry point. Frontend/backend/TarPass and runtime adapters
remain editable in Git. Release containers do not bind-mount that source: changing
Git files alone does not update a running image deployment.

For source development, configure `VERSE/.env` from its template, including
`IMAGE_REPOSITORY` and `PLATFORM_VERSION` for external model images. Frontend
development requires Node.js 22 and `npm ci --legacy-peer-deps`; use
`npm --ignore-scripts run dev` to avoid the automatic backend startup hook.
See [TarPass documentation](VERSE/tarpass/README.md) for that package.

Build and publish procedures are in [deploy/README.md](deploy/README.md).
SurfGen adapter builds use an existing model image via `SURFGEN_BASE_IMAGE`;
DELETE builds currently require the maintainer's cleaned `genova/delete:1.0.1`
base. A fresh clone is sufficient to **deploy**, but does not reproduce external
model environments from source. Preserve upstream licenses when distributing images.

For updates, wait for jobs to finish, back up data, check out the matching Git
revision, set the new `PLATFORM_VERSION`, then `pull` and `up -d --no-build --wait`.
Do not overwrite published version tags. This repository does not provide an
automatic cross-version database migration procedure. Git commits and registry
pushes are separate actions; never commit `.env`, data volumes, weights, or backups.
