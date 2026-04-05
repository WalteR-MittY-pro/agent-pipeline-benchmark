from __future__ import annotations

import json
from pathlib import Path


def make_pr_key(repo: str, pr_id: int) -> str:
    return f"{repo}#{pr_id}"


def load_pr_key_set(path_str: str | None) -> set[str]:
    if not path_str:
        return set()

    path = Path(path_str)
    if not path.exists():
        return set()

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return set()

    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path_str} must be a JSON array")

    keys: set[str] = set()
    for item in data:
        if isinstance(item, str):
            keys.add(item)
            continue
        if not isinstance(item, dict):
            continue
        repo = item.get("repo")
        pr_id = item.get("pr_id")
        if isinstance(repo, str) and isinstance(pr_id, int):
            keys.add(make_pr_key(repo, pr_id))
    return keys
