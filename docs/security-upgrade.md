# 持久化、管理员身份与工作流恢复

Compose 将业务状态存入 `harborpilot_data` 卷，路径 `/var/lib/harborpilot`；`HARBOR_AGENT_DATA_DIR` 可覆盖业务目录。`HARBOR_AGENT_SEED_DIR` 默认为仓库 `data`，只读种子与用户数据库、profile secret、工作流、快照分离。镜像构建上下文排除了 SQLite、用户快照、密钥和本地配置。

已有部署迁移前应停止 API/worker，备份原数据目录，将数据库、`.harborpilot_profile_secret` 和业务快照一起移入持久目录；再启动新版本。备份、恢复必须同时保留密钥与数据库。不要只复制 SQLite 主文件而丢弃活跃 WAL；使用 SQLite backup API 或停机后复制。

管理员请求必须提供 `HARBOR_AGENT_ADMIN_TOKEN` 对应的 `x-harbor-admin-token` 或 Bearer 凭据。localhost、代理回环来源和 testclient 均不会获得管理员身份；兼容保留的 `allow_insecure_local_admin` 不再授权。无 owner 的旧工作流仅管理员可访问。

首次创建 profile secret 通过完整临时文件和原子发布完成，文件权限为 0600；竞争进程读回同一个最终密钥，旧密钥不会被替换。

恢复操作在 SQLite 中认领工作流，整个读取、校验、保存和执行期间仅允许一个恢复者。重复并发请求返回 409，正常结束或校验失败释放认领。认领不自动超时：无法证明旧 worker 停止时，不能允许第二个执行者继续副作用。若进程崩溃，确认并停止旧 worker 后，管理员才能在备份后清理 `agent_runtime.sqlite` 的 `workflow_resume_claims` 中对应记录，再恢复。不要在仍运行的 worker 上删除认领。

回归：`python -m pytest -q tests`；确定性回测 `python -B scripts/run_agent_evals.py` 默认使用临时数据库，不调用付费模型。
