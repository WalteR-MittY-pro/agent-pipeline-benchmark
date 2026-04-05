# tests/test_fetch_prs.py
import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.fetch_prs import (
    INTEROP_KEYWORDS,
    INTEROP_LANG_PAIRS,
    _build_config_fingerprint,
    _has_interop_signal,
    _scan_key,
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


def test_fetch_prs_writes_snapshot_and_progress_per_pr(tmp_path):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    output_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    input_path = tmp_path / "repos_snapshot.json"
    input_path.write_text(json.dumps([repo_info]), encoding="utf-8")

    good_pr_files = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 30,
            "deletions": 5,
            "status": "modified",
        },
        {
            "path": "bridge_test.go",
            "lang": "Go",
            "is_test": True,
            "additions": 15,
            "deletions": 0,
            "status": "added",
        },
        {
            "path": "bridge.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 4,
            "status": "modified",
        },
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add CGo bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        },
        {
            "number": 8,
            "title": "No diff files",
            "merged_at": "2024-01-02T00:00:00",
            "base_sha": "def",
            "head_sha": "sha-2",
        },
    ]
    mock_client.get_pr_files.side_effect = [good_pr_files, []]

    run_config = {
        "max_prs_per_repo": 10,
        "target_items": 5,
        "min_diff_lines": 10,
        "max_diff_lines": 500,
        "db_path": ":memory:",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "progress_path": str(progress_path),
    }
    run_config["config_fingerprint"] = _build_config_fingerprint(run_config)

    with (
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=mock_client),
    ):
        result = fetch_prs(
            {
                "repos": [repo_info],
                "prs": [],
                "benchmark_items": [],
                "errors": [],
                "run_config": run_config,
            }
        )

    assert [pr["pr_id"] for pr in result["prs"]] == [7]

    with open(output_path, encoding="utf-8") as handle:
        persisted_prs = json.load(handle)
    assert [pr["head_sha"] for pr in persisted_prs] == ["sha-1"]

    with open(progress_path, encoding="utf-8") as handle:
        progress = json.load(handle)
    assert progress["completed_repos"] == ["test/repo"]
    assert progress["config_fingerprint"] == run_config["config_fingerprint"]
    assert progress["scanned_pr_keys"] == [
        _scan_key("test/repo", "sha-1"),
        _scan_key("test/repo", "sha-2"),
    ]


def test_fetch_prs_dedupes_against_existing_snapshot_when_progress_lags(tmp_path):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    output_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    input_path = tmp_path / "repos_snapshot.json"
    input_path.write_text(json.dumps([repo_info]), encoding="utf-8")

    existing_pr = {
        "repo": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "pr_id": 7,
        "pr_title": "Add CGo bridge",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "base_sha": "abc",
        "head_sha": "sha-1",
        "diff_files": [],
        "diff_total_lines": 55,
        "test_commands": None,
        "merged_at": "2024-01-01T00:00:00",
    }
    output_path.write_text(json.dumps([existing_pr]), encoding="utf-8")

    run_config = {
        "max_prs_per_repo": 10,
        "target_items": 5,
        "min_diff_lines": 10,
        "max_diff_lines": 500,
        "db_path": ":memory:",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "progress_path": str(progress_path),
    }
    run_config["config_fingerprint"] = _build_config_fingerprint(run_config)
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(input_path),
                "output_path": str(output_path),
                "completed_repos": [],
                "scanned_pr_keys": [],
                "config_fingerprint": run_config["config_fingerprint"],
            }
        ),
        encoding="utf-8",
    )

    good_pr_files = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 30,
            "deletions": 5,
            "status": "modified",
        },
        {
            "path": "bridge_test.go",
            "lang": "Go",
            "is_test": True,
            "additions": 15,
            "deletions": 0,
            "status": "added",
        },
        {
            "path": "bridge.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 4,
            "status": "modified",
        },
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add CGo bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        },
        {
            "number": 8,
            "title": "Another CGo bridge",
            "merged_at": "2024-01-02T00:00:00",
            "base_sha": "def",
            "head_sha": "sha-2",
        },
    ]
    mock_client.get_pr_files.return_value = good_pr_files

    with (
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=mock_client),
    ):
        result = fetch_prs(
            {
                "repos": [repo_info],
                "prs": [existing_pr],
                "benchmark_items": [],
                "errors": [],
                "run_config": run_config,
            }
        )

    assert [pr["head_sha"] for pr in result["prs"]] == ["sha-2"]
    mock_client.get_pr_files.assert_called_once_with("test/repo", 8)

    with open(output_path, encoding="utf-8") as handle:
        persisted_prs = json.load(handle)
    assert [pr["head_sha"] for pr in persisted_prs] == ["sha-1", "sha-2"]


