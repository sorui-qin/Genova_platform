# Genova 镜像分发

English installation instructions: [README.en.md](README.en.md).

本部署包用于全新安装，包含前端、API、后台任务服务、PostgreSQL、Redis、
蛋白准备、SurfGen、ECloudGen、DELETE 和 TarPass。现有源码开发部署继续使用 `VERSE/docker-compose.yml`。

## 分子生成高级设置

SurfGen / DELETE 开放搜索宽度（500）、最大生长步数（50）和随机种子（分别为 2020 / 2023）；元素概率阈值（0.3）、成键概率阈值（0.4）锁定为只读展示，后端拒绝修改。ECloudGen 开放解码噪声（0.1）、逆温度（2）、电子云数、每云解码次数和随机种子（默认 42，不可留空）。电子云数根据目标分子数估算，每云解码次数默认 100，两者可自定义；修改目标数量时重新计算。预算倍数在界面隐藏，内部默认 3。生成数量始终显示在高级设置之外；EPSO 仅展示可编辑设置及说明。

参数随 Job 保存并用于任务恢复。ECloudGen 修改噪声或逆温度后，原产量校准只用于初始预算估算；仍按实际产量补采样，受总预算限制。每云最多解码指定次数，batch 32，末批按剩余次数执行；保留全局去重。

开发环境更新后重启 `backend-api`、`worker-surfgen`、`worker-ecloudgen`；DELETE 必须通过现有 `deploy/delete.Dockerfile` 重新构建并重新创建 `worker-delete`，以加载采样参数补丁。发布构建会将 runtime 与模型补丁包含在最终镜像中。

## 分发与迁移边界

接收方使用 `deploy/compose.yml`，只需同一发布版本的八个应用镜像及 PostgreSQL、Redis 两个官方镜像，
共十个运行镜像。API、后台服务与 Dispatcher 共用 backend 镜像。
模型代码、权重及运行工具已包含在最终镜像中，无需携带旧版本镜像、本机模型源码或构建缓存。
Docker 拉取或导出最终镜像时会包含所需层；共享历史层不意味着必须保留历史镜像标签。

`compose.build.yml` 和各 Dockerfile 的旧基础镜像仅属于维护者重新构建的前提，不是接收方运行前提。
当前维护者构建仍有本地模型源码和基础镜像依赖，尚不等于完整的独立源码构建包。
分发使用下面的在线拉取或离线导出流程，不在接收方执行构建。

迁移已有实例时，还需单独备份和恢复 PostgreSQL、共享 `data` 以及原密钥配置；仅迁移镜像不会迁移用户、任务与结果。
恢复已有加密与认证数据时应保留相关原密钥。密钥通过私密渠道转移，不放入通用分发包。
GPU 驱动与架构兼容性仍由目标机器满足，详见 [SurfGen GPU 兼容性检查](SURFGEN_COMPATIBILITY.md)。

## 1. 接收方安装

目标主机需要 Linux x86_64、Docker Engine、Docker Compose 2.30+、NVIDIA 驱动和
已配置的 NVIDIA Container Toolkit。GPU 需兼容现有 CUDA 12.1 推理环境。
DELETE 沿用已验证的 CUDA 11.3 / PyTorch 1.10.1 环境；其他 GPU 模块使用各自镜像内的环境。
不需要在宿主机安装 Node.js、Conda 或模型依赖。
SurfGen 当前仅完成 RTX 4070 实机验收，RTX 5060 / 50 系列不能据此认定兼容；环境核查与诊断命令见
[SurfGen GPU 兼容性检查](SURFGEN_COMPATIBILITY.md)。

在本目录执行。先生成独立配置，已有 `.env` 时不要覆盖：

```bash
test ! -e .env && cp .env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

将三次生成的值分别填入 `.env` 的 `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、
`JWT_SECRET`。数据库与 Redis 的密码使用上述十六进制值，避免连接 URL 的转义问题。
`IMAGE_REPOSITORY` 和 `PLATFORM_VERSION` 必须与发布者提供的镜像一致。
默认网页端口为 `18001`，可通过 `WEB_PORT` 修改；数据库和 Redis 不暴露宿主机端口。
注册和访客绑定不会授予管理员权限。账号本人注册后，使用用户 UUID 授权或撤销：

```bash
docker compose --env-file .env -f compose.yml exec backend-api python -m backend.admin_users grant USER_UUID
docker compose --env-file .env -f compose.yml exec backend-api python -m backend.admin_users revoke USER_UUID
```

仅允许操作已存在、启用的正式账号，原有管理员标记保留。

