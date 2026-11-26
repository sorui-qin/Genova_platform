# Genova 前端

## 本地启动与 CUDA

运行 `npm run dev`（或 `dev:force`）会先启动后端和全部模型 Worker，再并发检查 Agent API 和 SurfGen、DELETE、ECloudGen、EPSO、TarPass 容器内的 CUDA。正常运行的容器会复用；停止的服务会启动，Compose 配置变化时会更新对应容器。检查失败的 GPU Worker 自动重新创建一次；仍不可用时终止启动并输出错误。`dev:force` 只强制刷新 Vite 依赖缓存，不强制重建后端。

启动检查需要当前用户能访问 Docker，并且宿主机 NVIDIA 驱动正常。脚本在运行环境中检查 CUDA。直接运行 Vite 会跳过该流程。平台运行期间若只有个别 Worker 报 NVML 或 CUDA 初始化错误，可按手动步骤定位并恢复对应服务。 [GPU 排障](../README.zh-CN.md#gpu-排障系统升级后容器无法使用-cuda)

机器正常重启后通常不需要重新创建容器。后端进程未启用源码热重载，修改后端源码后需手动重启受影响的服务；在本目录执行：

```bash
docker compose -f ../VERSE/docker-compose.yml restart backend-api backend-worker workflow-worker
```

修改 `genova_runtime` 后，同样需要重启对应 Worker 或 Dispatcher。

## 当前模块

- 蛋白准备
- SurfGen / ECloudGen 从头分子生成
- DELETE / EPSO 先导优化
- TarPass 后处理

默认入口为 `http://localhost:18001/genova/`。构建使用 `npm run build`。测试脚本和中英文目录检查在 `test` 分支维护。
