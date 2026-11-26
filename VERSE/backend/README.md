# 后端

API 使用 `/api/v1`，入口为 `backend.main:app`；`python -m backend.worker` 负责 Outbox 投递、结果回写和文件清理，`python -m backend.workflow_worker` 负责工作流。

`POST /api/v1/jobs` 必须传 `job_type`，仅接受 `protein_preparation`、`molecule_generation`、`property_optimization`、`molecule_postprocessing`。模型参数分别放入对应 `params` 子对象，文件使用 Dataset ID，不接收服务器路径。

- 分子生成：`params.molecule_generation.engine` 为 `surfgen` 或 `ecloudgen`。
- 先导优化：`params.property_optimization.engine` 为 `delete` 或 `epso`。
- 后处理：`params.postprocessing.source_job_id` 指向原生成任务。
- 蛋白准备使用 v2 preparation，生成使用已准备、校验通过的 v4 Context。

认证通过 Bearer JWT 或访客码；改密撤销旧访问令牌、刷新令牌和 WebSocket。管理员仅通过 `python -m backend.admin_users grant|revoke USER_UUID` 操作已有正式账号。

删除先调用 `POST /api/v1/jobs/deletions/preview` 获取关联清单与签名确认令牌，再调用 `POST /api/v1/jobs/deletions`，传 `job_ids` 和 `confirmation_token`。确认后删除关联任务、会话与专属文件，保留原始输入。详细资源限制、重试和升级操作见 [部署说明](../../deploy/README.md)。

历史任务通过通用结果和文件接口读取，不提供旧模型的新任务入口。