忘记密码：填写 `.env` 中的 `PUBLIC_BASE_URL`（须含 `/genova`，如 `http://服务器地址:18001/genova`）与 `SMTP_*` 后，用户可在登录页自助领取重置邮件（链接 30 分钟内有效、仅可用一次，
改密或重置后旧 HTTP Token 立即失效，已连接 WebSocket 在发送下一条事件前或最长约 5 秒内断开）。未配置邮件时，管理员确认用户身份后生成一次性链接并私下转交：

```bash
docker compose --env-file .env -f compose.yml exec backend-api python -m backend.password_reset user@example.com
```

**通过镜像仓库安装：**

```bash
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml pull
docker compose --env-file .env -f compose.yml up -d --no-build --wait
```

**通过离线包安装：** 保持包内文件不变，先校验，再导入。

```bash
sha256sum -c SHA256SUMS
docker image load -i images.tar.gz
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml up -d --no-build --pull never --wait
```

打开 `http://服务器地址:18001/genova/`。API、文件下载和 WebSocket 通过同一入口代理。
重启服务无需重新导入镜像或配置数据库。

PostgreSQL 使用 `pgdata` 命名卷，上传文件和结果使用 `data` 命名卷；卷名由 Compose
项目名隔离。API 首次启动时自动建表并初始化内置数据集，后台服务等待初始化完成。
所有处理文件的容器均使用 `/app/data`，内置数据集固定为 `/app/builtin_datasets`。
单卡默认 GPU 0：`SURFGEN_CUDA_VISIBLE_DEVICES` 控制 SurfGen/ECloudGen/TarPass，
`DELETE_CUDA_VISIBLE_DEVICES` 控制 DELETE。四者共用 GPU 文件锁，串行执行 GPU 阶段。
保留安装目录名称及项目名，避免启动到另一组空卷。不要使用 `down -v` 删除需要保留的数据。
Redis 使用 `redisdata` 卷和 AOF（`appendfsync always`）持久化队列。消息处理成功后才确认，
进程重启恢复未确认消息；后台重启会重新投递未完成任务的 Outbox，已保存的模型回执避免重复推理。
执行中断且没有成功回执的模型任务明确失败，需要用户新建任务重试。

首次从非持久化配置升级前，先排空任务并停止 API、后台进程及所有 Worker。
如需保留现有 Redis 键，先在旧 Redis 启用 AOF，等待重写完成，再将其完整 `/data/`
复制到新容器的 `redisdata` 卷后启动；不要直接用空卷替换仍有待处理消息的 Redis。

DELETE 保留原模型采样行为：部分指定生长点可能无结果并持续重试，日志反复出现
`Delete Can Not Generate in this mission`，期间占用共享 GPU 锁。本次在完整 `2VT4` 配体的
指定生长点上观察到此情况。取消 Job 只更新平台状态；终止计算还需重新创建
`worker-delete` 容器。请先取消该 Job，再仅重建 DELETE Worker：

```bash
docker compose --env-file .env -f compose.yml up -d --no-build --pull never \
  --force-recreate --no-deps worker-delete
```

## 2. 发布者构建

以下命令在完整源码仓库根目录执行。先按上节创建 `deploy/.env`，设置本次版本及镜像仓库地址，
例如 `IMAGE_REPOSITORY=ghcr.io/your-org/genova`、`PLATFORM_VERSION=1.0.2`。
本地验证可以保持默认仓库名 `genova`。版本发布后不覆盖同名标签。

平台仓库不再包含 SurfGen/DELETE 模型源码。正常部署直接拉取最终镜像。
维护者更新 SurfGen adapter 时，先拉取已发布镜像作为基础：

```bash
export SURFGEN_BASE_IMAGE='你的镜像仓库域名/你的命名空间/genova:surfgen-1.0.2'
docker pull "$SURFGEN_BASE_IMAGE"
```

将示例中的标签替换为实际保留的已发布版本；构建配置要求显式指定该基础镜像，不自动选择历史版本。

DELETE 发布构建使用本地已清理的 `genova/delete:1.0.1`；制作记录见
[DELETE.md](DELETE.md)。这些构建前提仅适用于维护者，接收方无需准备。

ECloudGen 构建使用本地 `ecloudgen:latest` 环境镜像（可由 `ECLOUDGEN_BASE_IMAGE` 覆盖），
以及平台根目录下的 `ECloudGen_official/` 模型源码和 `ckpt/32_ldm_4channel_ddpm_100.pt`、
`ckpt/ecloudgen_decipher_ckpt` 两份权重。基础环境可用 `docker build -t ecloudgen:latest ECloudGen_official` 构建。
平台 Dockerfile 会补入 Redis 客户端、当前模型代码、两份权重及 adapter；模型目录继续不纳入平台 Git。
发布新版本时修改 `deploy/.env` 中的 `PLATFORM_VERSION`，再构建：

