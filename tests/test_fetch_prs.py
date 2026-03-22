# tests/test_fetch_prs.py
import os, sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# tests/test_fetch_prs.py
import os, sys
from unittest.mock import patch, MagicMock

from nodes.fetch_prs import (
    _has_interop_signal,
    INTEROP_KEYWORDS,
    INTEROP_LANG_PAIRS,
    fetch_prs,
)


def test_interop_signal_detection():
    diff_files = [
        {
            "path": "bridge.go",
            "lang": "Go",
            "is_test": False,
            "additions": 10,
            "deletions": 2,
            "status": "modified",
        },
        {
            "path": "native.c",
            "lang": "C",
            "is_test": False,
            "additions": 5,
            "deletions": 1,
            "status": "modified",
        },
    ]
    assert _has_interop_signal(diff_files, "cgo") == True

    diff_files_go_only = [
        {
            "path": "main.go",
            "lang": "Go",
            "is_test": False,
            "additions": 10,
            "deletions": 0,
            "status": "modified",
        },
    ]
    assert _has_interop_signal(diff_files_go_only, "cgo") == False
    print("✓ Cross-language signal detection correct")


def test_interop_lang_pairs():
    assert "Go" in INTEROP_LANG_PAIRS["cgo"]
    assert "C" in INTEROP_LANG_PAIRS["cgo"]
    assert "Java" in INTEROP_LANG_PAIRS["jni"]
    assert "Python" in INTEROP_LANG_PAIRS["ctypes"]
    print("✓ Language pair definitions correct")


def test_fetch_prs_filters():
    mock_repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
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
            "path": "native.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 3,
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
    ]
    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 1,
            "title": "Add CGo bridge",
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
            assert pr["pr_id"] == 1
            assert pr["interop_type"] == "cgo"
            print("✓ fetch_prs filtering logic correct")


if __name__ == "__main__":
    test_interop_signal_detection()
    test_interop_lang_pairs()
    test_fetch_prs_filters()
    print("\n✅ fetch_prs.py verification passed")
    """PR filtering boundary tests (using mock)"""
    mock_repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }

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
            "path": "native.c",
            "lang": "C",
            "is_test": False,
            "additions": 20,
            "deletions": 3,
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
    ]

    mock_client = MagicMock()
    mock_client.list_prs.return_value = [
        {
            "number": 1,
            "title": "Add CGo bridge",
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
            assert pr["pr_id"] == 1
            assert pr["interop_type"] == "cgo"
            print("✓ fetch_prs filtering logic correct")


if __name__ == "__main__":
    test_interop_signal_detection()
    test_interop_lang_pairs()
    test_fetch_prs_filters()
    print("\n✅ fetch_prs.py verification passed")
