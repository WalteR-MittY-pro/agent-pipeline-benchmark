from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from nodes.llm_utils import call_anthropic, load_api_key
from nodes.stage2_utils import make_error


def _normalize_response(payload: Any) -> str:
    if isinstance(payload, tuple) and payload:
        return str(payload[0])
    if isinstance(payload, dict):
        parts: list[str] = []
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        return "\n".join(parts).strip()
    return str(payload or "")


async def _judge_quality(
    generated_code: str,
    model: str,
    *,
    pr: dict[str, Any] | None = None,
    interop_type: str | None = None,
) -> tuple[float, str]:
    if model in {"disabled", "mock-neutral", "mock-neutral-judge"}:
        return 50.0, "Judge disabled for local smoke."

    resolved_interop_type = interop_type or (pr or {}).get("interop_type", "unknown")
    prompt = (
        f"Evaluate the following {resolved_interop_type} cross-language glue code. "
        "Return JSON only in the shape "
        '{"memory": int, "error_handling": int, "style": int, "notes": str}.\n\n'
        f"Code:\n```text\n{generated_code}\n```"
    )
    try:
        raw_response = await call_anthropic(
            model=model,
            api_key=load_api_key("JUDGE_LLM_API_KEY", fallback="TARGET_LLM_API_KEY"),
            system_prompt="You are a strict code quality judge. Return JSON only.",
            user_prompt=prompt,
            max_tokens=512,
            temperature=0.0,
            timeout=60,
        )
        text = _normalize_response(raw_response)
        payload = json.loads(text)
        memory = float(payload["memory"])
        error_handling = float(payload["error_handling"])
        style = float(payload["style"])
        return (memory + error_handling + style) / 3.0, payload.get("notes", text)
    except Exception as exc:
        return 50.0, f"Judge fallback applied: {exc}"


async def score(state: dict[str, Any]) -> dict[str, Any]:
    pr = state["pr"]
    task = state.get("task")
    test_result = state.get("test_result") or {}
    generated_code = state.get("generated_code") or ""
    if not task or not test_result:
        return {
            "benchmark_items": [],
            "errors": [
                make_error(
                    pr,
                    stage="score",
                    reason="task_missing",
                    message="score requires task and test_result.",
                )
            ],
        }

    score_compile = 100.0 if test_result.get("compile_success") else 0.0
    total = int(test_result.get("total", -1) or -1)
    passed = int(test_result.get("passed", 0) or 0)
    score_test = 0.0 if total <= 0 else (passed / total) * 100.0

    try:
        score_quality, quality_notes = await _judge_quality(
            generated_code=generated_code,
            model=state["run_config"].get("judge_llm", "claude-sonnet-4-20250514"),
            pr=pr,
        )
    except Exception as exc:
        score_quality, quality_notes = 50.0, f"Judge fallback applied: {exc}"

    score_total = score_test * 0.6 + score_compile * 0.2 + score_quality * 0.2
    item = {
        "id": task["task_id"],
        "pr_metadata": pr,
        "task": task,
        "docker_image": state.get("image_tag"),
        "generated_code": generated_code,
        "test_result": test_result,
        "score_total": score_total,
        "score_test": score_test,
        "score_compile": score_compile,
        "score_quality": score_quality,
        "quality_notes": quality_notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"benchmark_items": [item]}
