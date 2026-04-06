from __future__ import annotations

from unittest.mock import patch

import pytest

from nodes.score import score


def _state() -> dict:
    return {
        "pr": {"repo": "conda/pycosat", "pr_id": 4, "interop_type": "python_cext"},
        "task": {"task_id": "python-cext-conda-pycosat-pr4-001"},
        "generated_code": "return NULL;",
        "test_result": {
            "passed": 3,
            "failed": 1,
            "errors": 0,
            "total": 4,
            "compile_success": True,
            "exit_code": 1,
            "stdout_tail": "failed",
        },
        "image_tag": "benchmark-conda-pycosat-pr4:latest",
        "run_config": {"judge_llm": "claude-sonnet-4-20250514"},
    }


@pytest.mark.asyncio
async def test_score_computes_formula():
    with patch("nodes.score._judge_quality", return_value=(90.0, "good")):
        result = await score(_state())

    item = result["benchmark_items"][0]
    assert item["score_compile"] == 100.0
    assert item["score_test"] == 75.0
    assert item["score_quality"] == 90.0
    assert round(item["score_total"], 2) == 83.0


@pytest.mark.asyncio
async def test_score_falls_back_to_neutral_quality_on_judge_failure():
    with patch("nodes.score._judge_quality", side_effect=RuntimeError("judge down")):
        result = await score(_state())

    assert result["benchmark_items"][0]["score_quality"] == 50.0
