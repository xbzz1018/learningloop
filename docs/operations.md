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
- 真实兼容性检查必须在注入新 Key 后由 `learningloop doctor` 显式执行，未检查的能力不会被宣称为可用。

## Secret Handling

The local `.env` is ignored by Git. Logs, events, traces, API responses, and usage exports store only provider aliases and redacted content. Replace any exposed key before sharing this repository.

For Tencent Cloud, enable `LEARNINGLOOP_AUTH_ENABLED=true` and create accounts with
`learningloop users create <username>`. The application scopes all sessions and usage by owner.
