---
name: course-planning
description: 用于生成或调整阶段学习路径、先修关系、每日容量和最终成果。
allowed-tools:
  - get_learner_profile
  - get_course_state
  - search_web
  - create_or_replace_course_plan
---

# 课程规划

根据目标、基础、期限和每日时间生成阶段计划。快速变化主题先调用 `search_web` 查找可靠资料。

计划必须包含 title、goal、duration_days、final_artifact 和 stages。每个 stage 包含小写短横线 id、title、objective、estimated_days 与 prerequisite_ids。

先检查总天数和先修关系，再调用 `create_or_replace_course_plan`。该工具只会创建审批请求；明确告诉用户计划尚未生效，等待批准。
