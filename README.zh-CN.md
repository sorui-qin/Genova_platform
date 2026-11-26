# Genova 安装与迁移指南

Genova 提供蛋白准备、SurfGen / ECloudGen 分子生成、DELETE / EPSO 先导优化及 TarPass 后处理，
共用账号、数据集、任务队列和结果服务。[English](README.md)

## 1. 代码与镜像的分工

仓库包含前端、后端、运行适配器、蛋白准备、内置样例和部署文件。SurfGen、ECloudGen、DELETE 的模型代码、权重和依赖由镜像提供，无需克隆模型源码；保留上游 [SurfGen 许可证](licenses/SurfGen.LICENSE)。

ECloudGen 按目标数量生成有效且去重的二维分子和 SMILES CSV，默认目标为 1,000。采样预算根据实测产量确定，默认最多补采样至初始预算的 3 倍；预算耗尽仍不足时会提示。高级设置可调整 noise（默认 0.1）、逆温度、电子云数、每云解码次数和随机种子。

EPSO 使用独立 Worker，支持可选的 GNINA 亲和力评分，详见 [EPSO 接入说明](deploy/EPSO.md)（离线包中为同目录的 `EPSO.md`）。

八个应用镜像共用一个仓库，标签分别为 `backend-1.0.2`、`frontend-1.0.2`、`protein-preparation-1.0.2`、`surfgen-1.0.2`、`ecloudgen-1.0.2`、`epso-1.0.2`、`delete-1.0.2` 和 `tarpass-1.0.2`。PostgreSQL 和 Redis 使用 `postgres:16-alpine` 和 `redis:7-alpine`。镜像和代码不包含实例账号、上传文件、历史任务或业务数据库。

## 2. 环境要求

- Linux x86_64，Docker Engine、Docker Compose 2.30+、Git、OpenSSL。
- NVIDIA 显卡与驱动，并为 Docker 配置
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。
- SurfGen、ECloudGen 和 EPSO 的 PyTorch 为 2.2.2，编译 CUDA 为 12.1。DELETE 使用 PyTorch
  1.10.1 和 CUDA 11.3，TarPass 使用 CUDA 12.1 runtime。新型号显卡可能需要重新构建模型镜像。
- 默认单卡运行，共享 GPU 文件锁。为镜像、解压层和持续增长的数据预留磁盘；
  现有发布包仅压缩镜像就约 11 GB。

镜像部署不需要宿主机安装 Node.js、Conda 或 CUDA Toolkit。

```bash
docker compose version
nvidia-smi
```

Windows 用户先完成第 5 节，再在 Ubuntu 中执行下面的 Linux 命令。

## 3. 克隆代码并在线安装

```bash
git clone https://github.com/sorui-qin/generation_platform.git
cd generation_platform
```

私有 Git 仓库需要相应访问权限。部署时使用与镜像版本配套的 Git 修订。
无需下载模型源码或手工复制权重。

全新安装时，在 `deploy/` 创建配置：

```bash
cd deploy
test ! -e .env && cp .env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

编辑 `.env`，实际仓库地址向发布者获取；下面的地址只是占位示例：

```dotenv
IMAGE_REPOSITORY=registry.example.com/your-namespace/genova
PLATFORM_VERSION=1.0.2
POSTGRES_PASSWORD=第一次生成的随机值
REDIS_PASSWORD=第二次生成的随机值
JWT_SECRET=第三次生成的随机值
```

保留模板中其他配置。三个密钥分别使用不同的十六进制随机值。
已有实例迁移时保留原配置中的密钥，不要重新生成。

私有镜像仓库先登录，登录地址只填写域名：

```bash
docker login registry.example.com
docker compose --env-file .env -f compose.yml config --images
docker compose --env-file .env -f compose.yml pull
docker compose --env-file .env -f compose.yml up -d --no-build --wait
docker compose --env-file .env -f compose.yml ps
```

Agent 后端启动时会将镜像中的 SurfGen/TarPass 协议文档写入 PostgreSQL；文件缺失或版本不匹配时 API 会启动失败。发布部署使用预构建镜像，仅拉取代码不会更新服务；构建方法见 [发布说明](deploy/README.md)。

本机浏览器访问 `http://localhost:18001/genova/`；远程访问替换为服务器地址。
`WEB_PORT` 控制宿主机端口。仅前端端口对外映射，API/WebSocket 通过 Nginx 转发；
公网 HTTPS 需另行配置。

PostgreSQL、Redis 默认从 Docker Hub 拉取。网络不通时可以离线导入，或同步到自己的
仓库后修改 `compose.yml` 中这两个服务的 `image`。

数据库和文件分别保存在 `pgdata`、`data` 命名卷，文件的容器内路径统一为 `/app/data`。
后续运行保持安装目录及 Compose 项目名稳定，避免启动到另一组空卷。
需要保留数据时不要执行 `docker compose down -v`。

## 4. 验证安装

在 `deploy/` 中执行：

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

