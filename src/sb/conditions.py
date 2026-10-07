"""Experimental conditions -> Harbor ``run`` arguments for ``sb.agent:SkillTerminus``.

    C0  no skills
    C1  gold skills in the pool and prefilled as loaded            (utilization only)
    C2  gold skills in the pool, model decides whether to load      (+ triggering)
    C3  gold + distractors in the pool, model selects               (+ discrimination)
    C4  distractors in the pool, one prefilled as loaded            (cost of a wrong pick)
    C5  distractors only, model decides                             (over-triggering)

Gold skills are the task's curated skills exported to ``data/skills/<task>/``.
Distractors are skill directories from other tasks (chosen by ``sb.pools``, later).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CONDITIONS = ("C0", "C1", "C2", "C3", "C4", "C5")
AGENT_IMPORT = "sb.agent:SkillTerminus"


@dataclass
class TrialSpec:
    task: str
    condition: str
    pool: list[Path] = field(default_factory=list)  # skill dirs injected via --skill
    prefill: list[str] = field(default_factory=list)
    gold: list[str] = field(default_factory=list)


def gold_skill_dirs(task: str, skills_root: Path = Path("data/skills")) -> list[Path]:
    root = skills_root / task
    return sorted(p.parent for p in root.glob("*/SKILL.md"))


def make_trial(
    task: str,
    condition: str,
    distractors: list[Path] | None = None,
    skills_root: Path = Path("data/skills"),
) -> TrialSpec:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected one of {CONDITIONS}")
    gold = gold_skill_dirs(task, skills_root)
    if not gold:
        raise ValueError(f"no gold skills for task {task!r} under {skills_root}")
    distractors = list(distractors or [])
    gold_names = [p.name for p in gold]
    if condition in ("C3", "C4", "C5") and not distractors:
        raise ValueError(f"{condition} needs distractor skill dirs")
    if overlap := {p.name for p in distractors} & set(gold_names):
        raise ValueError(f"distractors overlap gold skills: {sorted(overlap)}")

    spec = TrialSpec(task=task, condition=condition, gold=gold_names)
    if condition == "C1":
        spec.pool, spec.prefill = gold, gold_names
    elif condition == "C2":
        spec.pool = gold
    elif condition == "C3":
        spec.pool = gold + distractors
    elif condition == "C4":
        spec.pool, spec.prefill = distractors, [distractors[0].name]
    elif condition == "C5":
        spec.pool = distractors
    return spec


def harbor_args(spec: TrialSpec, tasks_root: Path = Path("data/tasks")) -> list[str]:
    """Arguments after ``harbor run`` (model/endpoint flags are added by the caller)."""
    args = ["-p", str(tasks_root / spec.task), "-a", AGENT_IMPORT]
    for d in spec.pool:
        args += ["--skill", str(d)]
    args += ["--ak", f"gold_skills={json.dumps(spec.gold)}"]
    if spec.prefill:
        args += ["--ak", f"prefill_skills={json.dumps(spec.prefill)}"]
    return args
