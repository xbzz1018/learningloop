# LearningLoop Architecture

```text
Browser / CLI
    |
    v
FastAPI + SSE application service
    |
    +--> SkillCatalog (UTF-8, progressive activation)
    +--> Goal state machine (topic / outcome / duration / capacity)
    +--> LearningLoop Runtime (domain lifecycle facade)
            +--> Agent Harness BaseAgent (bounded ReAct loop)
            |       +--> Interactive Agent (user requests)
            |       +--> Autonomous Agent (scheduler requests)
            |       +--> ModelPolicy: Flash / Pro
            |       +--> FallbackLLM: Official DeepSeek -> optional relay, same model only
            |       +--> Typed learning tools + ActionCard HITL
            |       +--> Checkpoint / tool-effect ledger / Trace / BudgetGuard
    |
    +--> SQLite operational ledger
    |       sessions, messages, events, actions, approvals, checkpoints,
    |       runs, agent_artifacts, tool_effects, users, auth_sessions,
    |       provider capabilities, model_calls, daily plans/reviews,
    |       notification settings/deliveries
    |
    +--> JSON learning workspace
            learner, course, concepts, errors, reviews
            + FSRS deterministic review scheduling
    |
    +--> Notification scheduler (08:30 plan / 20:30 review)
            + SMTP SSL/STARTTLS or explicit local outbox
```

## Agent 平面

LearningLoop 使用两个运行入口，共享一个 Harness Runtime：

- **Interactive Agent**：由用户消息触发，负责目标确认、学习辅导、练习反馈和计划建议。
- **Autonomous Agent**：由 SQLite Scheduler、到期复习和延期检测触发，负责每日计划、晚间复盘、恢复建议和邮件内容。

两个入口通过结构化学习状态、事件和 Agent Artifact 衔接，不拼接完整聊天文本。每次运行记录角色、Skill、模型、阶段、Checkpoint 和结果，前端可通过 Trace 接口查看。

## State Boundaries

The model never writes the database or JSON files directly. It emits tool calls or a validated `CoursePlan`. Read tools are automatic, reversible writes update structured state, and plan replacement/deletion/bulk changes create an approval request first.

Short-term context contains the last eight messages and a bounded summary. Long-term state is structured and queried selectively; the entire SQLite history is never placed into a model prompt. Harness WorkingMemory is turn-scoped; SQLite/JSON learning state is the only authoritative memory source.

Goal anchoring is deterministic at the workflow boundary: the assistant stores topic, current background, target outcome, duration, weekly cadence, and daily capacity as typed fields. When required fields are complete, an ActionCard asks whether to generate a course plan. The user never has to type “approve” into chat.

Approved courses contain structured LessonUnits instead of only stage titles. DailyTask records
the selected lesson content and a user's answer, notes, score and error category. A single typed
learning-result path updates the task, concept mastery, error history and FSRS card so the plan,
review center and daily recap read from the same state.

## Provider Policy

Flash is the default for routing, teaching, feedback, and memory summaries. Pro is selected by deterministic task metadata or explicit deep mode. Each route is wrapped with a circuit breaker and same-model provider fallback. Authentication and schema errors do not trigger fallback.

Prompt and Skill hashes are written into run events. Per-call records include requested/actual model, provider alias, Token fields, latency, retry/fallback attribution, and nullable cost. Application-level turn/day Token limits and the development cost ceiling are enforced before new requests.

## Deliberate Non-Goals

The core profile does not add Supervisor-style delegation, RAG, a vector database, MCP, Redis, Celery, voice, or vision. Those technologies do not improve the learning loop enough to justify their operational cost. The project instead demonstrates long-running interactive and autonomous Agent entrypoints, controlled state transitions, recoverability, owner isolation, and observable model/tool usage.
