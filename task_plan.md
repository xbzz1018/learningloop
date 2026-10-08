# LearningLoop 0.3.1 Functional Closure Plan

## Goal

Deliver a resume-grade personal learning assistant with a domain Agent Runtime, progressive Agent Skills, recoverable and idempotent state transitions, official DeepSeek routing, lightweight user isolation, observability, and Tencent Cloud deployment assets.

## Phases

- [x] 1. Create the standalone repository and Python 3.12 Conda environment
- [x] 2. Implement configuration, SQLite schema, usage normalization, and provider routing
- [x] 3. Implement learning state, Skills, tools, memory gate, FSRS, and approvals
- [x] 4. Implement FastAPI, SSE, native workbench UI, and CLI
- [x] 5. Add offline tests and pass deterministic quality gates
- [x] 6. Run bounded real-model compatibility checks and local Web QA
- [x] 7. Complete documentation and delivery status
- [x] 8. P0: package 0.3.0, offline Harness dependency, and versioned database migrations
- [x] 9. P1: domain Runtime, run stages, checkpoint repository, and tool-effect ledger
- [x] 10. P2: lazy Skills, code-enforced tool policy, bounded context, and authoritative memory boundary
- [x] 11. P3: official DeepSeek pricing profiles, complete usage semantics, and optional OpenTelemetry
- [x] 12. P4: lightweight account isolation and authenticated API/UI
- [x] 13. P5: OpenAPI snapshot, UI runtime status, backup/restore, and security checks
- [ ] 14. P6: Nginx/Tencent Cloud deployment assets, remote acceptance, and delivery documentation
- [x] 15. 双平面 Agent：Interactive/Autonomous 角色、结构化产物、Trace 与主动调度

## Locked Decisions

- Official DeepSeek is primary; VibeAPI/KCNE are opt-in same-model relays.
- Flash is the default model; Pro is rule-routed and capped to one call per turn.
- SQLite stores operational state; JSON files store structured learner state.
- Search uses DeepSeek Responses web_search, then DuckDuckGo.
- The service has no public registration. Operators create local accounts through the CLI; all learning data is owner-scoped.
- No RAG, vector database, MCP, Supervisor-style delegation, or general shell.
- The current pinned agent-harness remains the shared model/tool loop for two controlled roles: Interactive and Autonomous. Hermes, DeepAgents, OpenAI Agents SDK, and Pydantic AI Harness are not runtime dependencies.
- SQLite/JSON are authoritative. Harness WorkingMemory is turn-scoped; the unused long-term MemoryManager is removed.
- Caddy provides HTTPS only. Application session authentication replaces shared Basic Auth.

## Delivery Status

### 0.3.1 Functional Closure

- [x] P0: fix async WorkingMemory adapter and ordinary ReAct runtime
- [x] P1: add detailed LessonUnit content and deterministic topic fallback
- [x] P2: add task start/result APIs, structured result modal, mastery/error/FSRS writes
- [x] P3: add review result API and actionable review-center UI
- [x] P4: refresh OpenAPI, Docker image and browser workflow
- [x] P5: run the 10-case functional evaluation set and record failure analysis

