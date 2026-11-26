# SurfGen：RTX 5060 兼容性检查

检查日期：2026-09-20。检查对象为 `surfgen-perf-20260919` 与旧 `surfgen-1.0.2`。

## 结论与证据

兼容性检查时，旧版七个 `*-1.0.2` 应用镜像及切换前运行镜像均在本机；后续清理了部分闲置旧镜像，保留切换前回退镜像，远端旧标签未删除。
回退配置位于 `deploy/dist/performance-20260919/rollback.yml`；该目录未纳入 Git。

当前 SurfGen 不能视为已验证支持 RTX 5060。旧推理环境是优先排查项；没有收到反馈机器的错误日志，尚不能确认具体故障点。

| 项目 | 实际检查结果 |
| --- | --- |
| PyTorch / CUDA | 新旧镜像均为 `2.2.2 / 12.1` |
| PyG | 当前镜像 `2.5.3` |
| 扩展 | `pyg-lib 0.4.0+pt22cu121`、`torch-scatter 2.1.2+pt22cu121`、`torch-sparse 0.6.18+pt22cu121`、`torch-cluster 1.6.3+pt22cu121`、`torch-spline-conv 1.2.2+pt22cu121` |
| Torch 编译架构列表 | `sm_50 sm_60 sm_61 sm_70 sm_75 sm_80 sm_86 sm_90`，不含 `sm_120` |
| 实机验证范围 | RTX 4070（8.9）矩阵乘法、scatter、knn 均通过；此前完整 SurfGen 推理通过 |
| RTX 5060 验证 | 当前没有这张卡，未实测 |

RTX 5060 属于计算能力 12.0 的 Blackwell GPU，见 [NVIDIA GPU 列表](https://developer.nvidia.com/cuda/gpus)。
[PyTorch 2.7](https://pytorch.org/blog/pytorch-2-7/) 引入 Blackwell 支持与 CUDA 12.8 wheels。
不能仅凭编译列表缺少 `sm_120` 就断言每个算子必然失败：兼容 PTX 可以前向 JIT；但整个调用链的核心库和扩展都必须可用，见 [NVIDIA 兼容性说明](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/index.html)。
SurfGen 实际使用 scatter 和 knn，不能只检查 `torch.cuda.is_available()`。

新旧镜像的核心环境相同，回退旧镜像通常不能解决 GPU 架构支持问题；没有证据表明本次镜像瘦身引入了这一架构缺口。

## 在反馈机器上定位

从平台仓库根目录运行。以下命令只打印诊断信息和执行小型 GPU 算子，不创建平台任务：

```bash
nvidia-smi
docker compose -f VERSE/docker-compose.yml images worker-surfgen
docker compose -f VERSE/docker-compose.yml exec -T worker-surfgen nvidia-smi
docker compose -f VERSE/docker-compose.yml exec -T worker-surfgen \
  /opt/conda/envs/surfgen/bin/python -u - <<'PY'
import torch
from importlib.metadata import version
print('torch / CUDA:', torch.__version__, torch.version.cuda)
print('extensions:', {p: version(p) for p in ('torch-cluster', 'torch-scatter')})
print('available:', torch.cuda.is_available())
print('compiled architectures:', torch.cuda.get_arch_list())
assert torch.cuda.is_available(), 'CUDA unavailable inside container'
print('GPU:', torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))
x = torch.randn(8, 3, device='cuda')
x @ x.T
torch.cuda.synchronize()
print('matmul PASS')
from torch_scatter import scatter
scatter(x, torch.arange(8, device='cuda') % 2, dim=0)
torch.cuda.synchronize()
print('scatter PASS')
from torch_cluster import knn_graph
knn_graph(x, k=2)
torch.cuda.synchronize()
print('knn PASS')
PY
```

发布包用户将 `-f VERSE/docker-compose.yml` 换成实际 `--env-file .env -f compose.yml`。

- `no kernel image is available for execution on the device` / `invalid device function`：优先检查出错阶段对应的 CUDA 内核或扩展架构。
- `undefined symbol`：优先检查 Torch 与扩展的二进制版本是否混装。
- 宿主机正常、容器内 `NVML` 或 CUDA 不可用时，用同一镜像启动临时容器复测。临时容器通过时，按 `README.zh-CN.md` 的「GPU 排障」步骤重新创建受影响的 Worker 并复查 CUDA。
- `CUDA out of memory`：检查显存占用和实际推理峰值，不能直接归因于架构不兼容。

## 兼容镜像的最小改动方向

1. 单独验证一套支持 Blackwell 的 Torch/CUDA 组合；`PyTorch 2.7.x + cu128` 是已有官方支持的候选起点，不代表本项目已经验收通过。
2. 同步安装与 Torch/CUDA 匹配的全部 PyG 扩展，验证其 GPU 算子；若 wheel 不包含需要的架构，使用 CUDA 12.8 或更新工具链针对目标架构编译。对应矩阵见 [PyG 安装文档](https://pytorch-geometric.readthedocs.io/en/latest/install/installation.html)。只更换 Docker `FROM` 或宿主机 CUDA Toolkit 不会替换旧 Conda 内的 Torch/扩展。
3. 处理旧 checkpoint 加载：镜像 `/app/gen.py` 的 `torch.load` 未指定 `weights_only`，权重含 `easydict.EasyDict`。PyTorch 2.6 起默认值变化，升级时需对已验证、可信的内置权重显式处理加载策略，见 [序列化文档](https://docs.pytorch.org/docs/2.7/notes/serialization.html#torch-load-with-weights-only-true)。
4. 保持 CPU `surf_maker` 表面生成环境与原权重，检查宿主驱动实际支持 RTX 5060 和所选 CUDA 运行库；在 5060 上完成上述算子检查及 `3cl.pdb + 3cl_ligand.sdf` 全链路，并在 4070 回归后再发布新标签。

本次只检查并记录兼容风险，没有升级正在运行的依赖、重建或推送新镜像。
