# tests/test_github_client.py
"""
Test GitHubClient core functionality.
Note: This test makes real GitHub API requests (consumes quota).
Results are cached after first run.
"""

import os, sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from github_client import GitHubClient

HAS_GITHUB_TOKEN = bool(os.environ.get("GITHUB_TOKEN_1"))


def get_client():
    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    return GitHubClient(tokens, cache_db=":memory:")


@pytest.mark.skipif(not HAS_GITHUB_TOKEN, reason="no GitHub token")
def test_init():
    client = get_client()
    assert client is not None
    print("✓ GitHubClient initialized successfully")


@pytest.mark.skipif(not HAS_GITHUB_TOKEN, reason="no GitHub token")
def test_search_repos_returns_results():
    client = get_client()
    repos = client.search_repos(
        query="language:Go",
        min_stars=10000,
        max_results=3,
    )
    assert len(repos) > 0, "Search should return at least 1 result"
    assert "full_name" in repos[0]
    assert "clone_url" in repos[0]
    assert repos[0]["stars"] >= 10000
    print(
        f"✓ search_repos returned {len(repos)} results, first: {repos[0]['full_name']}"
    )


@pytest.mark.skipif(not HAS_GITHUB_TOKEN, reason="no GitHub token")
def test_list_prs_returns_merged():
    client = get_client()
    prs = client.list_prs("avelino/awesome-go", max_n=5)
    assert len(prs) > 0
    assert all(pr.get("merged_at") is not None for pr in prs)
    print(f"✓ list_prs returned {len(prs)} PRs, all merged")


@pytest.mark.skipif(not HAS_GITHUB_TOKEN, reason="no GitHub token")
def test_get_file_content():
    client = get_client()
    content = client.get_file_content("avelino/awesome-go", "HEAD", "README.md")
    assert len(content) > 100, "README should have substantial content"
    print(f"✓ get_file_content succeeded, content length: {len(content)} chars")


@pytest.mark.skipif(not HAS_GITHUB_TOKEN, reason="no GitHub token")
def test_cache_works():
    client = get_client()
    repos_1 = client.search_repos("language:Go", min_stars=10000, max_results=2)
    repos_2 = client.search_repos("language:Go", min_stars=10000, max_results=2)
    assert repos_1 == repos_2
    print("✓ Cache mechanism working")


def test_detect_lang():
    assert GitHubClient._detect_lang("bridge.go") == "Go"
    assert GitHubClient._detect_lang("native.c") == "C"
    assert GitHubClient._detect_lang("Wrapper.java") == "Java"
    assert GitHubClient._detect_lang("lib.rs") == "Rust"
    print("✓ Language detection correct")


def test_is_test_file():
    assert GitHubClient._is_test_file("bridge_test.go") == True
    assert GitHubClient._is_test_file("tests/test_bridge.py") == True
    assert GitHubClient._is_test_file("native.c") == False
    assert GitHubClient._is_test_file("bridge.go") == False
    print("✓ Test file detection correct")


def test_search_repos_dedups_code_search_matches():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    repo_a = SimpleNamespace(
        full_name="owner/repo-a",
        clone_url="https://github.com/owner/repo-a.git",
        stargazers_count=200,
        default_branch="main",
    )
    repo_b = SimpleNamespace(
        full_name="owner/repo-b",
        clone_url="https://github.com/owner/repo-b.git",
        stargazers_count=80,
        default_branch="master",
    )

    client._client = lambda: SimpleNamespace(
        search_code=lambda query: [
            SimpleNamespace(repository=repo_a),
            SimpleNamespace(repository=repo_a),
            SimpleNamespace(repository=repo_b),
        ]
    )

    repos = client.search_repos("language:Go", min_stars=100, max_results=5)
    assert [repo["full_name"] for repo in repos] == ["owner/repo-a"]


def test_list_prs_scans_past_unmerged_closed_prs():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    pulls = [
        SimpleNamespace(merged_at=None),
        SimpleNamespace(
            number=2,
            title="Merged 2",
            merged_at=SimpleNamespace(isoformat=lambda: "2024-01-02T00:00:00"),
            base=SimpleNamespace(sha="base-2"),
            head=SimpleNamespace(sha="head-2"),
        ),
        SimpleNamespace(
            number=3,
            title="Merged 3",
            merged_at=SimpleNamespace(isoformat=lambda: "2024-01-03T00:00:00"),
            base=SimpleNamespace(sha="base-3"),
            head=SimpleNamespace(sha="head-3"),
        ),
    ]

    repo = SimpleNamespace(
        get_pulls=lambda state, sort, direction: pulls,
    )
    client._client = lambda: SimpleNamespace(get_repo=lambda repo_full_name: repo)

    prs = client.list_prs("owner/repo", max_n=2)
    assert [pr["number"] for pr in prs] == [2, 3]


if __name__ == "__main__":
    test_init()
    test_detect_lang()
    test_is_test_file()
    test_search_repos_dedups_code_search_matches()
    test_list_prs_scans_past_unmerged_closed_prs()
    test_cache_works()
    test_search_repos_returns_results()
    test_list_prs_returns_merged()
    test_get_file_content()
    print("\n✅ github_client.py all verification passed")
