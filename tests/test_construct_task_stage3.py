import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes import construct_task as construct_task_module


FIXTURES = Path(__file__).parent / "fixtures"


def _load_pr() -> dict:
    return json.loads((FIXTURES / "sample_pr_python_cext.json").read_text(encoding="utf-8"))


def _state() -> dict:
    return {
        "pr": _load_pr(),
        "run_config": {"db_path": ":memory:", "task_strategy": "completion"},
        "env_spec": {
            "source": "llm",
            "base_image": "python:3.11",
            "system_deps": [],
            "build_cmds": ["python3 -m pip install ."],
            "test_cmds": ["PYTHONPATH=/app pytest -q tests/test_module.py"],
            "test_framework": "pytest",
            "dockerfile_content": None,
        },
        "image_tag": "benchmark-example-python-cext-demo-pr102:latest",
        "baseline_test_result": {
            "passed": 3,
            "failed": 0,
            "errors": 0,
            "total": 3,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "3 passed",
        },
    }


class FakeGitHubClient:
    def __init__(self, *, details=None, contents=None, tree=None):
        self._details = details or []
        self._contents = contents or {}
        self._tree = tree or []

    def get_pr_file_details(self, repo, pr_number):
        return list(self._details)

    def get_file_content(self, repo, sha, path):
        return self._contents.get(path, "")

    def get_repo_tree(self, repo, sha):
        return list(self._tree)


@pytest.mark.asyncio
async def test_construct_task_success():
    state = _state()
    head_content = "\n".join(
        [
            "#include <Python.h>",
            "",
            "static PyObject* demo(PyObject* self, PyObject* args) {",
            '    if (!PyArg_ParseTuple(args, "i", &value)) {',
            "        return NULL;",
            "    }",
            '    return Py_BuildValue("i", value);',
            "}",
            "",
        ]
    )
    fake_client = FakeGitHubClient(
        details=[
            {
                "path": "src/module.c",
                "lang": "C",
                "is_test": False,
                "status": "modified",
                "additions": 6,
                "deletions": 0,
                "patch": "@@ -1,0 +1,7 @@\n+static PyObject* demo(PyObject* self, PyObject* args) {\n+    if (!PyArg_ParseTuple(args, \"i\", &value)) {\n+        return NULL;\n+    }\n+    return Py_BuildValue(\"i\", value);\n+}\n",
            }
        ],
        contents={
            "src/module.c": head_content,
            "tests/test_module.py": "def test_demo(): pass\n",
        },
        tree=["src/module.c", "tests/test_module.py"],
    )

    with (
        patch.object(construct_task_module, "get_github_tokens_from_env", return_value=["token"]),
        patch.object(construct_task_module, "GitHubClient", return_value=fake_client),
            patch.object(construct_task_module, "_build_attempt_ranges", return_value=[(3, 7)]),
        patch.object(construct_task_module, "_line_keyword_density", return_value=1.0),
        patch.object(construct_task_module, "_evaluate_mask_attempt", AsyncMock(return_value=("valid", {"passed": 1}))),
        patch.object(
            construct_task_module,
            "run_file_in_container",
            AsyncMock(
                return_value={
                    "passed": 3,
                    "failed": 0,
                    "errors": 0,
                    "total": 3,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "3 passed",
                }
            ),
        ),
    ):
        result = await construct_task_module.construct_task(state)

    task = result["task"]
    assert task["task_id"].endswith("-001")
    assert task["target_file_path"] == "/app/src/module.c"
    assert task["host_lang"] == "C"
    assert task["target_lang"] == "Python"
    assert "<MASK>" in task["masked_code"]
    assert task["ground_truth"]


@pytest.mark.asyncio
async def test_construct_task_reports_patch_unavailable():
    state = _state()
    fake_client = FakeGitHubClient(details=[])
    with (
        patch.object(construct_task_module, "get_github_tokens_from_env", return_value=["token"]),
        patch.object(construct_task_module, "GitHubClient", return_value=fake_client),
    ):
        result = await construct_task_module.construct_task(state)

    assert result["task"] is None
    assert result["errors"][0]["reason"] == "patch_unavailable"


@pytest.mark.asyncio
async def test_construct_task_reports_mask_ineffective():
    state = _state()
    fake_client = FakeGitHubClient(
        details=[
            {
                "path": "src/module.c",
                "lang": "C",
                "is_test": False,
                "status": "modified",
                "additions": 2,
                "deletions": 0,
                "patch": "@@ -1,0 +1,2 @@\n+PyArg_ParseTuple\n+Py_BuildValue\n",
            }
        ],
        contents={"src/module.c": "PyArg_ParseTuple\nPy_BuildValue\n", "tests/test_module.py": "pass\n"},
        tree=["src/module.c", "tests/test_module.py"],
    )
    with (
        patch.object(construct_task_module, "get_github_tokens_from_env", return_value=["token"]),
        patch.object(construct_task_module, "GitHubClient", return_value=fake_client),
        patch.object(construct_task_module, "_evaluate_mask_attempt", AsyncMock(return_value=("ineffective", {"passed": 3}))),
    ):
        result = await construct_task_module.construct_task(state)

    assert result["task"] is None
    assert result["errors"][0]["reason"] == "mask_ineffective"
