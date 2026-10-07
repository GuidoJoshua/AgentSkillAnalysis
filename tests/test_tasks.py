from pathlib import Path

from sb.tasks import load_task, split_frontmatter


def test_split_frontmatter():
    meta, body = split_frontmatter("---\nagent:\n  timeout_sec: 60\n---\n\nDo the thing.\n")
    assert meta == {"agent": {"timeout_sec": 60}}
    assert body == "Do the thing."


def test_split_frontmatter_without_header():
    assert split_frontmatter("just text") == ({}, "just text")


def test_load_task(tmp_path: Path):
    root = tmp_path / "demo-task"
    (root / "environment" / "skills" / "docx").mkdir(parents=True)
    (root / "environment" / "skills" / "docx" / "SKILL.md").write_text("---\nname: docx\n---\nbody")
    (root / "task.md").write_text(
        "---\nagent:\n  timeout_sec: 300.0\nsandbox:\n  cpus: 2\n  memory_mb: 2048\n"
        "  network_mode: no-network\n---\n\nFill the template.\n"
    )
    task = load_task(root)
    assert task.id == "demo-task"
    assert task.instruction == "Fill the template."
    assert task.agent_timeout_sec == 300.0
    assert task.verifier_timeout_sec == 900.0
    assert (task.cpus, task.memory_mb, task.network) == (2.0, 2048, False)
    assert task.skill_names() == ["docx"]
    assert not task.uses_compose
