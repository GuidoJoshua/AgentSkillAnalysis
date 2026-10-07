"""Export SkillsBench (Harbor-format) tasks with skills un-baked.

Paper-era SkillsBench tasks copy ``environment/skills`` into the image at every
agent's skill path (``COPY skills /root/.claude/skills`` ...). Our conditions
need the skill pool to vary per trial, so the exported copy drops those COPY
lines and moves the task's curated skills out of the build context; Harbor then
injects whichever skills a condition calls for at ``/harbor/skills``.

Output layout::

    <out>/tasks/<id>/...            task without baked skills
    <out>/skills/<id>/<name>/...    the task's curated (golden) skills
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

COPY_SKILLS = re.compile(r"^\s*(COPY|ADD)\s+(--\S+\s+)*skills/?\s+(?P<dest>\S+).*$", re.IGNORECASE)
# Where agent runtimes look for skills; copies elsewhere put skill code into the task workspace.
AGENT_SKILL_DEST = re.compile(r"/\.(claude|codex|opencode|goose|factory|agents|gemini|github|cursor|terminus)/skills?/?$")


def strip_skill_copies(dockerfile: str) -> tuple[str, int, list[str]]:
    """Remove ``COPY skills <dest>`` lines.

    Returns the new text, how many lines were removed, and the destinations that
    were not agent skill paths (a sign the task uses skill code as environment tooling).
    """
    kept, removed, workspace_dests = [], 0, []
    for line in dockerfile.splitlines(keepends=True):
        m = COPY_SKILLS.match(line)
        if m:
            removed += 1
            if not AGENT_SKILL_DEST.search(m.group("dest")):
                workspace_dests.append(m.group("dest"))
            continue
        kept.append(line)
    return "".join(kept), removed, workspace_dests


def skill_dependent_lines(dockerfile: str) -> list[str]:
    """Remaining instructions that use skill files (comments and bare mkdir are harmless)."""
    out = []
    for ln in dockerfile.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or not re.search(r"skills?\b", s):
            continue
        if re.match(r"RUN\s+mkdir\s", s):
            continue
        out.append(s)
    return out


def export_task(src: Path, out: Path) -> dict:
    task_out = out / "tasks" / src.name
    if task_out.exists():
        shutil.rmtree(task_out)
    shutil.copytree(src, task_out, symlinks=True)

    report = {"task": src.name, "removed_copies": 0, "skills": [], "entangled": []}
    skills_src = task_out / "environment" / "skills"
    if skills_src.is_dir():
        dest = out / "skills" / src.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(skills_src), dest)
        report["skills"] = sorted(p.parent.name for p in dest.glob("*/SKILL.md"))

    dockerfile = task_out / "environment" / "Dockerfile"
    if dockerfile.exists():
        text, removed, workspace_dests = strip_skill_copies(dockerfile.read_text())
        dockerfile.write_text(text)
        report["removed_copies"] = removed
        report["entangled"] = [f"COPY skills -> {d}" for d in workspace_dests] + skill_dependent_lines(text)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", type=Path, default=Path("third_party/skillsbench-feb/tasks"))
    p.add_argument("--out", type=Path, default=Path("data"))
    args = p.parse_args(argv)

    reports = [export_task(t.parent, args.out) for t in sorted(args.src.glob("*/task.toml"))]
    for r in reports:
        if r["entangled"] or not r["skills"]:
            print(f"[exclude] {r['task']}: skills={len(r['skills'])} {r['entangled'][:2]}")
    usable = [r["task"] for r in reports if r["skills"] and not r["entangled"]]
    (args.out / "manifest.json").write_text(json.dumps({"usable": usable, "tasks": reports}, indent=2))
    print(f"exported {len(reports)} tasks ({len(usable)} usable) to {args.out}; see {args.out}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
