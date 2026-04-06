import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes import run_tests as run_tests_module


def _state() -> dict:
    return {
        "image_tag": "benchmark/test:latest",
        "generated_code": "return 42\n",
        "task": {
            "masked_code": "def f():\n    <MASK>\n",
            "target_file_path": "/app/src/module.py",
            "host_lang": "Python",
        },
        "env_spec": {
            "build_cmds": ["python -m py_compile src/module.py"],
            "test_cmds": ["pytest -q"],
            "test_framework": "pytest",
        },
        "run_config": {"max_concurrent_docker": 1},
    }


class DummySemaphore:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_run_tests_returns_compile_failure_and_cleans_up(monkeypatch):
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "compile_success": False,
            "exit_code": 1,
            "stdout_tail": "build failed",
        }

    monkeypatch.setattr(run_tests_module, "run_file_in_container", fake_run_file_in_container)

    result = await run_tests_module.run_tests(_state())
    assert result["test_result"]["compile_success"] is False
    assert result["test_result"]["total"] == 0


@pytest.mark.asyncio
async def test_run_tests_parses_test_failure(monkeypatch):
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 2,
            "failed": 1,
            "errors": 0,
            "total": 3,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "1 failed, 2 passed",
        }

    monkeypatch.setattr(run_tests_module, "run_file_in_container", fake_run_file_in_container)

    result = await run_tests_module.run_tests(_state())
    assert result["test_result"]["compile_success"] is True
    assert result["test_result"]["failed"] == 1
    assert result["test_result"]["passed"] == 2


@pytest.mark.asyncio
async def test_run_tests_handles_unparseable_output(monkeypatch):
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": -1,
            "failed": -1,
            "errors": -1,
            "total": -1,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "totally unknown output",
        }

    monkeypatch.setattr(run_tests_module, "run_file_in_container", fake_run_file_in_container)

    result = await run_tests_module.run_tests(_state())
    assert result["test_result"]["compile_success"] is True
    assert result["test_result"]["total"] == -1


@pytest.mark.asyncio
async def test_run_tests_timeout_bubbles_into_result(monkeypatch):
    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "compile_success": False,
            "exit_code": -1,
            "stdout_tail": "command timed out",
        }

    monkeypatch.setattr(run_tests_module, "run_file_in_container", fake_run_file_in_container)

    result = await run_tests_module.run_tests(_state())
    assert result["test_result"]["exit_code"] == -1
