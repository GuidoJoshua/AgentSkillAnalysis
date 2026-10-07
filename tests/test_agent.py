from harbor.agents.terminus_2.terminus_2 import Command

from sb.agent import SkillTerminusOptions, extract_load_request, split_shell_loads


def test_shell_load_is_intercepted():
    cmds = [
        Command(keystrokes="load_skill docx\n", duration_sec=0.1),
        Command(keystrokes="ls -la\n", duration_sec=0.1),
        Command(keystrokes="echo load_skill docx\n", duration_sec=0.1),
    ]
    names, kept = split_shell_loads(cmds)
    assert names == ["docx"]
    assert [c.keystrokes for c in kept] == ["ls -la\n", "echo load_skill docx\n"]


def test_load_request_string():
    content = '{"analysis": "a", "plan": "p", "commands": [], "load_skill": "docx"}'
    assert extract_load_request(content) == ["docx"]


def test_load_request_list_with_surrounding_text():
    content = 'Sure.\n{"analysis": "a", "plan": "p", "commands": [], "load_skill": ["pdf", "xlsx"]}\nDone'
    assert extract_load_request(content) == ["pdf", "xlsx"]


def test_load_request_survives_malformed_json():
    content = '{"analysis": "a", "load_skill": "docx", "commands": [{"keystrokes": "ls\n"}'
    assert extract_load_request(content) == ["docx"]


def test_no_load_request():
    assert extract_load_request('{"analysis": "a", "plan": "p", "commands": []}') == []
    assert extract_load_request("no json here") == []


def test_options_accept_condition_fields():
    opts = SkillTerminusOptions.model_validate(
        {"prefill_skills": ["docx"], "gold_skills": ["docx"], "skill_guidance": "must", "max_turns": 30}
    )
    assert opts.prefill_skills == ["docx"] and opts.skill_guidance == "must"
