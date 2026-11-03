# Operations Notes

## Local Commands

- `learningloop doctor`: show provider aliases, models, and configuration without calling the network.
- `learningloop doctor --live`: run the bounded model compatibility gate and store capability results.
- `learningloop serve`: start the local FastAPI application.
- `learningloop cleanup`: delete operational messages/events older than 90 days and attempt a lock-safe SQLite WAL checkpoint. A running server may defer the checkpoint.
- `learningloop users create <username>`: create a private account without exposing the password in shell history.
- `learningloop backup create --output <path>`: create a consistent SQLite backup.
- `learningloop backup restore --input <path> --confirm`: restore after stopping the service and require an explicit confirmation.

Optional quality and OTLP dependencies are pinned in `requirements.dev.lock` and
`requirements.observability.lock`; they are intentionally not installed into the production image.
The repository Pyright gate currently targets the new Runtime, auth, backup, context and hook modules;
the legacy service and provider adapters remain covered by pytest/Ruff while their older dynamic
dictionary boundaries are migrated incrementally.

## Current Live Gate Result

- 生产运行使用官方 DeepSeek Flash/Pro；模型和 Key 通过 `LEARNINGLOOP_DEEPSEEK_*` 注入，日志只记录 provider alias。
- Vibe/KCNE 配置仍兼容旧的本地环境，但默认不进入路由；设置 `LEARNINGLOOP_ENABLE_RELAY_FALLBACK=true` 后才允许同模型故障转移。
- `learningloop doctor` 只检查配置，状态为 `not_checked` 或 `missing_key`，不发请求；真实兼容性检查由显式的 `learningloop doctor --live` 执行，会消耗模型用量。
- Live 检查分别报告普通聊天、结构化输出、streaming、usage，以及 Flash 的 web search。`available` 仅表示普通聊天通过，不能代表所有能力通过；Pro web search 与工具调用未测，不宣称可用。
- 持久化的 `AuthenticationError`（401）、`PermissionDeniedError`（403）和 `missing_key` 会从新建模型路由中排除。修正本地配置后运行 `doctor --live` 复测，再重启应用以重建路由；web search 失败不会屏蔽普通聊天。
- KCNE Pro 真实认证、云端管理员创建、登录隔离、备份恢复和容器重启仍需独立验收；离线 Fake 测试不代表这些环节通过。

## Secret Handling

The local `.env` is ignored by Git. Logs, events, traces, API responses, and usage exports store only provider aliases and redacted content. Replace any exposed key before sharing this repository.

For Tencent Cloud, enable `LEARNINGLOOP_AUTH_ENABLED=true` and create accounts with
`learningloop users create <username>`. The application scopes all sessions and usage by owner.
