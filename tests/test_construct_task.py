from __future__ import annotations

from unittest.mock import patch

import pytest

from nodes.construct_task import construct_task


class FakeGitHubClient:
    def __init__(self, *, file_details, contents, tree=None):
        self._file_details = file_details
        self._contents = contents
        self._tree = tree or []

    def get_pr_file_details(self, repo, pr_id):
        return list(self._file_details)

    def get_file_content(self, repo, sha, path):
        return self._contents.get((sha, path), self._contents.get(path, ""))

    def get_repo_tree(self, repo, sha):
        return list(self._tree)


def _base_pr() -> dict:
    return {
        "repo": "conda/pycosat",
        "clone_url": "https://github.com/conda/pycosat.git",
        "pr_id": 4,
        "pr_title": "Teach solve to take iterables",
        "interop_type": "python_cext",
        "interop_layer": "runtime_embedding",
        "base_sha": "base",
        "head_sha": "head",
        "diff_files": [],
        "diff_total_lines": 10,
        "test_commands": None,
        "merged_at": "2024-01-01T00:00:00+00:00",
    }


def _base_state() -> dict:
    return {
        "pr": _base_pr(),
        "env_spec": {
            "source": "llm",
            "base_image": "python:3.11",
            "system_deps": [],
            "build_cmds": ["python3 -m pip install ."],
            "test_cmds": ["PYTHONPATH=/app pytest -q test_pycosat.py"],
            "test_framework": "pytest",
            "dockerfile_content": None,
        },
        "image_tag": "benchmark-conda-pycosat-pr4:latest",
        "baseline_test_result": {
            "passed": 5,
            "failed": 0,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "ok",
        },
        "run_config": {
            "db_path": ":memory:",
            "task_strategy": "completion",
            "max_concurrent_docker": 2,
        },
    }


@pytest.mark.asyncio
async def test_construct_task_builds_task_from_live_patch():
    head_content = """static PyObject* solve(PyObject *self, PyObject *args) {
    PyObject *clauses = NULL;
    if (!PyArg_ParseTuple(args, "O", &clauses)) {
        return NULL;
    }
    return Py_BuildValue("i", 1);
}"""
    file_details = [
        {
            "path": "pycosat.c",
            "lang": "C",
            "is_test": False,
            "additions": 8,
            "deletions": 2,
            "status": "modified",
            "patch": '@@ -1,4 +1,5 @@\n static PyObject* solve(PyObject *self, PyObject *args) {\n-    return NULL;\n+    if (!PyArg_ParseTuple(args, "O", &clauses)) {\n+        return NULL;\n+    }\n',
        },
        {
            "path": "test_pycosat.py",
            "lang": "Python",
            "is_test": True,
            "additions": 5,
            "deletions": 0,
            "status": "modified",
            "patch": "@@ -1 +1 @@\n+def test_it(): pass\n",
        },
    ]
    client = FakeGitHubClient(
        file_details=file_details,
        contents={
            ("head", "pycosat.c"): head_content,
            ("head", "test_pycosat.py"): "def test_it():\n    assert True\n",
        },
        tree=["test_pycosat.py"],
    )

    results = [
        {
            "passed": 0,
            "failed": 5,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "masked",
        },
        {
            "passed": 5,
            "failed": 0,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "restored",
        },
    ]

    async def fake_run_file_in_container(**kwargs):
        return results.pop(0)

    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.construct_task.GitHubClient", return_value=client),
        patch("nodes.construct_task.run_file_in_container", side_effect=fake_run_file_in_container),
    ):
        result = await construct_task(_base_state())

    task = result["task"]
    assert task["task_id"].endswith("-001")
    assert task["target_file_path"] == "/app/pycosat.c"
    assert "<MASK>" in task["masked_code"]
    assert "PyArg_ParseTuple" in task["ground_truth"]
    assert task["host_lang"] == "C"
    assert task["target_lang"] == "Python"


@pytest.mark.asyncio
async def test_construct_task_returns_patch_unavailable_when_details_missing():
    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch(
            "nodes.construct_task.GitHubClient",
            return_value=FakeGitHubClient(file_details=[], contents={}),
        ),
    ):
        result = await construct_task(_base_state())

    assert result["errors"][0]["reason"] == "patch_unavailable"


