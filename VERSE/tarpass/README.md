# TarPass 平台后处理

文中的回归测试和 benchmark 命令在 `test` 分支执行。

从 TarPass `aaf59c876eb2681d788a55ca46fcb629c7901fa5` 提取必要计算功能。
源码来源：https://github.com/sorui-qin/TarPass 。保留 MIT 许可证；SuCOS 和静电积分文件保留其上游来源标识。
不依赖原仓库的 `Targets`、benchmark CLI、pickle 文件或 Reference/Random 基准集合。

## 使用与部署

左侧 **Postprocessing** (`/postprocessing`) 选择自己的成功生成任务后提交；生成结果页的 **Open in Postprocessing** 自动选中源任务。左侧 **Results** (`/results`) 提供全部个人任务的类型/状态筛选和分页；后处理详情为 `/postprocessing/results?job_id=...`，旧详情链接自动跳转。
输入支持平台任务的三维／二维 SDF 和含 `smiles` 列的 CSV，优先使用 SDF；蛋白、对接框和参考配体继承源任务。非 3D 分子复用原项目 LigPrep 的 RDKit/MMFF → Open Babel MMFF94 流程生成构象，计算体积并参与性质前筛，通过后准备配体并对接；不执行原始姿态评分及原始 DockEval。流程为完整 MoleEval → 用户性质前筛（默认无条件，AND）→ 通过者的配体准备 → 对接及完整 DockEval；有有效原始三维姿态的记录额外执行原始姿态评分及完整 DockEval。被筛掉的记录保留性质和原因，全部淘汰时正常完成、不运行 Gnina/PLIP。缺少参考配体时相关三维比较标记不可用，不影响其他指标。
参考集合格式为 SDF 或每行首列 SMILES 的 `.smi` / `.txt`。无环分子的骨架相似度为空，不把两个空骨架当作完全相同。

2026-09-07 实测：`3cl` 上传→准备→SurfGen 生成 3 个分子→TarPass 两种姿态全指标→回写及可读 SDF 导出通过；无前筛送入 3 个、处理 4.17 秒，QED 前筛送入 1 个、处理 2.35 秒；全淘汰时未调用 Gnina/PLIP。此为单次小样本 Worker 处理时间（不含排队及生成），不作为普遍加速比。验收任务：`b4bf30c2-00b0-4d34-a833-d1ea7d9c70e2`（全量）、`8e639d94-603e-4609-908f-ee6dacb539e3`（前筛）。

在平台根目录执行：

```bash
docker compose -f VERSE/docker-compose.yml build worker-tarpass
docker compose -f VERSE/docker-compose.yml up -d --no-deps worker-tarpass
docker compose -f VERSE/docker-compose.yml restart backend-api backend-worker dispatcher worker-surfgen
```

维护前确认没有活跃任务。`tarpass/` 和 `genova_runtime/` 均挂载；源码变化重启 `worker-tarpass`，依赖和 Dockerfile 变化重新构建。
镜像默认下载 Gnina 1.3；已有可信的二进制 HTTP 缓存时，可通过构建参数 `GNINA_URL` 指定。
`TARPASS_CPUS=8`、`TARPASS_BATCH_SIZE=64` 为默认值。与 SurfGen 使用同一张 GPU，通过 `/app/data/.locks/gpu-0.lock` 互斥；CPU 评估不持锁。

## API 与结果

### 指标版本 2 对照

| 原 MoleEval 字段 | 平台字段 |
| --- | --- |
| clogP / hdonors / hacceptors / molwt / tpsa / molvol | logp / hbd / hba / exact_molecular_weight / tpsa / molecular_volume |
| heavy_atoms / heteroatoms / csp3 / rotatable_bonds / spiro_atoms / chiral_atoms / all_common | 同名 |
| completeness / heteroatom_ratio / flexibility / qed / sa_score | complete / heteroatom_ratio / flexibility / qed / sa_score |
| PAINS_alert / SureChEMBL_alert / Glaxo_alert | pains_alert / surechembl_alert / glaxo_alert |
| torsion angles / morgan fragments / bertzCT / spacial score | torsion_count / morgan_fragments / bertz_ct / spacial_score |
| ring numbers / largest ring / unexpect rings / fused numbers | ring_count / largest_ring / unusual_rings / fused_systems |
| highly fused / rings in fused system / unexpect ratio / fused ratio | highly_fused / rings_in_fused_system / unusual_ring_present / fused_ring_present |
| lipinski（原版五项满足数） | lipinski_violations（标准四项违规数） |

