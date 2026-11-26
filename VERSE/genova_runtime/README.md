# 平台 Runtime

文中的回归测试和 benchmark 命令在 `test` 分支执行。

平台通过 `POST /api/v1/jobs` 创建任务，后端解析 Dataset ID 与 Protein Context，再通过 Redis 分发到独立 Worker。

| 公共 job_type | 内部 task / 队列后缀 | adapter | Compose 服务 |
| --- | --- | --- | --- |
| `protein_preparation` | `protein_preparation` | `entry_protein_preparation.py` | `worker-protein-preparation` |
| `molecule_generation` | `surfgen` | `entry_surfgen.py` | `worker-surfgen` |
| `molecule_generation` | `ecloudgen` | `entry_ecloudgen.py` | `worker-ecloudgen` |
| `property_optimization` | `delete` | `entry_delete.py` | `worker-delete` |
| `property_optimization` | `epso` | `entry_epso.py` | `worker-epso` |
| `molecule_postprocessing` | `tarpass` | `entry_tarpass.py` | `worker-tarpass` |

`job_type` 必填；分子生成接受 `params.molecule_generation.engine="surfgen"` 或 `"ecloudgen"`。仅保留当前四个模块的平台接入。历史任务、已入库结果和文件仍可通过通用接口读取；旧模型专用页面、执行入口和结果解析已移除。独立模型目录不属于平台运行代码。

## Protein Context 准备与 SurfGen 兼容性

`entry_protein_preparation.py` 使用 PDBFixer → PDB2PQR 3.6.2 / PARSE → OpenMM（重原子约束、50 次最小化）→ `--assign-only` 最终参数验收。共用实现为 `pdb2pqr_compat.py`。

- 重新加氢前移除原有 H/D；默认只自动转换已验证白名单中的 `MSE → MET`（`SE → SD`、元素 `SE → S`）。`SEP`、`TPO`、`PTR`、`SEC` 及其他缺少可靠母体映射的修饰默认保留，并记录原因和下游影响。
- 按 TER、末端 OXT、相邻 C–N 距离大于 2.0 Å 或缺失主链原子划分片段。编号跳跃不用于推断序列。
- 仅重建 SEQRES 明确、双端锚定在 Docking Grid 外扩 5 Å 内、最多 4 个残基且编号无冲突的短缺口。其他缺口保留片段及末端原子。
- 工具使用临时片段 ID；输出恢复原链（包括空链）、编号、插入码和 TER。报告保存断点、原子数量、残基转换、映射、警告和各阶段状态。
- 最终验收检查原子覆盖、重原子参数、有限坐标和参数，以及 `--assign-only` 前后原子与坐标保持一致。金属与辅因子原位保留，不属于蛋白参数验收范围。

Context 的 `preparation.validation` 包含 `version: 1`、`status: passed|not_checked|failed`、`pdb2pqr_version: 3.6.2` 和通过时的 `prepared_sha256`。新任务与 Context 复用要求当前验收通过且文件摘要匹配；改变链、区域或 Docking Grid 后重新准备。关闭补氢的清理结果可以下载，Context 保持 `draft`。旧 Context 需重新准备；TarPass 新任务同样校验源任务保存的蛋白快照，旧源任务需用通过验收的 Context 重新生成。

SurfGen 表面环境通过 `/opt/pdb2pqr/bin/python -m genova_runtime.pdb2pqr_compat` 调用同一实现，运行时挂载由平台 Compose 提供。裁剪造成的单残基片段保留一个原有成键邻居，避免 PARSE 的单残基双末端参数缺失；原始孤立片段不通过参数验收。APBS 输出固定为 `temp1-PE0.dx`，检查 APBS、multivalue 返回码以及势能数量和有限值。

```bash
docker compose -f VERSE/docker-compose.yml exec -T backend-api \
  python -m unittest backend.tests.test_protein_context backend.tests.test_protein_context_jobs -q
```

准备和后台源码修改后重启 `worker-protein-preparation backend-api backend-worker`；SurfGen 模型更新后拉取新镜像并重新创建 `worker-surfgen`。GPU 验收采用 `VERSE/builtin_datasets/3cl.pdb`、配套 SDF，以及包含空链/断点的 2VT4。

