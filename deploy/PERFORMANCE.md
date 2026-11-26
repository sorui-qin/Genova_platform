# 平台性能与镜像瘦身验证

文中的回归测试和 benchmark 命令在 `test` 分支执行。

本次保留 `genova_frontend/`、`VERSE/` 和独立模型 Worker 的边界，没有新增服务架构或修改公共 API。
前端与后端已通过公共 API 分离，当前单机部署没有进一步拆仓库或拆服务的必要；模型仍按依赖环境独立构建。

## API 与前端

数据集列表和内置数据集列表批量查询文件；保留归属校验、分页与 Protein Context 当前文件筛选。
同一 PostgreSQL、回滚事务内的固定测试数据，预热一次后测量 15 次；以下为路由函数耗时，不含网络和鉴权。

| 数据集数 | SQL 次数：改前 → 改后 | p50：改前 → 改后 | p95：改前 → 改后 |
| --- | --- | --- | --- |
| 1 | 2 → 2 | 0.63 → 0.64 ms | 0.85 → 0.72 ms |
| 20 | 21 → 2 | 5.73 → 1.21 ms | 5.89 → 1.88 ms |
| 200 | 201 → 2 | 50.36 → 6.25 ms | 70.09 → 6.59 ms |

三维查看器在打开视图时加载；InteractionDrawer 在第一次绘图时加载，多实例共享请求，失败后可以重试。
生产 Nginx 对静态脚本、样式、SVG、JSON 和 WASM 启用 gzip；哈希资源长期缓存，HTML 与固定文件名资源重新校验。
清除了无引用的旧 PDF 脚本、示例 PDB、示例页面与 LaMGen 静态数据；保留 Ketcher 和 RDKit WASM。

## 验证命令

```bash
cd genova_frontend
npm run build
cd ..
docker compose -f VERSE/docker-compose.yml config --quiet
docker compose -f VERSE/docker-compose.yml exec -T backend-api \
  python -m unittest discover -s backend/tests -v
```

发布镜像不包含测试文件，镜像验收时将已有测试目录只读挂载到 `/tmp/tests` 后执行。
原环境和候选后端镜像均完成 66 项测试：65 项通过，1 项跳过。
浏览器验证覆盖绘图库延迟加载、并发单请求、网络失败重试、加载期间卸载、gzip、缓存头及 Ketcher 分子读写。
真实 DELETE 结果验证三维加载；真实 TarPass 结果验证三维视图与二维相互作用图，InteractionDrawer 按需请求一次。

## 镜像构建

