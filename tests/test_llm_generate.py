from __future__ import annotations

from unittest.mock import patch

import pytest

from nodes.llm_generate import extract_generated_code, llm_generate


def _state() -> dict:
    return {
        "pr": {"repo": "conda/pycosat", "pr_id": 4},
        "task": {
            "host_lang": "C",
            "target_lang": "Python",
            "masked_code": "int f() {\n    <MASK>\n}\n",
            "context_files": {"test.py": "assert True\n"},
        },
        "run_config": {"target_llm": "claude-sonnet-4-20250514"},
    }


def test_extract_generated_code_prefers_fenced_block():
    text = "hello\n```c\nreturn 0;\n```\nbye"
    assert extract_generated_code(text) == "return 0;"


def test_extract_generated_code_falls_back_to_raw_text():
    assert extract_generated_code("return NULL;\n") == "return NULL;"


@pytest.mark.asyncio
async def test_llm_generate_returns_generated_code_and_token_count():
    with patch(
        "nodes.llm_generate.call_anthropic",
        return_value=("```c\nreturn NULL;\n```", 123),
    ):
        result = await llm_generate(_state())

    assert result["generated_code"] == "return NULL;"
    assert result["llm_tokens_used"] == 123


@pytest.mark.asyncio
async def test_llm_generate_returns_empty_generation_error():
    with patch("nodes.llm_generate.call_anthropic", return_value=("", 11)):
        result = await llm_generate(_state())

    assert result["errors"][0]["reason"] == "empty_generation"


@pytest.mark.asyncio
async def test_llm_generate_returns_timeout_error():
    with patch("nodes.llm_generate.call_anthropic", side_effect=TimeoutError("slow")):
        result = await llm_generate(_state())

    assert result["errors"][0]["reason"] == "llm_timeout"
