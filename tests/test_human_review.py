import json
import importlib
import os
import sys
from argparse import Namespace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    Command = getattr(importlib.import_module("langgraph.types"), "Command")
except ModuleNotFoundError:
    from main import Command

import main
from nodes.human_review import _review_key, human_review
from state import BenchmarkState


SAMPLE_PRS = [
    {
        "pr_id": 1,
        "repo": "a/b",
        "pr_title": "Add CGo bridge",
        "interop_type": "cgo",
        "interop_layer": "ffi",
    },
    {
        "pr_id": 2,
        "repo": "c/d",
        "pr_title": "JNI wrapper",
        "interop_type": "jni",
        "interop_layer": "ffi",
    },
]


def test_review_key_format():
    assert _review_key(SAMPLE_PRS[0]) == "a/b#1"


def test_skip_review_passthrough_by_default():
    state = cast(
        BenchmarkState,
        {
            "prs": SAMPLE_PRS,
            "repos": [],
            "benchmark_items": [],
            "errors": [],
            "run_config": {},
        },
    )
    assert human_review(state) == {}


def test_human_review_uses_approved_pr_keys():
    state = cast(
        BenchmarkState,
        {
            "prs": SAMPLE_PRS,
            "repos": [],
            "benchmark_items": [],
            "errors": [],
            "run_config": {"skip_review": False},
        },
    )

    with patch(
        "nodes.human_review.interrupt", return_value={"approved_pr_keys": ["c/d#2"]}
    ):
        result = human_review(state)

    assert [pr["pr_id"] for pr in result["prs"]] == [2]


def test_prompt_review_returns_review_keys():
    prs_summary = [
        {"review_key": "a/b#1", "title": "One"},
        {"review_key": "c/d#2", "title": "Two"},
    ]
    with patch("builtins.input", return_value="2"):
        assert main.prompt_review(prs_summary) == ["c/d#2"]


def test_run_fetch_resumes_in_process_when_review_enabled(tmp_path):
    output_path = tmp_path / "snapshot.json"
    interrupt_result = {
        "__interrupt__": [
            SimpleNamespace(
                value={
                    "prs_summary": [{"review_key": "a/b#1", "title": "Add CGo bridge"}]
                }
            )
        ]
    }
    final_result = {"prs": [{"repo": "a/b", "pr_id": 1, "interop_type": "cgo"}]}

    class FakeApp:
        def __init__(self):
            self.calls = []

        def invoke(self, payload: Any, config: Any):
            self.calls.append((payload, config))
            return interrupt_result if len(self.calls) == 1 else final_result

    fake_app = FakeApp()
    args = Namespace(
        db=str(tmp_path / "bench.db"),
        thread_id="thread-1",
        interop_types="cgo",
        min_stars=100,
        output=str(output_path),
        review=True,
    )

    with (
        patch("graph.build_graph", return_value=fake_app),
        patch("main.prompt_review", return_value=["a/b#1"]),
    ):
        result = main.run_fetch(args)

    assert result == final_result["prs"]
    assert len(fake_app.calls) == 2
    assert isinstance(fake_app.calls[1][0], Command)
    with open(output_path, encoding="utf-8") as handle:
        assert json.load(handle) == final_result["prs"]
