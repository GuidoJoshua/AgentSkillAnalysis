from pathlib import Path

from sb.export_tasks import export_task, skill_dependent_lines, strip_skill_copies

DOCKERFILE = """FROM ubuntu:24.04
COPY data.json /root/data.json
# Copy skills to all agent paths
COPY skills /root/.claude/skills
COPY skills/ /root/.codex/skills
COPY --chown=root skills /etc/claude-code/.claude/skills
WORKDIR /root
"""


def test_strip_skill_copies():
    text, removed, workspace = strip_skill_copies(DOCKERFILE)
    assert removed == 3
    assert workspace == []
    assert "COPY data.json /root/data.json" in text
    assert ".claude/skills" not in text


def test_workspace_copies_and_skill_runs_mark_task_entangled():
    df = "COPY skills/ /app/skills/\nCOPY skills /root/.claude/skills\nRUN mkdir -p /app/skills\nRUN cd /root/.claude/skills/x && npm install\n"
    text, removed, workspace = strip_skill_copies(df)
    assert (removed, workspace) == (2, ["/app/skills/"])
    assert skill_dependent_lines(text) == ["RUN cd /root/.claude/skills/x && npm install"]


def test_export_task_moves_skills_out_of_context(tmp_path: Path):
    src = tmp_path / "src" / "demo"
    (src / "environment" / "skills" / "docx").mkdir(parents=True)
    (src / "environment" / "skills" / "docx" / "SKILL.md").write_text("---\nname: docx\n---\n")
    (src / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (src / "task.toml").write_text('version = "1.0"\n')

    out = tmp_path / "out"
    report = export_task(src, out)

    assert report["skills"] == ["docx"]
    assert report["removed_copies"] == 3
    assert report["entangled"] == []
    assert not (out / "tasks" / "demo" / "environment" / "skills").exists()
    assert (out / "skills" / "demo" / "docx" / "SKILL.md").exists()
    # The source checkout is untouched.
    assert (src / "environment" / "skills" / "docx" / "SKILL.md").exists()
