from __future__ import annotations

import json
from pathlib import Path

from nodes.aggregate import aggregate_results


def test_aggregate_filters_dedups_and_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    items = [
        {
            "id": "task-1",
            "pr_metadata": {"repo": "a/b", "interop_layer": "ffi", "interop_type": "cgo"},
            "task": {"difficulty": "easy", "ground_truth": "ok"},
            "docker_image": "img",
            "generated_code": "code",
            "test_result": {"total": 1},
            "score_total": 80.0,
            "score_test": 80.0,
            "score_compile": 100.0,
            "score_quality": 60.0,
            "quality_notes": "ok",
            "created_at": "now",
        },
        {
            "id": "task-1",
            "pr_metadata": {"repo": "a/b", "interop_layer": "ffi", "interop_type": "cgo"},
            "task": {"difficulty": "easy", "ground_truth": "ok"},
            "docker_image": "img",
            "generated_code": "better",
            "test_result": {"total": 1},
            "score_total": 85.0,
            "score_test": 85.0,
            "score_compile": 100.0,
            "score_quality": 70.0,
            "quality_notes": "ok",
            "created_at": "now",
        },
        {
            "id": "task-2",
            "pr_metadata": {"repo": "x/y", "interop_layer": "wasm", "interop_type": "wasm"},
            "task": {"difficulty": "hard", "ground_truth": ""},
            "docker_image": "img",
            "generated_code": "",
            "test_result": {"total": 0},
            "score_total": 10.0,
            "score_test": 0.0,
            "score_compile": 0.0,
            "score_quality": 50.0,
            "quality_notes": "bad",
            "created_at": "now",
        },
    ]
    result = aggregate_results(
        {
            "benchmark_items": items,
            "errors": [{"stage": "construct_task"}],
            "prs": [],
            "run_config": {},
        }
    )

    assert len(result["benchmark_items"]) == 1
    dataset = json.loads(Path("output/benchmark_dataset.json").read_text())
    assert dataset[0]["generated_code"] == "better"
    assert Path("output/summary_report.md").exists()
