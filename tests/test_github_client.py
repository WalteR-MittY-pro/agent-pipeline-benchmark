# tests/test_github_client.py
"""
Test GitHubClient core functionality.
Note: This test makes real GitHub API requests (consumes quota).
Results are cached after first run.
"""

import os, sys
from types import SimpleNamespace
import pytest
from github import GithubException
from requests.exceptions import ProxyError

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import github_client
from github_client import GitHubClient, get_github_tokens_from_env, load_project_env

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


def test_get_github_tokens_from_env_requires_primary_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_2", raising=False)

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN_1"):
        get_github_tokens_from_env(env_path=tmp_path / ".missing-env")


def test_load_project_env_reads_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GITHUB_TOKEN_1="token_one"\nGITHUB_TOKEN_2=token_two\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_2", raising=False)

    loaded = load_project_env(env_file)

    assert loaded["GITHUB_TOKEN_1"] == "token_one"
    assert loaded["GITHUB_TOKEN_2"] == "token_two"
    assert os.environ["GITHUB_TOKEN_1"] == "token_one"
    assert os.environ["GITHUB_TOKEN_2"] == "token_two"


def test_get_github_tokens_from_env_falls_back_to_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GITHUB_TOKEN_1=token_one\nGITHUB_TOKEN_2=token_two\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_2", raising=False)

    assert get_github_tokens_from_env(env_path=env_file) == ["token_one", "token_two"]


def test_get_github_tokens_from_env_rejects_dead_local_proxy(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN_1=token_one\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_2", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setattr(github_client, "_is_proxy_reachable", lambda host, port: False)

    with pytest.raises(RuntimeError, match="local proxy is not reachable"):
        get_github_tokens_from_env(env_path=env_file)


def test_get_github_tokens_from_env_bypasses_proxy_when_requested(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN_1=token_one\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN_1", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN_2", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("GITHUB_BYPASS_PROXY", "1")
    monkeypatch.setattr(
        github_client,
        "_is_proxy_reachable",
        lambda host, port: pytest.fail("proxy reachability should not be checked"),
    )

    assert get_github_tokens_from_env(env_path=env_file) == ["token_one", "token_one"]
    assert "api.github.com" in os.environ["NO_PROXY"]
    assert "github.com" in os.environ["NO_PROXY"]


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


def test_api_call_does_not_retry_404():
    client = object.__new__(GitHubClient)
    client._throttle = lambda: None

    calls = {"count": 0}

    def always_404():
        calls["count"] += 1
        raise GithubException(404, {"message": "Not Found"}, None)

    with pytest.raises(GithubException):
        client._api_call(always_404, max_retries=3)

    assert calls["count"] == 1


def test_search_repos_cache_key_includes_max_results():
    client = object.__new__(GitHubClient)
    cache_store = {}
    calls = []

    def cache_get(key):
        return cache_store.get(key)

    def cache_set(key, value, ttl_hours=24.0):
        cache_store[key] = value

    repo_a = SimpleNamespace(
        full_name="owner/repo-a",
        clone_url="https://github.com/owner/repo-a.git",
        stargazers_count=200,
        default_branch="main",
    )
    repo_b = SimpleNamespace(
        full_name="owner/repo-b",
        clone_url="https://github.com/owner/repo-b.git",
        stargazers_count=180,
        default_branch="main",
    )

    def search_code(query):
        calls.append(query)
        if len(calls) == 1:
            return [SimpleNamespace(repository=repo_a)]
        return [
            SimpleNamespace(repository=repo_a),
            SimpleNamespace(repository=repo_b),
        ]

    client._cache_get = cache_get
    client._cache_set = cache_set
    client._api_call = lambda func, *args, **kwargs: func()
    client._client = lambda: SimpleNamespace(search_code=search_code)

    first = client.search_repos("language:Go", min_stars=100, max_results=1)
    second = client.search_repos("language:Go", min_stars=100, max_results=2)

    assert [repo["full_name"] for repo in first] == ["owner/repo-a"]
    assert [repo["full_name"] for repo in second] == ["owner/repo-a", "owner/repo-b"]
    assert len(calls) == 2


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


def test_get_pr_files_skips_when_github_diff_is_not_available():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    diff_error = GithubException(
        422,
        {
            "message": "Server Error: Sorry, this diff is taking too long to generate.",
            "errors": [
                {
                    "resource": "PullRequest",
                    "field": "diff",
                    "code": "not_available",
                }
            ],
        },
        None,
    )

    class UnavailableDiffFiles:
        def __iter__(self):
            raise diff_error

    pr = SimpleNamespace(get_files=lambda: UnavailableDiffFiles())
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    client._client = lambda: SimpleNamespace(get_repo=lambda repo_full_name: repo)

    assert client.get_pr_files("owner/repo", 123) == []


def test_get_pr_files_skips_when_github_reports_missing_diff_data():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    diff_error = GithubException(
        422,
        {
            "message": "Sorry, there was a problem generating this diff. The repository may be missing relevant data.",
            "errors": [
                {
                    "resource": "PullRequest",
                    "field": "diff",
                    "code": "not_available",
                }
            ],
        },
        None,
    )

    class UnavailableDiffFiles:
        def __iter__(self):
            raise diff_error

    pr = SimpleNamespace(get_files=lambda: UnavailableDiffFiles())
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    client._client = lambda: SimpleNamespace(get_repo=lambda repo_full_name: repo)

    assert client.get_pr_files("owner/repo", 456) == []


def test_get_pr_file_details_includes_patch_data():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    files = [
        SimpleNamespace(
            filename="pycosat.c",
            additions=10,
            deletions=4,
            status="modified",
            patch="@@ -1,2 +1,3 @@\n-old\n+new\n",
        )
    ]
    pr = SimpleNamespace(get_files=lambda: files)
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    client._client = lambda: SimpleNamespace(get_repo=lambda repo_full_name: repo)

    details = client.get_pr_file_details("owner/repo", 7)

    assert details == [
        {
            "path": "pycosat.c",
            "lang": "C",
            "is_test": False,
            "additions": 10,
            "deletions": 4,
            "status": "modified",
            "patch": "@@ -1,2 +1,3 @@\n-old\n+new\n",
        }
    ]


def test_api_call_wraps_proxy_errors_with_actionable_message(monkeypatch):
    client = object.__new__(GitHubClient)
    client._throttle = lambda: None
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    with pytest.raises(RuntimeError, match="configured proxy is unavailable"):
        client._api_call(lambda: (_ for _ in ()).throw(ProxyError("boom")), max_retries=1)


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
