"""Command-line entry point: ``sb <command> ...``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sb.sandbox import Sandbox, build_image
from sb.tasks import Task, load_tasks


def results_dir() -> Path:
    return Path(os.environ.get("SB_RESULTS_DIR", "results"))


def _oracle_one(task: Task, skip_solve: bool = False) -> dict:
    """Build the task image, run the reference solution, then the verifier."""
    rec: dict = {"task": task.id, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "skip_solve": skip_solve}
    start = time.monotonic()
    try:
        image = build_image(task)
        rec["image"] = image
        with Sandbox(task, image) as box:
            solve_tail = ""
            if not skip_solve:
                solve = box.run_oracle()
                rec["solve_exit"] = solve.exit_code
                rec["solve_timed_out"] = solve.timed_out
                solve_tail = solve.output[-2000:]
            reward, verify = box.run_verifier()
            rec["reward"] = reward
            rec["verify_exit"] = verify.exit_code
            if reward != 1.0 and not skip_solve:
                rec["solve_tail"] = solve_tail
                rec["verify_tail"] = verify.output[-2000:]
    except Exception as e:  # keep the sweep going; record why this task failed
        rec["error"] = f"{type(e).__name__}: {e}"[:2000]
        rec["reward"] = None
    rec["seconds"] = round(time.monotonic() - start, 1)
    return rec


def cmd_oracle(args: argparse.Namespace) -> int:
    """Check that sandbox + verifier work: the oracle should score 1 on every usable task."""
    tasks = [t for t in load_tasks(args.tasks or None) if not t.uses_compose]
    out = results_dir() / ("verifier_empty.jsonl" if args.skip_solve else "oracle.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists() and not args.tasks:
        done = {json.loads(line)["task"] for line in out.read_text().splitlines() if line.strip()}
    todo = [t for t in tasks if t.id not in done]
    print(f"{len(todo)} tasks to check ({len(done)} already recorded) -> {out}", flush=True)

    passed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, out.open("a") as f:
        futures = {pool.submit(_oracle_one, t, args.skip_solve): t for t in todo}
        for fut in as_completed(futures):
            rec = fut.result()
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            ok = rec.get("reward") == 1.0
            passed += ok
            status = "PASS" if ok else ("ERROR" if "error" in rec else "FAIL")
            print(f"[{status}] {rec['task']} reward={rec.get('reward')} {rec['seconds']}s", flush=True)
    print(f"oracle passed {passed}/{len(todo)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sb")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("oracle", help="run reference solutions through the verifier")
    p.add_argument("--tasks", nargs="*", help="task ids (default: all tasks)")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--skip-solve", action="store_true", help="verify an untouched environment (expect reward 0)")
    p.set_defaults(func=cmd_oracle)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