模型输入缓存通过 `context_features.CACHE_VERSION` 和 `CONTRACT` 控制兼容性；输入格式或特征计算语义发生不兼容变化时升级 `CACHE_VERSION`，并重新保存 Context 构建输入。普通源码修改不会使缓存失效。文件内容、结构映射、Context 输入和特征参数的绑定校验继续保留；报告不再重复记录源码和产物哈希。原子、残基 ID 格式保持不变。

## ECloudGen

从头生成选择 `engine="ecloudgen"`，需要已准备的 Protein Context 及其中的参考配体 SDF。
`target_num_molecules` 为最终有效且全局去重的分子目标数，默认 1,000，必须为正整数。高级设置开放 `noise=0.1`、`inv_temp=2`、`budget_multiplier=3` 和 `seed=42`；种子不可留空，在创建任务时保存。质量参数不同于默认校准条件时，`sampling_plan.calibration_matches=false`，初始预算估算仅供参考。
高级设置展示 `num_clouds` 和 `decodes_per_cloud`，支持自定义；`budget_multiplier` 从界面隐藏。`GET /api/v1/jobs/molecule-generation/sampling-plan?target_num_molecules=N` 与 Worker 共用估算函数，默认 D=100，读取 `ecloudgen_calibration.json` 中 C=32、D=64/128 的保守产量，线性插值估算每云产量（约 32.27 个），据目标数计算 C。电子云数留空时，修改目标数量会重新估算初始云数。任务恢复沿用已保存的自动预算或手填参数。
C 至少为 4 且为 4 的倍数；D 为正整数。每云最多解码 D 次，batch=32，末批按剩余次数执行。自定义 D 在校准点间插值，低于最小校准点时按比例估算，高于最大校准点时保守沿用最大校准点产量；范围外估算标记 `extrapolated=true`。
参考配体仅以原位重原子坐标定位口袋；输入缓存只包含蛋白口袋通道，不计算参考配体的 xTB 电子云。沿用 `generate_from_pdb.py` 的扩散配置和权重；扩散 batch 固定为 4，解码 batch 保持 32，全部结果按 canonical SMILES 跨云去重。

SurfGen / ECloudGen 的源参考组件无需通过 CCD 化学重建，可保留共价配体断键后的原位几何。显式移除共价配体时，蛋白准备保存断键残基信息，并在受体构建阶段按标准残基模板恢复和重新质子化。当前只有 CYS `SG` 单键连接具有已验证的恢复模板；其他共价修饰保留原结构和连接信息，并记录为未恢复项。DELETE、EPSO 和 TarPass 的分子参考继续要求合法化学结构。
不足时按实际每云唯一产量生成新云补采样，D 保持用户设置，总云数及原始采样次数分别最多为初始预算的 `budget_multiplier` 倍（默认 3）。每轮完整解码该轮全部电子云，再从截至该轮的全局唯一候选池中无放回随机抽取 N 个；抽样固定使用用户输入 seed，补采样轮次的扩散/解码 seed 递增不改变最终抽样 seed。候选不足 N 个时保留全部并继续补采样，达标后不再启动下一轮。CSV 中已抽中的分子按 SMILES 排序，CSV 与 `result_count` 严格一致。
预算耗尽但有结果时返回已有分子，`reached_target=false`、`stop_reason=budget_exhausted`，结果页提示缺口；零产出任务失败。
`generation_metadata.json` 保存初始预算、实际消耗、各轮文件与计数、生成种子、抽样种子 `selection_seed`、校准版本和停止原因。C 超过 32 的估算带 `extrapolated=true`。
`num_clouds` 表示初始电子云数；`target_num_molecules` 仍是最终分子目标，旧的 `num_molecules` 不再接受。旧任务结果可读，缺少目标数量的旧任务重新生成需要填写新目标。部署切换前先完成旧队列任务。

