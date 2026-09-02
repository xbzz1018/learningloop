from __future__ import annotations

import re
from dataclasses import dataclass
from math import ceil

from learningloop.learning.schemas import CoursePlan, CourseStage, LessonUnit


@dataclass(frozen=True)
class ContentProfile:
    concepts: tuple[str, ...]
    explanation: str
    example: str
    exercise: str
    expected_output: str
    acceptance_criteria: str


_PROFILES: tuple[tuple[tuple[str, ...], ContentProfile], ...] = (
    (
        ("python", "编程", "脚本"),
        ContentProfile(
            concepts=("变量与数据类型", "函数", "控制流"),
            explanation="围绕 Python 的核心语法建立可运行的最小知识单元，先理解输入、处理和输出，再逐步组合成小程序。",
            example='name = "LearningLoop"\nminutes = 30\nprint(f"{name}: {minutes} 分钟")',
            exercise="编写一个命令行脚本，读取学习主题和可用分钟数，并输出一条今日学习安排。",
            expected_output="输入主题和分钟数后，程序输出包含主题、时间和完成标准的安排。",
            acceptance_criteria="脚本可以独立运行；至少使用一个函数；输入为空时给出可理解的提示。",
        ),
    ),
    (
        ("web", "前端", "fastapi", "接口"),
        ContentProfile(
            concepts=("HTTP 请求与响应", "路由", "JSON"),
            explanation="从一次完整的 HTTP 请求开始理解 Web 服务：路由接收输入，业务代码处理状态，响应返回稳定的数据结构。",
            example='@app.get("/health")\ndef health():\n    return {"status": "ok"}',
            exercise="实现一个带参数的健康检查接口，返回请求参数、服务状态和当前时间。",
            expected_output="请求接口后得到可解析的 JSON，字段名称稳定且状态码正确。",
            acceptance_criteria="接口可以启动；参数缺失时返回校验错误；正常请求返回 200 和 JSON。",
        ),
    ),
    (
        ("数据结构", "算法", "leetcode"),
        ContentProfile(
            concepts=("数组与哈希表", "复杂度", "边界条件"),
            explanation="先用简单数据结构表达问题，再比较不同实现的时间和空间复杂度，最后用边界案例验证算法。",
            example="numbers = [2, 7, 11, 15]\nseen = {}\n# 用哈希表记录已经见过的数字",
            exercise="实现一个函数，返回数组中和为目标值的两个元素下标，并处理空数组和无解情况。",
            expected_output="对有解、无解、重复元素和空输入分别返回稳定结果。",
            acceptance_criteria="函数有类型清晰的输入输出；时间复杂度不高于 O(n)；至少包含 4 个测试案例。",
        ),
    ),
    (
        ("sql", "数据库", "postgres", "mysql"),
        ContentProfile(
            concepts=("SELECT", "JOIN", "聚合与索引"),
            explanation="把业务问题拆成实体、关系和查询条件，使用 SQL 返回可核对的结果，并关注重复数据和索引边界。",
            example="SELECT course_id, COUNT(*) AS task_count\nFROM learning_tasks\nGROUP BY course_id;",
            exercise="设计课程、任务和学习记录三张表，查询每门课程的完成数、未完成数和完成率。",
            expected_output="查询结果按课程聚合，每行都能解释来源和计算方式。",
            acceptance_criteria="查询可以执行；JOIN 条件明确；完成率分母为 0 时不会报错或产生错误结果。",
        ),
    ),
    (
        ("机器学习", "machine learning", "深度学习", "模型"),
        ContentProfile(
            concepts=("训练集与测试集", "特征", "评估指标"),
            explanation="从可验证的数据划分开始建立机器学习流程，先明确任务和指标，再比较模型输出与真实标签。",
            example="X_train, X_test, y_train, y_test = train_test_split(\n    X, y, test_size=0.2, random_state=42\n)",
            exercise="选择一个小型公开数据集，完成数据划分、基线模型训练和至少一个评估指标计算。",
            expected_output="输出训练/测试样本数量、基线指标和一段结果解释。",
            acceptance_criteria="固定随机种子；测试数据不参与训练；指标和数据集划分能够复现。",
        ),
    ),
    (
        ("agent", "大模型", "llm", "智能体"),
        ContentProfile(
            concepts=("结构化输出", "工具调用", "状态与恢复"),
            explanation="把 Agent 看成受约束的运行时：模型负责选择下一步，工具负责副作用，状态机和 Schema 负责验证边界。",
            example='class ToolResult(BaseModel):\n    status: Literal["ok", "failed"]\n    data: dict[str, Any]',
            exercise="设计一个只允许读取课程状态和记录学习结果的 typed tool，并为重复调用增加幂等键。",
            expected_output="工具参数、结果结构和重复调用行为都有明确约定。",
            acceptance_criteria="非法参数被拒绝；写操作有来源和幂等键；异常可恢复且不重复修改状态。",
        ),
    ),
)

