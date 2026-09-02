# Progress

## 2026-08-31

- Created `F:\code\homework\project\learningloop` as an independent Git repository.
- Created Conda environment `learningloop` with Python 3.12.
- Added package metadata, environment declaration, secret-safe example configuration, and persistent planning files.
- Implementation is in phase 2: configuration, persistence, provider routing, and usage accounting.
- Offline suite passes 22 tests; Ruff passes.
- Official DeepSeek was added as the production-first provider. Relay providers remain opt-in fallback and are not silently selected.
- Deterministic planning flow now validates `CoursePlan` once and always creates an approval request; approved plans alone are persisted.
- Real end-to-end checks: one Flash goal-intake run and one Pro deep-plan run completed. The Pro run used one call, 2,309 tokens, and generated six stages; course state changed only after approval.
- Browser QA passed desktop layout, mobile 390px no-overflow, new-session creation, SSE completion refresh, and usage panel.
- Fixed idle processing indicator visibility and lock-safe SQLite cleanup.
- Final offline quality gate: 28 tests passed; `pip check` and Ruff passed.

## 2026-09-01

- Added `DailyPlan` and `DailyReview` schemas with deterministic scheduling constraints and model-assisted summaries.
- Added SQLite daily plan, review, notification settings and delivery tables with an idempotency key per session/date/type.
- Added SMTP/local-outbox notification service adapted from the existing OnCallAgent mail configuration pattern.
- Added an in-process single-worker scheduler: daily plan at 08:30 and review at 20:30 in Asia/Shanghai, six-hour catch-up window, retry/backoff and skip recording.
- Added plan-table UI with date grouping, completion percentage, status chips and stage completion actions.
- Added notification and daily-plan APIs, CLI commands, Dockerfile, Compose and notification documentation.
- Final offline quality gate: 32 tests passed; Ruff passed. Docker Compose configuration parses successfully; image build was blocked only by the environment's intermittent GitHub DNS/network access to the pinned Harness dependency.

- Replaced chat-text approvals with idempotent ActionCards for execute, continue, suggest and reject decisions; decisions do not add user chat messages.
- Approval now applies the course and creates today's deterministic plan in one operation; suggestions create a new proposal and retain history.
- Rebuilt the UI as a workbench with separate conversation, plan, progress, review, AgentOps usage and notification views; renamed the agent to 学习助手 and visually separated roles.
- Added cache-field semantics and P50/P95 latency to the usage view.
- Added notification verification gating so local outbox output is not treated as a verified SMTP delivery.
- Added a local Harness wheel for the pinned commit. Docker image build, Compose startup, health checks and browser smoke now pass without cloning GitHub during the build.
- Current offline quality gate: 35 tests passed; Ruff passed; desktop and 390px responsive browser QA passed.
- ActionCard workflow, session menu, refreshed workbench layout, verified SMTP configuration mapping, local Harness wheel Docker packaging, and container health validation are now complete.
- Real SMTP delivery was not triggered automatically; use the Notification Settings test button after checking the recipient address.
- Docker image rebuilt from the updated source, Compose container is healthy on `127.0.0.1:8765`, and the containerized workbench has no browser console errors.
- Fixed Docker Skill discovery by making `skills_dir` explicit and moved Skill selection inside the run error boundary; stale runs now emit an error instead of hanging.
- Added retry API/UI that reuses the latest user message without duplicating it. The previously stuck session was recovered successfully: status completed, one model call, and message count unchanged.
- Added typed learning-goal slots and a deterministic goal-complete ActionCard before plan generation; this prevents repeated goal-anchoring questions and makes workflow transitions explicit.
- Added application-level historical cost enforcement plus prompt/Skill version hashes in run metadata.
- Removed the unused HTMX CDN, vendored the fixed Lucide build locally, and enabled cross-document view transitions to reduce navigation flicker.
- Live browser chat validation passed: optimistic user message, SSE assistant reply, input recovery, no page refresh, and no console errors.
- Current offline quality gate: 37 tests passed; Ruff and JavaScript syntax checks passed.
- Earlier 0.2.0 baseline unified the package, FastAPI, and health version; the 0.3.0 release supersedes it with Runtime, auth, migration, and deployment upgrades.
- Fixed the no-response production failure caused by `/app/skills` discovery; stale runs now become recoverable and the existing stuck session was successfully retried.
- Added structured goal slots and a workflow checkpoint before plan generation, plus historical cost enforcement and local Lucide/view-transition assets.

