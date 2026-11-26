# EPSO 实施与验收报告

完成日期：2026-09-19。未创建 commit；未新增生产依赖、数据库表、migration 或 HTTP 接口。
接口示例、完整 objective 矩阵、runtime 输入输出、参数来源和部署命令见 [EPSO.md](EPSO.md)。

本报告记录 2026-09-19 的初版验收。当时 EPSO 运行在独立 Worker 中，使用 ECloudGen 镜像，验收范围为二维性质优化。加入可选 GNINA 评分后的镜像和 CUDA 验证命令见 [当前 EPSO 部署说明](EPSO.md#参数来源与部署)。

## 架构与范围

```text
/molopt: DELETE | ECloud EPSO
  → POST /api/v1/jobs (property_optimization)
  → JobTask(task_code=property_optimization, runtime_task=epso)
  → QueueOutbox → Dispatcher → genova:queue:epso
  → worker-epso (ECloudGen 共用镜像、GPU 0 共享文件锁)
  → 独立子进程: seed embedding → latent move → decode → re-encode → fitness
  → CSV + trajectory + metadata → backend-worker → SmallMoleculeResult
  → /molopt/results → TarPass CSV → 构象生成、对接与评估
```

初版 EPSO 的计算范围为二维优化，验收产物为 CSV、轨迹和 metadata。三维构象、对接和 PLIF 在后续 TarPass 任务中完成。

## 分阶段报告

| 阶段完成内容 | changed files | 本阶段测试及结果 | 尚未解决的问题与下一阶段门槛 |
|---|---|---|---|
| Phase 1：目标编译、严格解码、官方优化流程与记录、独立子进程 | `entry_epso.py`、`epso_objectives.py`、`coati_purifications.py`、`test_helpers.py` | 九项×六模式、指定评分点、自定义 softness、非法值、真实甲烷与失败标记、异常传播、真实 BasePSOptimizer + fake inference、最后一轮新分子、重新编码、去重、轨迹、复现、dry-run、进程异常和锁释放通过 | 官方源码在镜像内，进入 Phase 3 重建后再验证严格接口；已完成 |
| Phase 2：后端分支、来源和参数校验、Outbox、结果与分页 | `jobs.py`、`result_rows.py`、现有后端测试、`queue_worker.py`、`queue_dispatcher.py` | 输入拒绝、单 SDF/单记录、覆盖来源、权限、公共/内部任务名、结果数值化、成功/失败/重复消息、DELETE smiles-only CSV 通过 | 真实 API 发现 JSON 原地修改未持久化；已修复并增加 SQLAlchemy committed-state 回归断言 |
| Phase 3：两套 Worker 配置、启动检查和镜像 | 两套 Compose、`start-backend.mjs`、`.gitignore` | 开发/发布 `docker compose config -q` 通过；共用镜像构建通过；镜像严格解码、checkpoint 加载和容器 CUDA 通过 | 无独立 Dockerfile、无重复 build；所有 GPU 阶段均使用同一锁路径；门槛已满足 |
| Phase 4：表单、目标、引擎隔离、恢复、结果和下载 | 两个 molopt Vue 文件、中英文 catalog | Vite build、i18n、现有前端检查通过；真实 Chromium 检查 EPSO 恢复、显式 seed、引擎切换、HBD/区间字段、三个下载、动态列、CSV TarPass 链接，无浏览器异常 | DELETE 恢复以真实 Context/候选/Ketcher + Job 响应 fixture 验证，不新增 DELETE GPU 优化任务 |
| Phase 5：回归和兼容性 | 扩展现有后端测试与 `test_helpers.py` | unittest 65 项，成功，跳过 1 项；临时 venv pytest：64 passed、1 skipped、46 subtests passed；vue-tsc 113 条原有错误，输出与基线完全相同，molopt 无错误 | 既有 typecheck 错误及环境跳过项未扩大范围修复；临时测试脚本清理，不增加生产依赖 |
| Phase 6：真实 API/GPU/TarPass 验收 | 无额外生产代码 | 两次 8 粒子×2 步×seed 2024，CSV/轨迹逐字节一致；真实结果分页、artifact 下载、跨账号拒绝、来源恢复通过；TarPass 生成 5 个三维对接分子；进程退出和锁释放通过 | 单机单卡串行；不承诺跨硬件逐位复现，无未完成的接入阻塞项 |

各阶段文件的完整 diff stat 统一列于末尾，包含未暂存的新文件。`AGENTS.md` 按项目约定仅本地更新，不纳入版本控制。

## 实际测试

- `docker compose -f VERSE/docker-compose.yml exec -T backend-api python -m unittest backend.tests.test_protein_context backend.tests.test_protein_context_jobs -q`：65 项，成功，1 项环境跳过。
- `pytest VERSE/backend/tests` 的容器等价路径 `/tmp/epso-pytest/bin/python -m pytest backend/tests -q`：64 passed、1 skipped、46 subtests passed。pytest 仅安装到 `/tmp` 临时 venv。
- `docker compose -f VERSE/docker-compose.yml exec -T worker-epso python -c 'from genova_runtime.test_helpers import check_epso; check_epso()'`：通过。
- `npm run build`、`npm run check:i18n`、`node scripts/check-tarpass.mjs`：通过。
- `vue-tsc --noEmit -p tsconfig.app.json`：113 条既有错误，使用 `/tmp/epso-baseline-typecheck.log` 比较，最终输出完全相同。
- 开发与发布 Compose：通过。发布配置校验使用临时占位环境变量，不输出真实凭据。
- Chromium：真实 EPSO 页面与下载通过；真实显式数据集 seed 恢复通过；DELETE fixture 恢复与 Ketcher 兼容性通过。

## GPU 与端到端结果

测试输入为仓库内置 3cl 蛋白和参考配体，通过真实 API 创建独立验收 guest、Protein Context 和准备任务。

| 项目 | 结果 |
|---|---|
| Protein Context | `e6eebbfa-2cda-44e5-9cb6-bca192cfce74` |
| 蛋白准备 Job | `a0ccfaec-8577-45eb-aa39-1ba0f111a1c3`，succeeded |
| EPSO 第一次 | `dbece3b5-6f31-4bec-bf6f-964bbe0f9628`，pending → running → succeeded |
| EPSO 第二次 | `041a1a79-631c-4008-ba8a-09b60534dca2`，pending → running → succeeded |
| 配置 | 8 粒子、1 swarm、2 步、最多返回 5、seed 2024、QED ≥ 0.6 |
| 每次输出 | 5 个有效且 canonical 去重分子，17 个唯一评估分子，0 次解码失败 |
| 轨迹 | step=0、1、2，包含最后更新；两次 CSV 和 trajectory 逐字节相同 |
| 子进程内耗时 | 约 5.74 秒、5.72 秒；不含排队时间 |
| 基线提示 | seed QED 已超过 0.6、fitness=1；页面正确提示没有评分提升，仍产生新分子 |
| EPSO 三维 | 无 `generated.sdf`，无 `generated_sdf` 字段 |
| 显式 seed 覆盖 Job | `e6c5021a-a27e-48ad-a57a-29905706863b`，succeeded，实际文件来源恢复通过 |
| TarPass Job | `383a351e-6172-4063-88db-ec2dc4785d30`，succeeded |
| TarPass 输入/输出 | 原 EPSO 完整 CSV；5 个 RDKit 可读三维对接分子；manifest 无 `--score_only` |
| 下载与权限 | CSV、trajectory、metadata 成功下载，其他 guest 读取 artifact 返回 404 |
| 资源释放 | 无 EPSO 子进程遗留，GPU 文件锁可立即非阻塞获取；显卡剩余 156 MiB 属于非 EPSO 进程，不以整卡归零为条件 |
| 软件 | Python 3.12.9、Torch 2.2.2、CUDA 12.1、RDKit 2024.09.5、NumPy 1.26.4 |
| checkpoint SHA-256 | `e8560ed861b85260fd05ab13d4ebec4e7fe6e251163f45713fc690c5fc2b0e5a` |

首个探测 Job `012e94e1-b071-483d-8ff9-028ce037e3aa` 推理成功，但暴露恢复来源未写入数据库的问题。
修复后以上两次正式验收及显式 seed Job 均验证了持久化。测试产生的数据保留在各自 Job 目录。

## 限制与后续

- 保持 Context 必填、单文件单分子 SDF、单 swarm、GPU 0 串行。
- 相似度只是评分，不保证骨架或三维姿态保留。EPSO 输出二维结果，TarPass 的三维属于后处理结果。
- seed 属于排行榜；不足目标数不补跑，无新分子/无提升/缺口分别提示。
- 20 步和 `[-10,10]` 是官方示例默认值，不是全 latent 空间校准结论。
- Ligand-only EPSO、ADMET oracle、批量 docking/PLIF oracle、Pareto 均未实现。
- 初次验收时曾仅放行 `coati_purifications.py`。后续已改为 `deploy/ecloudgen-runtime-patch.py` 构建时应用补丁，恢复整体忽略模型目录。以下 diff stat 保留初次验收时的快照。

## 完整 diff stat

```text
.gitignore | +8 -1
VERSE/backend/result_rows.py | +7 -0
VERSE/backend/routers/jobs.py | +59 -14
VERSE/backend/tests/test_protein_context_jobs.py | +89 -2
VERSE/docker-compose.yml | +16 -0
VERSE/genova_runtime/README.md | +7 -0
VERSE/genova_runtime/queue_dispatcher.py | +2 -0
VERSE/genova_runtime/queue_worker.py | +4 -1
VERSE/genova_runtime/test_helpers.py | +119 -0
deploy/README.md | +6 -0
deploy/compose.yml | +14 -0
genova_frontend/scripts/start-backend.mjs | +1 -0
genova_frontend/src/i18n/locales/platform.en-US.js | +43 -0
genova_frontend/src/i18n/locales/platform.zh-CN.js | +43 -0
genova_frontend/src/pages/molopt/index.vue | +118 -19
genova_frontend/src/pages/molopt/results.vue | +31 -7
ECloudGen_official/models/ECloudDecipher/generative/coati_purifications.py | +159 -0
VERSE/genova_runtime/entry_epso.py | +154 -0
VERSE/genova_runtime/epso_objectives.py | +134 -0
deploy/EPSO.md | +116 -0
deploy/EPSO_VALIDATION.md | +105 -0
21 files changed, 1235 insertions(+), 44 deletions(-)
```
