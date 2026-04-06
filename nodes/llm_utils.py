from __future__ import annotations

import json
import os

import aiohttp

from github_client import load_project_env

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def load_api_key(name: str, fallback: str | None = None) -> str:
    load_project_env()
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if fallback:
        value = os.environ.get(fallback, "").strip()
        if value:
            return value
    return ""


def _extract_text(payload: dict) -> str:
    parts: list[str] = []
    for block in payload.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts).strip()


def _extract_token_count(payload: dict) -> int:
    usage = payload.get("usage") or {}
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


async def call_anthropic(
    *,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout: int = 60,
) -> tuple[str, int]:
    if not api_key:
        raise RuntimeError("Missing Anthropic API key.")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.post(ANTHROPIC_URL, headers=headers, json=payload) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Anthropic API error {response.status}: {text}")
            decoded = json.loads(text)
    return _extract_text(decoded), _extract_token_count(decoded)