`lipinski_violations` 为 MW > 500、logP > 5、HBD > 5、HBA > 10 的违规数，越小越好；阈值相等不违规。原仓库分子量判断已为 `<= 500`，其五项规则还包含 logP 下限及可旋转键限制，不能与标准四项违规数直接互换。平台保留 `molecular_weight`（平均分子量），新增 `exact_molecular_weight` 对应原版精确质量。

DockEval 在 `original.*` 与 `docked.*` 下完整覆盖 score→affinity、no_clashes、SuCOS→sucos、shape/ESP→shape_similarity/electrostatic_similarity、centroid shift→centroid_shift、LE→le_heavyatom/le_mw 和 PLIP 相互作用/关键残基匹配；另保留 CNN 分数及姿态体积。无参考配体时返回 `unavailable` 原因，不计为计算异常。

二维指标按去氢、标准化 SMILES 复用，体积按物理记录计算：有原始三维构象时保留坐标，否则使用生成构象；姿态评价使用准备后的构象。原版也进行 SMILES 标准化，但部分结构指标直接使用原输入，显式氢表示不同的输入可能产生差异。单指标计算异常保留其他指标，缺失值不能通过依赖它的前筛。`manifest.versions.platform_metrics=3`，历史缺失指标显示未计算，不自动重算。

`POST /api/v1/jobs`：

```json
{
  "job_type": "molecule_postprocessing",
  "params": {
    "job_name": "TarPass evaluation",
    "postprocessing": {
      "source_job_id": "<generation-job-uuid>",
      "prefilters": [{"metric": "qed", "op": "gte", "value": 0.5}],
      "key_interactions": [{
        "interaction_type": "H-Bond", "match_mode": "any",
        "residues": [{"chain_id": "A", "residue_name": "GLU", "residue_number": 166, "insertion_code": ""}]
      }],
      "reference_dataset_id": null
    }
  }
}
```

- `GET /jobs/{source_job_id}/postprocessing/options`：可选指标、相互作用和受体残基。
- `GET /jobs?source_job_id=...`：关联后处理记录。
- `GET /jobs?job_type=...&status=...&limit=...&offset=...`：按当前用户、类型和状态在数据库筛选后分页。
- options 返回 `metric_info`（名称、类型、单位）及 `reference_available`；输出增加 `prefilter_counts`（evaluated/passed/filtered/submitted_to_docking）。
- `POST /jobs/{evaluation_job_id}/postprocessing/results`：`filters`、`sort_by`、`descending`、`offset`、`limit`，返回 `total` 和当前页。
- `POST /jobs/{evaluation_job_id}/postprocessing/export`：同一筛选条件，另传 `format=csv|sdf` 和 `pose=original|docked`。导出所有匹配行，不受分页限制。`original_sdf` 仅保存有效原始三维记录，生成的初始构象不作为 Original 导出；SDF 没有对应姿态的行不导出，并通过 `X-Exported-Count`、`X-Skipped-Count` 明确数量。
- 原有 Job artifact 接口支持 `output_csv`、`results_json`、`original_sdf`、`docked_sdf`、`manifest_json`。

以上相对路径均位于 `/api/v1`。只有服务器解析文件路径，客户端提交 Job/Dataset ID。
每条 SDF／CSV 记录使用稳定 `molecule_id` 和 `source_index`，新增 `has_original_pose` 标识；同结构不同构象保留独立行。详细相互作用和指标错误保存在 JSON，CSV 包含展开后的数值指标。

## 结果聚类与改造对照

所有平台生成来源共用结果页的聚类和代表选择，不改变评价任务或重新运行对接。结果查询与导出请求均可附加：

```json
{
  "sort_by": "docked.affinity",
  "descending": false,
  "clustering": {
    "basis": "molecule",
    "similarity_threshold": 0.6,
    "representatives_per_cluster": 1,
    "representatives_only": false
  }
}
```

