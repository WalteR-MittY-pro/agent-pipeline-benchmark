# tests/test_fetch_repos.py
import os
import sys
import pytest

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


if __name__ == "__main__":
    test_search_queries_coverage()
    test_fetch_repos_small_scale()
