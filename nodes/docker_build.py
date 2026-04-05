from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nodes.stage2_utils import make_error, tail_text


async def _run_command(cmd: list[str], timeout: int) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, stdout.decode("utf-8", errors="ignore")
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return -1, "docker build timed out"


async def docker_build(state: dict[str, Any]) -> dict[str, Any]:
    from graph import get_docker_semaphore

    pr = state["pr"]
    dockerfile_path = Path(state["dockerfile_path"])
    image_tag = state["image_tag"]
    build_retries = int(state.get("build_retries", 0))

    cmd = [
        "docker",
        "build",
        "-t",
        image_tag,
        "-f",
        str(dockerfile_path),
        "--no-cache",
        str(dockerfile_path.parent),
    ]

    async with get_docker_semaphore(
        state["run_config"].get("max_concurrent_docker", 4)
    ):
        exit_code, output = await _run_command(cmd, timeout=600)

    if exit_code == 0:
        return {
            "build_status": "success",
            "build_log": tail_text(output),
        }

    return {
        "build_status": "failed",
        "build_retries": build_retries + 1,
        "build_log": tail_text(output),
        "errors": [
            make_error(
                pr,
                stage="docker_build",
                reason="docker_build_failed",
                message=tail_text(output, max_lines=100),
                attempt=build_retries + 1,
            )
        ],
    }