## 2026-09-02

- Started the 0.3.0 resume-grade upgrade after reconciling the approved plan with the current implementation.
- Locked the architecture to one pinned agent-harness loop, a thin LearningLoop Runtime facade, authoritative SQLite/JSON state, official DeepSeek production routes, optional OpenTelemetry, and lightweight account isolation.
- Confirmed that existing Enter handling, session actions, SSE cursor reconnect, ActionCards, and local Docker wheel packaging must be preserved rather than rebuilt.
- P0-P2 completed: package version 0.3.0, local Harness wheel resolution, versioned schema migrations, domain Runtime stages, tool-effect ledger, lazy Skill activation, code-owned tool policy, and bounded ContextBuilder.
- P3 completed in code: official DeepSeek remains the production profile, usage/cache semantics are preserved, and OpenTelemetry model spans are optional and fail closed when extras are absent.
- P4 completed: Argon2id-backed local accounts, cookie sessions, owner-scoped session/action/usage APIs, login page, logout, and cross-user isolation tests.
- P5 completed: OpenAPI 3.1 snapshot, SQLite Backup API CLI, Caddyfile, Tencent Cloud Compose, security/recovery/deployment documentation, and 44 offline tests.
- Docker no longer invokes apt or GitHub during the build. The image rebuilt successfully, the Compose container is healthy, and an in-container backup passed `integrity_check`.
- P6 remains pending only for real Tencent Cloud DNS/HTTPS/backup acceptance; no server connection was attempted without a domain and SSH authorization.
- Official DeepSeek smoke (isolated data directory) passed for Flash and Pro: model list, JSON output, streaming, usage and actual model IDs all matched. The smoke used 5 billable calls, 8,207 total tokens, and an official-price estimate of $0.00342444.
- The local `.env` now contains the official key without exposing it in repository files or logs; the running local container reports both official routes configured.
- `pip-audit` identified and was resolved for pytest 8.4.2 -> 9.0.3, but the follow-up audit could not reach PyPI because of a transient TLS EOF; no vulnerability result is claimed for the complete lock until that audit is rerun.
- Final local validation: 45 tests passed, Ruff passed, scoped Pyright passed, `pip check` passed, OpenAPI snapshot parsed, official smoke data is isolated, Docker builds without apt/GitHub access, the container is healthy, and the application user can write `/data`.
- Refined the visible workbench after browser review: current session is shown by default, history sessions are explicitly expandable, the navigation rail can be collapsed, Runtime stage/Skill are visible in the context panel, and usage now shows cache-hit rate plus Flash/Pro distribution.
- Rebuilt the image after the UI update; the running local page at `127.0.0.1:8765` shows the 0.3.0 workbench and the container remains healthy.
- Fixed ActionCard post-decision synchronization: the workspace now updates the Runtime stage, progress summary, pending-action count, and today's task preview through API refreshes without a full-page reload.
- Action decisions are idempotent at the service boundary; a repeated execute/reject request returns the persisted action state and cannot repeat plan writes or daily-plan creation.
- Added stable DOM hooks for the workspace summary and aligned the static asset cache version so a stale browser bundle cannot hide the new behavior.
- Browser QA verified the approved flow end to end: the workbench shows `completed` and today's tasks immediately, and the date-grouped plan table contains the generated stages. Browser console errors: none.
- Current offline quality gate: 46 tests passed; Ruff, Python compilation, JavaScript syntax, Docker build, health check, and local workbench smoke passed.

## 2026-09-02 · 0.3.1 functional closure

