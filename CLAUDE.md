# AgentSkillAnalysis (skill-bottleneck)

에이전트가 스킬을 쓰다가 실패할 때, 병목이 **선택(라우팅)**인지 **활용(따르기)**인지 분해하는 연구의 실험 코드.
첫 논문, 목표는 2026년 12월 초 원고 완성. 사용자와는 한국어로 대화한다.

- 연구 계획 문서: https://claude.ai/code/artifact/4cef7902-680d-48c1-84c6-08cbdabaf7be (claude.ai Docs, 같은 계정이면 어디서든 열림)
- 이 파일은 개인 3090 서버에서 진행한 대화(2026-10-01 ~ 10-07)의 결정과 진행 상황을 연구실 서버로 넘기기 위해 정리한 것.

## 연구 질문
스킬 = `SKILL.md`(frontmatter의 name·description + body). 표준 구조(progressive disclosure)에서는 description 목록만 컨텍스트에 있고, 모델이 고르면 body 전체가 로드된다. 그래서 실패 경로는 둘이다.
- **선택 실패**: 아예 안 부름 / 방해 스킬만 부름
- **활용 실패**: 정답 스킬을 불렀지만 안 따름 / 따랐는데도 실패

- RQ1: 실패 중 선택 실패와 활용 실패의 비중은?
- RQ2: 후보 풀이 커지거나 헷갈리는 스킬이 많아지면 병목이 어떻게 이동하나?
- RQ3: 에이전트(모델·하네스) 간 전이 실패는 어느 단계에서 생기나? (먼저 모델만 교체, 하네스 교차는 확장)

## 실험 조건 (`src/sb/conditions.py`)
| 조건 | 후보 풀 | prefill | 남는 역할 |
|---|---|---|---|
| C0 | 없음 | - | 기준선 |
| C1 | 정답 스킬 | 정답 | 활용만 |
| C2 | 정답 스킬 | - | 호출 여부 + 활용 |
| C3 | 정답 + 방해 N | - | 호출 + 변별 + 활용 |
| C4 | 방해 | 방해 1개 | 오선택 비용 |
| C5 | 방해만 | - | 과잉 호출 |

비교: C1−C0 스킬 가치, C1−C2 안 불러서 잃는 몫, C2−C3 변별 실패, C1의 실패분 = 활용 병목.
정답 스킬은 메타데이터가 아니라 "oracle로 넣었을 때 실제로 성공률을 올리는 스킬"로 최종 정의할 예정(파일럿에서 결정).

## 구성과 설계 결정
- **실험장 = Harbor 0.24.0** (Laude Institute의 에이전트 평가 프레임워크: 과제 Docker 환경, 에이전트 실행, 채점, 반복). Codex·Claude Code가 Harbor 내장 에이전트라 나중에 확장할 때 에이전트 이름만 바꾸면 된다. 그래서 선택함.
- **과제 = SkillsBench 논문 시점(commit `7a3eb84a`, 2026-02-14) Harbor 형식 과제.** 이 시점 과제는 Dockerfile에서 스킬을 이미지에 구워 넣어서(`COPY skills /root/.claude/skills` 등), `src/sb/export_tasks.py`가 그 줄을 빼고 스킬을 `data/skills/<task>/`로 분리한다. 스킬은 조건마다 Harbor `--skill`로 `/harbor/skills`에 주입.
  - 86개 중 **74개 사용 가능**. 12개는 스킬 코드를 과제 작업공간(`/app/skills` 등)에 복사하거나 빌드에 쓰는 과제라 제외(C0 오염). 사유는 `data/manifest.json`.
- **에이전트 = `sb.agent:SkillTerminus`** (Harbor Terminus-2 상속, SkillsBench의 terminus-2-skills 형식을 이어받음).
  - 스킬 목록은 name+description만 노출(경로 숨김). 로드는 JSON 응답의 `"load_skill": "<name>"`.
  - **쉘로 `load_skill docx`를 입력해도 같은 로드로 처리**(`via: shell`). Qwen3-8B가 실제로 이렇게 했고, 처리 안 하면 형식 실수가 "안 부름"으로 잘못 집계됨.
  - 로드된 SKILL.md는 터미널 출력 10KB 절단에서 제외.
  - 로딩 기록: 실행마다 `agent/skill_events.json` (`type`: load / prefill / bash_read, `turn`, `gold`, `via`).
  - C1·C4 prefill: 첫 턴에 모델이 스킬을 불러온 것처럼 대화를 시작(자연 로딩과 같은 위치·형식).
  - `skill_guidance=neutral|must`: 원본 terminus-2-skills 프롬프트의 "MUST check if any skill matches BEFORE executing commands" 문구는 호출을 강하게 유도해 선택 병목을 과소평가하게 만든다. 기본은 neutral, must는 비교·재현용.
  - Terminus-2의 자동 요약은 끈다(`enable_summarize=false`): 요약 중 스킬 내용이 사라질 수 있음.
