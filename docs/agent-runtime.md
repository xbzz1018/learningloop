# Agent Runtime 设计

LearningLoop 使用一个共享的模型工具循环和两个 Agent 运行入口。上游 `agent-harness` 提供 `BaseAgent`、WorkingMemory、BudgetGuard 和事件类型；`LearningLoopRuntime` 负责把这些通用能力约束到学习领域。

## 两个运行入口

```text
用户消息                    SQLite Scheduler / 到期复习
    ↓                                   ↓
Interactive Agent                Autonomous Agent
    └──────────── 结构化学习状态 ────────┘
                         ↓
                   SQLite / FSRS / 邮件
```

Interactive Agent 处理实时目标确认、讲解、练习和反馈；Autonomous Agent 处理 08:30 计划、20:30 复盘和延期恢复。两者共享 Skill Catalog、Tool Policy、Checkpoint 和 Usage Ledger，但使用独立的角色配置、上下文范围、工具白名单和预算。

## 一次运行

```text
收到消息
→ 创建 Run
→ 构建受限上下文
→ 选择 Skill
→ 检查 Skill 工具矩阵
→ 选择 Flash/Pro
→ 执行 BaseAgent ReAct 循环
→ 校验工具副作用
→ 保存 Checkpoint
→ 生成 ActionCard 或完成
```

`runs` 记录角色、阶段和错误，`agent_artifacts` 保存结构化交接结果，`checkpoints` 记录最近稳定状态，`tool_effects` 用稳定哈希防止重试重复写入。模型输出不是事实源，课程、掌握度和 FSRS 日期只由 Pydantic Schema 与领域工具写入。

## Skill 和工具

Skill 采用 `SKILL.md` 渐进加载。frontmatter 中的 `allowed-tools` 仅用于声明和提示，最终权限由 Python `SkillPolicy` 决定。搜索工具只返回不可信观察，不能直接改变长期状态。

## 记忆

- WorkingMemory：一次 Agent Run 内的思考和工具观察；
- 会话上下文：最近消息和有界摘要；
- 业务记忆：SQLite/JSON 中的目标、课程、知识点、错误和复习卡片。

上游长期 MemoryManager 不作为第二事实源使用。这样恢复、审计和用量统计都能从本地数据库复算。

## Trace 接口

```text
GET /api/v1/runs/{run_id}/trace
GET /api/v1/sessions/{session_id}/agent-status
GET /api/v1/usage/agents
```

Trace 返回运行角色、阶段事件、结构化产物和模型调用摘要，便于区分前台交互与后台主动任务。
