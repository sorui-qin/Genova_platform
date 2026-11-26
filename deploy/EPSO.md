# ECloud EPSO 接入

文中的回归测试和 benchmark 命令在 `test` 分支执行。

EPSO 与 DELETE 共用 `property_optimization`、Job API、认证、Dataset、结果表和 artifact API。
DELETE 继续使用编辑片段与三维生成；EPSO 使用完整 seed 的二维 SMILES 做 latent 优化。
EPSO 关联已准备的 Protein Context。启用亲和力时，EPSO 使用 Context 已校验的共享受体、对接框和 pH。

## API

```json
{
  "job_type": "property_optimization",
  "protein_context_id": "<prepared-context-id>",
  "params": {
    "job_name": "EPSO optimization",
    "property_optimization": {
      "engine": "epso",
      "num_molecules": 100,
      "objectives": [
        {"metric": "qed", "mode": "lower_bound", "lower": 0.6, "weight": 1},
        {"metric": "sa", "mode": "lower_bound", "lower": 0.6, "weight": 1},
        {"metric": "mw", "mode": "range", "lower": 250, "upper": 500, "weight": 1}
      ],
      "optimizer": {"num_particles": 200, "num_swarms": 1, "num_steps": 20, "seed": 2024}
    }
  }
}
```

提交 `POST /api/v1/jobs`。不提供 `ligand_dataset_id` 时用 Context 参考配体；主动替换时提交顶层
`ligand_dataset_id`，必须恰有一个 SDF 文件、一个有效分子。拒绝多记录、无效分子、未知字段、
路径、checkpoint、desirability 点和底层优化参数。`params.seed_source` 与 task payload 保存实际文件 ID。
恢复任务时若 Context 准备文件或 seed 文件发生变化，页面拒绝静默切换输入。

## 目标矩阵

| metric | 含义 | 默认 softness | maximize/minimize 默认端点 |
|---|---|---:|---|
| qed | 官方 QED | 0.1 | 0–1 |
| sa | 官方归一化 SA，越高越好 | 0.1 | 0–1 |
| mw | 官方 `get_weight` 精确分子量 | 50 | 必填 |
| logp | 官方 logP | 0.5 | 必填 |
| lipinski | 官方五项规则满足数 | 1 | 0–5 |
| hba | 官方 HBA | 1 | 必填 |
| hbd | RDKit `Lipinski.NumHDonors` | 1 | 必填 |
| heavy_atom_count | 官方重原子数 | 1 | 必填 |
| similarity | 官方 Morgan 指纹与 seed 的 Tanimoto 相似度 | 0.1 | 0–1 |

上述九项均支持以下六种模式。`clip(z)=min(1,max(0,z))`，`s=softness>0`。

| mode | 字段 | desirability |
|---|---|---|
| lower_bound | lower=L | clip((x-L+s)/s) |
| upper_bound | upper=U | clip((U+s-x)/s) |
| range | lower=L, upper=U | 上两式的最小值 |
| target | target=T | clip(1-abs(x-T)/s) |
| maximize | lower=L, upper=U | clip((x-L)/(U-L)) |
| minimize | lower=L, upper=U | 1-clip((x-L)/(U-L)) |

权重为正，metric 不重复，数值有限，阈值受自然边界约束。`L<U`；softness 只用于前四项。
内部编译成官方 `ScoringFunction` 的线性评分点并截断端点，fitness 保持官方加权平均。
Backend 导入校验器不加载 Torch 或官方模型。

## Gnina 亲和力目标

1. 在「先导优化」选择 ECloud EPSO、已准备的 Protein Context 和起始配体。Protein Context 需要有已校验的受体和对接框。
2. 在「优化目标」点击「添加目标」，选择「Gnina 对接能量（kcal/mol）」并设置权重。要同时偏向较易合成且 QED 达标的分子，可以加上 SA 和 QED，分别设下限 0.6 和过渡宽度 0.1。两项在各自达标后得满分，低于门槛时仍可由其他目标弥补总分。
3. 提交前查看分子对接数上限。粒子数与步数增加时，待评分分子可能增加，对接也可能耗时更长。
4. 在结果页查看对接能量和相对起始配体的改善量。需要导出姿态或按统一条件比较多次搜索时，使用 TarPass 对候选进行复评。

在 `objectives` 加入 `{"metric":"gnina_affinity","mode":"seed_relative","weight":1}` 启用亲和力。每轮对新出现的有效分子生成临时构象，并用 Gnina 计算 `minimizedAffinity`，单位为 kcal/mol。使用与 TarPass 相同的配体准备和对接参数。任务内按包含立体化学的 canonical SMILES 复用分数。已有二维目标照常计算，使用同一个加权平均更新粒子。

设起始配体的对接能量为 `E₀`，尺度为 `s = max(E₀ + 8, 0.5)`。候选的能量为 `E`，令 `z = ln(3) × (E₀ − E) / s`。达到或优于起始配体时取 `sigmoid(z)`，变差时取 `sigmoid(2z)`。因此，改善一个尺度得 0.75 分，持平得 0.5 分，变差一个尺度得 0.1 分。能量越低，亲和力项得分越高。