- `src/sb/sandbox.py`, `src/sb/cli.py`(`sb oracle`)는 Harbor 도입 전에 만든 자체 샌드박스·오라클 점검기(현재 SkillsBench task.md 형식용). 지금 실험 경로는 Harbor.

## 파일
- `src/sb/agent.py` SkillTerminus · `src/sb/conditions.py` 조건 → harbor 인자 · `src/sb/export_tasks.py` 과제 변환
- `scripts/setup_data.sh` 새 머신에서 `third_party/`, `data/` 재생성 · `scripts/run_terminus.sh <task> <C0..C5>` 단일 실행
- `docker/compose.yaml` vLLM + runner, `docker/Dockerfile.vllm`, `configs/models.yaml` GPU별 모델 프리셋
- git 제외: `third_party/`, `data/`, `jobs/`(Harbor 결과), `docker/.env`, `notes/`

## 실행
```bash
uv sync && scripts/setup_data.sh
cp .env.example docker/.env      # 모델·TP 조정 (configs/models.yaml 참고)
docker compose -f docker/compose.yaml up -d --build vllm
uv run harbor run -p data/tasks/offer-letter-generator -a oracle -o jobs   # 오라클 점검
scripts/run_terminus.sh offer-letter-generator C1
uv run pytest -q                 # 단위 테스트 16개
```
Harbor + 로컬 vLLM은 `-m hosted_vllm/agent`, `--ak api_base=...`, `--ak model_info={max_input_tokens,...}` 필요(run_terminus.sh에 있음).

## 진행 상황 (2026-10-07)
- 완료: 환경(M0), 오라클 점검 일부(M1: 자체 runner 3개, Harbor 1개 통과), C0·C1·C2 실행 확인(M2·M3).
- 결과(offer-letter-generator, Qwen3-8B, 각 1회, 의미 없음 — 장치 동작 확인용): 기본 Terminus-2 스킬 없음 0점(시간 초과), 스킬 줘도 안 부름 0점, C1 0점, C2 쉘 로딩 처리 후 **1점**.
- 다음:
  1. **연구실 서버 Docker 구성 확인** (아래 주의 참고) ← 가장 먼저
  2. 74개 과제 Harbor 오라클 일괄 점검 → 사용 가능 과제 확정
  3. 파일럿 일괄 실행기: 과제 × {C0, C1} × 3회, 점수 + skill_events 집계 표 → C1−C0 효과 큰 과제 20~30개 선정
  4. 방해 스킬 풀(`sb.pools`): 다른 과제 스킬 중 임베딩 similar / random, 실제 body 사용(stub 금지)
  5. 따르기 측정: 정답 SKILL.md에서 확인 가능한 지시 5~10개 추출(LLM + 사람 검수) → 궤적 판정

## 환경 주의
- **연구실 서버는 반드시 Docker로만 실행(호스트에 라이브러리 설치 금지).** Harbor도 컨테이너 안에서 돌려야 한다. Harbor는 과제 컨테이너에 호스트 경로를 bind mount하므로, Docker 소켓을 넘긴 컨테이너 안에서 실행하면 경로가 어긋날 수 있다(미검증). 해결 후보: runner 컨테이너에 저장소를 호스트와 **같은 절대경로**로 마운트.
- GPU 구성(A100×2 / A6000×4 / 4090×4)은 미정. `configs/models.yaml` 참고. 개인 3090 서버에서는 실행 1개씩만 가능(32k 기준 동시성 1.2).
- 개인 3090 서버 드라이버는 CUDA 12.7이라 `docker/Dockerfile.vllm`(이미지의 compat 라이브러리 제거) + `NVIDIA_DISABLE_REQUIRE=1`이 필요했다. 드라이버가 최신이면 원본 `vllm/vllm-openai` 이미지를 써도 된다.
- 오픈 모델로 먼저 진행하고, 결과가 긍정적이면 API 모델로 확장(사용자 결정).

## 작업 원칙 (사용자 요청)
- 선행 연구 조사 시 ICML·NeurIPS·ICLR·ACL 등 탑티어를 우선 확인하고, 각 논문의 게재처(본회의/워크숍/arXiv)를 명시한다. 확인 못 하면 "arXiv, 게재처 미확인".
- 주요 선행 연구: Demystifying Agent Skills (arXiv 2608.14036; 스킬은 절차적 앵커 65.7%, 지식 주입 4.5%. 단 공개 코드에서 방해 스킬이 stub body이고 "사용"을 경로 정규식으로 셈), Skill Retrieval Augmentation (arXiv 2604.24594; 불러올지 결정하는 단계가 병목), SkillsBench (arXiv 2602.12670), SkillRouter (arXiv 2603.22455).
