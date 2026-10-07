"""Load SkillsBench tasks (native ``task.md`` packages).

Layout per task::

    tasks/<id>/task.md               YAML frontmatter + instruction body
    tasks/<id>/environment/          Dockerfile, input files, skills/<name>/SKILL.md
    tasks/<id>/oracle/solve.sh       reference solution
    tasks/<id>/verifier/test.sh      writes 0/1 to /logs/verifier/reward.txt
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Task:
    id: str
    root: Path
    instruction: str
    agent_timeout_sec: float
    verifier_timeout_sec: float
    cpus: float
    memory_mb: int
    network: bool
    metadata: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def env_dir(self) -> Path:
        return self.root / "environment"

    @property
    def skills_dir(self) -> Path:
        return self.env_dir / "skills"

    @property
    def oracle_dir(self) -> Path:
        return self.root / "oracle"

    @property
    def verifier_dir(self) -> Path:
        return self.root / "verifier"

    @property
    def uses_compose(self) -> bool:
        return any(self.env_dir.glob("docker-compose*"))

    def skill_names(self) -> list[str]:
        if not self.skills_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.skills_dir.glob("*/SKILL.md"))


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``---``-delimited YAML frontmatter from the markdown body."""
    if not text.startswith("---"):
        return {}, text.strip()
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body.strip()


def load_task(root: Path) -> Task:
    meta, body = split_frontmatter((root / "task.md").read_text(encoding="utf-8"))
    agent = meta.get("agent") or {}
    verifier = meta.get("verifier") or {}
    sandbox = meta.get("sandbox") or {}
    return Task(
        id=root.name,
        root=root,
        instruction=body,
        agent_timeout_sec=float(agent.get("timeout_sec", 900)),
        verifier_timeout_sec=float(verifier.get("timeout_sec", 900)),
        cpus=float(sandbox.get("cpus", 1)),
        memory_mb=int(sandbox.get("memory_mb", 4096)),
        network=sandbox.get("network_mode", "public") != "no-network",
        metadata=meta.get("metadata") or {},
    )


def tasks_dir() -> Path:
    return Path(os.environ.get("SB_TASKS_DIR", "third_party/skillsbench/tasks"))


def load_tasks(ids: list[str] | None = None, root: Path | None = None) -> list[Task]:
    root = root or tasks_dir()
    if ids:
        return [load_task(root / i) for i in ids]
    return [load_task(p.parent) for p in sorted(root.glob("*/task.md"))]