- `clustering` 默认 `null`。`basis=molecule|scaffold`，骨架采用 Bemis–Murcko；两者使用 Morgan radius=2、2048 bits 和 Tanimoto 距离的 Butina 聚类。阈值为 `[0,1]`，对应中心邻域，不保证所有成员两两满足阈值。
- 先应用状态及指标筛选，再对全部匹配记录中的不同结构聚类，最后选代表、分页。最多 2,000 个不同结构，超出返回 422，要求继续筛选；不截断记录。无环分子在骨架模式下按不同完整结构单独成簇。
- 同结构多构象共享簇，但完整结果保留每条记录。每簇选择 1–20 个不同结构，按查询排序取各结构最佳记录；缺少排名指标的记录不当选。相同分数按 `molecule_id` 升序，使用 `molecule_id` 排序可进行确定性选择。
- 返回 `clustering` 摘要与 `cluster_id`、`cluster_size`（不同结构数）、`cluster_record_count`、`is_representative` 行字段。CSV 包含这些字段；SDF 保留原始三维记录与稳定 ID，沿用姿态选择和跳过计数。导出不受分页影响。
- 新建的 DELETE 后处理内部 payload 继承服务器解析的 `fragment_sdf`。结果页使用原始三维坐标及元素的一一映射（0.01 Å）生成二维改造预览，检查保留片段内部连接；绿色保留、橙红色删除、蓝色新增。缺失或映射不明确时显示不可用，不影响评价和聚类。
- 历史二维 DELETE SDF 无法恢复原始生成姿态，须重新生成，不能通过任意嵌入三维坐标冒充原始姿态。历史已完成 TarPass 结果可直接聚类，缺少片段元数据时不提供改造预览。

DELETE 基础镜像已固化模型三维输出及连接点约束，当前构建通过 `deploy/delete.Dockerfile` 更新 runtime。适配器拒绝无三维坐标或非有限坐标输出，空结果失败。模型函数检查使用独立临时容器，避免修改常驻 Worker 的输入文件：

```bash
docker compose -f VERSE/docker-compose.yml run --rm --no-deps worker-delete python3 -m genova_runtime.test_helpers
docker compose -f VERSE/docker-compose.yml exec -T backend-api python -m unittest backend.tests.test_protein_context_jobs
```

## 指标语义与失败行为

- 前筛默认为空；用户设定的条件之间为 AND。后筛调整不触发重新计算。缺失值不能通过依赖该值的条件。
- 原始姿态保留重原子坐标。Gnina 输入在副本上按任务 pH 加氢/质子化；原始下载文件保留输入结构。
- 分子量使用 RDKit 平均分子量，Lipinski 记录标准四项阈值的违规数。区别于上游的精确质量和混合条件计数；旋转键单独展示。
- 质心偏移统一使用重原子；不因加氢数量不同而出现人工偏移。
- PLIP 氢键供体/受体以配体为视角。保留 TarPass 的盐桥并入合并氢键、π 堆积并入疏水接触规则。私有 PDB 副本重编号后映射回原始链、残基和插入码。
- 没有关键相互作用规则时匹配率为空；没有参考配体时三维参考比较为空。参考集合最近邻默认关闭，不计算 FCD 等集合级指标。
- Gnina 固定 `fast`、`rescore`、`exhaustiveness=8`、`num_modes=1`、`seed=42`，按其默认 CNN 排名选第一姿态。`affinity` 为 `minimizedAffinity`，另外保留 `cnn_score`、`cnn_affinity`，不能混用。
- 无效记录、前筛淘汰和单分子错误保留状态及原因；部分指标失败记为 `partial`。任务级故障进入 `failed`，原生成 Job 不变。全部正常前筛淘汰仍为成功。
- `manifest.json` 保存输入哈希、程序版本、命令、规则和分阶段耗时。保存每批中间输出用于定位错误；首期不自动恢复被中断的批次，重新提交会创建新 Job。

## 验证与性能

### 万条结果浏览