```bash
export SOURCE_REVISION=$(git rev-parse HEAD)
export BUILD_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker compose --env-file deploy/.env -f deploy/compose.yml -f deploy/compose.build.yml build \
  backend-api worker-protein-preparation worker-surfgen worker-ecloudgen worker-epso worker-delete worker-tarpass frontend
```

后端 API、后台服务与 Dispatcher 共用 `backend` 镜像，无需重复构建。
应用镜像标签记录发布版本、源码 commit 和构建时间；发布应用代码应来自已确认的源码版本。
离线包的 `image-manifest.jsonl` 记录镜像 ID、仓库 digest、架构及标签；本地新构建镜像在推送前可能没有仓库 digest。
模型本身或权重更新需要由模型维护者提供新镜像。
前端固定构建为 `/genova/`，由 Nginx 提供服务；修改代码后重新构建对应发布镜像。

**推送应用镜像：** 八个应用镜像共用一个仓库，以 `backend-1.0.2`、
`frontend-1.0.2`、`protein-preparation-1.0.2`、`surfgen-1.0.2`、
`ecloudgen-1.0.2`、`epso-1.0.2`、`delete-1.0.2`、`tarpass-1.0.2` 标签区分。先登录仓库。

使用新配置构建的镜像已经具有目标标签，可直接推送：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yml push \
  backend-api worker-protein-preparation worker-surfgen worker-ecloudgen worker-epso worker-delete worker-tarpass frontend
```

PostgreSQL 与 Redis 使用官方镜像，在线安装直接拉取。
向接收方提供本目录的 `compose.yml`、`.env.example`、`README.md`、`DELETE.md`、`SURFGEN_COMPATIBILITY.md`，并告知镜像仓库地址和版本。
不要发送自己的 `.env`。

**导出完整离线包：** 先确保官方镜像也在本地；导出参数使用本次版本和镜像仓库地址。

```bash
docker compose --env-file deploy/.env -f deploy/compose.yml pull postgres redis
bash deploy/export.sh deploy/dist/genova-1.0.2-single-repo 1.0.2 "$IMAGE_REPOSITORY"
```

第三个参数填写实际镜像仓库地址（本地构建默认是 `genova`），输出到新的版本目录。

导出脚本包含十个去重后的运行镜像、部署文件、空密钥模板、镜像名称和 ID 清单及 SHA-256
校验文件。它不读取实例 `.env`、数据卷或业务数据；目标目录已存在时拒绝覆盖。
镜像缺失或导出中断时不会产生完整发布目录。传送整个输出目录即可。

## 3. 验证与维护

在安装目录执行：

```bash
docker compose --env-file .env -f compose.yml ps
docker compose --env-file .env -f compose.yml exec -T backend-api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:18000/healthz').read().decode())"
docker compose --env-file .env -f compose.yml exec -T worker-surfgen \
  /opt/conda/envs/surfgen/bin/python -c \
  "import torch; assert torch.cuda.is_available(); torch.zeros(1, device='cuda'); torch.cuda.synchronize(); print(torch.cuda.get_device_name(0))"
docker compose --env-file .env -f compose.yml exec -T worker-epso \
  /opt/conda/envs/ecloudgen/bin/python -c \
  'import torch; print(torch.ones(1, device="cuda").item())' </dev/null
docker compose --env-file .env -f compose.yml exec -T worker-tarpass \
  python -c "import ctypes; assert ctypes.CDLL('libcuda.so.1').cuInit(0) == 0"
docker compose --env-file .env -f compose.yml exec -T worker-tarpass gnina --version
docker compose --env-file .env -f compose.yml exec -T worker-delete \
  python3 -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
```

验收：注册账号，使用内置 `3cl` 蛋白和配体完成蛋白准备，生成一个 SurfGen 分子，再提交
TarPass 后处理；再用上传的 PDB/SDF 完成蛋白准备与 DELETE 自动改造、指定生长点生成，
并将 DELETE 结果提交 TarPass；检查任务成功、有效 SMILES、CSV/SDF 下载，以及刷新结果页和实时状态更新。
下载的 SDF 可用模型容器中的 RDKit 验证：

```bash
docker compose --env-file .env -f compose.yml exec -T worker-tarpass python -c \
  "import sys; from rdkit import Chem; mols=list(Chem.ForwardSDMolSupplier(sys.stdin.buffer)); assert mols and all(m is not None and m.GetNumConformers() for m in mols); print(len(mols))" \
  < generated.sdf