- Fixed the production blocker in `TurnMemory`: Harness `fire()` now receives an async coroutine instead of `None` when a tool returns a structured result.
- Added a normal ReAct integration test covering tool call, structured tool observation and final assistant answer.
- Extended `CourseStage` and `DailyTask` with `LessonUnit` content: concepts, explanation, example, exercise, expected output and acceptance criteria.
- Added deterministic topic content profiles for Python, Web, data structures/algorithms, SQL, machine learning and Agent development, plus a non-empty generic fallback for other topics.
- Planning now requires non-empty title, goal and stages. Invalid, empty or incomplete model plans are enriched locally and visibly marked as fallback content.
- Added task start, task detail and task result APIs. Structured result submission updates mastery, errors, FSRS and the saved daily plan through the existing typed learning tool.
- Rebuilt the plan view as an actionable task workspace with expandable learning content, start/record-result buttons and a structured result modal. The review view now exposes recent errors and a review-result modal.
- Regenerated the OpenAPI 3.1 snapshot with 33 paths and added contract assertions for task and review endpoints.
- Regression status: 53 offline tests pass, Ruff/compile/JavaScript checks pass, Docker image is healthy at version 0.3.1.
- Live Docker Flash smoke passed after the fix: a new session completed a normal ReAct tool loop with 1 call and 1,226 tokens (official estimate `$0.00038208`); no coroutine or stream-crash error appeared in the smoke window.
- Browser verified detailed task expansion, task start, result recording, recent-error display and deterministic daily review generation.
- OpenAPI was regenerated after the activity route was added; the final snapshot contains 35 paths and version `0.3.1`.
- Final image rebuild includes the activity API and all task/review UI changes; Compose remains healthy and the final plan-page screenshot shows detailed tasks, completion state, and result actions.
- Added Functional Evaluation V1 with 10 isolated deterministic scenarios and versioned JSON/Markdown results. The final run passed 10/10; structured artifacts, recovery, state integrity and idempotency each passed 100%.
- The functional suite's local P50/P95 was 456.63/667.25 ms, explicitly labelled as offline scenario runtime rather than model latency. The report records the runner SHA-256 and each case result.
- Full acceptance after the evaluation: 53 pytest cases, Ruff, dependency checks, secret scan and Docker health all pass. Real Tencent Cloud and real SMTP remain external acceptance items.

## 2026-09-02 · 双平面 Agent 增强

- Added `interactive` and `autonomous` Agent roles on the shared Harness runtime; legacy calls default to `interactive`.
- Added versioned migration 003 with agent-role fields, parent run linkage and `agent_artifacts` storage.
- Connected the 08:30 plan and 20:30 review scheduler to Autonomous Agent entrypoints while preserving direct service injection for tests.
- Added Trace, Agent status and role-level usage endpoints; refreshed the OpenAPI 3.1 snapshot.
- Added role/artifact/endpoint regression coverage. Current offline gate: 55 tests passed, Ruff and compilation passed.
- Measurement work remains: context reduction, summary compression, Flash share and routing cost delta require fixed baselines before resume use.
- Fixed a migration ordering issue where an index referenced `parent_run_id` before migration 003 added the column; legacy `/data` databases now start and migrate safely without data deletion.
- Added Agent Artifact Pydantic validation, role-specific tool/Skill matrices, runtime role metadata, dynamic role display in the workbench, and the metrics measurement module.
- Final regression: 58 pytest cases passed, Ruff passed, scoped Pyright reported 0 errors, `pip check` passed, JavaScript syntax passed, OpenAPI contract passed, and Docker Compose rebuilt with a healthy `0.3.1` container.
- User-confirmed real SMTP test delivery succeeded; the resume may state that SMTP delivery was verified, but no delivery-rate percentage is claimed.
- Added and executed Resume Metrics V1 against official DeepSeek: 16 calls measured progressive Skill loading, bounded context, summary compression and frozen routing cases.
- Verified results: 74.28% Skill input-token reduction, 57.82% bounded-history reduction, 95.34% summary reduction, 80% Flash share and 33.07% estimated cost reduction versus counterfactual Pro-only pricing.
- Tencent Cloud deployment remains blocked because the only discovered host (`43.131.243.184`) times out during SSH banner exchange and no `learn.xbzz.cloud` DNS record exists.