- SurfGen、DELETE 和后处理源任务预览按页查询，默认 20 条；TarPass 默认 50 条。`GET /api/v1/jobs/{job_id}/results` 保持数组响应，增加 `X-Total-Count`，支持 `search`、`sort_by=created_at|smiles|qed|logp|sa|tpsa|weight`、`descending`。`GET /api/v1/jobs/{job_id}/results/summary` 返回全任务指标均值，缺失指标为 `null`。
- TarPass 筛选、排序和分页使用既有 PostgreSQL `small_molecule_results.extra`；表格不返回 `interaction_details`。历史任务首次访问通过任务行锁补齐无 SMILES 的无效记录，并保存 `result_index_version=1`，后续不再读取完整 `results.json`。CSV/SDF 导出复用相同筛选顺序，采用流式响应，不受当前分页影响。
- `GET /api/v1/jobs/{job_id}/structures` 返回 `{total, records:[{source_index}], version}`。生成结果传 `result_id`；TarPass 传 `molecule_id` 与 `pose=original|docked`；生成姿态默认 `pose=generated`。支持 `offset` 和 `limit`（默认 100，最多 500）。`GET /api/v1/jobs/{job_id}/structures/{source_index}?pose=...` 只返回一条有效三维 SDF。相同 SMILES 的不同物理构象保持独立。
- `GET /api/v1/jobs/{job_id}/structures/context` 返回任务快照对应的蛋白和参考配体 `{dataset_id,file_id,format}`；继续通过既有 Dataset 下载接口读取。缺失受体时可以单独展示配体。
- 每份 SDF 的相邻 `*.index.json` 保存记录偏移、长度、名字和规范 SMILES；索引不修改源文件。文件 inode、大小、纳秒修改时间或索引格式版本变化会重建；文件锁避免并发重复构建，临时文件原子发布。新任务回写时预建；历史产物首次访问建立一次。索引可删除后重建，不能原地修改 SDF 后伪造原文件版本。
- TarPass 结果表的分子编号打开纯分子三维 SDF 预览，编号下方 `3D View` 打开结合模式。SurfGen、DELETE 默认 Original；其他来源（包括 ECloudGen）以及没有原始三维姿态的记录默认 Docked。只有明确识别的原位模型提供结合模式的 Original / Docked / 叠合对比；纯分子预览仍可切换两种可用构象。
- 叠合使用相同 `molecule_id` 在两份 SDF 中各自的物理记录，保持受体坐标、不做分子对齐；Original 碳原子为青色，Docked 为紫色。切换复用相机、受体及已加载构象，显示当前构象的 5 Å 口袋；叠合显示两者口袋范围。PLIP 侧栏与二维图按弹窗中的姿态选择同步。
- 表格不再提供构象选择器；SDF 导出按钮单独选择 Original / Docked，并保留当前筛选与排序，CSV 继续包含两套指标。预览选择不改变筛选、聚类或导出。
- 浏览器用一个 RDKit Worker 绘图，视口附近按需执行，SVG LRU 上限 20 MiB，输入、尺寸、SMARTS 与高亮均参与缓存键。结构文本缓存上限 32 MiB，参考配体首次勾选才下载；切换构象仅替换候选配体和口袋，复用 Molstar、蛋白及参考配体。离页释放场景，退出登录清除缓存。
- 相互作用图轮询复用版本化指纹和蛋白摘要，不扫描整份 SDF。编辑高亮使用单记录读取及 512 项有界缓存。PLIP 首次补算仍受 CPU 队列排队影响；聚类继续限制在 2000 个不同结构以内。

2026-09-11 验收：独立合成任务分别包含 1000、5000、10000 条记录，覆盖无效记录、重复 SMILES、不同坐标及缺失 docked pose。真实 PostgreSQL / HTTP 接口在 10 并发混合读取下，最终万条测试的 P95 为：分页 136ms、单结构 83ms、已缓存相互作用图 103ms；三份 SDF 首次建索引合计约 1.4 秒。此组 SDF 为含氢乙醇构象，用于检验规模增长与查询路径，不代表复杂分子首次解析或计算速度，也不包含公网传输。

浏览器使用仓库 `VERSE/builtin_datasets/3cl.pdb`、`3cl_ligand.sdf` 验证白色候选、延迟参考配体、构象切换和蛋白场景复用。RDKit 初始化后，100 张不同结构的未缓存绘图约 0.15 秒，缓存读取约 0.2ms，未记录到绘图导致的主线程长任务。连续翻页 100 次保持按页请求；100 次构象切换只下载一次蛋白和两条 SDF，场景节点数量保持不变，JS 堆增长约 3.1 MiB。实际结果页弹窗关闭后恢复页面交互，重新打开保留构象和相机。

本次后端 47 项回归完成（1 项因环境依赖跳过），前端构建、TarPass 检查及双语检查通过；全量 `vue-tsc` 仍有既有类型错误。真实 3cl CPU PLIP 验证返回 6 条相互作用，复用明细时不重新计算，源 SDF 字节和坐标不变。

回归命令（数据库检查使用独立测试记录并回滚）：

```bash
docker compose -f VERSE/docker-compose.yml exec -T backend-api python -m unittest backend.tests.test_protein_context_jobs
npm --prefix genova_frontend run check:i18n
node genova_frontend/scripts/check-tarpass.mjs
npm --prefix genova_frontend run build
```

本次改动不需要数据库迁移或新增依赖；重启 `backend-api`、`backend-worker`、`worker-tarpass` 后生效。历史首次访问的索引建立不纳入缓存命中延迟目标。