```

升级前等待任务完成，修改 `.env` 中版本，拉取或导入对应镜像，再运行 `up -d --no-build`。
本次提供全新安装，不提供跨版本数据库迁移或历史实例备份恢复。

容器报告 NVML 或 CUDA 初始化错误时，先对照宿主机和同镜像临时容器，再决定是否重新创建受影响的 Worker。离线包内在同目录的 `README.zh-CN.md` 查看排查命令、恢复验证和 2026-11-24 的 EPSO / TarPass 案例。 [源码仓库 GPU 排障](../README.zh-CN.md#gpu-排障系统升级后容器无法使用-cuda)

## Genova 更名部署

升级前先排空运行任务并备份数据库、共享数据与密钥配置；保留上一版完整镜像供回退。镜像更新与业务数据迁移分别进行。

### EPSO Worker

`worker-epso` 和 `worker-ecloudgen` 分别消费自己的队列。EPSO 使用独立镜像，构建时复用同版本 ECloudGen 的模型环境和权重，以及 TarPass 的配体准备和 GNINA 环境。 [EPSO 镜像与部署](EPSO.md#参数来源与部署)

SurfGen 和 ECloudGen 的基础镜像只作为多阶段构建的环境来源；最终镜像使用 CUDA 12.1.1 base，
保留原 Conda 环境中的 CUDA 库、模型版本和权重，排除包缓存、重复基础层及 APBS 示例数据。
重新构建时建议通过 `SURFGEN_BASE_IMAGE`、`ECLOUDGEN_BASE_IMAGE` 指定已验证镜像的不可变 digest。
构建需要 Docker Buildx/BuildKit，以应用各 Dockerfile 对应的 `.dockerignore`。
开发 Compose 的所有平台服务也统一使用 `IMAGE_REPOSITORY` 和 `PLATFORM_VERSION`，便于整体切换和回退。

构建后重新创建 `worker-epso`；启动脚本同时检查其 CUDA。输入、目标语义、严格解码修正、
CSV → TarPass 流程及验证命令见 [EPSO.md](EPSO.md)。


## Agent 多轮预算与继续处理（c7bc945 后增量）

开发和发布环境均使用 `.env.example` 中的 `AGENT_*` 配置：单请求输出 8192、回合累计输出 32768、16 次模型请求、24 次工具尝试、240 秒活跃期限、300 秒租约；历史目标 24000 估算词元、输入硬上限 32768、最终字节保护 512000。租约必须至少比期限多 60 秒。

`AGENT_MODEL_CONTEXT_WINDOW=0` 表示窗口尚未核实；按可信端点能力设置后，会额外约束“估算输入 + 输出预留 + 1024 <= 窗口”。小输出能力模型通过 `AGENT_REQUEST_OUTPUT_TOKENS` 收紧。配置不根据用户提交的模型名称猜测。

这次更新须包含新 backend/frontend 镜像；只更新 Git 不会替换旧发行镜像。使用新的完整发布镜像集，在无活跃 Agent 回合的维护窗口更新（当前目录为 `deploy`）：

```bash
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml stop backend-api workflow-worker
docker compose --env-file .env -f compose.yml run --rm --no-deps backend-api python -m backend.workflows.migrate
docker compose --env-file .env -f compose.yml up -d --force-recreate --no-deps backend-api workflow-worker frontend
docker compose --env-file .env -f compose.yml exec -T backend-api python -m backend.agent.runner
docker compose --env-file .env -f compose.yml exec -T workflow-worker python -m backend.agent.runner
docker compose --env-file .env -f compose.yml logs --since 5m backend-api workflow-worker
```

新增迁移为历史复合索引，不删除旧账单或数据。日志核对 `Agent effective budget`；CLI 显示生效数值、SDK 版本和运行器代码哈希。环境变化须 recreate；新解释器的输出不能替代常驻进程更新验证。本轮不要求重建 GPU 模型镜像。

“继续处理”恢复的是未完成 Agent 回合：每任务链最多两次、每账户每小时十次；原账单与检查点保留，重新校验权限/版本/输入，规划身份跨恢复保持一致。它不会替代审批或自动重新提交已运行的科学任务。

## LLM API 多配置迁移

已有实例升级时，使用包含本次改动的 backend/frontend 镜像，在重启服务前执行迁移（当前目录为 `deploy`）：

```bash
docker compose --env-file .env -f compose.yml stop backend-api workflow-worker
docker compose --env-file .env -f compose.yml run --rm --no-deps backend-api python -c \
  'from pathlib import Path; from backend.db import engine; connection = engine.raw_connection(); cursor = connection.cursor(); cursor.execute(Path("/app/backend/migrations/20261012_agent_api_profiles.sql").read_text()); connection.commit(); connection.close()'