注册账号，上传仓库中的 `VERSE/builtin_datasets/3cl.pdb` 和 `3cl_ligand.sdf`，
完成蛋白准备，生成一个 SurfGen 分子，再对结果运行 TarPass。
同时用内置 `2VT4` 输入测试 DELETE。确认任务成功、SMILES 有效、CSV/SDF 可下载。
仅检测到 GPU 不代表所有推理任务兼容。

排查日志：

```bash
docker compose --env-file .env -f compose.yml logs --tail=100
```

DELETE 已知限制：部分指定生长点可能持续重试，占用 GPU 锁。先取消该 Job，
再重新创建 DELETE Worker，才会终止实际计算：

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps worker-delete
```

仅取消 Job 会修改数据库状态，不会终止模型进程。

### GPU 排障：系统升级后容器无法使用 CUDA

遇到 `Failed to initialize NVML: Unknown Error`、`CUDA_ERROR_NO_DEVICE` 或
`No CUDA GPUs are available` 时，先检查宿主机、现有 Worker 和同镜像的临时容器。
以下示例从发布安装目录执行。源码开发从仓库根目录执行，将 `docker compose --env-file .env -f compose.yml`
换成 `docker compose -f VERSE/docker-compose.yml`。把 `worker` 改成受影响的 Compose 服务名。

```bash
worker=worker-epso
nvidia-smi
docker compose --env-file .env -f compose.yml exec -T "$worker" nvidia-smi </dev/null
container_id=$(docker compose --env-file .env -f compose.yml ps -q "$worker")
image_id=$(docker inspect --format '{{.Image}}' "$container_id")
docker run --rm --pull never --network none --gpus all --entrypoint nvidia-smi "$image_id"
```

- 宿主机失败时，先检查 NVIDIA 驱动和内核模块。驱动或内核升级后如果需要重启，重启后先确认宿主机 `nvidia-smi` 正常。
- 宿主机正常、临时容器也失败时，用本地已知可用的 CUDA 基础镜像重复临时容器测试。如果仍失败，检查 Docker 的 GPU 配置和 NVIDIA Container Toolkit。如果基础镜像成功，检查业务镜像及服务的 GPU 配置。 [Docker GPU 文档](https://docs.docker.com/engine/containers/gpu/)
- 同镜像临时容器正常、现有 Worker 失败时，重点检查现有容器的 GPU 设备访问权限。Docker 使用 `systemd` 管理 cgroup 时，`systemctl daemon-reload` 等更新可能导致运行中的容器丢失 GPU 权限。可通过 `docker info --format '{{.CgroupDriver}}'` 和系统日志核对。 [NVIDIA 排障说明](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html#containers-losing-access-to-gpus-with-error-failed-to-initialize-nvml-unknown-error)

确认受影响的 Worker 没有正在执行的任务后，用本地镜像重新创建该服务。

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps "$worker"
```

用业务进程的运行环境验证一次实际 CUDA 运算。EPSO 和 ECloudGen 使用 `/opt/conda/envs/ecloudgen/bin/python`，SurfGen 使用 `/opt/conda/envs/surfgen/bin/python`，DELETE 使用 `python3`。TarPass 用其 Python 环境调用 CUDA runtime 分配和释放显存。

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

若 `nvidia-smi` 正常但计算失败，检查 `CUDA_VISIBLE_DEVICES`、框架的 CUDA 构建版本和报错算子对当前 GPU 架构的支持。CUDA 运算通过后，可重新提交因 GPU 不可用而失败的任务。

#### 2026-11-24 本机排障记录

2026-11-24，本机 EPSO 和 TarPass 容器无法访问 NVIDIA 设备，同镜像临时容器正常。系统日志显示故障容器启动后发生过 systemd 重载，具体触发操作未确认。用原镜像重新创建两个 Worker 后，EPSO 的 CUDA 张量运算及 TarPass 的显存分配、写入和读回通过；未在此次排障中验证业务推理和对接。

## 5. Windows / WSL 2

Windows 安装支持 WSL 的 NVIDIA 驱动。在管理员 PowerShell 执行：

```powershell
wsl --install -d Ubuntu
wsl --update
wsl -l -v
```

确认 Ubuntu 的 VERSION 为 2。安装 Docker Desktop，启用：

- `Use the WSL 2 based engine`。
- `Resources → WSL Integration` 中的 Ubuntu。
- 使用 Linux containers。

采用 Docker Desktop 集成时，不需要在 Ubuntu 另装 Docker 守护进程。
不要在 WSL 内安装 Linux NVIDIA 显卡驱动，GPU 驱动由 Windows 提供。

在 Ubuntu 文件系统中克隆，例如 `~/generation_platform`，按照第 3–4 节部署。
Windows 浏览器访问 `http://localhost:18001/genova/`，镜像无需转换。
本版本尚未完成 WSL 端到端验收，需要在实际显卡上逐个验证模型。

