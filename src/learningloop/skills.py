from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from harness.skills import Skill


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str
    path: Path
    tool_hints: tuple[str, ...]
    content_hash: str


class SkillCatalog:
    REQUIRED = {
        "goal-anchoring",
        "course-planning",
        "daily-tutoring",
        "review-coaching",
        "plan-recovery",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._descriptors: dict[str, SkillDescriptor] = {}
        self._loaded: dict[str, Skill] = {}
        for directory in sorted(root.iterdir() if root.exists() else []):
            if directory.is_dir() and (directory / "SKILL.md").exists():
                descriptor = self._read_descriptor(directory / "SKILL.md")
                self._descriptors[descriptor.name] = descriptor
        missing = sorted(self.REQUIRED - self._descriptors.keys())
        if missing:
            raise RuntimeError(
                f"Skill catalog is incomplete at {self.root}: missing {', '.join(missing)}"
            )

    @staticmethod
    def _parse(path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"Skill is missing YAML frontmatter: {path}")
        _, raw_frontmatter, body = text.split("---", 2)
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
        return frontmatter, body.strip()

    @classmethod
    def _read_descriptor(cls, path: Path) -> SkillDescriptor:
        frontmatter, _body = cls._parse(path)
        name = str(frontmatter.get("name") or "").strip()
        description = str(frontmatter.get("description") or "").strip()
        tools = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools") or []
        if not name or not description:
            raise ValueError(f"Skill requires name and description: {path}")
        if name != path.parent.name:
            raise ValueError(f"Skill name must match its directory: {path}")
        return SkillDescriptor(
            name=name,
            description=description,
            path=path,
            tool_hints=tuple(str(tool) for tool in tools),
            content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _activate(self, name: str) -> Skill:
        if name in self._loaded:
            return self._loaded[name]
        descriptor = self._descriptors[name]
        _frontmatter, body = self._parse(descriptor.path)
        skill = Skill(
            name=descriptor.name,
            description=descriptor.description,
            instructions=body,
            tool_hints=list(descriptor.tool_hints),
        )
        self._loaded[name] = skill
        return skill

    @property
    def activated_names(self) -> set[str]:
        return set(self._loaded)

    def get(self, name: str) -> Skill:
        if name not in self._descriptors:
            raise KeyError(name)
        return self._activate(name)

    def metadata(self) -> list[dict[str, str]]:
        return [
            {"name": item.name, "description": item.description}
            for item in self._descriptors.values()
        ]

    def select(
        self,
        text: str,
        *,
        has_course: bool,
        has_due_reviews: bool,
        goal_ready: bool = False,
    ) -> Skill:
        skill, _reason = self.select_with_reason(
            text,
            has_course=has_course,
            has_due_reviews=has_due_reviews,
            goal_ready=goal_ready,
        )
        return skill

    def select_with_reason(
        self,
        text: str,
        *,
        has_course: bool,
        has_due_reviews: bool,
        goal_ready: bool = False,
    ) -> tuple[Skill, str]:
        lowered = text.lower()
        if any(word in lowered for word in ("落后", "漏学", "调整计划", "重新排期")):
            name = "plan-recovery"
            reason = "recovery intent"
        elif has_due_reviews or any(word in lowered for word in ("复习", "回顾", "错题")):
            name = "review-coaching"
            reason = "due review or review intent"
        elif any(word in lowered for word in ("计划", "路线", "课程安排", "plan", "roadmap")):
            name = "course-planning"
            reason = "explicit planning intent"
        elif not has_course and goal_ready:
            name = "course-planning"
            reason = "goal slots complete"
        elif not has_course or any(word in lowered for word in ("目标", "想学", "开始学习")):
            name = "goal-anchoring"
            reason = "goal information required"
        else:
            name = "daily-tutoring"
            reason = "active course tutoring"
        return self._activate(name), reason

    def version_hash(self, skill: Skill) -> str:
        return self._descriptors[skill.name].content_hash
