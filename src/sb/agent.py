"""Terminus-2 with an explicit, logged ``load_skill`` action.

Harbor's Terminus-2 lists skills with their SKILL.md paths and leaves loading to
``cat``, so loads are only visible as shell text. This subclass makes loading a
first-class action so selection can be measured exactly:

* The skills section lists name + description (no paths) and tells the model to
  add ``"load_skill": "<name>"`` (or a list) to its JSON response.
* A ``load_skill <name>`` line typed as a shell command counts as the same load
  (``via: shell``) and is not sent to the terminal.
* The SKILL.md body is returned at the top of the next observation, exempt from
  the 10 KB terminal-output truncation.
* Every load is recorded with its turn: ``skill_events.json`` in the agent logs
  dir and ``context.metadata["skill_events"]``. Shell reads of skill files are
  recorded separately as ``bash_read`` so bypasses are not lost.
* ``prefill_skills`` starts the conversation as if the model had loaded those
  skills on its first turn (conditions C1/C4), in the same message position and
  format as a natural load.

Run with Harbor:
    harbor run -a sb.agent:SkillTerminus -m hosted_vllm/agent --skill <dir> \
        --ak prefill_skills='["docx"]' --ak gold_skills='["docx"]' ...
"""

from __future__ import annotations

import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal, override

import yaml
from pydantic import Field

from harbor.agents.terminus_2.terminus_2 import Command, Terminus2, Terminus2Options
from harbor.environments.base import BaseEnvironment
from harbor.llms.chat import Chat
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Observation, ObservationResult, Step, ToolCall

SKILL_BLOCK_START = "<<<SKILL_CONTENT>>>"
SKILL_BLOCK_END = "<<<END_SKILL_CONTENT>>>"

NEUTRAL_GUIDANCE = (
    "Skills are packages of instructions (and sometimes scripts) for particular kinds of work. "
    "To read a skill's full instructions, add a top-level field \"load_skill\" to your JSON "
    "response with the skill name (or a list of names). The contents will appear at the top "
    "of the next terminal output. Commands in the same response still run."
)
# Wording used by SkillsBench's terminus-2-skills; nudges the model to check skills first.
MUST_GUIDANCE = (
    "If skills are available, you MUST check if any skill matches the task BEFORE executing commands. "
    + NEUTRAL_GUIDANCE
)


class SkillTerminusOptions(Terminus2Options):
    prefill_skills: list[str] = Field(
        default_factory=list,
        description="Skills shown as already loaded on the first turn (C1/C4).",
    )
    gold_skills: list[str] = Field(
        default_factory=list,
        description="Skills that count as correct for this task (logging only).",
    )
    skill_guidance: Literal["neutral", "must"] = Field(
        default="neutral",
        description="How strongly the prompt pushes skill use.",
    )


