from __future__ import annotations

import os
import tempfile
from typing import Any

from nodes.docker_runtime import (
    build_full_source,
    docker_cp,
    docker_exec,
    docker_run,
    docker_stop,
    language_suffix,
    runtime_build_cmds,
)
from nodes.stage2_utils import make_error
from parsers import get_parser


async def run_file_in_container(
    *,
    image_tag: str,
    target_file_path: str,
    file_content: str,
    host_lang: str,
    env_spec: dict[str, Any],
    max_concurrent_docker: int = 4,
) -> dict[str, Any]:
    from graph import get_docker_semaphore

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

            cp_exit, cp_output = await docker_cp(local_tmp_name, container_id, target_file_path)
            if cp_exit != 0:
                result = parser.parse(cp_output, cp_exit)
                result["compile_success"] = False
                return result

            for command in runtime_build_cmds(env_spec):
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

            test_command = " && ".join(env_spec.get("test_cmds") or [])
            exit_code, output = await docker_exec(container_id, test_command, timeout=300)
            result = parser.parse(output, exit_code)
            result["compile_success"] = True
            return result
        finally:
            if local_tmp_name and os.path.exists(local_tmp_name):
                os.unlink(local_tmp_name)
            await docker_stop(container_id)


async def run_tests(state: dict[str, Any]) -> dict[str, Any]:
    pr = state.get("pr") or {}
    task = state.get("task")
    generated_code = state.get("generated_code") or ""
    image_tag = state.get("image_tag")
    env_spec = state.get("env_spec")
    if not task or not image_tag or not env_spec:
        return {
            "test_result": None,
            "errors": [
                make_error(
                    pr,
                    stage="run_tests",
                    reason="task_missing",
                    message="run_tests requires task, env_spec, and image_tag.",
                )
            ],
        }

    full_source = build_full_source(task["masked_code"], generated_code)
    result = await run_file_in_container(
        image_tag=image_tag,
        target_file_path=task["target_file_path"],
        file_content=full_source,
        host_lang=task["host_lang"],
        env_spec=env_spec,
        max_concurrent_docker=state["run_config"].get("max_concurrent_docker", 4),
    )

    if result["exit_code"] == -1:
        return {
            "test_result": result,
            "errors": [
                make_error(
                    pr,
                    stage="run_tests",
                    reason="test_timeout",
                    message=result["stdout_tail"],
                )
            ],
        }
    if not result["compile_success"]:
        return {
            "test_result": result,
            "errors": [
                make_error(
                    pr,
                    stage="run_tests",
                    reason="compile_failed",
                    message=result["stdout_tail"],
                )
            ],
        }
    if result["total"] == -1:
        return {
            "test_result": result,
            "errors": [
                make_error(
                    pr,
                    stage="run_tests",
                    reason="test_output_unparseable",
                    message=result["stdout_tail"],
                )
            ],
        }
    return {"test_result": result}
