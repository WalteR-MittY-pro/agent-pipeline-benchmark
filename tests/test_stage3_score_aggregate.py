import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes import aggregate as aggregate_module
from nodes import score as score_module


@pytest.mark.asyncio
async def test_score_uses_judge_response(monkeypatch):
    async def fake_quality(pr, generated_code, model):
        return 75.0, '{"memory": 75, "error_handling": 75, "style": 75}'

    async def fake_judge_quality(*args, **kwargs):
        return await fake_quality(None, None, None)

    monkeypatch.setattr(score_module, "_judge_quality", fake_judge_quality)
    result = await score_module.score(
        {
            "pr": {"repo": "owner/repo", "pr_id": 1, "interop_type": "cgo"},
            "task": {"task_id": "cgo-owner-repo-pr1-001"},
            "generated_code": "code",
            "test_result": {"compile_success": True, "total": 4, "passed": 3},
            "image_tag": "benchmark/test:latest",
            "run_config": {"judge_llm": "claude-sonnet-4-20250514"},
        }
    )
    item = result["benchmark_items"][0]
    assert round(item["score_total"], 2) == 80.0


@pytest.mark.asyncio
async def test_score_quality_falls_back(monkeypatch):
    monkeypatch.setattr(
        score_module,
        "call_anthropic",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("judge failed")),
    )
    monkeypatch.setattr(score_module, "load_api_key", lambda name, fallback=None: "key")
    score_value, notes = await score_module._judge_quality(
        interop_type="cgo",
        generated_code="code",
        model="claude-sonnet-4-20250514",
    )
    assert score_value == 50.0
    assert "judge failed" in notes


def test_aggregate_filters_dedups_and_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    item_good = {
        "id": "task-1",
        "pr_metadata": {"repo": "owner/repo", "interop_type": "cgo", "interop_layer": "ffi"},
        "task": {"difficulty": "medium", "ground_truth": "code"},
        "docker_image": "benchmark/test:latest",
        "generated_code": "answer",
        "test_result": {"total": 4},
        "score_total": 88.0,
        "score_test": 100.0,
        "score_compile": 100.0,
        "score_quality": 40.0,
        "quality_notes": "ok",
        "created_at": "2026-01-01T00:00:00Z",
    }
    item_dup = dict(item_good)
    item_dup["score_total"] = 50.0
    item_bad = dict(item_good)
    item_bad["id"] = "task-2"
    item_bad["generated_code"] = ""

    result = aggregate_module.aggregate_results(
        {
            "run_config": {"per_repo_cap": None},
            "benchmark_items": [item_good, item_dup, item_bad],
            "errors": [{"reason": "mask_ineffective"}],
            "prs": [{"repo": "owner/repo"}],
        }
    )
    assert len(result["benchmark_items"]) == 1
    dataset = json.loads(Path("output/benchmark_dataset.json").read_text(encoding="utf-8"))
    assert len(dataset) == 1
    assert Path("output/summary_report.md").exists()
