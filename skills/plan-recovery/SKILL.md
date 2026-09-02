---
name: plan-recovery
description: 用于漏学、明显落后、时间变化或需要重新安排剩余课程的场景。
allowed-tools:
  - get_learner_profile
  - get_course_state
  - get_concept_state
  - create_or_replace_course_plan
---

# 计划恢复

先识别落后原因和新的可用时间，只调整未完成部分。保留已完成阶段和掌握证据，不通过降低标准伪造进度。

说明调整影响后调用 `create_or_replace_course_plan` 创建审批请求。未经用户批准，不写入新计划。
