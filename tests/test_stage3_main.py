from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import main
from graph import route_after_compile


def _pr() -> dict:
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


def test_route_after_compile_enters_construct_task_when_stage3_enabled():
    assert (
        route_after_compile({"compile_status": "success", "run_config": {}}, stage2_only=False)
        == "construct_task"
    )


def test_load_image_manifest_reads_stage2_status_list(tmp_path):
    manifest = tmp_path / "stage2_pr_statuses.json"
    manifest.write_text(
        json.dumps([{"repo": "conda/pycosat", "pr_id": 4, "image_tag": "img:latest"}]),
        encoding="utf-8",
    )
    mapping = main.load_image_manifest(str(manifest))
    assert mapping["conda/pycosat#4"] == "img:latest"


def test_run_single_pr_seeds_reusable_image_tag(tmp_path):
    pr_path = tmp_path / "pr.json"
    pr_path.write_text(json.dumps(_pr()), encoding="utf-8")

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
        excluded_prs=None,
        stage2_only=False,
        image_tag="benchmark-conda-pycosat-pr4:latest",
        task_strategy=None,
        target_llm=None,
        judge_llm=None,
    )

    with patch("graph.build_pr_subgraph", return_value=fake_app):
        main.run_single_pr(args)

    assert fake_app.last_payload["image_tag"] == "benchmark-conda-pycosat-pr4:latest"
    assert fake_app.last_payload["build_status"] == "success"


def test_run_build_uses_image_manifest_and_collects_benchmark_items(tmp_path, monkeypatch):
    input_path = tmp_path / "prs.json"
    input_path.write_text(json.dumps([_pr()]), encoding="utf-8")
    output_path = tmp_path / "stage3_results.jsonl"
    manifest = tmp_path / "stage2_pr_statuses.json"
    manifest.write_text(
        json.dumps([{"repo": "conda/pycosat", "pr_id": 4, "image_tag": "img:latest"}]),
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
                "benchmark_items": [
                    {
                        "id": "task-1",
                        "pr_metadata": payload["pr"],
                        "task": {"difficulty": "easy", "ground_truth": "ok"},
                        "docker_image": payload["image_tag"],
                        "generated_code": "code",
                        "test_result": {"total": 1},
                        "score_total": 99.0,
                        "score_test": 100.0,
                        "score_compile": 100.0,
                        "score_quality": 95.0,
                        "quality_notes": "great",
                        "created_at": "now",
                    }
                ],
                "errors": [],
            }

    args = Namespace(
        input=str(input_path),
        output=str(output_path),
        db=":memory:",
        thread_id="build-test",
        excluded_prs=None,
        stage2_only=False,
        image_manifest=str(manifest),
        task_strategy=None,
        target_llm=None,
        judge_llm=None,
    )

    monkeypatch.chdir(tmp_path)
    with patch("graph.build_pr_subgraph", return_value=FakeApp()):
        summaries = main.run_build(args)

    assert summaries[0]["image_tag"] == "img:latest"
    assert Path("output/benchmark_dataset.json").exists()