### Mol* 2D 相互作用预览

- TarPass 结果的 Mol* 工具栏使用 `2D / 3D` 原位切换。二维图显示当前物理记录和姿态的 PLIP 原子/原子组端点；芳环连接环中心。点击残基返回三维定位，滚轮缩放、右键拖动平移。
- `POST /api/v1/jobs/{job_id}/postprocessing/interactions-2d` 接收 `{"molecule_id":"m00000000","pose":"original"}`，`pose` 也可为 `docked`；同路径 `GET` 用查询参数轮询。返回 `status`，成功时返回 `diagram: {version, plip_version, scene, interactions}`，失败时返回 `error`。
- 新评估在 `metrics.original/docked.interaction_details` 中保留明细，绘图复用该次 PLIP 判定。original 明细的 `source_input_fingerprint` 绑定准备前的原始 SDF，`input_fingerprint` 保留准备后实际评测配体的指纹，避免键存储顺序及质子化变化导致错误重算。图中的 `ligand_atom_ids` 是场景配体重原子列表的零基索引；PDB 重编号通过唯一原子名映射，并核对元素和坐标。图中的原始相互作用不重复绘制指标中的合并统计项。
- 有有效明细时 POST 同步生成并缓存二维布局，直接返回 `succeeded`，不创建辅助任务或进入轮询。只有缺失有效明细时才走 `JobTask / QueueOutbox / task=tarpass`，内部操作为 `interactions_2d`，补算 CPU PLIP，不运行 Gnina；补算明细写回对应数据库结果记录，后续布局重建继续复用。`plip2d_` 前缀的辅助任务不进入原 Job 的状态聚合、任务列表或分子结果计数；重试也不改写原评分与筛选结果。
- 缓存为 `/app/data/jobs/{job_id}/interactions-2d/{hash}.json`，哈希覆盖蛋白内容、配体化学结构及三维坐标、记录 ID、姿态、PLIP 和绘图版本。重复请求复用任务；输入变化或缓存缺失可重新生成。缺失三维姿态、蛋白或可靠原子映射时明确失败，不生成猜测的原子级连线。
- 明细格式版本与二维布局版本独立；修改布局只重建图。复用明细的图缓存还包含评测配体指纹，避免命中以前基于准备前结构补算的图。
- 补算在回写明细前同时发布原请求键和明细复用键对应的图，保证跨越数据库回写时刻的轮询均能读取结果。
- 后端改动后重启 `backend-api`、`backend-worker` 和 `worker-tarpass`；无数据库迁移或新增依赖。

```bash
docker compose -f VERSE/docker-compose.yml exec -T backend-api \
  python -m unittest backend.tests.test_protein_context_jobs
```

`benchmark.py` 在独立进程中对比上游静电与精确最近邻内核，100/1000 个候选各重复三次。
输入不足时循环扩展，并报告原始记录数；这不是整条对接流程的加速测试。

```bash
PYTHONPATH=VERSE OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  /home/sorui/anaconda3/envs/tarpass/bin/python -m tarpass.benchmark \
  --baseline /home/sorui/Research/Tarpass \
  --input-sdf /path/to/generated.sdf \
  --reference-ligand VERSE/builtin_datasets/3cl_ligand.sdf \
  --protein-pdb VERSE/builtin_datasets/3cl.pdb \
  --output /tmp/tarpass-benchmark.json
```

本次以 12 个生成结构循环扩展，参考集合 10000 条：1000 候选的静电内核中位耗时从 0.601 秒降到 0.239 秒；最近邻从 0.774 秒降到 0.540 秒，后者进程峰值内存从 694 MiB 降到 232 MiB。数值在 `1e-8` 容差内一致。
这些数字不包含 Gnina、PLIP、输入准备或进程初始化，不能外推为端到端加速比例。

端到端验收已在独立镜像中完成：通过 HTTP 上传 3cl PDB 和 ligand、准备 Protein Context、生成 3 个分子、提交后处理，3 条结果均成功。验证了数据库回写、按源任务查询历史、阈值后筛、跨分页导出，原始及对接 SDF 均被 RDKit 完整读取。
既有后端测试文件扩展后共 25 项通过；另验证了同结构不同构象、混合/损坏 SDF、全部前筛淘汰、对接 ID 映射及带插入码的 PLIP 残基匹配。前端构建和 TypeScript 检查通过。