docker compose --env-file .env -f compose.yml up -d --force-recreate --no-deps backend-api workflow-worker frontend
```

迁移可重复执行，保留已有 LLM 配置和加密密钥；新建实例由现有建表流程创建所需表。

### Help 知识库

`/help`（默认地址 `/genova/help`）跟随平台语言设置，提供双语模型指南、参数说明、全部 TarPass 后筛指标和参考文献；只读接口为 `GET /api/v1/help`，不返回用户或任务数据。

模型参数放在各模型页内；`/help?group=metrics` 将 50 项指标定义按九类连续展示，覆盖 63 个筛选字段。`article=<条目 ID 或字段名>` 定位到对应卡片，Original 与 Docked 共用指标说明；`group=metrics&section=<分类 ID>` 定位到小节。

维护入口是 `VERSE/backend/agent/knowledge/help_catalog.json`。页面与 Agent 的 `list_project_knowledge` / `read_project_knowledge` 共用这些条目，默认值由运行时配置补入。后端启动时按内容哈希幂等入库；检索使用随当前版本发布的 Help 内容，历史引用仍可解析。`KNOWLEDGE_BACKEND=none` 会禁用 Agent 检索，不影响 Help 页面阅读。

发布时更新 backend/frontend 最终镜像；已有 Dockerfile 会包含知识文件，不需要数据库迁移、模型重建或接收方源码目录。开发环境的后端挂载修改后重启 `backend-api`；其他加载 Agent 代码的后台进程也需随版本更新。无需额外向量数据库或在线文献服务。

## 本地与局域网 ChatGPT OAuth

Agent 的 LLM 设置支持 API Key 和 ChatGPT OAuth。OAuth 用于个人本地及局域网自托管试用；不改变 Genova 账户登录。首次使用按官方动态注册流程申请用户授权，不需要 client secret 或合作伙伴 API Key。

开发部署使用 `VERSE/docker-compose.yml` 已有的 `18000` 端口。分发部署额外合并本机配置：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yml -f deploy/compose.chatgpt-local.yml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yml -f deploy/compose.chatgpt-local.yml up -d
```

先登录 Genova，再打开设置 → LLM 配置 → 新配置 → ChatGPT OAuth → Continue with ChatGPT。在弹出的 OpenAI 页面允许使用 ChatGPT plan，返回设置后选择模型并保存。新授权不会自动覆盖当前配置。回调固定为 `http://127.0.0.1:18000/api/v1/agent/settings/chatgpt/callback`，同机浏览器自动完成回调；局域网浏览器使用下面的手动提交流程。

后端镜像包含授权及推理代码，运行仍使用现有 PostgreSQL、Redis 和共享数据卷，无需安装 Codex CLI。源码开发更新后重启 `backend-api` 和 `workflow-worker`；分发镜像需要重新构建后使用新版本。启动会自动应用 `20261014_agent_chatgpt_oauth.sql`；手动维护数据库时先确保已应用 `20261012_agent_api_profiles.sql`，再应用此迁移。

凭据在 PostgreSQL 加密保存，刷新通过 Redis 锁串行执行；host ID 保存在 `DATA_ROOT/.auth/chatgpt-host-id`。同一实例重启或迁移应保留数据库、数据卷及 `JWT_SECRET`；复制成另一个独立实例时删除复制的 host ID，首次使用会重新生成。授权事务十分钟过期，access/refresh/ID tokens 不发送到前端。

局域网授权需将 `PUBLIC_BASE_URL` 设为管理员明确配置的入口（含应用前缀，例如 `https://genova.example.com/genova` 或 `http://100.81.91.51:18001/genova`）；后端按配置中的固定 Origin 校验来源，不根据请求 Host 或转发头生成交付地址。支持 HTTP 和 HTTPS，推荐使用可信 HTTPS。HTTP 会明文传输平台登录凭据和授权码，仅用于可信局域网。配置变更后重新创建 `backend-api`。开发 Compose 同样支持此变量。

远程用户从配置的平台地址点击 Continue with ChatGPT，完成授权后复制授权窗口地址栏中的完整回调 URL，粘贴到平台弹窗并点击“完成授权”。回调页即使显示拒绝连接，也可复制地址。不需要下载工具或建立 SSH 隧道；授权尝试 10 分钟内有效。错误地址可修正，过期或已消费的授权需重新发起。授权码不写入浏览器存储，服务器只解析提交的 URL，不访问它。

