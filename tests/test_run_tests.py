from __future__ import annotations

from unittest.mock import patch

import pytest

from nodes.run_tests import run_tests


def _state() -> dict:
    return {
        "pr": {"repo": "conda/pycosat", "pr_id": 4},
        "task": {
            "masked_code": "def solve():\n    <MASK>\n",
            "target_file_path": "/app/test.py",
            "host_lang": "Python",
        },
        "generated_code": "return 1",
        "image_tag": "benchmark-conda-pycosat-pr4:latest",
        "env_spec": {
            "build_cmds": ["python3 -m pip install ."],
            "test_cmds": ["pytest -q"],
            "test_framework": "pytest",
        },
        "run_config": {"max_concurrent_docker": 2},
    }


@pytest.mark.asyncio
async def test_run_tests_reconstructs_full_source_before_injection():
    captured = {}

    async def fake_run_file_in_container(**kwargs):
        captured.update(kwargs)
        return {
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "total": 1,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "ok",
        }

    with patch("nodes.run_tests.run_file_in_container", side_effect=fake_run_file_in_container):
        result = await run_tests(_state())

    assert "return 1" in captured["file_content"]
    assert "<MASK>" not in captured["file_content"]
    assert result["test_result"]["passed"] == 1


@pytest.mark.asyncio
async def test_run_tests_returns_compile_failed_error():
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "compile_success": False,
            "exit_code": 1,
            "stdout_tail": "compile error",
        }

    with patch("nodes.run_tests.run_file_in_container", side_effect=fake_run_file_in_container):
        result = await run_tests(_state())

    assert result["errors"][0]["reason"] == "compile_failed"


@pytest.mark.asyncio
async def test_run_tests_returns_timeout_error():
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "compile_success": False,
            "exit_code": -1,
            "stdout_tail": "timed out",
        }

    with patch("nodes.run_tests.run_file_in_container", side_effect=fake_run_file_in_container):
        result = await run_tests(_state())

    assert result["errors"][0]["reason"] == "test_timeout"


@pytest.mark.asyncio
async def test_run_tests_returns_unparseable_error():
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": -1,
            "failed": -1,
            "errors": -1,
            "total": -1,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "weird output",
        }

    with patch("nodes.run_tests.run_file_in_container", side_effect=fake_run_file_in_container):
        result = await run_tests(_state())

    assert result["errors"][0]["reason"] == "test_output_unparseable"
