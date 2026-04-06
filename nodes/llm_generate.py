from __future__ import annotations

import re
from typing import Any

from nodes.llm_utils import call_anthropic, load_api_key
from nodes.stage2_utils import make_error


FENCED_CODE_RE = re.compile(r"```[\w+-]*\n(?P<code>.*?)```", re.DOTALL)


def get_target_llm_api_key() -> str:
    return load_api_key("TARGET_LLM_API_KEY")


def extract_generated_code(text: str) -> str:
    match = FENCED_CODE_RE.search(text or "")
    if match:
        return match.group("code").strip()
    return (text or "").strip()


def _normalize_response(payload: Any) -> tuple[str, int]:
    if isinstance(payload, tuple) and len(payload) == 2:
        return str(payload[0]), int(payload[1] or 0)

    if isinstance(payload, dict):
        parts: list[str] = []
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        usage = payload.get("usage") or {}
        token_count = int(usage.get("input_tokens", 0) or 0) + int(
            usage.get("output_tokens", 0) or 0
        )
        return "\n".join(parts).strip(), token_count

    return str(payload or ""), 0


async def llm_generate(state: dict[str, Any]) -> dict[str, Any]:
    pr = state["pr"]
    task = state.get("task")
    if not task:
        return {
            "generated_code": "",
            "errors": [
                make_error(
                    pr,
                    stage="llm_generate",
                    reason="task_missing",
                    message="llm_generate requires a constructed BenchmarkTask.",
                )
            ],
        }

    system_prompt = (
        f"You are an expert in {task['host_lang']} and {task['target_lang']} interop programming. "
        "Complete the <MASK> section. Return only the replacement code, with no explanation."
    )
    target_model = state["run_config"].get("target_llm", "claude-sonnet-4-20250514")
    if target_model in {"mock-ground-truth", "ground-truth"}:
        return {
            "generated_code": task.get("ground_truth", "").strip(),
            "llm_tokens_used": 0,
        }

    context_parts: list[str] = []
    for path, content in (task.get("context_files") or {}).items():
        context_parts.append(f"### {path}\n```\n{content}\n```")
    user_prompt = (
        "## Context Files\n"
        + ("\n\n".join(context_parts) if context_parts else "(none)")
        + f"\n\n## File To Complete\n```{str(task['host_lang']).lower()}\n{task['masked_code']}\n```\n\n"
        "Return only the code that should replace <MASK>."
    )

    try:
        raw_response = await call_anthropic(
            model=target_model,
            api_key=get_target_llm_api_key(),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=2048,
            temperature=0.0,
            timeout=60,
        )
        response_text, token_count = _normalize_response(raw_response)
    except TimeoutError:
        return {
            "generated_code": "",
            "llm_tokens_used": 0,
            "errors": [
                make_error(
                    pr,
                    stage="llm_generate",
                    reason="llm_timeout",
                    message="Target LLM request timed out.",
                )
            ],
        }
    except Exception as exc:
        return {
            "generated_code": "",
            "llm_tokens_used": 0,
            "errors": [
                make_error(
                    pr,
                    stage="llm_generate",
                    reason="llm_timeout",
                    message=str(exc),
                )
            ],
        }

    generated_code = extract_generated_code(response_text)
    if not generated_code:
        return {
            "generated_code": "",
            "llm_tokens_used": token_count,
            "errors": [
                make_error(
                    pr,
                    stage="llm_generate",
                    reason="empty_generation",
                    message="Target LLM returned an empty code snippet.",
                )
            ],
        }

    return {
        "generated_code": generated_code,
        "llm_tokens_used": token_count,
    }