参考：[Docker WSL](https://docs.docker.com/desktop/features/wsl/)、
[Docker GPU](https://docs.docker.com/desktop/features/gpu/)、
[NVIDIA WSL](https://docs.nvidia.com/cuda/wsl-user-guide/)。

## 6. 离线迁移镜像

发布端先拉取全部镜像，再从仓库根目录导出。第三个参数必须与本地已有镜像的仓库地址一致：

```bash
bash deploy/export.sh deploy/dist/genova-1.0.2-single-repo 1.0.2 \
  registry.example.com/your-namespace/genova
```

脚本打包八个去重后的运行镜像、部署文件、空密钥模板、镜像 ID 和校验文件。
只分发该输出目录，不要分发整个 `deploy/dist/`，其中可能包含清理前的私有备份。
接收方运行离线包不需要代码仓库或模型源码。

在接收方包目录执行：

```bash
sha256sum -c SHA256SUMS
docker image load -i images.tar.gz
test ! -e .env && cp .env.example .env
chmod 600 .env
```

新安装填好三个独立密钥，然后执行：

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

必须使用包内配套的 Compose 和模板。早期 `genova-1.0.2` 离线包仍使用旧的多仓库
命名，不能混用现在单仓库格式的配置。已存在的导出目录不会被脚本覆盖。

## 7. 保留账号、历史任务和上传文件的迁移

迁移镜像不等于备份数据。跨主机迁移先保持相同应用版本，数据库版本升级另行处理。
停止新提交，等待排队及运行任务完成，再停止应用写入。Redis 队列通过 `redisdata` 卷持久化，
执行中的模型进程仍不能跨主机恢复，迁移前必须排空任务。

### 7.1 来源是当前镜像部署

在来源部署目录执行，备份目录使用新的私有目录：

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

确认每条命令成功，再安全传输备份。正式切换期间保持来源应用停止，避免两边继续写入。
若仅演练备份，可通过 `docker compose --env-file .env -f compose.yml up -d --no-build`
恢复来源服务。备份包含敏感数据和密钥，不能提交 Git 或放入公开分发包。

### 7.2 来源是旧的源码挂载部署

从旧仓库根目录用 `docker compose -f VERSE/docker-compose.yml` 停止其应用服务，
并使用相同 Compose 前缀执行上述 `pg_dump`。
旧版文件位于宿主机 `VERSE/data/`，需要打包目录内容：

```bash
tar -C VERSE/data -czf /path/to/private-backup/data.tar.gz .
```

私下保存 `VERSE/.env`。目标端以发布模板创建配置，迁移原数据库设置与 `JWT_SECRET`，
不要直接用开发 `.env` 覆盖发布配置。数据文件的容器路径仍保持 `/app/data`。

### 7.3 恢复到空目标实例

先准备相同版本镜像及部署文件，校验备份的 `SHA256SUMS`。
当前发布部署的 `instance.env` 可恢复为目标 `.env`；开发配置则按上一节映射。
使用目标机器适用的仓库地址和 GPU 设置，保留原实例密钥。
不要预先启动后端初始化数据库，也不要向已有业务数据库执行下面的恢复。

在目标部署目录执行：

```bash
docker compose --env-file .env -f compose.yml up -d --wait postgres redis
docker compose --env-file .env -f compose.yml exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < ~/genova-backup/database.dump
docker compose --env-file .env -f compose.yml run --rm --no-deps -T \
  --entrypoint tar backend-api -C /app/data -xzf - < ~/genova-backup/data.tar.gz
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

用已有账号登录，检查历史任务和文件下载正常后，再停用旧主机。
数据库和文件必须来自同一次停止写入后的备份，不能混入目标原有数据。

## 8. 开发、发布和升级

默认部署入口是 `deploy/compose.yml`。`VERSE/docker-compose.yml` 是单独的源码开发入口。
发布容器不挂载仓库源码，因此修改代码或 `git pull` 不会自动更新运行中的镜像。

源码开发使用 `VERSE/.env.example` 创建 `VERSE/.env`，设置模型镜像所用的
`IMAGE_REPOSITORY` 和 `PLATFORM_VERSION`。前端开发需要 Node.js 22，执行
`npm ci --legacy-peer-deps`，再用 `npm --ignore-scripts run dev` 避免自动启动后端的 hook。
TarPass 细节见 [VERSE/tarpass/README.md](VERSE/tarpass/README.md)。

构建和推送见 [deploy/README.md](deploy/README.md)。维护者更新 SurfGen adapter 时，
使用 `SURFGEN_BASE_IMAGE` 指定已发布模型镜像；DELETE 构建目前依赖维护者本地的
清理基础镜像 `genova/delete:1.0.1`。克隆仓库足以部署，但不能单独从源码重建外部模型环境。
模型代码或权重更新由模型维护者提供新镜像，分发时保留上游许可证。

升级前等待任务完成并备份，切到配套 Git 修订，修改 `PLATFORM_VERSION`，执行 `pull`
和 `up -d --no-build --wait`。不覆盖已经发布的版本标签，也不把版本回退视作数据库回退。
当前未提供自动跨版本数据库迁移流程。Git 提交和镜像推送是独立操作；
实例 `.env`、权重、数据卷及备份不应进入 Git。