- Offline tests: 53 passed.
- Ruff: passed.
- Live compatibility: Vibe Flash/Pro core chat passed; KCNE Flash core chat and web search passed; KCNE Pro returned 401.
- Local Web: `http://127.0.0.1:8765/` is running with the latest code.
- Current usage ledger includes live doctor checks and two real learning flows; costs are estimated because relay actual-cost fields were unavailable.
- Daily plan/review persistence, 08:30/20:30 SMTP scheduling, idempotent delivery records, and the date-grouped plan table are implemented.
- Docker Compose is configured for a single `/data` volume and single-worker scheduler. A local wheel preserves the pinned Harness commit, so image builds no longer clone GitHub.
- Course approvals use ActionCards and immediately create today's plan; the Web workbench separates conversation, plan, progress, review, usage and notification views.
- ActionCard decisions are event-driven and do not append chat messages. Docker now installs the pinned Harness wheel locally; container health and browser smoke pass.
- SMTP fields are mapped into the ignored local `.env`; the Notification Settings test action completed a real SMTP delivery successfully.
- Current acceptance: 37 offline tests, Ruff, JavaScript syntax, Docker build/health, and live SSE chat response all pass.
- Container Skill loading and retry recovery are verified against the previously stuck session; no duplicate user message was written.
- The 0.3.0 runtime baseline is superseded by 0.3.1 functional-closure changes; the Docker health endpoint reports `0.3.1`.
- P0-P5 implementation is complete: local wheel dependency, versioned migrations, Runtime stages, lazy Skills, owner-scoped auth, OpenAPI snapshot, optional OTel bridge, and SQLite Backup API.
- Docker image builds without apt or GitHub clone, and the local container reports healthy after the 0.3.1 rebuild.
- Browser review confirmed the current workbench UI: current-session-first sidebar, explicit history expansion, collapsible navigation, Runtime stage/Skill panel, cache-hit rate, and Flash/Pro usage split.
- Official DeepSeek smoke passed for Flash and Pro: model IDs, JSON output, streaming, and usage all passed; 5 calls used 8,207 tokens with a $0.003424 official-price estimate.
- ActionCard execution now refreshes the workspace summary without a page reload; Runtime stage, pending actions, progress and today's task preview are updated from the state API.
- Repeated ActionCard decisions are idempotent and return the stored action state. The browser flow was rechecked against a real approved plan and the generated date-grouped plan table.
- Final local acceptance after the UI/runtime fixes: 46 tests passed and the Compose container is healthy.
- 0.3.1 detailed-content and task-result changes are covered by 53 passing tests; the OpenAPI snapshot now contains 35 paths.
- The live Docker Flash smoke completed a normal ReAct tool loop in a new session: `completed`, 1 call, 1,226 tokens, official-price estimate `$0.00038208`.
- The same smoke window contains no `a coroutine was expected` or `stream crashed` errors. Task details, start state, result modal, mastery/error and deterministic review were verified in the browser.
- Functional Evaluation V1 passed 10/10 deterministic scenarios. Final structured artifacts, recovery, state integrity and idempotency each passed 100%; these are functional metrics, not model-quality or production-load results.
- Tencent Cloud HTTPS and public health check passed on `https://learningloop.43-131-243-184.nip.io`; admin-account, backup/restore and restart acceptance remain.

### 双平面 Agent 增强

- [x] 新增 Interactive/Autonomous Agent 角色字段、运行产物和按角色用量聚合。
- [x] 定时计划和复盘通过 Autonomous Agent 入口运行，保留旧 DailyLearningService 注入兼容。
- [x] 新增 Run Trace、Agent 状态和结构化产物 API，并更新 OpenAPI 快照。
- [x] 新增角色、产物、调度入口和 Trace 回归测试；当前离线测试为 58 项。
- [x] 指标测量：冻结 10 个路由场景和 3 组上下文对照；Flash 占比 80%，Skill/历史/摘要输入 Token 分别减少 74.28%/57.82%/95.34%，混合路由相对 Pro-only 官方价格估算降低 33.07%。

## Error Log

| Error | Attempt | Resolution |
|---|---:|---|
| Initial patch targeted the prior workspace | 1 | Restored prior files and switched to target-scoped apply_patch. |
| Upstream Skill Loader used Windows GBK for UTF-8 Chinese Skills | 1 | Added a local UTF-8 loader that returns the upstream Skill type. |
| Secret scan matched fixture keys in test source | 1 | Scan only real local `.env` secrets against non-secret project files. |
| Pro generated plan prose without invoking approval tool | 1 | Replaced high-risk planning with a deterministic structured-output and approval node. |
| Explicit plan request routed to goal anchoring when no course existed | 1 | Prioritized explicit plan/roadmap intent before the empty-course fallback. |
| Docker build stalled on Debian apt mirrors | 1 | Removed unnecessary apt dependency; the Python base image and locked wheels are sufficient. |
| pip-audit could not reach pypi.org over TLS | 1 | Upgraded the locally reported pytest vulnerability to 9.0.3; rerun the audit from a network with stable PyPI access. |
| Harness `fire()` received `None` from `TurnMemory.write_working_fact` | 1 | Made the compatibility method async and added a normal ReAct integration test; live Docker Flash smoke now completes without the exception. |
| Empty model JSON passed default Pydantic values | 1 | Added non-empty business validation for title, goal and stages before deterministic fallback. |
| Windows temporary SQLite file remained locked after functional evaluation | 1 | Enabled `TemporaryDirectory(ignore_cleanup_errors=True)` so post-run cleanup cannot discard completed case results. |
| Functional owner-isolation fixture created a session before its user | 1 | Create both owner records first so the case evaluates access isolation instead of failing the foreign-key precondition. |
