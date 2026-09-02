# Findings

## Upstream Baselines

- Agent Harness commit: `c06e0a9ebbbd50543dbf6463201ac07887d5e03e`.
- Learn Anything Skill commit: `2886af46b67bcdf5e73e085307d0e8747b47090d`.
- The Harness already supplies ReAct, Skill loading, fallback/routing adapters, SQLite sessions, working-memory compaction, checkpoints, traces, and token budget primitives.
- LearningLoop does not copy the upstream MCP, sub-agent, Rust executor, vector-memory, or provider OAuth entrypoints.

## Provider Configuration

- The private attachment contains four keys across VibeAPI and KCNE.
- Each provider has a distinct Flash key and Pro key.
- Secret values are never copied into planning documents, logs, traces, API responses, or committed files.

## Design Notes

- Main agent calls use the upstream Chat Completions adapter wrapped with per-attempt auditing.
- Web search uses a separate Responses API call so built-in web_search can be capability-tested without replacing the Harness adapter.
- Missing usage and price values remain null. Official DeepSeek pricing is stored only as a versioned estimate.
- The upstream `load_skill()` uses `Path.read_text()` without an encoding and fails on Chinese Skills under a GBK Windows locale. LearningLoop loads UTF-8 explicitly while preserving the upstream `Skill` contract.
- Real compatibility gate: Vibe Flash/Pro passed chat, structured output, streaming, and usage; Vibe Responses web_search returned an upstream error. KCNE Flash also passed Responses web_search. KCNE Pro returned HTTP 401 on both `/models` and `/v1/models`.
- The first Pro ReAct planning run completed without calling the approval tool. High-risk plan generation now bypasses open-ended ReAct: one structured model call is validated as `CoursePlan`, then code always creates an approval request.
- The current service directly constructs Harness `BaseAgent`; the project Runtime must remain a thin domain facade rather than duplicate the upstream multi-agent orchestrator.
- Harness `MemoryManager` is configured with `memory_context_enabled=False` and `context_max_episodes=0`; it is not a valid long-term-memory claim. Structured SQLite/JSON state and bounded summaries remain authoritative.
- Skill instructions are injected only for the selected Skill. The catalog parses frontmatter and hashes at startup, then loads the full `SKILL.md` body only when that Skill is activated.
- The browser already implements Enter/Shift+Enter, session rename/pin/delete, SSE event cursors, heartbeat, and reconnect. These are regression targets, not new features.
- Docker installs the vendored Harness wheel and `pyproject.toml` resolves the same local package version, so builds no longer require a live GitHub clone.
- Laboratory use requires lightweight owner isolation but not organizations, RBAC, OAuth, or public registration. Caddy will terminate TLS; the application will own login sessions.
- ActionCard decisions must update both the approval/action ledger and the Run stage. Returning the persisted terminal action on repeated requests prevents duplicate plan writes after browser retries.
- The workspace summary is server-rendered for first paint and then reconciled from `/state`, `/plans`, and `/actions/pending`; this keeps the right rail accurate after an approval without `window.location.reload()`.
- Harness `BaseAgent` calls `fire(self._memory.write_working_fact(...))` for structured tool observations; the compatibility adapter must therefore return an awaitable even when LearningLoop intentionally keeps long-term facts in SQLite/JSON.
- A Pydantic-valid default `CoursePlan` can still be business-empty. Title, goal and at least one stage are required before accepting model output; otherwise the deterministic topic fallback is used.
- A task result can create an FSRS card whose `due_at` is in the future. “Review scheduled” and “due today” are distinct states and must be represented separately in tests and UI.
- Functional Evaluation V1 separates deterministic system correctness from model quality: its 10/10 result supports resume claims about workflow integrity, recovery and idempotency, but not answer accuracy or production latency.
- Offline scenario P50/P95 includes Python setup, SQLite and service initialization for each isolated case. It must never be presented as DeepSeek response latency.

## 2026-09-02 双平面 Agent 实施结果

- 保留共享 Harness ReAct 循环，新增 `interactive` 与 `autonomous` 两种运行角色；没有增加 LLM Supervisor 或 Agent 间自然语言拼接。
- 实时消息由 Interactive Agent 入口处理；SQLite Scheduler 的每日计划和复盘由 Autonomous Agent 入口处理。
- `runs`、模型调用、事件和 Agent Artifact 记录角色；新增 Trace、Agent 状态和按角色用量 API。
- 旧记录通过迁移默认归为 `interactive`，旧测试和调用方式保持兼容。
- 回归结果：55 项 pytest 通过，Ruff 与 Python 编译检查通过；原功能评测 10/10 场景通过，结构化产物、恢复、状态一致性和幂等性均 100%。
- 30%、40%、70% 的 Token/路由/成本数字没有证据，暂不写入简历；需要在固定输入和 Pro-only 基线上重新测量。

## 2026-09-02 简历指标冻结结果

- 使用官方 DeepSeek 路由完成 10 个固定任务和 3 组上下文对照，共 16 次小规模调用。
- 路由结果为 Flash 8 次、Pro 2 次，固定场景 Flash 占比 80%。
- Provider 返回的输入 Token 显示：渐进式 Skill 加载 `762 -> 196`，减少 74.28%；受限历史上下文 `2034 -> 858`，减少 57.82%；结构化摘要 `1245 -> 58`，减少 95.34%。
- 同一批真实 Token 按官方价格重算：混合路由 `$0.00369006`，反事实 Pro-only `$0.00551298`，估算降低 33.07%。
- 原先“成本降低约 40%”不成立，简历只能写约 33%；Token 指标必须标注为固定提示对照，不能泛化为所有请求。
