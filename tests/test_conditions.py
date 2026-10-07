from pathlib import Path

import pytest

from sb.conditions import harbor_args, make_trial


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    for task, name in [("t1", "docx"), ("other", "pdf")]:
        d = tmp_path / task / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    return tmp_path


def test_c0_has_no_skills(skills_root):
    spec = make_trial("t1", "C0", skills_root=skills_root)
    assert spec.pool == [] and spec.prefill == [] and spec.gold == ["docx"]
    assert "--skill" not in harbor_args(spec)


def test_c1_prefills_gold(skills_root):
    spec = make_trial("t1", "C1", skills_root=skills_root)
    assert [p.name for p in spec.pool] == ["docx"] and spec.prefill == ["docx"]
    args = harbor_args(spec)
    assert 'prefill_skills=["docx"]' in args


def test_c4_prefills_a_distractor(skills_root):
    spec = make_trial("t1", "C4", distractors=[skills_root / "other" / "pdf"], skills_root=skills_root)
    assert spec.prefill == ["pdf"] and spec.gold == ["docx"]


def test_distractor_conditions_require_distractors(skills_root):
    with pytest.raises(ValueError):
        make_trial("t1", "C3", skills_root=skills_root)
