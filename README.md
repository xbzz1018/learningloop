# LearningLoop

[![Offline Tests](https://github.com/xbzz1018/learningloop/actions/workflows/offline-tests.yml/badge.svg?branch=main)](https://github.com/xbzz1018/learningloop/actions/workflows/offline-tests.yml)

LearningLoop 0.3.1 is a personal learning assistant for long-running study goals. It turns a vague goal into an executable plan, guides daily work, schedules FSRS reviews, and records the evidence needed to recover after interruptions.

The runtime has two controlled entrypoints: an Interactive Agent for user conversations and an Autonomous Agent for scheduled plans, reviews, and recovery. Both entrypoints load Chinese learning Skills, call typed tools, preserve learning state, require approval before replacing a plan, and record every model call's usage and cost estimate.

## What this project demonstrates

- A domain Runtime facade over a reusable Agent Harness instead of business logic scattered across prompts.
- Typed tools, owner-scoped state, approval gates, idempotent effects, checkpoints, and recovery.
- A practical split between JSON learner state, SQLite event/history state, and operational Web views.
- Usage, pricing, retry and fallback records that keep missing cost data as `null` instead of inventing zeroes.

## What Is Implemented

- A locally configured OpenAI-compatible provider supplies Flash/Pro routes. No endpoint, key, or provider account is included in this public repository.
- Five Skills: goal anchoring, course planning, daily tutoring, review coaching, and plan recovery.
- SQLite stores sessions, messages, events, approvals, checkpoints, provider capabilities, and per-request usage.
- JSON files store the learner profile, course plan, concept mastery, errors, and FSRS review cards.
- The Web workspace renders a date-grouped plan table with completion percentage and stage completion actions.
- Course stages and daily tasks contain actionable LessonUnit content: concepts, explanations, examples, exercises, expected output and acceptance criteria. Task results record answers, notes and scores, then update mastery, errors and FSRS.
- The plan and review pages are operational workspaces rather than read-only summaries: users can expand lessons, start tasks, submit results and record reviews without writing chat commands.
- An in-process SQLite scheduler can generate daily plans and reviews at configured times, then deliver them by SMTP or a local outbox in development.
- Local Web UI: `GET /`, FastAPI JSON API, SSE events, HITL approvals, and usage CSV/JSON export.
- Provider search capability is probed when live mode is explicitly enabled. DuckDuckGo is the fallback when the configured provider search tool is unavailable.
- The 0.3 runtime adds a domain Runtime facade, stage checkpoints, an idempotent tool-effect ledger, optional OpenTelemetry spans, and owner-scoped private accounts.
- Interactive and Autonomous runs are recorded separately with structured Agent Artifacts, Trace endpoints, role-level usage aggregation, and the same Checkpoint and tool-policy boundaries.

## Quick Start

```powershell
conda env create -f environment.yml
conda activate learningloop
python -m pip install -r requirements.lock
python -m pip install -e ".[dev]" --no-deps
# Optional quality gates/OTLP: pip install -r requirements.dev.lock -r requirements.observability.lock
Copy-Item .env.example .env
# Fill the four keys in .env locally. Never commit this file.
learningloop doctor
learningloop serve
```

Open <http://127.0.0.1:8765/>.

Run the bounded compatibility checks only when you explicitly want to spend API tokens:

```powershell
learningloop doctor --live
```

### Daily email reminders

Configure the `LEARNINGLOOP_SMTP_*` values in the ignored `.env`, create a session, and save
notification settings through `PUT /api/v1/notifications/settings/{session_id}`. The default
schedule is 08:30 for today's plan and 20:30 for the daily review in `Asia/Shanghai`.

For local testing without SMTP, leave the SMTP values empty and run:

```powershell
learningloop notifications run-once --force
```

Messages are written to `data/notifications/outbox/`. The same command is safe to repeat because
each session/date/notification type has an idempotency key.

See [`docs/notifications.md`](docs/notifications.md) for the SMTP mapping and recovery behavior.

### Docker

The local service is intentionally a single-container, single-worker deployment so the SQLite scheduler
cannot run duplicate jobs:

```powershell
docker compose up -d --build
```

The container stores the database, learning state, traces and notification outbox in `/data`.

For a Tencent Cloud private instance with lightweight account isolation and HTTPS, see
[`docs/deployment-tencent-cloud.md`](docs/deployment-tencent-cloud.md) and run
`docker-compose.tencent.yml` with a domain configured in `.env`.

## Model And Cost Policy

The application records input, cached input, cache-miss input, output, reasoning, total tokens, latency, provider alias, requested/actual model, retry/fallback status, and estimated cost for every model request. Missing usage or pricing fields remain `null`.

The price table is local, versioned configuration; it is not a claim about any provider's bill. Use `/api/v1/usage`, `/api/v1/usage/calls`, or the CSV export to inspect and recalculate usage.

Default safeguards are 4 model calls per turn, 120K input tokens per turn, 16K output tokens per turn, 150 calls per day, and a `$5` development cost ceiling when cost data is available.

## Attribution And Scope

This project uses the MIT-licensed `react-agent-harness` project at commit `c06e0a9ebbbd50543dbf6463201ac07887d5e03e` for the generic runtime and the MIT-licensed `learn-anything-skill` project at commit `2886af46b67bcdf5e73e085307d0e8747b47090d` for learning workflow references. Their license texts are preserved under `third_party/`.

LearningLoop-specific work is the dual-provider model policy, UTF-8 Skill loading on Windows, typed learning tools, SQLite/JSON learning state, Memory Gate, FSRS integration, approval workflow, web API/UI, usage ledger, and local acceptance tests.

The local profile is single-user and authentication-disabled for development. The Tencent Cloud profile enables lightweight owner isolation without public registration, organizations, OAuth, or complex RBAC. Neither profile includes RAG, MCP, vector memory, multi-agent orchestration, document upload, voice, or vision. The Web workbench separates conversation, plan, progress, review, usage, and notification views.

## Safety and privacy boundary

This repository is intended for a private learning workspace. Provider keys, SMTP credentials, learner data, SQLite state, notification outbox files and local traces stay in the ignored `.env`/`data/` paths. The application does not claim to be a general tutoring platform, a clinical or financial advisor, or a production multi-tenant service.

## Contribution and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Do not put provider URLs, API keys, SMTP passwords, learner data, or local traces in Issues, Pull Requests, logs, or screenshots.

## Current Acceptance Notes

The public CI covers the offline test suite. Live provider, SMTP, and deployment checks are opt-in and must be run only after local secrets and endpoints are configured; their results are not represented as public provider guarantees.

The versioned evaluation report is stored in [`evaluations/results/functional-v1.md`](evaluations/results/functional-v1.md), with per-case details and the runner SHA-256 in the adjacent JSON file.