`POST /api/v1/agent/settings/chatgpt/start` 支持 `mode=local|manual`，默认 `local`；认证接口 `POST /api/v1/agent/settings/chatgpt/complete` 接受 `attempt_id` 和 `callback_url`，校验当前用户、尝试、回调地址及 state 后一次性完成授权。后续 Token 保存、刷新及模型请求仍由服务器处理。此手动提交为平台适配，需要在目标部署进行真实授权验收；不改变供应商的网络和地区要求。

订阅推理使用官方 `/v1/responses`，设置 `stream=true`、`store=false`，本地保存所需会话历史。测试连接也会消耗额度。接口不接受 `max_output_tokens`，客户端在响应后检查预算，超限后阻止后续模型与工具调用，但单次响应可能超出预算。额度耗尽或授权失效时停止，不自动切换到付费 API Key。用量及应用上限在 ChatGPT Settings → Usage 管理。

断开授权会尝试撤销远端 renewable session 并清除本地 tokens。若提示远端撤销未确认，请在 ChatGPT Settings 中断开此应用；注册身份与 client ID 会保留，重新授权复用原注册。

官方协议：[注册与授权](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[会话管理](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)、[推理限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)。

## Clash Verge / 用户级代理

按步骤操作请看 [代理设置指南](代理设置指南.md)，包含平台用户操作、管理员设置和其他代理软件的填写方法。

从 `feat/jev-decision-assist` 恢复网络代理设置，当前用于 LLM API、ChatGPT OAuth 的 token 交换、OIDC/JWKS、刷新、撤销和模型请求。用户在设置 → 网络代理中输入地址，也可从建议列表选择已允许地址，再保存开启或关闭；保存的代理独立于 LLM 配置，删除 LLM 配置不会删除代理设置。

部署管理员通过 `AGENT_PROXY_ALLOWED_URLS` 指定可选的无认证 HTTP(S) 代理地址，多个地址用逗号分隔；留空只允许直连。例如宿主机 Clash Verge 的 Mixed Port 为 `7897`：

```dotenv
AGENT_PROXY_ALLOWED_URLS=http://host.docker.internal:7897
```

Clash Verge 需开启 Allow LAN，并监听容器可访问的宿主机地址；容器里的 `127.0.0.1` 指向容器自身。开发与发布 Compose 的 `backend-api`、`workflow-worker` 已包含 `host.docker.internal:host-gateway` 映射。修改允许地址列表后重新创建这两个服务，用户选择代理后新的请求立即生效。

全新数据库随 API 启动创建 `agent_proxy_settings`；手动迁移使用 `20261013_agent_proxy.sql`。已有 JEV 分支的代理记录直接复用，不迁移或恢复 JEV 决策模块。

若浏览器授权成功但后端报 `unsupported_country_region_territory`，检查后端实际使用的用户代理。此前的授权 code 已使用，修正网络后需要重新开始授权。

若授权或代理设置接口返回 404，检查 `/openapi.json` 是否包含 `/api/v1/agent/settings/chatgpt/start` 和 `/api/v1/agent/settings/proxy`。服务健康但缺少这些路由，说明运行的镜像或源码挂载未包含此分支代码；重新创建对应服务。多个分支共用 `verse` Compose 项目时，启动另一个分支会覆盖当前 API 和 Worker 的挂载配置。


## LLM 推理设置

设置 → LLM 配置 → 读取模型能力，选择推理档位、思考开关或思考 Token 上限后保存。选择“模型默认”时省略对应参数；思考 Token 上限和推理强度是不同控制，不转换成统一档位。配置切换恢复已保存值，主动修改 Base URL 或模型时重置推理设置。

能力按 Base URL、模型 ID 和 API 协议识别，优先使用供应商模型列表返回的能力字段，没有这些字段时使用经官方文档确认的内置规则。来源显示为服务端元数据、平台内置或用户声明；未知服务不猜测档位。模型列表查询不发送推理请求，连接测试会使用选定参数并可能计费。

高级设置允许自定义服务声明协议和控制类型：`reasoning_effort`、`reasoning.effort`、`thinking.type`、`enable_thinking`、`thinking_budget`，填写支持值及预算范围。不能覆盖模型、消息、工具、请求地址或凭据；已识别官方模型的限制不能用声明绕过。声明和测试连接成功不证明供应商实际执行了参数。保存时校验并保留能力快照，运行时不重复查询模型列表；供应商变更能力后需重新读取并保存。

OpenAI 官方 `gpt-6-luna` 自动使用 Responses，以支持推理与工具调用；DeepSeek 使用 Chat Completions。Qwen、GLM 按具体接口规则选择协议和控制参数，自定义网关通过高级设置声明自己的协议。所有 Agent 阶段共用同一个模型配置，保留现有用量预算；显式思考预算的可选上限同时受平台单请求输出预算约束。

新增接口为 `POST /api/v1/agent/settings/capabilities`，现有读取、保存和测试接口增加可空 `reasoning` 配置。API 启动自动应用 `20261014_agent_reasoning.sql`，向配置表和激活设置表添加可空 JSONB 字段；已有 API Key 密文及配置保持不变，旧配置继续使用模型默认。源码部署修改后重启 `backend-api` 和 `workflow-worker`，发布镜像需重新构建 backend 与 frontend。

OAuth、代理及推理设置已合并到 `main`；ChatGPT OAuth 仍仅用于个人本地试用，局域网远程浏览器可通过配置的平台地址手动提交本机回调地址。公网部署使用 API Key 配置，不启用本机 OAuth 部署覆盖配置。公网迁移使用 API Key 配置，不携带本地 OAuth 授权记录。GPT API Key 仍受供应商地区政策和服务器网络出口限制；不自动使用代理、转发服务或替换模型。

## 两周数据保留

默认 `DATA_RETENTION_ENABLED=false`，不会自动删除数据，也不显示保留声明。需要开启时，在本部署 `.env` 设置 `DATA_RETENTION_ENABLED=true`，在发布目录执行：

```bash
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml up -d --force-recreate --no-deps backend-api backend-worker workflow-worker
```

API、后台和工作流服务必须使用同一开关。无需修改前端构建参数；前端读取后端策略，仅在数据上传、模型运行、结果和 Agent 页面显示声明，并向首次进入的用户弹窗提示。

文件自上传完成、结果自任务结束保留 14 天；Agent 会话在最后一次用户互动 14 天后整体删除，后台轮询不续期。首次开启时，历史数据获得至少 14 天宽限期；首次开启时间随数据库迁移，服务重启或重新开启不重置。仍被有效任务、结果或会话引用的数据延后删除，正常情况下每小时清理一次。

清理包含数据库记录及上传、结果、中间文件、预览缓存和执行回执内容；执行回执与 Redis 只保留阻止重复执行的无内容过期标记。失败的文件删除自动重试。账号、API 配置、内置数据和模型代码、权重不清理；外部备份和已下载文件不受此机制影响。删除不可恢复，关闭开关只能停止后续清理。

首次升级到支持此功能的版本时，需部署对应的后端、Dispatcher、模型 Worker 和前端镜像，再开启开关；各 Worker 的新版队列入口用于识别过期回执，不改变模型推理逻辑。发布交付仍只需最终版本镜像、部署配置及适配的宿主 GPU 驱动，已有实例另行迁移数据库、共享数据和密钥配置。


## 资源准入与主动删除

访客同时允许 1 个未结束计算，正式账号允许 3 个；一次 Context 兼容性校验共用一个名额，PLIP 预览单独占用名额。取消后实际进程仍运行时继续占用。
存储默认上限为访客 500 MB、正式账号 5120 MB，统计自有数据集、任务产物及等待清理文件，硬链接去重。超限拒绝新计算与上传，已接受的计算可完成。

删除采用 `POST /api/v1/jobs/deletions/preview` 预览，再携带返回的 `confirmation_token` 调用 `POST /api/v1/jobs/deletions`。请求均传 `job_ids`。确认整组删除关联下游任务、执行会话和专属文件；原始上传、内置输入和未选中的共享输入保留。运行中的关联计算阻止删除。
预览有效期 10 分钟，依赖或文件变化返回 `409 DELETE_PREVIEW_CHANGED`，须重新预览确认。旧 DELETE 入口同样要求确认令牌。
数据库删除与清理记录一起提交，文件在提交后清理；`cleanup_status=pending` 表示后台每 30 秒重试，独立于 `DATA_RETENTION_ENABLED`。不会批量清除历史软删除记录。

访问令牌绑定密码指纹，不含指纹的旧访问令牌失效；仍有效的刷新令牌可自动续期，已撤销的会话需要重新登录。旧 v3 Context 仍可读取和下载，创建新计算必须使用当前 v4 Context。

维护端模型镜像构建需要 Docker Buildx／BuildKit；接收方运行最终镜像，无需构建工具或历史镜像。


### 智能体只读排障与上下文预算（2026-10-28）

智能体可按名称查找本人可访问的 Job 及关联准备资源，读取子任务错误、日志和报告。诊断源限定在该 Job 工作目录中的日志与准备报告，按来源 ID 读取，过滤敏感信息；搜索及分页返回行号、字符位置和文件版本。输入日志视为数据，不授予执行权限。调查达到预算时保存阶段性证据与读取位置，下一轮可续查；不会自动修改参数或重跑计算。历史任务未保留的日志无法还原。

模型窗口保存在现有 API 配置档的 `context_window` 字段。保存时优先使用 `/models` 的 `context_window` 元数据，接口未提供时可填写经确认的模型总窗口。切换模型或服务地址后重新确认窗口。API 自动应用 `backend/migrations/20261028_agent_context_window.sql`；关闭自动建表的部署需自行执行该迁移。窗口未确认的配置档维持最多 32K 输入预算，不再使用跨模型共享的窗口声明。

平台默认单次输入上限为 131072 token、压缩目标为 98304 token、序列化请求上限为 2097152 bytes，分别由 `AGENT_CONTEXT_MAX_INPUT_TOKENS`、`AGENT_CONTEXT_TARGET_TOKENS`、`AGENT_CONTEXT_BYTES` 控制。输入上限还会扣除模型窗口内的输出预算和安全余量。每次日志读取最多约 6000 token，截断时可按返回位置继续读取。上述为工程初始预算，不代表模型质量或最优排障长度保证。

ECloudGen 口袋生成只构建和缓存蛋白口袋通道，不计算或校验未参与生成的参考配体 xTB 电子云。参考配体可选：有配体时保留按重原子中心截取口袋的方式，无配体时使用保存的位点中心。历史上因缺少参考配体而验证失败的 Context 需重新保存并验证；已有成功缓存仍可使用。SurfGen / ECloudGen 可使用共价配体的原位重原子几何定位口袋；蛋白准备移除共价连接后恢复标准残基并重新质子化，无法可靠恢复时任务失败。DELETE、EPSO 和 TarPass 的分子参考仍执行化学结构校验。ECloudGen 模型或构建补丁变化后，依次重建 ECloudGen 和 EPSO 镜像，再重新创建 `worker-ecloudgen worker-epso`。挂载的 runtime 变化后，重启受影响的 Worker。模型输入缓存由 `context_features.CACHE_VERSION` 和 `CONTRACT` 控制兼容性，源码修改不再触发失效；输入格式或特征计算语义不兼容时升级缓存版本，已有 Context 再重新保存并验证输入。直接调用模型其他 xTB 路径时，失败日志仍由镜像补丁保存在 `xtb_failure_*.log`。

问答正文默认面向入门研究者，先回答当前问题并解释必要术语；参数定义在说明含义和影响后结束，建议和排障再给具体下一步，不设固定句数。补充背景通过 `diagnostic_notes` 字段与正文分开返回，与已读取的任务错误、日志摘录、来源和行号一起在默认折叠的“依据与详情”中查看。普通问答不带入此前排障记录。
历史诊断长答保存在会话中，模型上下文仅保留引用；需要追问时通过现有历史工具按回合、正文或诊断说明分段读取，避免重复长答主导后续回复。
问答读取工具事实后，增加一次无工具的文字整理调用，沿用同一模型和回合预算。调查阶段返回经过校验的 SessionDecision／SessionReply，正文整理只输出文字，由后端填入 message，避免再次生成 JSON 的转义错误。整理保留第一阶段的操作决策与补充详情；参数定义、结果分析和失败排查共用这一表达路径。排障整理只接收本轮读取的失败任务、日志全文及来源列表，保留“具体日志未保留”等上下文；其他工作流或步骤成功不参与失败原因判断。正文整理不可用时保留已完成的调查回答。
公共回复表达由 `backend/agent/prompts.py` 的 `REPLY_STYLE` 统一配置，对话、规划与正文整理共用该规则，默认照顾入门研究者。默认系统提示词、六个 Skills 和模型工具说明均为英文；回复语言由当前会话自动判断，短确认或纯标识符消息沿用最近实质提问的语言，无需语言设置。
场景方法由 `backend/agent/skills/` 提供。对话和规划共用 Skills 目录，由模型按当前问题语义调用 `read_skill` 加载，支持不同语言的问题。Skill 获得当前实际工具列表，规划根据是否提供 `preview_workflow` 分别走候选验证或会话后端。历史诊断证据与读取位置在加载 `failure-triage` 后提供，普通问题保留历史引用。结果统计与来源由后端填入结果卡片，正文保留面向研究目标的解释。修改后重启 backend-api、backend-worker 和 workflow-worker。
