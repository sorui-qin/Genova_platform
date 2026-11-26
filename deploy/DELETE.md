# DELETE 清理版镜像

Genova `1.0.2` 最终 DELETE 镜像采用 `${IMAGE_REPOSITORY}:delete-1.0.2`
（原离线包标签为 `genova/delete:1.0.2`）：在下述清理版 `1.0.1` 上更新平台 runtime，
通过共享 `/app/data/.locks/gpu-0.lock` 与 SurfGen、TarPass 串行执行 GPU 阶段。
发布版包含独立 Worker 服务，无需源码挂载。以下 `1.0.1` 记录描述其已验证的清理基础。

清理版标签为 `genova/delete:1.0.1`。模型代码、权重、runtime 和内置数据均在镜像中，部署端不需要 `Delete/` 源码或公司镜像仓库账号。

本次仅在本机构建，尚未推送镜像仓库。其他机器使用前，需要发布该镜像或通过 `docker save` / `docker load` 导入。

`VERSE/docker-compose.yml` 的 `worker-delete` 直接引用该镜像，不再隐式构建旧镜像。切换运行容器时在仓库根目录执行：

```bash
docker compose -f VERSE/docker-compose.yml up -d --no-deps --force-recreate worker-delete
```

## 清理边界

- 最终镜像从固定摘要的公开 NVIDIA CUDA 镜像构建，不继承旧 DELETE 镜像层。
- 仅从已备份的 `genova/delete:v1` 选择推理代码、权重和所需依赖。保留现有生长点约束与三维结果修复。
- 不复制公司任务服务、`common`、额外分子过滤系统、过滤数据、Git 元数据、模型样例、运行残留、旧 `/app` 和安装包缓存。
- 不复制 Conda 历史、Python 下载来源元数据、Notebook 和 Web 服务包；保留复制依赖中的许可证及版权声明。
- `/opt/delete/runtime-files.sha256` 记录从旧镜像选择并清理后的运行文件哈希。构建时检查已知公司域名；该检查不代表模型代码与权重的分发权利已获确认。

## 维护者构建

仅维护者需要本机原镜像；部署用户直接拉取清理版。原镜像及构建缓存包含未脱敏内容，不应公开发布。

在仓库根目录执行（显式限制构建上下文，也适用于旧 Docker 构建器）：

```bash
set -o pipefail
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='test_*.py' -czf - \
  VERSE/delete-worker.Dockerfile VERSE/delete-image-clean.py \
  VERSE/genova_runtime VERSE/builtin_datasets \
  | docker build -f VERSE/delete-worker.Dockerfile -t genova/delete:1.0.1 -
```

构建源默认是已打过平台补丁的 `genova/delete:v1`，不能替换为未打补丁的公司原镜像；模型补丁已固化在基础镜像，不再保留重复补丁文件。

## 备份与恢复

清理前备份保存在本机 `deploy/dist/backups/delete-before-clean-20260915-202852/`，不纳入 Git，也不要放入对外分发包。包含当前镜像及原公司基础镜像、镜像配置、构建历史和校验文件。已通过压缩完整性、SHA256 及实际 `docker load` 验证。

```bash
cd deploy/dist/backups/delete-before-clean-20260915-202852
sha256sum -c SHA256SUMS
docker load -i delete-images.tar.gz
```

该备份仅包含镜像，不包含宿主机挂载数据和数据库卷。清理版使用新标签，原镜像保留。

## 本次验收

- 清理镜像 ID：`sha256:9ed5491ca63b4dcc1d67e17bede77ba47316e1d41f5682eadf79132d510d050d`。
- 扫描全部 14 层、24,267 个文件，未检出已知公司域名及禁止目录；未继承公司专属镜像层。
- 原有 DELETE 进程及约束检查通过；断网 GPU 验证覆盖自动生长点和指定生长点，均生成可读的三维 SDF 与有效 SMILES CSV。
- 独立 Redis 的 dry-run 成功/失败消息与状态写回通过；Compose 配置检查通过。
- 本地详细记录：`deploy/dist/delete-clean-1.0.1/verification.json`。该验收没有切换现有运行容器，也没有执行前端上传到数据库回写的完整平台验收。
