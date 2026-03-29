# tests/test_fetch_repos.py
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.fetch_repos import fetch_repos, SEARCH_QUERIES


def test_search_queries_coverage():
    from state import INTEROP_TYPES

    all_types = [t for types in INTEROP_TYPES.values() for t in types]
    for t in all_types:
        assert t in SEARCH_QUERIES, f"Missing search query for {t}"
    print(f"✓ All {len(all_types)} interop_types have search queries")


@pytest.mark.skipif(not os.environ.get("GITHUB_TOKEN_1"), reason="no GitHub token")
def test_fetch_repos_small_scale():
    initial_state = {
        "run_config": {
            "interop_types": ["cgo"],
            "min_stars": 1000,
            "target_repo_count": 3,
            "db_path": ":memory:",
        },
        "repos": [],
        "prs": [],
        "benchmark_items": [],
        "errors": [],
    }
    result = fetch_repos(initial_state)
    repos = result["repos"]
    assert len(repos) > 0, "Should find at least 1 CGo repo"
    assert all(r["interop_type"] == "cgo" for r in repos)
    assert all(r["interop_layer"] == "ffi" for r in repos)
    assert all(r["stars"] >= 1000 for r in repos)
    print(
        f"✓ fetch_repos returned {len(repos)} repos: {[r['full_name'] for r in repos]}"
    )


def test_fetch_repos_uses_multiple_passes_to_reach_target():
    mock_client = MagicMock()
    mock_client.search_repos.side_effect = [
        [
            {
                "full_name": "shared/repo-1",
                "clone_url": "https://github.com/shared/repo-1.git",
                "stars": 100,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "shared/repo-2",
                "clone_url": "https://github.com/shared/repo-2.git",
                "stars": 90,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
        ],
        [
            {
                "full_name": "shared/repo-1",
                "clone_url": "https://github.com/shared/repo-1.git",
                "stars": 100,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "shared/repo-2",
                "clone_url": "https://github.com/shared/repo-2.git",
                "stars": 90,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
        ],
        [
            {
                "full_name": "shared/repo-1",
                "clone_url": "https://github.com/shared/repo-1.git",
                "stars": 100,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "shared/repo-2",
                "clone_url": "https://github.com/shared/repo-2.git",
                "stars": 90,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "cgo/repo-3",
                "clone_url": "https://github.com/cgo/repo-3.git",
                "stars": 80,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "cgo/repo-4",
                "clone_url": "https://github.com/cgo/repo-4.git",
                "stars": 70,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
        ],
        [
            {
                "full_name": "shared/repo-1",
                "clone_url": "https://github.com/shared/repo-1.git",
                "stars": 100,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "shared/repo-2",
                "clone_url": "https://github.com/shared/repo-2.git",
                "stars": 90,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "jni/repo-3",
                "clone_url": "https://github.com/jni/repo-3.git",
                "stars": 85,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
            {
                "full_name": "jni/repo-4",
                "clone_url": "https://github.com/jni/repo-4.git",
                "stars": 75,
                "interop_type": "",
                "interop_layer": "",
                "languages": {},
                "default_branch": "main",
            },
        ],
    ]

    state = {
        "run_config": {
            "interop_types": ["cgo", "jni"],
            "min_stars": 50,
            "target_repo_count": 4,
            "repo_search_passes": 3,
            "db_path": ":memory:",
        },
        "repos": [],
        "prs": [],
        "benchmark_items": [],
        "errors": [],
    }

    with (
        patch("nodes.fetch_repos.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_repos.GitHubClient", return_value=mock_client),
    ):
        result = fetch_repos(state)

    repos = result["repos"]
    assert len(repos) == 4
    assert [repo["full_name"] for repo in repos] == [
        "shared/repo-1",
        "shared/repo-2",
        "jni/repo-3",
        "cgo/repo-3",
    ]
    searched_quotas = [call.kwargs["max_results"] for call in mock_client.search_repos.call_args_list]
    assert searched_quotas == [2, 2, 4, 4]


if __name__ == "__main__":
    test_search_queries_coverage()
    test_fetch_repos_small_scale()
