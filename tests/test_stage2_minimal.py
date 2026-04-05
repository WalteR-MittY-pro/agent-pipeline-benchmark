import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import pytest

from langgraph.constants import END

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main
import graph
from graph import route_after_build, route_after_compile, route_after_dockerfile
from nodes.build_dockerfile import build_dockerfile
from nodes.infer_env import extract_run_steps, infer_env


FIXTURES = Path(__file__).parent / "fixtures"


class FakeGitHubClient:
    def __init__(self, tree=None, contents=None):
        self._tree = tree or []
        self._contents = contents or {}

    def get_repo_tree(self, repo_full_name, sha):
        return list(self._tree)

    def get_file_content(self, repo_full_name, sha, file_path):
        return self._contents.get(file_path, "")


def _load_pr(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_infer_env_uses_repo_dockerfile_layer():
    pr = _load_pr("sample_pr_cgo.json")
    fake_client = FakeGitHubClient(
        tree=["Dockerfile", "go.mod"],
        contents={
            "Dockerfile": "FROM golang:1.22\nCMD [\"go\", \"test\", \"./...\"]\n",
            "go.mod": "module example.com/demo\n",
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    env_spec = result["env_spec"]
    assert env_spec["source"] == "repo_dockerfile"
    assert env_spec["test_framework"] == "go_test"
    assert "go test -json ./..." in env_spec["dockerfile_content"]


def test_infer_env_falls_back_to_failed_when_no_signal_exists():
    pr = _load_pr("sample_pr_wasm.json")
    pr["interop_type"] = "unknown_interop"
    fake_client = FakeGitHubClient(tree=[], contents={})

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    assert result["env_spec"]["source"] == "failed"
    assert result["errors"][0]["reason"] == "infer_env_failed"


def test_infer_env_python_cext_bootstraps_pytest_and_python_deps():
    pr = _load_pr("sample_pr_python_cext.json")
    fake_client = FakeGitHubClient(
        tree=["setup.py", "requirements.txt", "pyBigWigTest/test.py"],
        contents={
            "setup.py": "from setuptools import setup\n",
            "requirements.txt": "numpy\npytest\n",
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    env_spec = result["env_spec"]
    assert env_spec["source"] == "llm"
    assert any("pytest" in cmd for cmd in env_spec["build_cmds"])
    assert "PYTHONPATH=/app pytest -q pyBigWigTest/test.py" in env_spec["test_cmds"]


def test_infer_env_python_root_test_file_uses_exact_target():
    pr = _load_pr("sample_pr_python_cext.json")
    fake_client = FakeGitHubClient(
        tree=["setup.py", "test_pycosat.py"],
        contents={
            "setup.py": "from setuptools import setup\n",
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    assert "PYTHONPATH=/app pytest -q test_pycosat.py" in result["env_spec"]["test_cmds"]


def test_extract_run_steps_prunes_workflow_noise_and_keeps_relevant_lines():
    workflow = """
    - name: Linux
      run: |
        sudo apt install tinyproxy
        LIBSSH2_VERSION=1.11.1 LIBGIT2_VERSION=1.9.1 /bin/sh build.sh test
        git config user.name bot
        git push origin branch
    """
    commands = extract_run_steps(workflow, "test")
    assert commands == ["LIBSSH2_VERSION=1.11.1 LIBGIT2_VERSION=1.9.1 /bin/sh build.sh test"]


def test_extract_run_steps_prunes_macos_only_support_lines():
    workflow = """
    - name: macOS
      run: |
        export OPENSSL_PREFIX=`brew --prefix openssl@3`
        LIBSSH2_VERSION=1.11.1 LIBGIT2_VERSION=1.9.1 /bin/sh build.sh test
    """
    commands = extract_run_steps(workflow, "test")
    assert commands == ["LIBSSH2_VERSION=1.11.1 LIBGIT2_VERSION=1.9.1 /bin/sh build.sh test"]


def test_extract_run_steps_keeps_git_submodule_support_for_build_blocks():
    workflow = """
    - name: Build static
      run: |
        git submodule update --init
        sudo apt-get install -y --no-install-recommends libssh2-1-dev
        make build-libgit2-static
        git push origin branch
    """
    commands = extract_run_steps(workflow, "build")
    assert commands == [
        "git submodule update --init\nsudo apt-get install -y --no-install-recommends libssh2-1-dev\nmake build-libgit2-static"
    ]


def test_infer_env_normalizes_python_command_and_adds_python_dep():
    pr = _load_pr("sample_pr_cgo.json")
    fake_client = FakeGitHubClient(
        tree=[".github/workflows/ci.yml"],
        contents={
            ".github/workflows/ci.yml": """
name: CI
jobs:
  build:
    steps:
      - run: python ci/download-wasmtime.py
      - run: go test
"""
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    env_spec = result["env_spec"]
    assert "python3 ci/download-wasmtime.py" in env_spec["build_cmds"]
    assert "python3" in env_spec["system_deps"]


def test_infer_env_uses_go_mod_version_for_cgo_base_image():
    pr = _load_pr("sample_pr_cgo.json")
    fake_client = FakeGitHubClient(
        tree=[".github/workflows/ci.yml", "go.mod"],
        contents={
            ".github/workflows/ci.yml": """
name: CI
jobs:
  build:
    steps:
      - run: go build
      - run: go test
""",
            "go.mod": "module example.com/demo\n\ngo 1.26.0\n",
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    assert result["env_spec"]["base_image"] == "golang:1.26"


def test_infer_env_skips_repo_dockerfile_with_unresolved_stage_aliases():
    pr = _load_pr("sample_pr_cgo.json")
    fake_client = FakeGitHubClient(
        tree=["Dockerfile", ".github/workflows/ci.yml", "go.mod"],
        contents={
            "Dockerfile": "FROM php-base AS common\nCOPY --from=golang-base /usr/local/go /usr/local/go\n",
            ".github/workflows/ci.yml": """
name: CI
jobs:
  build:
    steps:
      - run: python ci/download-wasmtime.py
      - run: go test
""",
            "go.mod": "module example.com/demo\n",
        },
    )

    with (
        patch("nodes.infer_env.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.infer_env.GitHubClient", return_value=fake_client),
    ):
        result = infer_env({"pr": pr, "run_config": {"db_path": ":memory:"}})

    env_spec = result["env_spec"]
    assert env_spec["source"] == "github_actions"
    assert env_spec["dockerfile_content"] is None


def test_build_dockerfile_renders_template_for_non_repo_dockerfile(tmp_path):
    pr = _load_pr("sample_pr_python_cext.json")
    state = {
        "pr": pr,
        "env_spec": {
            "source": "llm",
            "base_image": "python:3.11",
            "system_deps": ["git", "build-essential"],
            "build_cmds": ["python3 setup.py build_ext --inplace"],
            "test_cmds": ["pytest -q"],
            "test_framework": "pytest",
            "dockerfile_content": None,
        },
    }

    result = build_dockerfile(state)
    dockerfile_path = Path(result["dockerfile_path"])
    assert dockerfile_path.exists()
    assert "FROM python:3.11" in result["dockerfile_content"]
    assert result["image_tag"].startswith("benchmark-example-python-cext-demo-pr")


def test_route_after_build_handles_success_retry_and_end():
    assert route_after_build(
        {
            "env_spec": {"source": "github_actions"},
            "build_status": "success",
            "build_retries": 0,
            "dockerfile_path": "/tmp/Dockerfile",
        }
    ) == "compile_verify"
    assert route_after_build(
        {
            "env_spec": {"source": "github_actions"},
            "build_status": "failed",
            "build_retries": 1,
            "dockerfile_path": "/tmp/Dockerfile",
        }
    ) == "docker_build"
    assert route_after_build(
        {
            "env_spec": {"source": "failed"},
            "build_status": "failed",
            "build_retries": 0,
            "dockerfile_path": None,
        }
    ) == END


def test_route_after_dockerfile_skips_failed_env_specs():
    assert route_after_dockerfile(
        {
            "env_spec": {"source": "failed"},
            "dockerfile_path": None,
        }
    ) == END
    assert route_after_dockerfile(
        {
            "env_spec": {"source": "llm"},
            "dockerfile_path": "/tmp/Dockerfile",
        }
    ) == "docker_build"


def test_route_after_compile_respects_stage2_only_and_repair_flag():
    assert route_after_compile(
        {"compile_status": "success", "compile_repair_rounds": 0, "run_config": {}},
        stage2_only=True,
    ) == END
    assert route_after_compile(
        {
            "compile_status": "retryable",
            "compile_repair_rounds": 1,
            "run_config": {"enable_compile_repair": True},
        },
        stage2_only=True,
    ) == "compile_verify"


def test_run_single_pr_invokes_pr_subgraph_with_fixture(tmp_path):
    pr_path = tmp_path / "pr.json"
    pr = _load_pr("sample_pr_cgo.json")
    pr_path.write_text(json.dumps(pr), encoding="utf-8")

    class FakeApp:
        def __init__(self):
            self.last_payload = None
            self.last_config = None

        async def ainvoke(self, payload, config=None):
            self.last_payload = payload
            self.last_config = config
            return {
                **payload,
                "compile_status": "success",
                "baseline_test_result": {
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "total": 1,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "ok",
                },
                "errors": [],
            }

    fake_app = FakeApp()
    args = Namespace(
        pr_json=str(pr_path),
        db=":memory:",
        thread_id="single-pr-test",
    )

    with patch("graph.build_pr_subgraph", return_value=fake_app):
        result = main.run_single_pr(args)

    assert fake_app.last_payload["pr"]["repo"] == pr["repo"]
    assert fake_app.last_config["configurable"]["thread_id"] == "single-pr-test"
    assert result["compile_status"] == "success"


def test_run_single_pr_rejects_excluded_pr(tmp_path):
    pr_path = tmp_path / "pr.json"
    excluded_path = tmp_path / "excluded_prs.json"
    pr = _load_pr("sample_pr_cgo.json")
    pr_path.write_text(json.dumps(pr), encoding="utf-8")
    excluded_path.write_text(
        json.dumps([{"repo": pr["repo"], "pr_id": pr["pr_id"]}]), encoding="utf-8"
    )

    args = Namespace(
        pr_json=str(pr_path),
        db=":memory:",
        thread_id="single-pr-test",
        excluded_prs=str(excluded_path),
    )

    with pytest.raises(SystemExit, match="marked excluded"):
        main.run_single_pr(args)


def test_run_build_writes_jsonl_summaries(tmp_path):
    input_path = tmp_path / "prs.json"
    output_path = tmp_path / "stage2_results.jsonl"
    input_path.write_text(
        json.dumps([_load_pr("sample_pr_cgo.json"), _load_pr("sample_pr_python_cext.json")]),
        encoding="utf-8",
    )

    class FakeApp:
        async def ainvoke(self, payload, config=None):
            return {
                **payload,
                "compile_status": "success",
                "baseline_test_result": {
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "total": 1,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "ok",
                },
                "errors": [],
            }

    args = Namespace(
        input=str(input_path),
        output=str(output_path),
        db=":memory:",
        thread_id="build-test",
    )

    with patch("graph.build_pr_subgraph", return_value=FakeApp()):
        summaries = main.run_build(args)

    assert len(summaries) == 2
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["coarse_status"] == "baseline_test_passed"


def test_run_build_skips_excluded_prs(tmp_path):
    input_path = tmp_path / "prs.json"
    output_path = tmp_path / "stage2_results.jsonl"
    excluded_path = tmp_path / "excluded_prs.json"
    pr1 = _load_pr("sample_pr_cgo.json")
    pr2 = _load_pr("sample_pr_python_cext.json")
    input_path.write_text(json.dumps([pr1, pr2]), encoding="utf-8")
    excluded_path.write_text(
        json.dumps([{"repo": pr1["repo"], "pr_id": pr1["pr_id"]}]), encoding="utf-8"
    )

    class FakeApp:
        async def ainvoke(self, payload, config=None):
            return {
                **payload,
                "compile_status": "success",
                "baseline_test_result": {
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "total": 1,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "ok",
                },
                "errors": [],
            }

    args = Namespace(
        input=str(input_path),
        output=str(output_path),
        db=":memory:",
        thread_id="build-test",
        excluded_prs=str(excluded_path),
    )

    with patch("graph.build_pr_subgraph", return_value=FakeApp()):
        summaries = main.run_build(args)

    assert len(summaries) == 1
    assert summaries[0]["pr"]["pr_id"] == pr2["pr_id"]


def test_run_build_resolves_summary_records_to_full_metadata(tmp_path, monkeypatch):
    input_path = tmp_path / "runnable.json"
    output_path = tmp_path / "stage2_results.jsonl"
    snapshot_path = tmp_path / "prs_snapshot.json"
    full_pr = _load_pr("sample_pr_cgo.json")
    summary_pr = {
        "repo": full_pr["repo"],
        "pr_id": full_pr["pr_id"],
        "interop_type": full_pr["interop_type"],
        "status": "baseline_passed",
    }
    input_path.write_text(json.dumps([summary_pr]), encoding="utf-8")
    snapshot_path.write_text(json.dumps([full_pr]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    class FakeApp:
        async def ainvoke(self, payload, config=None):
            return {
                **payload,
                "compile_status": "success",
                "baseline_test_result": {
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "total": 1,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "ok",
                },
                "errors": [],
            }

    args = Namespace(
        input=str(input_path),
        output=str(output_path),
        db=":memory:",
        thread_id="build-test",
    )

    with patch("graph.build_pr_subgraph", return_value=FakeApp()):
        summaries = main.run_build(args)

    assert summaries[0]["pr"]["head_sha"] == full_pr["head_sha"]


def test_run_single_pr_resolves_summary_record_to_full_metadata(tmp_path, monkeypatch):
    pr_path = tmp_path / "pr.json"
    snapshot_path = tmp_path / "prs_snapshot.json"
    full_pr = _load_pr("sample_pr_cgo.json")
    summary_pr = {
        "repo": full_pr["repo"],
        "pr_id": full_pr["pr_id"],
        "interop_type": full_pr["interop_type"],
        "status": "baseline_passed",
    }
    pr_path.write_text(json.dumps(summary_pr), encoding="utf-8")
    snapshot_path.write_text(json.dumps([full_pr]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    class FakeApp:
        def __init__(self):
            self.last_payload = None

        async def ainvoke(self, payload, config=None):
            self.last_payload = payload
            return {
                **payload,
                "compile_status": "success",
                "baseline_test_result": {
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "total": 1,
                    "compile_success": True,
                    "exit_code": 0,
                    "stdout_tail": "ok",
                },
                "errors": [],
            }

    fake_app = FakeApp()
    args = Namespace(
        pr_json=str(pr_path),
        db=":memory:",
        thread_id="single-pr-test",
    )

    with patch("graph.build_pr_subgraph", return_value=fake_app):
        main.run_single_pr(args)

    assert fake_app.last_payload["pr"]["head_sha"] == full_pr["head_sha"]


def test_real_build_pr_subgraph_preserves_errors_and_short_circuits_failed_env():
    pr = _load_pr("sample_pr_cgo.json")

    def fake_infer_env(state):
        return {
            "env_spec": {
                "source": "failed",
                "base_image": "golang:1.22",
                "system_deps": [],
                "build_cmds": [],
                "test_cmds": [],
                "test_framework": "generic",
                "dockerfile_content": None,
            },
            "build_status": "failed",
            "errors": [
                {
                    "pr_id": pr["pr_id"],
                    "repo": pr["repo"],
                    "stage": "infer_env",
                    "reason": "infer_env_failed",
                    "message": "no viable environment",
                }
            ],
        }

    with patch.object(graph, "infer_env", fake_infer_env):
        app = graph.build_pr_subgraph(db_path=":memory:", stage2_only=True)
        result = app.invoke(
            main.make_initial_pr_state(
                pr,
                {
                    **main.BASE_RUN_CONFIG,
                    "db_path": ":memory:",
                    "enable_compile_repair": False,
                },
            ),
            {"configurable": {"thread_id": "real-pr-subgraph-test"}},
        )

    assert result["errors"][0]["reason"] == "infer_env_failed"
    assert result.get("dockerfile_path") is None
