import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes import llm_generate as llm_generate_module


@pytest.mark.asyncio
async def test_llm_generate_extracts_fenced_code(monkeypatch):
    monkeypatch.setattr(llm_generate_module, "load_api_key", lambda name: "key")

    async def fake_call_anthropic(**kwargs):
        return "```python\nreturn 42\n```", 15

    monkeypatch.setattr(llm_generate_module, "call_anthropic", fake_call_anthropic)
    result = await llm_generate_module.llm_generate(
        {
            "pr": {"repo": "example/repo", "pr_id": 1},
            "task": {"host_lang": "Python", "target_lang": "C", "masked_code": "def f():\n    <MASK>\n", "context_files": {}},
            "run_config": {"target_llm": "claude-sonnet-4-20250514"},
        }
    )
    assert result["generated_code"] == "return 42"
    assert result["llm_tokens_used"] == 15


@pytest.mark.asyncio
async def test_llm_generate_empty_response(monkeypatch):
    monkeypatch.setattr(llm_generate_module, "load_api_key", lambda name: "key")

    async def fake_call_anthropic(**kwargs):
        return "   ", 2

    monkeypatch.setattr(llm_generate_module, "call_anthropic", fake_call_anthropic)
    result = await llm_generate_module.llm_generate(
        {
            "pr": {"repo": "example/repo", "pr_id": 1},
            "task": {"host_lang": "Python", "target_lang": "C", "masked_code": "def f():\n    <MASK>\n", "context_files": {}},
            "run_config": {"target_llm": "claude-sonnet-4-20250514"},
        }
    )
    assert result["generated_code"] == ""
    assert result["errors"][0]["reason"] == "empty_generation"


@pytest.mark.asyncio
async def test_llm_generate_provider_error(monkeypatch):
    monkeypatch.setattr(llm_generate_module, "load_api_key", lambda name: "key")

    async def fake_call_anthropic(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_generate_module, "call_anthropic", fake_call_anthropic)
    result = await llm_generate_module.llm_generate(
        {
            "pr": {"repo": "example/repo", "pr_id": 1},
            "task": {"host_lang": "Python", "target_lang": "C", "masked_code": "def f():\n    <MASK>\n", "context_files": {}},
            "run_config": {"target_llm": "claude-sonnet-4-20250514"},
        }
    )
    assert result["errors"][0]["reason"] == "llm_timeout"
