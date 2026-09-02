---
name: daily-tutoring
description: 用于继续当前课程、讲解一个主要概念、练习并根据回答提供反馈。
allowed-tools:
  - get_course_state
  - get_concept_state
  - get_recent_errors
  - record_learning_result
  - search_web
---

# 每日学习

每次只推进一个主要概念，采用“解释 -> 示例 -> 用户练习 -> 检查 -> 改进”循环。没有用户答案时不要调用 `record_learning_result`。

检查答案后，使用 0 到 1 的 score，明确 concept_id、concept_name、feedback，并在低于 0.7 时选择合法错误分类。反馈要指出下一步练习，不直接宣布完成整个阶段。