SurfGen 与 ECloudGen 使用多阶段构建，保留原模型环境和权重，最终阶段使用 CUDA 12.1.1 base。
Conda 环境内已有 CUDA 库；最终镜像不再继承重复 CUDA runtime 层。
SurfGen 保留 Conda、两个模型环境、PDB2PQR、APBS 和 MSMS，排除约 1.2 GB 的 APBS 示例数据。
`perf-20260919` 的 ECloudGen 与 EPSO Worker 使用同一个镜像，排除基础 Conda 环境、包缓存与旧源码/权重层。加入可选 GNINA 评分后的 EPSO 构建见 [当前部署说明](EPSO.md#参数来源与部署)。
DELETE 沿用已有筛选运行文件的镜像；TarPass 保留 Gnina 及其 CUDA runtime，只排除 pip 缓存和测试文件。

构建需要 Buildx/BuildKit，以使用 Dockerfile 专属 `.dockerignore`；源模型镜像应指定已验证 digest。
此次 TarPass 构建复用了原镜像内同版本 Gnina 1.3 二进制，避免重复下载；默认构建仍使用官方发布地址。

## 镜像体积

下表对比已发布 `1.0.2` 与本次 `perf-20260919`，单位为十进制 GB。
记录 `docker image inspect --format '{{.Size}}'` 的原始指标；本机 Docker 29 使用 containerd image store，
此值不等同于 `docker image ls` 显示的本地总占用，也不代表独立 `docker save | gzip` 离线包实测大小。

| 镜像 | 改前 | 改后 |
| --- | ---: | ---: |
| backend | 0.126 | 0.126 |
| frontend | 0.047 | 0.048 |
| protein-preparation | 0.148 | 0.148 |
| SurfGen | 6.120 | 4.182 |
| ECloudGen / EPSO（当时共用） | 7.573 | 4.897 |
| DELETE | 3.402 | 3.402 |
| TarPass | 2.494 | 2.493 |

七个应用镜像的该指标合计从 19.91 GB 降至 15.30 GB，约减少 23%。
主要收益来自移除模型基础镜像重复环境与历史层；没有强行裁剪模型运行依赖。

本机 `docker image ls` 的总占用显示：SurfGen 19.5 → 13.7 GB，ECloudGen 21.4 → 14.3 GB。
该口径可能包含跨镜像共享层，不能直接作为文件系统释放空间承诺；旧镜像保留用于回退。
SurfGen 的 APBS 调用改用现有 `genova_runtime.pdb2pqr_compat`；其内容 SHA256 与旧镜像同名功能模块一致。

## 完整链路与本机切换

隔离 PostgreSQL、Redis 和数据目录中，以仓库 `SurfGen/example/3cl.pdb` 与 `3cl_ligand.sdf` 完成上传、Protein Context 和蛋白准备。
SurfGen 生成 1 个、ECloudGen 生成 1 个、EPSO 返回 3 个、DELETE 生成 1 个，任务均成功回写；TarPass 完成对 DELETE 结果的后处理。
检查了无效数量拒绝与跨用户数据集访问拒绝；SurfGen 首次候选镜像缺少旧模块引用时，任务正确进入失败状态，修复后新任务成功。
所有模型的 CSV 下载正常；SurfGen/DELETE 下载 SDF 均可由 RDKit 读取。
五种结果页通过真实浏览器检查，三维库只在打开视图后加载，TarPass 二维相互作用图正常。
SurfGen/ECloudGen 权重和 Gnina 二进制 SHA256 与原运行容器一致。
这些是小规模功能验收，不代表大批量生成吞吐基准。

2026-09-19 本机 `VERSE/.env` 已切换为 `IMAGE_REPOSITORY=genova`、`PLATFORM_VERSION=perf-20260919`，
重建 API、后台服务、Dispatcher 及所有模型 Worker 容器；未重建 PostgreSQL/Redis。
切换前无活动任务；切换后 API `/healthz` 正常，Worker 在线，GPU 容器检查通过。
生产历史任务仍为 succeeded 71、failed 25、canceled 3。
前端完成生产镜像构建与隔离 Nginx 验收；本机原先没有运行永久前端服务，本次未额外启动。

旧镜像保留，原环境文件和精确镜像清单位于未纳入 Git 的 `deploy/dist/performance-20260919/`。
需要回退镜像与配置时，在仓库根目录执行：

```bash
cp deploy/dist/performance-20260919/previous.env VERSE/.env
docker compose -f VERSE/docker-compose.yml \
  -f deploy/dist/performance-20260919/rollback.yml up -d \
  --force-recreate --no-deps --no-build --pull never \
  backend-api backend-worker dispatcher worker-protein-preparation \
  worker-surfgen worker-ecloudgen worker-epso worker-delete worker-tarpass
```

开发 Compose 挂载当前源码，上述命令只回退镜像和配置；源码回退需单独处理。
临时验收容器、数据与测试脚本在验收后清理，已有测试文件的回归用例保留。

2026-09-20 已清理九个未被运行容器使用的平台旧镜像，文件系统可用空间增加约 3.1 GB。
保留当前发布镜像、切换前回退镜像及维护者构建依赖；未删除远端镜像、构建缓存或数据卷。

## 镜像推送

2026-09-19，经用户明确授权，七个应用镜像已推送到：

```text
crpi-694j0nltrobkbz8r.cn-hangzhou.personal.cr.aliyuncs.com/genova-platform/genova
```

标签分别为 `backend-perf-20260919`、`frontend-perf-20260919`、`protein-preparation-perf-20260919`、
`surfgen-perf-20260919`、`ecloudgen-perf-20260919`、`delete-perf-20260919`、`tarpass-perf-20260919`。
此次发布的 EPSO Worker 使用 `ecloudgen-perf-20260919`。推送保留了原有的 `1.0.2` 标签。
七个远端镜像索引与全部子清单的 SHA256 均已核对，索引 digest 与本地镜像一致。
期间出现 TLS 超时和读取限流，降低校验频率后全部通过。
推送日志与 digest 清单保存在本机 `deploy/dist/performance-20260919/push-results.json` 和 `remote-verification.json`。
本次推送未修改运行中服务的镜像配置。

## 2026-09-21：首次访问与模块切换

此次检查确认了以下前端开销：数据中心初始化补写 URL，根路由 key 又强制重建页面；
守卫、布局及 Dashboard 重复请求 `/auth/me`；空白模块提前加载三维库；
Vite 全局 `no-store` 阻止依赖缓存，虚拟路由的依赖在首次访问时才被发现并触发整页重载。
首页还默认加载开发工具，并通过 CSS 引入 Google Fonts。

修复保持现有后端 API：

- 数据中心只加载当前标签，移除初始化导航；保留模块任务恢复所需的 `fullPath` key。
- `/auth/me` 合并并发请求，按凭据在内存复用 30 秒；登录、退出、恢复码切换和认领时失效。
  旧请求及旧 Token 刷新不会覆盖新账户；同账户刷新完成后的迟到 401 可以用新 Token 重试。
- 共用蛋白查看组件在首次加载结构时才导入 Molstar，并等待画布初始化；生产分包隔离三维库，
  避免通用运行时 helper 将其重新带入首屏。
- Vite 启动时扫描页面依赖，恢复默认缓存；开发工具改为显式启用，字体使用系统字体栈。
- 首页顶部和底部主按钮统一进入 Dashboard，底部重复按钮移除。
- GPU Worker 检查并发执行，保留失败重建、复检及整体非零退出。
- 三个组件移除冗余 `defineProps`、`defineEmits`、`defineExpose` 导入，独立编译无 `compiler-sfc` 警告。

### 本机对照

以下为单次对照，不是统计性性能承诺。浏览器使用新上下文，服务已启动，
按首页、数据中心、生成、优化、蛋白准备、Dashboard、数据中心顺序整页访问。
“可见”记录页面标题出现的时间，不代表三维结构加载完成；传输量包含资源响应头，后续页面可复用前页缓存。
测试游客个人数据和任务列表为空，内置数据集为 6 条。

| 页面 | 标题可见：改前 → 改后 | 传输量：改前 → 改后 |
| --- | --- | --- |
| 首页 | 322 → 211 ms | 8.85 → 5.40 MB |
| 数据中心首次 | 1937 → 215 ms | 22.64 → 2.00 MB |
| 从头生成空白表单 | 1066 → 286 ms | 22.03 → 0.27 MB |
| 先导优化空白表单 | 770 → 251 ms | 22.30 → 0.27 MB |
| 蛋白准备空白表单 | 1065 → 251 ms | 22.43 → 0.27 MB |
| Dashboard | 289 → 138 ms | 9.90 → 0.54 MB |
| 数据中心再次进入 | 607 → 163 ms | 22.64 → 0.05 MB |

数据中心首次 `/auth/me` 请求由 4 次降至 1 次，数据集请求由 4 次降至当前标签的 1 次；
Dashboard 用户请求由 3 次降至 1 次。同页标签切换复用列表与用户信息。
空白页面仍加载轻量查看器外壳，Molstar 库和画布仅在需要结构时加载。

在没有活动任务、容器已运行的同一宿主环境中，真实旧启动脚本耗时 11.64 秒，
新脚本耗时 5.48 秒，全部 CUDA 检查通过；不包含首次拉取镜像或创建数据库的成本。

后端使用临时游客连续读取 5 次，`/auth/me`、个人数据集、内置数据集和任务列表的中位耗时
分别为 8.64、9.90、7.35、3.22 ms。个人空列表不能代表大账户性能；此次没有依据新增后端缓存或索引。

### 验证与使用

已通过开发与生产 Nginx 浏览器验收：首次/再次打开真实 PDB、标签历史、Dashboard 入口、
空缓存 Vite 首次访问、用户请求去重、游客并发初始化、恢复码身份切换、Token 刷新及迟到请求保护。
列表失败后切换标签可重试。动态模块下载失败会被浏览器缓存，页面明确提示刷新后重试，已验证刷新恢复；
不会自动刷新页面。生产首页和列表不提前请求 Molstar 库，gzip 和哈希资源长期缓存正常。
启动故障分支使用模拟 Docker 覆盖成功、失败后恢复及最终失败，验证全部检查结束后才退出。

```bash
cd genova_frontend
npm run build
npm run check:i18n
node scripts/check-auth.mjs
npm run dev
# 需要 Vue / Query 开发面板时：
VITE_DEVTOOLS=true npm run dev
```

保留最小鉴权回归检查 `scripts/check-auth.mjs`；临时浏览器脚本、游客及 Nginx 验收容器在完成后清理。
全量 `vue-tsc --noEmit -p tsconfig.app.json` 仍有 113 条原有诊断；与修改前源码副本对比，无新增诊断。
构建仍提示原有 Tailwind 歧义类及大型三维资源 chunk，未屏蔽这些警告。
修改后需重新启动 Vite；本次未构建或发布模型镜像，也未改动数据库结构。
