import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import graph
import main


FIXTURES = Path(__file__).parent / "fixtures"


def _load_pr(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_route_after_compile_enters_construct_task():
    assert graph.route_after_compile(
        {"compile_status": "success", "compile_repair_rounds": 0, "run_config": {}},
        stage2_only=False,
    ) == "construct_task"


def test_run_single_pr_passes_image_tag_to_payload(tmp_path):
    pr_path = tmp_path / "pr.json"
    pr = _load_pr("sample_pr_python_cext.json")
    pr_path.write_text(json.dumps(pr), encoding="utf-8")

    class FakeApp:
        def __init__(self):
            self.last_payload = None

        async def ainvoke(self, payload, config=None):
            self.last_payload = payload
            return {**payload, "errors": []}

    fake_app = FakeApp()
    args = Namespace(
        pr_json=str(pr_path),
        db=":memory:",
        thread_id="single-pr-image-test",
        stage2_only=False,
        image_tag="benchmark-conda-pycosat-pr4:latest",
        target_llm=None,
        judge_llm=None,
        task_strategy=None,
        excluded_prs=None,
    )
    with patch("graph.build_pr_subgraph", return_value=fake_app):
        main.run_single_pr(args)

    assert fake_app.last_payload["image_tag"] == "benchmark-conda-pycosat-pr4:latest"


def test_run_build_uses_image_manifest_and_aggregates(tmp_path):
    input_path = tmp_path / "prs.json"
    output_path = tmp_path / "results.jsonl"
    manifest_path = tmp_path / "manifest.json"
    pr = _load_pr("sample_pr_python_cext.json")
    input_path.write_text(json.dumps([pr]), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "repo": pr["repo"],
                    "pr_id": pr["pr_id"],
                    "image_tag": "benchmark-conda-pycosat-pr4:latest",
                }
            ]
        ),
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
                "task": {"task_id": "python_cext-example-python-cext-demo-pr102-001"},
                "generated_code": "answer",
                "test_result": {"passed": 1, "failed": 0, "errors": 0, "total": 1, "compile_success": True, "exit_code": 0, "stdout_tail": "ok"},
                "benchmark_items": [
                    {
                        "id": "python_cext-example-python-cext-demo-pr102-001",
                        "pr_metadata": pr,
                        "task": {"difficulty": "easy", "ground_truth": "gt"},
                        "docker_image": payload["image_tag"],
                        "generated_code": "answer",
                        "test_result": {"total": 1},
                        "score_total": 100.0,
                        "score_test": 100.0,
                        "score_compile": 100.0,
                        "score_quality": 100.0,
                        "quality_notes": "ok",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "errors": [],
            }

    with (
        patch("graph.build_pr_subgraph", return_value=FakeApp()),
        patch("nodes.aggregate.aggregate_results", return_value={"benchmark_items": []}) as aggregate_mock,
    ):
        summaries = main.run_build(
            Namespace(
                input=str(input_path),
                output=str(output_path),
                db=":memory:",
                thread_id="build-image-test",
                excluded_prs=None,
                stage2_only=False,
                image_manifest=str(manifest_path),
                target_llm=None,
                judge_llm=None,
                task_strategy=None,
            )
        )

    assert summaries[0]["image_tag"] == "benchmark-conda-pycosat-pr4:latest"
    assert aggregate_mock.called
