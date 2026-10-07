"""Per-trial task containers, driven through the Docker SDK.

The runner itself may live in a container with the host's Docker socket
mounted, so task containers are siblings: files go in and out with
``put_archive``/``get_archive`` rather than bind mounts, whose source paths
would be resolved on the host.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import docker

from sb.tasks import Task

OUTPUT_LIMIT = 16_000  # chars of combined stdout/stderr returned per command
TIMEOUT_EXIT = 124  # exit status of coreutils `timeout`


@dataclass
class ExecResult:
    exit_code: int
    output: str
    seconds: float
    timed_out: bool
    truncated: bool


def _client() -> docker.DockerClient:
    return docker.from_env(timeout=600)


def _dir_digest(path: Path) -> str:
    """Content hash of a build context, so edited tasks get a fresh image tag."""
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file() and "skills" not in p.relative_to(path).parts:
            h.update(str(p.relative_to(path)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def build_image(task: Task, client: docker.DockerClient | None = None) -> str:
    """Build (or reuse) the task's environment image and return its tag."""
    client = client or _client()
    tag = f"sb-task-{task.id}:{_dir_digest(task.env_dir)}"
    try:
        client.images.get(tag)
    except docker.errors.ImageNotFound:
        client.images.build(path=str(task.env_dir), tag=tag, rm=True, pull=False)
    return tag


def _tar_dir(src: Path, arcname: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(src), arcname=arcname)
    return buf.getvalue()


def _clip(text: str, limit: int = OUTPUT_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = limit // 2
    dropped = len(text) - limit
    return f"{text[:half]}\n... [{dropped} chars truncated] ...\n{text[-half:]}", True


class Sandbox:
    """A running task container. Use as a context manager."""

    def __init__(self, task: Task, image: str, client: docker.DockerClient | None = None):
        self.task = task
        self.image = image
        self.client = client or _client()
        self.container = None

    def __enter__(self) -> Sandbox:
        self.container = self.client.containers.run(
            self.image,
            command=["sleep", "infinity"],
            name=f"sb-{self.task.id}-{uuid.uuid4().hex[:8]}",
            detach=True,
            nano_cpus=int(self.task.cpus * 1e9),
            mem_limit=f"{self.task.memory_mb}m",
            network_mode=None if self.task.network else "none",
            labels={"sb.task": self.task.id},
        )
        return self

    def __exit__(self, *exc) -> None:
        if self.container is not None:
            self.container.remove(force=True)
            self.container = None

    def exec(self, command: str, timeout: float = 600, workdir: str | None = None) -> ExecResult:
        wrapped = ["timeout", "-k", "5", str(int(timeout)), "bash", "-lc", command]
        start = time.monotonic()
        res = self.container.exec_run(wrapped, workdir=workdir, demux=False)
        seconds = time.monotonic() - start
        text = (res.output or b"").decode("utf-8", errors="replace")
        text, truncated = _clip(text)
        return ExecResult(res.exit_code, text, seconds, res.exit_code == TIMEOUT_EXIT, truncated)

    def put_dir(self, src: Path, dest: str) -> None:
        """Copy local directory ``src`` to ``dest`` inside the container."""
        parent, name = dest.rstrip("/").rsplit("/", 1)
        parent = parent or "/"
        self.container.exec_run(["mkdir", "-p", parent])
        self.container.put_archive(parent, _tar_dir(src, name))

    def read_file(self, path: str) -> str | None:
        res = self.container.exec_run(["cat", path])
        if res.exit_code != 0:
            return None
        return res.output.decode("utf-8", errors="replace")

    def run_oracle(self) -> ExecResult:
        self.put_dir(self.task.oracle_dir, "/oracle")
        return self.exec("bash /oracle/solve.sh", timeout=self.task.agent_timeout_sec, workdir="/oracle")

    def run_verifier(self) -> tuple[float | None, ExecResult]:
        """Run the task's verifier; returns (reward, exec result). reward None = verifier error."""
        # Drop conftest.py files the agent may have planted to steer pytest.
        self.exec(
            "find / -xdev -name conftest.py -not -path '/verifier/*' "
            "-not -path '/proc/*' -not -path '/usr/*' -delete 2>/dev/null; true",
            timeout=120,
        )
        self.put_dir(self.task.verifier_dir, "/verifier")
        self.exec("mkdir -p /logs/verifier", timeout=30)
        res = self.exec("bash /verifier/test.sh", timeout=self.task.verifier_timeout_sec)
        raw = self.read_file("/logs/verifier/reward.txt")
        try:
            reward = float(raw.strip()) if raw is not None else None
        except ValueError:
            reward = None
        return reward, res
