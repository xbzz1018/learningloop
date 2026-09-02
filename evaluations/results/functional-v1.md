# LearningLoop Functional Evaluation V1

Generated at: `2026-09-02T09:23:39.537114+00:00`

## Aggregate

- Scenarios: 10/10 passed
- Scenario pass rate: 100.0%
- Final structured artifact rate: 100.0%
- Recovery success rate: 100.0%
- State integrity rate: 100.0%
- Idempotency rate: 100.0%
- Offline scenario latency P50/P95: 456.63/667.25 ms

These are deterministic functional scenarios, not model-quality or production-load metrics.

## Cases

| Case | Category | Status | Latency ms |
|---|---|---:|---:|
| react_tool_loop | agent_runtime | passed | 387.38 |
| structured_plan | structured_output | passed | 299.63 |
| empty_plan_fallback | structured_output | passed | 318.75 |
| approval_idempotency | recovery | passed | 483.14 |
| task_mastery | state_integrity | passed | 430.12 |
| low_score_error | state_integrity | passed | 545.10 |
| review_reschedule | state_integrity | passed | 667.25 |
| notification_idempotency | idempotency | passed | 628.71 |
| owner_isolation | isolation | passed | 284.99 |
| restart_recovery | recovery | passed | 570.39 |