_GENERIC_PROFILE = ContentProfile(
    concepts=("核心概念", "实践步骤", "结果验证"),
    explanation="围绕阶段目标拆解概念、实践和验证三个步骤，先形成最小可运行结果，再根据反馈补齐薄弱点。",
    example="先写出一个最小输入和输出示例，再逐步增加一个真实约束。",
    exercise="针对本阶段目标完成一个小练习，记录输入、过程、输出和遇到的问题。",
    expected_output="得到一个可以复现的练习结果，并能说明它如何满足阶段目标。",
    acceptance_criteria="练习可以重复执行；结果与目标对应；至少记录一个边界情况和改进方向。",
)


def _profile(topic: str) -> ContentProfile:
    lowered = topic.lower()
    for keywords, profile in _PROFILES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return profile
    return _GENERIC_PROFILE


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:50] or "lesson"


def _stage_has_detail(stage: CourseStage) -> bool:
    if not stage.key_concepts or not stage.stage_acceptance_criteria or not stage.recommended_practice:
        return False
    if not stage.lessons:
        return False
    return all(
        lesson.concepts
        and lesson.explanation
        and lesson.example
        and lesson.exercise
        and lesson.expected_output
        and lesson.acceptance_criteria
        for lesson in stage.lessons
    )


def enrich_course_plan(plan: CoursePlan, topic: str, *, source: str | None = None) -> CoursePlan:
    """补全不完整课程内容，同时保留模型已经提供的字段。"""

    profile = _profile(topic)
    all_complete = all(_stage_has_detail(stage) for stage in plan.stages)
    stages: list[CourseStage] = []
    for stage in plan.stages:
        if _stage_has_detail(stage):
            stages.append(stage.model_copy(update={"content_status": "complete"}))
            continue
        default_lesson = LessonUnit(
            id=f"{_slug(stage.id)}-lesson-1",
            title=f"{stage.title}：核心练习",
            concepts=list(stage.key_concepts or profile.concepts),
            explanation=profile.explanation + f" 本阶段聚焦：{stage.objective}",
            example=profile.example,
            exercise=profile.exercise,
            expected_output=profile.expected_output,
            acceptance_criteria=profile.acceptance_criteria,
            estimated_minutes=25,
        )
        existing = stage.lessons[0] if stage.lessons else None
        if existing:
            default_lesson = existing.model_copy(
                update={
                    "concepts": existing.concepts or default_lesson.concepts,
                    "explanation": existing.explanation or default_lesson.explanation,
                    "example": existing.example or default_lesson.example,
                    "exercise": existing.exercise or default_lesson.exercise,
                    "expected_output": existing.expected_output or default_lesson.expected_output,
                    "acceptance_criteria": existing.acceptance_criteria or default_lesson.acceptance_criteria,
                }
            )
        stages.append(
            stage.model_copy(
                update={
                    "key_concepts": list(stage.key_concepts or profile.concepts),
                    "lessons": [default_lesson],
                    "stage_acceptance_criteria": stage.stage_acceptance_criteria
                    or default_lesson.acceptance_criteria,
                    "recommended_practice": stage.recommended_practice or default_lesson.exercise,
                    "content_status": "complete" if all_complete else "fallback",
                }
            )
        )
    content_source = source or ("model" if all_complete else "fallback")
    return plan.model_copy(update={"stages": stages, "content_source": content_source})


def fallback_course_plan(
    topic: str,
    *,
    duration_days: int = 14,
    target_outcome: str = "完成一个可复现的学习成果",
) -> CoursePlan:
    """模型不可用时提供非空、可执行的最小课程计划。"""

    profile = _profile(topic)
    titles = (
        ("环境与基础", "建立最小运行环境和核心概念"),
        ("核心方法", "理解主题中的主要方法和常见模式"),
        ("动手练习", "通过一个小练习验证核心方法"),
        ("综合应用", "把知识点组合成可运行结果"),
        ("复盘与交付", "修正问题并整理最终成果"),
    )
    days_per_stage = max(1, ceil(max(1, duration_days) / len(titles)))
    stages = [
        CourseStage(
            id=f"fallback-stage-{index}",
            title=title,
            objective=objective,
            estimated_days=days_per_stage,
            prerequisite_ids=[f"fallback-stage-{index - 1}"] if index > 1 else [],
            key_concepts=list(profile.concepts),
        )
        for index, (title, objective) in enumerate(titles, start=1)
    ]
    plan = CoursePlan(
        title=f"{topic or '主题'}学习计划",
        goal=f"围绕{topic or '当前主题'}完成学习并产出成果",
        duration_days=max(1, min(365, duration_days)),
        final_artifact=target_outcome,
        stages=stages,
        content_source="fallback",
    )
    return enrich_course_plan(plan, topic, source="fallback")


__all__ = ["enrich_course_plan", "fallback_course_plan"]