def _frontmatter(text: str) -> dict[str, Any]:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_load_request(content: str) -> list[str]:
    """Skill names requested via a top-level ``load_skill`` field, in order."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        # Fall back to the field alone so a malformed command list doesn't hide a load.
        m = re.search(r'"load_skill"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\])', content)
        if not m:
            return []
        try:
            data = {"load_skill": json.loads(m.group(1))}
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []
    req = data.get("load_skill")
    if isinstance(req, str):
        req = [req]
    if not isinstance(req, list):
        return []
    return [n.strip() for n in req if isinstance(n, str) and n.strip()]


SHELL_LOAD = re.compile(r"^\s*load_skill\s+[\"']?([\w.-]+)[\"']?\s*$")


def split_shell_loads(commands: list[Command]) -> tuple[list[str], list[Command]]:
    """Pull ``load_skill <name>`` lines out of a command batch.

    Returns the requested names and the commands left to run in the terminal.
    """
    names, kept = [], []
    for cmd in commands:
        lines = cmd.keystrokes.splitlines()
        hits = [m.group(1) for ln in lines if (m := SHELL_LOAD.match(ln))]
        if hits and len(hits) == len([ln for ln in lines if ln.strip()]):
            names += hits
        else:
            kept.append(cmd)
    return names, kept


class SkillTerminus(Terminus2):
    options_model = SkillTerminusOptions
    options: SkillTerminusOptions

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._skills: dict[str, dict[str, str]] = {}  # name -> {description, dir, body}
        self._skill_events: list[dict[str, Any]] = []
        self._pending_skill_text: str = ""

    @staticmethod
    @override
    def name() -> str:
        return "skill-terminus"

    @override
    def version(self) -> str | None:
        return "0.1.0"

    # ----- skill discovery and prompt -----

    @override
    async def _build_skills_section(self, environment: BaseEnvironment) -> str | None:
        self._skills = {}
        if not self.skills_dir or not await environment.is_dir(self.skills_dir):
            return None
        found = await environment.exec(
            f"find {shlex.quote(self.skills_dir)} -mindepth 2 -maxdepth 2 -name SKILL.md -type f | sort",
            timeout_sec=10,
        )
        for path in (found.stdout or "").split():
            res = await environment.exec(f"cat {shlex.quote(path)}", timeout_sec=10)
            if res.return_code != 0 or not res.stdout:
                continue
            fm = _frontmatter(res.stdout)
            name = str(fm.get("name") or PurePosixPath(path).parent.name)
            self._skills[name] = {
                "description": str(fm.get("description") or "No description provided."),
                "dir": str(PurePosixPath(path).parent),
                "body": res.stdout,
            }
        if not self._skills:
            return None

        guidance = MUST_GUIDANCE if self.options.skill_guidance == "must" else NEUTRAL_GUIDANCE
        items = "\n".join(
            f"  <skill>\n    <name>{n}</name>\n    <description>{s['description']}</description>\n  </skill>"
            for n, s in self._skills.items()
        )
        return f"\n\nSkills:\n{guidance}\n<available_skills>\n{items}\n</available_skills>"

    # ----- loading -----

    def _record(self, kind: str, skill: str, found: bool, extra: dict | None = None) -> None:
        # turn = index of the model call that issued it; -1 = the synthetic prefill turn.
        self._skill_events.append(
            {
                "turn": -1 if kind == "prefill" else self._n_episodes - 1,
                "type": kind,
                "skill": skill,
                "found": found,
                "gold": skill in self.options.gold_skills,
                "time": datetime.now(timezone.utc).isoformat(),
                **(extra or {}),
            }
        )

    def _render_loads(self, loads: list[tuple[str, str]], kind: str) -> str:
        """``loads`` = (skill name, channel) pairs; channel is json | shell | prefill."""
        parts = []
        for name, via in loads:
            skill = self._skills.get(name)
            self._record(kind, name, skill is not None, {"via": via})
            if skill is None:
                available = ", ".join(self._skills) or "none"
                parts.append(f"Skill not found: {name}. Available skills: {available}.")
            else:
                parts.append(
                    f"Loaded skill: {name} (files are in {skill['dir']})\n---\n{skill['body'].strip()}"
                )
        return f"{SKILL_BLOCK_START}\n" + "\n\n".join(parts) + f"\n{SKILL_BLOCK_END}\n\n"

    def _record_shell_reads(self, commands: list[Command]) -> None:
        for cmd in commands:
            for name, skill in self._skills.items():
                if skill["dir"] in cmd.keystrokes:
                    self._record("bash_read", name, True, {"keystrokes": cmd.keystrokes[:300]})

    @override
    async def _handle_llm_interaction(self, chat, prompt, original_instruction="", session=None):
        commands, complete, feedback, analysis, plan, llm_response = await super()._handle_llm_interaction(
            chat, prompt, original_instruction, session
        )
        # Small models often type the action as a shell command; treat it as the same
        # load (not sent to the terminal) so a format slip isn't scored as "never loaded".
        shell_names, kept = split_shell_loads(commands)
        loads = [(n, "json") for n in extract_load_request(llm_response.content or "")]
        loads += [(n, "shell") for n in shell_names if n not in {m for m, _ in loads}]
        self._pending_skill_text = self._render_loads(loads, "load") if loads else ""
        self._record_shell_reads(kept)
        return kept, complete, feedback, analysis, plan, llm_response

    @override
    async def _execute_commands(self, commands, session):
        timed_out, output = await super()._execute_commands(commands, session)
        if self._pending_skill_text:
            output = self._pending_skill_text + output
            self._pending_skill_text = ""
        return timed_out, output

    @override
    def _limit_output_length(self, output: str, max_bytes: int = 10000) -> str:
        """Truncate terminal output only; a loaded skill is passed through whole."""
        if output.startswith(SKILL_BLOCK_START) and SKILL_BLOCK_END in output:
            skill, rest = output.split(SKILL_BLOCK_END, 1)
            return skill + SKILL_BLOCK_END + super()._limit_output_length(rest, max_bytes)
        return super()._limit_output_length(output, max_bytes)

    # ----- prefill (C1/C4) -----

    @override
    async def _run_agent_loop(self, initial_prompt: str, chat: Chat, original_instruction: str = "") -> None:
        names = list(self.options.prefill_skills)
        if not names:
            return await super()._run_agent_loop(initial_prompt, chat, original_instruction)

        missing = [n for n in names if n not in self._skills]
        if missing:
            raise ValueError(f"prefill_skills not in the skill pool: {missing}")

        # The synthetic first turn: the model "chose" to load these skills and ran nothing.
        synthetic = json.dumps(
            {
                "analysis": "Before running commands, I will read the instructions of the relevant skill.",
                "plan": "Load the skill and follow its guidance in the next steps.",
                "commands": [],
                "load_skill": names if len(names) > 1 else names[0],
            },
            indent=2,
        )
        terminal = self._limit_output_length(await self._session.get_incremental_output())
        observation = self._render_loads([(n, "prefill") for n in names], "prefill") + (
            terminal or "Current Terminal Screen:\n"
        )
        chat.messages.extend(
            [{"role": "user", "content": initial_prompt}, {"role": "assistant", "content": synthetic}]
        )
        self._trajectory_steps.append(
            Step(
                step_id=len(self._trajectory_steps) + 1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="agent",
                model_name=self._model_name,
                message=synthetic,
                tool_calls=[
                    ToolCall(tool_call_id=f"prefill_{i}", function_name="load_skill", arguments={"name": n})
                    for i, n in enumerate(names)
                ],
                observation=Observation(results=[ObservationResult(content=observation)]),
                extra={"prefill": True},
            )
        )
        return await super()._run_agent_loop(observation, chat, original_instruction)

    # ----- results -----

    @override
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        self._skill_events = []
        try:
            await super().run(instruction, environment, context)
        finally:
            summary = {
                "pool": sorted(self._skills),
                "gold": list(self.options.gold_skills),
                "prefill": list(self.options.prefill_skills),
                "guidance": self.options.skill_guidance,
                "events": self._skill_events,
            }
            context.metadata = {**(context.metadata or {}), "skill_events": summary}
            (self.logs_dir / "skill_events.json").write_text(json.dumps(summary, indent=2))
