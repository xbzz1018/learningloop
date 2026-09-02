---
name: goal-anchoring
description: 用于首次学习、建立新目标或用户尚未提供基础、期限和每日时间的场景。
allowed-tools:
  - get_learner_profile
  - get_course_state
  - update_learner_profile
---

# 学习目标锚定

先确认 learning_topic、background、target_outcome、duration_days、weekly_days 和 daily_minutes。信息不足时一次只追问最关键的问题，不生成虚假的完整计划。

规则：

1. 先调用 `get_learner_profile` 和 `get_course_state`。
2. 用户明确的信息通过 `update_learner_profile` 写入对应结构化字段，不要只拼进 background。
3. 给出一句目标复述和仍缺失的信息。
4. 不声称用户已掌握任何未经练习验证的知识点。