校准脚本：`ECloudGen_official/cases/quantity_calibration/run.py`；数据和图表：`ECloudGen_official/results/quantity_calibration/`。
实验覆盖 C=4/8/16/32、D=32/64/128/256/512；IMDPH、adrb1、drd2 用于校准，Eg5 用于独立验证，种子为 2025/2026/2027。
耗时比较采用实测解码前缀加加载开销，以及按云数分摊的扩散耗时，属于成本估算；不是每个网格点独立启动的精确计时。

只输出 SMILES CSV，不执行构象嵌入或 MMFF，不返回 `generated_sdf`，生成结果页只展示二维结构，可进入 TarPass 后处理生成构象、计算体积并对接。

模型输入、临时 pocket 和电子云保存在每个 Job 的独立目录。扩散和解码使用分开的子进程，共用 GPU 0 文件锁；解码权重先通过仓库自带 CPU loader 加载，再移到 GPU 0，以兼容权重内保存的 cuda:1 设备信息。
开发 Compose 挂载 adapter，修改后重启 `worker-ecloudgen`；模型代码和权重进入镜像，变化后重新 build。

```bash
docker compose -f VERSE/docker-compose.yml build worker-ecloudgen
docker compose -f VERSE/docker-compose.yml up -d --no-deps worker-ecloudgen
docker compose -f VERSE/docker-compose.yml exec -T worker-ecloudgen \
  python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
```

## Redis 队列协议

总入口为 `genova:queue:dispatch`，Dispatcher 按内部 `task` 转发到 `genova:queue:{task}`。通用 Worker 执行对应 adapter，状态写入 `genova:job:{queue_job_id}`，结果写入 `genova:queue:result`。

消费者通过 `BLMOVE` 将消息移入对应的 `:processing` 列表，处理成功后才删除；结果消息在数据库提交后确认。
每个队列使用共享 `DATA_ROOT` 文件锁保持单个活跃消费者，重启先按原顺序恢复未确认消息。
后台重启会重新投递未完成任务的 Outbox；模型回执和结果事务锁保证重复投递不会重复推理或插入结果。
Redis 使用 `redisdata` 持久卷及 AOF。更新队列实现时须同时更新 Dispatcher、后台进程和所有模型 Worker。

成功结果格式：

```json
{
  "job_id": "queue-job-uuid",
  "task": "surfgen",
  "status": "succeeded",
  "result": {
    "engine": "surfgen",
    "output_csv": "/app/data/jobs/.../generated_molecules.csv",
    "generated_sdf": "/app/data/jobs/.../generated.sdf",
    "result_count": 1
  }
}
```

失败结果使用 `status="failed"` 与 `error`。API、后台 Worker 和模型 Worker 共用 `/app/data`，不向前端暴露 Redis。

## 部署与验证

在平台根目录执行：

```bash
docker compose -f VERSE/docker-compose.yml config --quiet
docker compose -f VERSE/docker-compose.yml up -d
docker compose -f VERSE/docker-compose.yml ps
docker compose -f VERSE/docker-compose.yml logs -f dispatcher
```

Redis 连接由 `VERSE/.env` 的 `REDIS_URL` 提供，必须包含密码。挂载的 runtime 源码修改后重启对应 Worker；镜像依赖修改后重新构建。TarPass 参数和验证见 [tarpass/README.md](../tarpass/README.md)。

## ECloud EPSO

