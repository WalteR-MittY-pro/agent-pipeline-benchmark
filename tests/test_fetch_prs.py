# tests/test_fetch_prs.py
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.fetch_prs import (
    INTEROP_KEYWORDS,
    INTEROP_LANG_PAIRS,
    _has_interop_signal,
    fetch_prs,
)


def test_interop_signal_detection_supports_expanded_pairs():
    cgo_with_cpp = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 10,
            "deletions": 2,
            "status": "modified",
        },
        {
            "path": "native.cpp",
            "lang": "C++",
            "is_test": False,
            "additions": 5,
            "deletions": 1,
            "status": "modified",
        },
    ]
    assert _has_interop_signal(cgo_with_cpp, "cgo") is True

    jni_with_kotlin = [
        {
            "path": "Wrapper.kt",
            "lang": "Kotlin",
            "is_test": False,
            "additions": 12,
            "deletions": 0,
            "status": "modified",
        },
        {
            "path": "native.cpp",
            "lang": "C++",
            "is_test": False,
            "additions": 9,
            "deletions": 3,
            "status": "modified",
        },
    ]
    assert _has_interop_signal(jni_with_kotlin, "jni") is True

    v8_cpp_diff = [
        {
            "path": "embedder.cpp",
            "lang": "C++",
            "is_test": False,
            "additions": 20,
            "deletions": 2,
            "status": "modified",
        },
        {
            "path": "script.ts",
            "lang": "TypeScript",
            "is_test": False,
            "additions": 10,
            "deletions": 1,
            "status": "modified",
        },
    ]
    assert _has_interop_signal(v8_cpp_diff, "v8_cpp") is True

    cpp_only = [
        {
            "path": "embedder.cpp",
            "lang": "C++",
            "is_test": False,
            "additions": 10,
            "deletions": 0,
            "status": "modified",
        }
    ]
    assert _has_interop_signal(cpp_only, "v8_cpp") is False


def test_interop_tables_cover_documented_stage1_types():
    assert "v8_cpp" in INTEROP_KEYWORDS
    assert INTEROP_LANG_PAIRS["cgo"] == ({"Go"}, {"C", "C++"})
    assert INTEROP_LANG_PAIRS["jni"] == ({"Java", "Kotlin"}, {"C", "C++"})
    assert INTEROP_LANG_PAIRS["v8_cpp"] == (
        {"C++"},
        {"JavaScript", "TypeScript"},
    )


def test_fetch_prs_filters_accept_v8_cpp():
    mock_repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "v8_cpp",
        "interop_layer": "runtime_embedding",
        "stars": 1000,
        "default_branch": "main",
    }
    good_pr_files = [
        {
            "path": "embedder.cpp",
            "lang": "C++",
            "is_test": False,
            "additions": 30,
            "deletions": 5,
            "status": "modified",
        },
        {
            "path": "script.ts",
            "lang": "TypeScript",
            "is_test": False,
            "additions": 20,
            "deletions": 3,
            "status": "modified",
        },
        {
            "path": "script.test.ts",
            "lang": "TypeScript",
            "is_test": True,
            "additions": 15,
            "deletions": 0,
            "status": "added",
        },
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add V8 bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "def",
        }
    ]
    mock_client.get_pr_files.return_value = good_pr_files

    with patch.dict(os.environ, {"GITHUB_TOKEN_1": "fake_token"}):
        with patch("nodes.fetch_prs.GitHubClient", return_value=mock_client):
            result = fetch_prs(
                {
                    "repos": [mock_repo_info],
                    "prs": [],
                    "benchmark_items": [],
                    "errors": [],
                    "run_config": {
                        "max_prs_per_repo": 10,
                        "target_items": 5,
                        "min_diff_lines": 10,
                        "max_diff_lines": 500,
                        "db_path": ":memory:",
                    },
                }
            )

    assert len(result["prs"]) == 1
    pr = result["prs"][0]
    assert pr["pr_id"] == 7
    assert pr["interop_type"] == "v8_cpp"


if __name__ == "__main__":
    test_interop_signal_detection_supports_expanded_pairs()
    test_interop_tables_cover_documented_stage1_types()
    test_fetch_prs_filters_accept_v8_cpp()
    print("\n✅ fetch_prs.py verification passed")