@pytest.mark.asyncio
async def test_construct_task_returns_no_interop_signal_for_signal_free_ranges():
    head_content = """int helper(int value) {
    int local = value + 1;
    return local;
}"""
    file_details = [
        {
            "path": "helper.c",
            "lang": "C",
            "is_test": False,
            "additions": 3,
            "deletions": 1,
            "status": "modified",
            "patch": "@@ -1,3 +1,3 @@\n-int helper(int value) {\n+int helper(int value) {\n",
        }
    ]

    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "total": 1,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "ok",
        }

    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch(
            "nodes.construct_task.GitHubClient",
            return_value=FakeGitHubClient(
                file_details=file_details,
                contents={("head", "helper.c"): head_content},
            ),
        ),
        patch("nodes.construct_task.run_file_in_container", side_effect=fake_run_file_in_container),
    ):
        result = await construct_task(_base_state())

    assert result["errors"][0]["reason"] == "no_interop_signal"


@pytest.mark.asyncio
async def test_construct_task_returns_mask_ineffective_when_masked_file_keeps_baseline():
    head_content = """static PyObject* solve(PyObject *self, PyObject *args) {
    if (!PyArg_ParseTuple(args, "O", &args)) {
        return NULL;
    }
    return Py_BuildValue("i", 1);
}"""
    file_details = [
        {
            "path": "pycosat.c",
            "lang": "C",
            "is_test": False,
            "additions": 6,
            "deletions": 1,
            "status": "modified",
            "patch": '@@ -1,4 +1,4 @@\n if (!PyArg_ParseTuple(args, "O", &args)) {\n',
        }
    ]

    async def fake_run_file_in_container(**kwargs):
        return {
            "passed": 5,
            "failed": 0,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 0,
            "stdout_tail": "still passes",
        }

    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch(
            "nodes.construct_task.GitHubClient",
            return_value=FakeGitHubClient(
                file_details=file_details,
                contents={("head", "pycosat.c"): head_content},
            ),
        ),
        patch("nodes.construct_task._build_attempt_ranges", return_value=[(2, 4)]),
        patch("nodes.construct_task.run_file_in_container", side_effect=fake_run_file_in_container),
    ):
        result = await construct_task(_base_state())

    assert result["errors"][0]["reason"] == "mask_ineffective"


@pytest.mark.asyncio
async def test_construct_task_returns_mask_breaks_compilation_after_retries():
    head_content = """static PyObject* solve(PyObject *self, PyObject *args) {
    if (!PyArg_ParseTuple(args, "O", &args)) {
        return NULL;
    }
    return Py_BuildValue("i", 1);
}"""
    file_details = [
        {
            "path": "pycosat.c",
            "lang": "C",
            "is_test": False,
            "additions": 6,
            "deletions": 1,
            "status": "modified",
            "patch": '@@ -1,4 +1,4 @@\n if (!PyArg_ParseTuple(args, "O", &args)) {\n',
        }
    ]

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

    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch(
            "nodes.construct_task.GitHubClient",
            return_value=FakeGitHubClient(
                file_details=file_details,
                contents={("head", "pycosat.c"): head_content},
            ),
        ),
        patch("nodes.construct_task._build_attempt_ranges", return_value=[(2, 4)]),
        patch("nodes.construct_task.run_file_in_container", side_effect=fake_run_file_in_container),
    ):
        result = await construct_task(_base_state())

    assert result["errors"][0]["reason"] == "mask_breaks_compilation"


@pytest.mark.asyncio
async def test_construct_task_returns_ground_truth_invalid_when_restore_mismatches():
    head_content = """static PyObject* solve(PyObject *self, PyObject *args) {
    if (!PyArg_ParseTuple(args, "O", &args)) {
        return NULL;
    }
    return Py_BuildValue("i", 1);
}"""
    file_details = [
        {
            "path": "pycosat.c",
            "lang": "C",
            "is_test": False,
            "additions": 6,
            "deletions": 1,
            "status": "modified",
            "patch": '@@ -1,4 +1,4 @@\n if (!PyArg_ParseTuple(args, "O", &args)) {\n',
        }
    ]
    results = [
        {
            "passed": 0,
            "failed": 5,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "masked",
        },
        {
            "passed": 4,
            "failed": 1,
            "errors": 0,
            "total": 5,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "restore mismatch",
        },
    ]

    async def fake_run_file_in_container(**kwargs):
        return results.pop(0)

    with (
        patch("nodes.construct_task.get_github_tokens_from_env", return_value=["token"]),
        patch(
            "nodes.construct_task.GitHubClient",
            return_value=FakeGitHubClient(
                file_details=file_details,
                contents={("head", "pycosat.c"): head_content},
            ),
        ),
        patch("nodes.construct_task._build_attempt_ranges", return_value=[(2, 4)]),
        patch("nodes.construct_task.run_file_in_container", side_effect=fake_run_file_in_container),
    ):
        result = await construct_task(_base_state())

    assert result["errors"][0]["reason"] == "ground_truth_invalid"