单个候选无法评分时，该粒子退回上一有效分子。起始配体无法评分或对接进程故障时，任务失败并记录原因。启用时，结果 CSV 加入 `gnina_affinity` 和 `gnina_affinity_improvement`。改善量为正表示比起始配体更好。轨迹额外记录截至每步的最低对接能量，元数据保存评分参数、受体哈希、对接选项和耗时。

配体准备沿用 TarPass 的 Open Babel 回退流程。RDKit 的 MMFF 优化未收敛时，重复准备同一个配体可能得到不同构象，重新对接的能量也可能变化。对比两次搜索的候选时，可以用同一批 TarPass 结果作为统一的评分口径。

## Runtime 与结果

`epso → genova:queue:epso → worker-epso → entry_epso.run_job`，公共 task code 为 `property_optimization`。
ECloudGen 的生成任务由 `worker-ecloudgen` 消费 `genova:queue:ecloudgen`。两个 Worker 使用独立容器，可分别重启或重建。

输入包含 `reference_ligand`、`protein_pdb`、`structure_context`、`ph`、目标和优化参数、
`output_dir/output_csv/trajectory_csv/metadata_json`。路径均由后端生成。
CPU loader 加载 `ckpt/ecloudgen_decipher_ckpt` 后转 GPU 0；维度读取 `encoder.embed_dim`。
每个任务独立子进程，退出释放 CUDA；使用 `/app/data/.locks/gpu-0.lock` 与其他 GPU Worker 串行。

流程为官方 `Swarm.next_step → decode → re-encode → update_fitness`。
严格解码失败返回 `None`，保留该粒子上一有效 SMILES；真实 `C` 有效，模型异常向上传播。
官方其他调用默认继续使用原有行为。记录层保留初始状态和最后一步，不修改官方移动或评分公式。

- `results.csv`：`rank,smiles,fitness,generation` 及启用的性质；canonical 去重、fitness 降序，同分按首次出现顺序。
- `trajectory.csv`：`step,best_fitness,best_smiles`，含 `0..num_steps`。
- `metadata.json`：checkpoint 路径、参数、seed、起始配体 SMILES、计数、解码失败、耗时和版本。
- EPSO 结果为二维结构与 CSV。启用亲和力时，构象仅用于本次评分，查看和下载对接姿态使用 TarPass。
- 起始配体参与排名，可能出现在返回结果中。`generation` 为首次评估迭代。数量不足时，页面提示缺口。页面也会提示无新分子和无评分提升的情况。
- TarPass 读取完整 CSV，自己生成构象并对接；不执行 EPSO 原始姿态评分。

## 参数来源与部署

200 粒子、20 步与 `[-10,10]` 搜索范围对应仓库 `ECloudGen_official/play_around/BRD4_EPSO.ipynb`
多目标示例。`Swarm`/`BasePSOptimizer.from_query` 默认惯性 0.9、phi1/2/3=2、初始速度范围
`[-0.6,0.6]`；解码函数默认 batch=128、max_attempts=4。API 固定单 swarm，部署固定 GPU 0。
返回数、粒子数、步数和 seed 可编辑，后端执行约束。默认请求 100 个分子。普通任务最多请求 1,000 个，启用 GNINA 亲和力评分时最多请求 500 个。
不能根据旧 CDDD 注释把搜索范围改为 `[-1,1]`。

初版的 EPSO 和 ECloudGen Worker 使用同一个镜像。引入可选的 GNINA 亲和力评分后，EPSO 增加了独立镜像。构建以 TarPass 镜像为基础，从同版本 ECloudGen 镜像复制 Conda 环境、模型代码和解码权重。启用评分时，EPSO 在自己的容器内调用 TarPass 环境运行配体准备和 GNINA。构建定义见源码仓库的 `deploy/epso.Dockerfile`。

若严格解码补丁、模型代码或复制的权重有变动，先重建 ECloudGen 镜像，再重建 EPSO 镜像并重新创建受影响的 Worker。容器报 NVML 或 CUDA 初始化错误时，按发布目录或源码仓库的 `README.zh-CN.md` 中「GPU 排障」一节检查。

```bash
docker compose -f VERSE/docker-compose.yml build worker-ecloudgen worker-epso
docker compose -f VERSE/docker-compose.yml up -d --force-recreate --no-deps worker-ecloudgen worker-epso
```

发布构建 ECloudGen 镜像也包含 runtime；开发通过只读挂载加载 runtime。
`ECloudGen_official/` 整体忽略；`deploy/ecloudgen-runtime-patch.py` 在镜像构建时应用严格解码修改，支持原始源码和已打补丁源码。模型源码与权重无需纳入平台 Git。

```bash
docker compose -f VERSE/docker-compose.yml exec -T worker-epso \
  python -c 'from genova_runtime.test_helpers import check_epso; check_epso()'
docker compose -f VERSE/docker-compose.yml exec -T backend-api \
  python -m unittest backend.tests.test_protein_context backend.tests.test_protein_context_jobs -q
cd genova_frontend
npm run build
npm run check:i18n
node scripts/check-tarpass.mjs
./node_modules/.bin/vue-tsc --noEmit -p tsconfig.app.json
```

复现只保证在同一模型、软件和 GPU 环境验证；不承诺跨硬件逐位一致。
