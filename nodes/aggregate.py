from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


LAYER_ORDER = {"ffi": 0, "runtime_embedding": 1, "wasm": 2}
DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def aggregate_results(state: dict[str, Any]) -> dict[str, Any]:
    items = list(state.get("benchmark_items") or [])
    errors = list(state.get("errors") or [])
    run_config = state.get("run_config") or {}

    filtered = [
        item
        for item in items
        if item.get("generated_code")
        and item.get("task", {}).get("ground_truth")
        and item.get("test_result", {}).get("total", 0) != 0
    ]

    deduped: dict[str, dict[str, Any]] = {}
    for item in filtered:
        current = deduped.get(item["id"])
        if current is None or item["score_total"] > current["score_total"]:
            deduped[item["id"]] = item
    filtered = list(deduped.values())

    per_repo_cap = run_config.get("per_repo_cap")
    if per_repo_cap:
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in filtered:
            grouped[item["pr_metadata"]["repo"]].append(item)
        capped: list[dict[str, Any]] = []
        for repo_items in grouped.values():
            capped.extend(
                sorted(repo_items, key=lambda item: item["score_total"], reverse=True)[: int(per_repo_cap)]
            )
        filtered = capped

    filtered.sort(
        key=lambda item: (
            LAYER_ORDER.get(item["pr_metadata"]["interop_layer"], 99),
            item["pr_metadata"]["interop_type"],
            DIFFICULTY_ORDER.get(item["task"]["difficulty"], 99),
            -item["score_total"],
        )
    )

    dataset_path = Path(run_config.get("dataset_output_path", "output/benchmark_dataset.json"))
    _write_json(dataset_path, filtered)

    by_type = Counter(item["pr_metadata"]["interop_type"] for item in filtered)
    by_layer = Counter(item["pr_metadata"]["interop_layer"] for item in filtered)
    by_difficulty = Counter(item["task"]["difficulty"] for item in filtered)
    by_stage = Counter(error.get("stage", "unknown") for error in errors)
    lines = [
        "# Benchmark Summary",
        "",
        f"- final_items: {len(filtered)}",
        f"- total_errors: {len(errors)}",
        "",
        "## By Interop Type",
    ]
    for key, value in sorted(by_type.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Interop Layer"])
    for key, value in sorted(by_layer.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Difficulty"])
    for key, value in sorted(by_difficulty.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Error Stages"])
    for key, value in sorted(by_stage.items()):
        lines.append(f"- {key}: {value}")

    summary_path = Path(run_config.get("summary_output_path", "output/summary_report.md"))
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"benchmark_items": filtered}
