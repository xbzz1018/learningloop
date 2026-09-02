from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learningloop.models import AgentRole


@dataclass(frozen=True)
class AgentProfile:
    """一个运行入口的固定能力边界，避免只靠 Prompt 区分角色。"""

    role: AgentRole
    name: str
    description: str
    max_steps: int
    context_message_limit: int
    allowed_skills: frozenset[str]
    allowed_tools: frozenset[str]
    allow_state_proposals: bool


class AgentPolicy:
    PROFILES = {
        AgentRole.INTERACTIVE: AgentProfile(
            role=AgentRole.INTERACTIVE,
            name="Interactive Agent",
            description="处理用户主动发起的学习对话、目标确认和练习反馈。",
            max_steps=4,
            context_message_limit=8,
            allowed_skills=frozenset(
                {"goal-anchoring", "course-planning", "daily-tutoring", "review-coaching", "plan-recovery"}
            ),
            allowed_tools=frozenset(
                {
                    "get_learner_profile",
                    "get_course_state",
                    "get_concept_state",
                    "get_due_reviews",
                    "get_recent_errors",
                    "update_learner_profile",
                    "record_learning_result",
                    "create_or_replace_course_plan",
                    "search_web",
                }
            ),
            allow_state_proposals=True,
        ),
        AgentRole.AUTONOMOUS: AgentProfile(
            role=AgentRole.AUTONOMOUS,
            name="Autonomous Agent",
            description="处理定时计划、每日复盘、到期复习和延期恢复。",
            max_steps=3,
            context_message_limit=0,
            allowed_skills=frozenset({"daily-tutoring", "review-coaching", "plan-recovery"}),
            allowed_tools=frozenset(
                {
                    "get_learner_profile",
                    "get_course_state",
                    "get_concept_state",
                    "get_due_reviews",
                    "get_recent_errors",
                    "create_or_replace_course_plan",
                    "record_learning_result",
                }
            ),
            allow_state_proposals=True,
        ),
    }

    @classmethod
    def profile_for(cls, role: AgentRole) -> AgentProfile:
        return cls.PROFILES[role]

    @classmethod
    def validate_skill(cls, role: AgentRole, skill_name: str) -> None:
        profile = cls.profile_for(role)
        if skill_name not in profile.allowed_skills:
            raise PermissionError(f"{profile.name} cannot activate Skill: {skill_name}")


class SkillPolicy:
    """Code-owned capability matrix; Skill frontmatter never grants a tool by itself."""

    TOOL_MATRIX = {
        "goal-anchoring": {
            "get_learner_profile",
            "get_course_state",
            "update_learner_profile",
        },
        "course-planning": {
            "get_learner_profile",
            "get_course_state",
            "search_web",
            "create_or_replace_course_plan",
        },
        "daily-tutoring": {
            "get_course_state",
            "get_concept_state",
            "get_recent_errors",
            "record_learning_result",
            "search_web",
        },
        "review-coaching": {
            "get_due_reviews",
            "get_recent_errors",
            "get_concept_state",
            "record_learning_result",
        },
        "plan-recovery": {
            "get_learner_profile",
            "get_course_state",
            "get_concept_state",
            "create_or_replace_course_plan",
        },
    }

    def tools_for(self, skill: Any, registry: dict[str, Any]) -> dict[str, Any]:
        allowed = self.TOOL_MATRIX.get(skill.name)
        if allowed is None:
            raise PermissionError(f"unknown Skill capability policy: {skill.name}")
        declared = set(skill.tool_hints)
        if not declared.issubset(allowed):
            extra = ", ".join(sorted(declared - allowed))
            raise PermissionError(f"Skill requests tools outside policy: {extra}")
        missing = allowed - registry.keys()
        if missing:
            raise RuntimeError(f"tool registry is incomplete: {', '.join(sorted(missing))}")
        return {name: registry[name] for name in sorted(allowed)}