def test_fetch_prs_skips_excluded_prs(tmp_path):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    excluded_path = tmp_path / "excluded_prs.json"
    excluded_path.write_text(
        json.dumps([{"repo": "test/repo", "pr_id": 7}]), encoding="utf-8"
    )

    good_pr_files = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 30,
            "deletions": 5,
            "status": "modified",
        },
        {
            "path": "bridge_test.go",
            "lang": "Go",
            "is_test": True,
            "additions": 15,
            "deletions": 0,
            "status": "added",
        },
        {
            "path": "bridge.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 4,
            "status": "modified",
        },
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Excluded",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        },
        {
            "number": 8,
            "title": "Keep",
            "merged_at": "2024-01-02T00:00:00",
            "base_sha": "def",
            "head_sha": "sha-2",
        },
    ]
    mock_client.get_pr_files.return_value = good_pr_files

    with (
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=mock_client),
    ):
        result = fetch_prs(
            {
                "repos": [repo_info],
                "prs": [],
                "benchmark_items": [],
                "errors": [],
                "run_config": {
                    "max_prs_per_repo": 10,
                    "target_items": 5,
                    "min_diff_lines": 10,
                    "max_diff_lines": 500,
                    "db_path": ":memory:",
                    "excluded_prs_path": str(excluded_path),
                },
            }
        )

    assert [pr["pr_id"] for pr in result["prs"]] == [8]
    mock_client.get_pr_files.assert_called_once_with("test/repo", 8)


def test_fetch_prs_rejects_progress_with_mismatched_fingerprint(tmp_path):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    output_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    input_path = tmp_path / "repos_snapshot.json"
    input_path.write_text(json.dumps([repo_info]), encoding="utf-8")

    run_config = {
        "max_prs_per_repo": 10,
        "target_items": 5,
        "min_diff_lines": 10,
        "max_diff_lines": 500,
        "db_path": ":memory:",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "progress_path": str(progress_path),
        "config_fingerprint": "new-fingerprint",
    }
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(input_path),
                "output_path": str(output_path),
                "completed_repos": [],
                "scanned_pr_keys": [],
                "config_fingerprint": "old-fingerprint",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="progress file"):
        fetch_prs(
            {
                "repos": [repo_info],
                "prs": [],
                "benchmark_items": [],
                "errors": [],
                "run_config": run_config,
            }
        )


def test_fetch_prs_logs_percentage_progress(tmp_path, caplog):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    output_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    input_path = tmp_path / "repos_snapshot.json"
    input_path.write_text(json.dumps([repo_info]), encoding="utf-8")

    good_pr_files = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 30,
            "deletions": 5,
            "status": "modified",
        },
        {
            "path": "bridge_test.go",
            "lang": "Go",
            "is_test": True,
            "additions": 15,
            "deletions": 0,
            "status": "added",
        },
        {
            "path": "bridge.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 4,
            "status": "modified",
        },
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add CGo bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        },
        {
            "number": 8,
            "title": "Another CGo bridge",
            "merged_at": "2024-01-02T00:00:00",
            "base_sha": "def",
            "head_sha": "sha-2",
        },
    ]
    mock_client.get_pr_files.return_value = good_pr_files

    run_config = {
        "max_prs_per_repo": 10,
        "target_items": 5,
        "min_diff_lines": 10,
        "max_diff_lines": 500,
        "db_path": ":memory:",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "progress_path": str(progress_path),
    }
    run_config["config_fingerprint"] = _build_config_fingerprint(run_config)

    caplog.set_level(logging.INFO, logger="nodes.fetch_prs")

    with (
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=mock_client),
    ):
        fetch_prs(
            {
                "repos": [repo_info],
                "prs": [],
                "benchmark_items": [],
                "errors": [],
                "run_config": run_config,
            }
        )

    messages = [record.message for record in caplog.records]
    assert any(
        "Progress [############------------] 50.0%" in message for message in messages
    )
    assert any(
        "current repo test/repo [########--------] 50.0%" in message
        for message in messages
    )
    assert any(
        "Completed repo test/repo: [########################] 100.0% overall"
        in message
        for message in messages
    )


if __name__ == "__main__":
    test_interop_signal_detection_supports_expanded_pairs()
    test_interop_tables_cover_documented_stage1_types()
    test_fetch_prs_filters_accept_v8_cpp()
    print("\n✅ fetch_prs.py verification passed")
