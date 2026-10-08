# 定时学习提醒

LearningLoop 的提醒功能是单用户、邮件优先的本地能力。默认在 `Asia/Shanghai` 时区每天
08:30 生成并发送今日学习计划，20:30 生成并发送当日复盘。

## SMTP 配置

`F:\code\homework\OnCallAgent\OpspilotAgent` 中的 `MailService` 提供了 SSL/STARTTLS
配置参考。只需把 SMTP 字段以 `LEARNINGLOOP_SMTP_*` 名称写入 LearningLoop 自己的、已被
`.gitignore` 忽略的 `.env`；不要直接加载 OnCallAgent 的完整 `.env`，不要复制验证码、认证
或模型密钥。

没有配置 SMTP 时，邮件会写入 `data/notifications/outbox/`，用于离线开发和测试。

## 配置会话

```powershell
$body = @{ email = "learner@example.com"; enabled = $true; timezone = "Asia/Shanghai"; morning_time = "08:30"; evening_time = "20:30" } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8765/api/v1/notifications/settings/<session-id>" -ContentType "application/json" -Body $body
```

测试发送：

```powershell
learningloop notifications test --session-id <session-id>
```

手动运行到期任务（仍受幂等键保护）：

```powershell
learningloop notifications run-once --force
```

## 调度保证

- 调度器运行在单容器、单 Worker 的 FastAPI 生命周期中，每 30 秒检查一次。
- `session_id + local_date + schedule_type` 是唯一幂等键，同一提醒不会重复发送。
- 发送失败最多重试 3 次并记录错误类型，不影响学习状态保存。
- 服务重启后允许补发 6 小时内的任务，过期任务标记为 `skipped`。
- 短信、验证码网站自动化和公网通知服务不在首版范围内。