`property_optimization.engine=epso` 使用 `entry_epso.py`，内部任务/队列为
`epso` / `genova:queue:epso`。`worker-epso` 和 `worker-ecloudgen` 各自消费队列，可以单独重建。
EPSO 镜像包含 ECloudGen 模型组件和 TarPass 对接环境，两个 Worker 通过 GPU 文件锁轮流使用同一张显卡。
EPSO 输出 SMILES CSV、轨迹和 metadata。启用亲和力目标时，逐轮对接临时构象并记录分数。需要对接姿态时使用 TarPass。
ObjectiveSpec、默认参数来源、部署与验证命令见 [EPSO 接入说明](../../deploy/EPSO.md)。
容器报告 NVML 或 CUDA 初始化错误时，见 [GPU 排障](../../README.zh-CN.md#gpu-排障系统升级后容器无法使用-cuda)。


## 生成数量与停止信息

生成结果中的 `requested_count`、`result_count`、`shortfall`、`reached_target` 分别表示请求数、最终有效去重数、缺口和是否达标。SurfGen 与 ECloudGen 的请求上限为 50,000，DELETE 为 10,000。三种模型的新建表单默认请求 1,000。实际交付数量取决于输入和搜索结果。

- SurfGen 请求 1,000 或以下时按用户种子搜索一次。请求更多时，平台按任务 ID 生成并保存起始种子，每轮最多请求 1,000。
- ECloudGen 使用自动电子云预算和默认采样参数时，首轮直接请求完整目标。请求 50,000 个分子时，初始预算为 1,552 个电子云。首轮不足时继续以每轮最多 1,000 补足。手填电子云数或改变采样设置时走分轮路径。部署者可通过 `ECLOUDGEN_FULL_TARGET=false` 关闭完整目标模式。
- DELETE 首轮直接请求目标数量并使用原编辑方案。已核验的产量达到目标九成且仍有缺口时，自动换种子补一次，每次补轮最多请求 1,000。

每轮使用 `(task_seed + r * 10000000) % 2**32` 派生种子，运行结束后释放 GPU 锁。SurfGen 和 DELETE 排除 SMILES 与三维记录不对应的条目。ECloudGen 从有效唯一池确定性选取目标数量。继续生成时保留已发布的分子和文件。

多轮任务在达标、满 1,000 轮、连续 3 轮零新增或首段 12 小时用完时结束。Worker 重启时恢复已完成的轮次，当前轮用原种子重跑。取消和超时终止当前轮进程。预算耗尽且已有分子时先交付，零产出任务失败。首段到期且有可交付结果时，SurfGen 多种子任务可通过 `POST /api/v1/jobs/{job_id}/continue` 手动追加一次 12 小时。每轮数据保存在 `generation_rounds.json`。

`generation_stats` 的过程计数按轮累加，不代表跨轮唯一数；任务的全局唯一候选池数量见 `unique_pool_count`，最终交付数见 `result_count`。单轮 SurfGen / DELETE 的计数定义如下：`initial_state_count` 为初始化状态数，`proposed_state_count` 为后续扩展经现有概率阈值筛选后返回的状态数，包含未完成分子的中间状态；`finished_state_count` 才表示被检查的结束状态数。SurfGen 的 `valid_unique_count` 是截断输出前的有效唯一数，结束状态数等于有效唯一数、重复数及被拒绝数之和。DELETE 达标后可能在一批状态处理途中关闭生成器，因此 `processed_state_count` 可能小于提议状态数；`valid_finished_count` 是通过结束状态检查的数量，`valid_unique_count` 是跨搜索累计的唯一输出数。DELETE 还会重建入选的运行中状态，`reconstruction_attempt_count` 单独统计这些重建尝试，不能与结束状态数相加视为唯一分子数；`last_search_stop_reason` 记录最后一个完整搜索轮次的原因。

ECloudGen 的 `sampled_count`、`valid_count`、`invalid_count`、`duplicate_count`、`unique_pool_count` 统计完整轮次解码及累计候选池，候选池可大于最终返回数。EPSO 的 `decode_request_count` 是粒子级解码请求数，失败后沿用上一结构；它不是解码器内部批量尝试数。`evaluated_particle_record_count` 是优化轨迹中检查的粒子记录数，包含重复及回退结构，不代表独立分子数或性质函数调用次数。

SurfGen、ECloudGen 和 DELETE 使用 `generation_metadata` 保存任务汇总与各轮新增量。EPSO 执行一次优化，并通过 `metadata_json` 返回统计。EPSO 默认请求 100，普通任务上限为 1,000，启用 GNINA 亲和力评分时上限为 500。SurfGen / DELETE 的模型计数改动需通过各自 runtime patch 重建镜像；只重启 Worker 不足以生效。

尚未更新模型镜像时，适配器仍返回可确认的请求数、返回数和缺口；旧模型没有提供的计数或未达标停止原因不作推测。