2026-09-10 P0/P1 验收：3cl 上传及准备后，DELETE 普通片段替换生成 2 条、指定衍生位点生成 1 条有效三维记录；两种来源均通过 TarPass 原始姿态评分、重对接、分子/骨架聚类、改造预览、CSV 与两种姿态 SDF 导出。最终生成任务为 `6cdb9416-3481-47f7-8a68-731f6beb7238`、`2bb161e6-722c-4c34-aafb-502e0fb07b0a`，后处理任务为 `d7cf70d8-0085-433c-8f15-99be72e594ff`、`f259de32-02ff-4c32-abf0-ca79decf5196`。最终镜像验证生成器可正常关闭，无 `generator ignored GeneratorExit`。历史 SurfGen 后处理任务 `1ad5ded7-a831-4f15-85d0-cafe8135dd9a` 的 52 个结构也通过两种聚类检查。

2026-09-11 Mol* 2D 验收：前述独立访客任务通过真实 HTTP 历史补算、并发去重、缓存及失败重试，原 Job 状态、时间戳和摘要不变；在容器内核对真实氢键/疏水端点与 π 堆积环中心，三维坐标不变。浏览器用仓库 3cl 样例验证原位切换、相机保持、残基定位、姿态/记录切换及监听器释放。后端 45 项回归完成（1 项因环境依赖跳过），前端构建、TarPass 检查和双语检查通过；全量 `vue-tsc` 仍有既有类型错误，本次二维组件未出现新增报错。

2026-09-11 明细复用修复：任务 `743ec8b3-a923-40e6-9235-126da17707bc` 的 100 条 original 明细经源文件、manifest、物理记录和准备后 batch 核验后补齐源指纹，原 JSON 备份为任务 `tarpass/results.pre-plip-source-binding.json`；SDF、坐标及评分不变。两种姿态共 200 次真实 HTTP 请求在 10 并发下全部直接成功，新增辅助任务为 0，P95 约 354ms（包含鉴权、数据库访问、首次布局及缓存写入）。单独布局 P95 约 0.57ms；原流程一次实际请求等待 Outbox 约 1574ms，Worker 执行约 11ms。历史记录 5 个并发请求仅补算一次，明细成功回写，再次打开约 19ms。后端 48 项回归完成（1 项因环境依赖跳过），真实 CPU PLIP 验证评测后预览及补算后预览均不重复调用 PLIP；浏览器验证实际二维 SVG 渲染成功，只发送一次 POST、零轮询。

最终重复验收：200 次已有图缓存的请求在 10 并发下 P95 约 283ms，仍无新增辅助任务；另一个历史记录的 5 个并发请求仅补算一次，明细回写后的 GET 直接成功（约 9ms），无缓存键切换导致的 `not_requested` 窗口。


## 非 3D 输入回归

构象生成只发生在 TarPass 后处理，ECloudGen 生成阶段仍输出 SMILES CSV。二维或无效坐标在构象生成前移除；RDKit 固定种子 42，MMFF 优化失败时使用 Open Babel。体积阶段生成的构象用于后续配体准备，避免重复嵌入。构象失败保留已计算的二维性质；体积缺失不能通过体积前筛，未被前筛淘汰但无法准备的记录标记失败。缺少原始姿态以 `metrics.original.unavailable` 表达，不使成功对接记录变成 partial。

平台内部 payload 使用 `input_sdf` 或 `input_csv`，后者要求 `smiles` 列。dry-run 的 CSV 路径只列出 dock；SDF 路径列出可能的 score_only/dock，并以 `original_requires_3d` 标明只有有效原始三维记录参与评分。

在平台根目录运行已有专项检查：

```bash
docker compose -f VERSE/docker-compose.yml exec -T worker-tarpass python -c 'from genova_runtime.test_helpers import check_tarpass_non3d; check_tarpass_non3d()'
```

2026-09-19 验收：两条已有 ECloudGen SMILES 经 HTTP API → Outbox/Redis → TarPass Worker → 数据库回写完成，均为 succeeded；计算耗时约 7.2 秒，体积为 198.304、215.096 Å³，Gnina affinity 为 -6.36861、-4.27235 kcal/mol。只执行 dock，Original SDF 导出 0 条并报告跳过 2 条，Docked SDF 导出 2 条且可被 RDKit 读取，三维结构接口及 CSV 导出通过。临时验收任务及文件在验证后清理。后端 52 项回归通过（1 项环境依赖跳过），TarPass 专项检查、前端行为检查、双语检查及构建通过。
