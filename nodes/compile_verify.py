from __future__ import annotations

from typing import Any

from nodes.docker_runtime import docker_stop, run_command, runtime_build_cmds, wrap_shell_command
from nodes.stage2_utils import make_error, tail_text
from parsers import get_parser


async def _docker_run(image_tag: str) -> tuple[int, str]:
    return await _run_command(
        ["docker", "run", "-d", "--rm", image_tag, "sleep", "infinity"],
        timeout=60,
    )


async def _docker_exec(container_id: str, command: str) -> tuple[int, str]:
    return await _run_command(
        ["docker", "exec", container_id, "sh", "-lc", wrap_shell_command(command)],
        timeout=600,
    )


async def _docker_stop(container_id: str) -> None:
    await docker_stop(container_id)


_run_command = run_command


async def compile_verify(state: dict[str, Any]) -> dict[str, Any]:
    from graph import get_docker_semaphore

    pr = state["pr"]
    env_spec = state["env_spec"]
    repair_rounds = int(state.get("compile_repair_rounds", 0))
    repair_enabled = bool(state["run_config"].get("enable_compile_repair"))
    build_cmds = runtime_build_cmds(env_spec)
    test_cmds = list(env_spec.get("test_cmds") or [])

    if not test_cmds:
        return {
            "compile_status": "failed",
            "errors": [
                make_error(
                    pr,
                    stage="compile_verify",
                    reason="test_framework_unsupported",
                    message="No test commands were available for baseline verification.",
                )
            ],
        }

    async with get_docker_semaphore(
        state["run_config"].get("max_concurrent_docker", 4)
    ):
        run_exit, run_output = await _docker_run(state["image_tag"])
        if run_exit != 0:
            return {
                "compile_status": "failed",
                "errors": [
                    make_error(
                        pr,
                        stage="compile_verify",
                        reason="docker_build_failed",
                        message=tail_text(run_output, max_lines=100),
                    )
                ],
            }
        container_id = run_output.strip()

        try:
            build_outputs: list[str] = []
            for command in build_cmds:
                exit_code, output = await _docker_exec(container_id, command)
                build_outputs.append(output)
                if exit_code != 0:
                    return {
                        "compile_status": "retryable" if repair_enabled else "failed",
                        "compile_repair_rounds": repair_rounds + 1 if repair_enabled else repair_rounds,
                        "compile_repair_log": tail_text("\n".join(build_outputs)),
                        "errors": [
                            make_error(
                                pr,
                                stage="compile_verify",
                                reason="compile_unrecoverable",
                                message=tail_text(output, max_lines=100),
                            )
                        ],
                    }

            test_outputs: list[str] = []
            last_exit_code = 0
            for command in test_cmds:
                last_exit_code, output = await _docker_exec(container_id, command)
                test_outputs.append(output)
                if last_exit_code != 0:
                    break

            combined_test_output = "\n".join(test_outputs)
            parser = get_parser(env_spec.get("test_framework"))
            baseline_test_result = parser.parse(combined_test_output, last_exit_code)

            if baseline_test_result["total"] <= 0:
                return {
                    "compile_status": "failed",
                    "baseline_test_result": baseline_test_result,
                    "errors": [
                        make_error(
                            pr,
                            stage="compile_verify",
                            reason="test_output_unparseable",
                            message=tail_text(combined_test_output, max_lines=100),
                        )
                    ],
                }

            if last_exit_code == -1:
                return {
                    "compile_status": "failed",
                    "compile_repair_rounds": repair_rounds,
                    "baseline_test_result": baseline_test_result,
                    "errors": [
                        make_error(
                            pr,
                            stage="compile_verify",
                            reason="baseline_timeout",
                            message="Baseline test command timed out.",
                        )
                    ],
                }

            if (
                last_exit_code != 0
                or not baseline_test_result["compile_success"]
                or baseline_test_result["failed"] > 0
            ):
                return {
                    "compile_status": "failed",
                    "compile_repair_rounds": repair_rounds,
                    "baseline_test_result": baseline_test_result,
                    "errors": [
                        make_error(
                            pr,
                            stage="compile_verify",
                            reason="baseline_tests_failing",
                            message=tail_text(combined_test_output, max_lines=100),
                        )
                    ],
                }

            return {
                "compile_status": "success",
                "compile_repair_rounds": repair_rounds,
                "baseline_test_result": baseline_test_result,
                "compile_repair_log": tail_text("\n".join(build_outputs + test_outputs)),
            }
        finally:
            await _docker_stop(container_id)
