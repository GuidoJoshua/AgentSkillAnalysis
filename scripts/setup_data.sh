#!/usr/bin/env bash
# Recreate third_party/ and data/ (not in git) on a fresh machine.
#   scripts/setup_data.sh
set -euo pipefail
cd "$(dirname "$0")/.."

SKILLSBENCH_URL=https://github.com/benchflow-ai/skillsbench.git
CURRENT_COMMIT=9a1f4dd5f7659f75707435da3ce854b6e48321d1  # task.md format (BenchFlow era), used by src/sb/sandbox.py
PAPER_COMMIT=7a3eb84a                                   # Harbor format, SkillsBench paper (2026-02-14)

mkdir -p third_party
if [ ! -d third_party/skillsbench/.git ]; then
  git clone "$SKILLSBENCH_URL" third_party/skillsbench
fi
git -C third_party/skillsbench fetch -q origin
git -C third_party/skillsbench checkout -q "$CURRENT_COMMIT"

if [ ! -e third_party/skillsbench-feb/.git ]; then
  git -C third_party/skillsbench worktree add -q ../skillsbench-feb "$PAPER_COMMIT"
fi

# Paper-era tasks with skills un-baked -> data/tasks, data/skills, data/manifest.json
rm -rf data/tasks data/skills
uv run python -m sb.export_tasks --src third_party/skillsbench-feb/tasks --out data
