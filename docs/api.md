# API 契约

完整 OpenAPI 3.1 快照位于 [`docs/openapi.json`](openapi.json)。前端只调用 `/api/v1`，不直接访问数据库或 Runtime 内部对象。

## 认证

腾讯云 profile 使用 Cookie 会话：

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

开发 profile 可以关闭认证，所有数据使用 `local` owner。生产 profile 必须启用认证。

## 运行和恢复

创建消息接口返回 `202` 和 `run_id`，客户端随后订阅：

```text
POST /api/v1/sessions/{session_id}/messages
GET  /api/v1/sessions/{session_id}/events?after={event_id}
GET  /api/v1/sessions/{session_id}/runs
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/trace
GET  /api/v1/sessions/{session_id}/agent-status
```

SSE 事件带递增 ID。客户端断线后使用最后一个事件 ID重新请求，不重复提交用户消息。

## 状态写入

计划替换、批量调整和其他高风险操作通过 ActionCard：

```text
GET  /api/v1/actions/pending
GET  /api/v1/actions/{action_id}
POST /api/v1/actions/{action_id}/decision
```

重复决策返回已落库状态，不重复应用工具副作用。

运行 Trace 会返回 Agent 角色、阶段事件、结构化产物和模型调用摘要。实时用户请求标记为
`interactive`，定时计划、复盘和恢复任务标记为 `autonomous`。

## 学习任务和复习

课程计划批准后，前端使用任务接口完成真实学习记录：

```text
GET  /api/v1/plans/{session_id}
GET  /api/v1/plans/{session_id}/today
GET  /api/v1/plans/{session_id}/tasks/{task_id}
POST /api/v1/plans/{session_id}/tasks/{task_id}/start
POST /api/v1/plans/{session_id}/tasks/{task_id}/result
POST /api/v1/plans/{session_id}/tasks/{task_id}/complete
```

`result` 接口接收 `score`、`answer`、`notes` 和可选 `error_category`。服务端先通过
typed learning tool 更新掌握度、错题和 FSRS，再保存 DailyPlan，重复提交不会重复写入。

复习中心使用：

```text
GET  /api/v1/reviews/{session_id}/due
GET  /api/v1/reviews/{session_id}/today
POST /api/v1/reviews/{session_id}/items/{concept_id}/result
```

按 Agent 角色查看模型调用：

```text
GET /api/v1/usage/agents
```

课程内容中的 LessonUnit 包含知识点、解释、示例、练习、预期结果和验收标准。模型输出
不完整时使用确定性内容模板，并在计划的 `source`/`content_source` 中标记来源。
