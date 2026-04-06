from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import Any

from parsers import get_parser
from state import EnvSpec, TestResult
from nodes.stage2_utils import tail_text


LANG_TO_SUFFIX = {
    "Go": ".go",
    "Python": ".py",
    "Java": ".java",
    "Rust": ".rs",
    "JavaScript": ".js",
    "TypeScript": ".ts",
    "C": ".c",
    "C++": ".cpp",
    "Ruby": ".rb",
    "Lua": ".lua",
    "Other": ".txt",
}

def language_suffix(host_lang: str | None) -> str:
    return LANG_TO_SUFFIX.get(host_lang or "Other", ".txt")


def build_full_source(masked_code: str, generated_code: str) -> str:
    return masked_code.replace("<MASK>", generated_code, 1)


def runtime_build_cmds(env_spec: EnvSpec) -> list[str]:
    return list(env_spec.get("build_cmds") or [])


async def run_command(cmd: list[str], timeout: int) -> tuple[int, str]:
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
        return -1, "command timed out"


def wrap_shell_command(command: str) -> str:
    normalized = re.sub(
        r"(^|[;&|]\s*|\s)pytest(?=\s)",
        lambda match: f"{match.group(1)}python3 -m pytest",
        command,
    )
    return (
        "if [ -x /usr/local/go/bin/go ]; then "
        'export GOROOT="${GOROOT:-/usr/local/go}"; '
        'export GOPATH="${GOPATH:-/go}"; '
        'export PATH="${GOROOT}/bin:${GOPATH}/bin:${PATH}"; '
        "fi; "
        "if [ -d /app/static-build/install/lib/pkgconfig ]; then "
        "export PKG_CONFIG_PATH=/app/static-build/install/lib/pkgconfig:${PKG_CONFIG_PATH}; "
        "fi; "
        f"{normalized}"
    )


async def docker_run(image_tag: str, *, timeout: int = 60) -> tuple[int, str]:
    return await run_command(
        ["docker", "run", "-d", "--rm", image_tag, "sleep", "infinity"],
        timeout=timeout,
    )


async def docker_exec(
    container_id: str,
    command: str,
    *,
    timeout: int = 600,
) -> tuple[int, str]:
    return await run_command(
        ["docker", "exec", container_id, "sh", "-lc", wrap_shell_command(command)],
        timeout=timeout,
    )


async def docker_cp(
    local_path: str,
    container_id: str,
    target_path: str,
    *,
    timeout: int = 60,
) -> tuple[int, str]:
    return await run_command(
        ["docker", "cp", local_path, f"{container_id}:{target_path}"],
        timeout=timeout,
    )


async def docker_stop(container_id: str) -> None:
    await run_command(["docker", "stop", container_id], timeout=60)


async def run_file_in_container(
    *,
    image_tag: str,
    target_file_path: str,
    file_content: str,
    host_lang: str,
    env_spec: EnvSpec,
    max_concurrent_docker: int = 4,
) -> TestResult:
    from graph import get_docker_semaphore

    build_cmds = runtime_build_cmds(env_spec)
    test_cmds = list(env_spec.get("test_cmds") or [])
    parser = get_parser(env_spec.get("test_framework"))
    local_tmp_name: str | None = None

    async with get_docker_semaphore(max_concurrent_docker):
        run_exit, run_output = await docker_run(image_tag)
        if run_exit != 0:
            return parser.parse(run_output, run_exit)
        container_id = run_output.strip()

        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=language_suffix(host_lang),
                delete=False,
            ) as handle:
                handle.write(file_content)
                local_tmp_name = handle.name

            cp_exit, cp_output = await docker_cp(
                local_tmp_name,
                container_id,
                target_file_path,
            )
            if cp_exit != 0:
                return {
                    "passed": 0,
                    "failed": 0,
                    "errors": 1,
                    "total": 0,
                    "compile_success": False,
                    "exit_code": cp_exit,
                    "stdout_tail": cp_output,
                }

            for command in build_cmds:
                exit_code, output = await docker_exec(container_id, command, timeout=120)
                if exit_code != 0:
                    return {
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "total": 0,
                        "compile_success": False,
                        "exit_code": exit_code,
                        "stdout_tail": output,
                    }

            test_cmd = " && ".join(test_cmds)
            if not test_cmd:
                return {
                    "passed": 0,
                    "failed": 0,
                    "errors": 1,
                    "total": 0,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "No test commands were available.",
                }

            exit_code, output = await docker_exec(container_id, test_cmd, timeout=300)
            result = parser.parse(output, exit_code)
            result["compile_success"] = True
            return result
        finally:
            if local_tmp_name and os.path.exists(local_tmp_name):
                os.unlink(local_tmp_name)
            await docker_stop(container_id)
