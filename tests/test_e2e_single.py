import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main
from github_client import load_project_env


def _has_required_env() -> bool:
    load_project_env()
    return bool(os.environ.get("GITHUB_TOKEN_1"))


@pytest.mark.docker
@pytest.mark.integration
@pytest.mark.skipif(not _has_required_env(), reason="GitHub/LLM credentials not configured")
def test_single_pr_image_reuse_pycosat_smoke(tmp_path):
    runnable = json.loads(Path("output/runnable_baseline_10.json").read_text(encoding="utf-8"))
    pr = next(item for item in runnable if item["repo"] == "conda/pycosat" and item["pr_id"] == 4)
    pr_path = tmp_path / "pycosat_pr.json"
    pr_path.write_text(json.dumps(pr), encoding="utf-8")

    result = main.run_single_pr(
        Namespace(
            pr_json=str(pr_path),
            db="benchmark_runs.db",
            thread_id="smoke-pycosat-stage3",
            stage2_only=False,
            image_tag="benchmark-conda-pycosat-pr4:latest",
            target_llm="mock-ground-truth",
            judge_llm="disabled",
            task_strategy="completion",
            excluded_prs=None,
        )
    )

    benchmark_items = result.get("benchmark_items") or []
    assert benchmark_items
