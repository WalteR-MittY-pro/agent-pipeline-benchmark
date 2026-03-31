import json
import os
import sys
import hashlib
from argparse import Namespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main


def _fingerprint_for_stage1(
    max_prs_per_repo=100,
    target_items=None,
    min_diff_lines=50,
    max_diff_lines=2000,
):
    relevant = {
        "max_prs_per_repo": max_prs_per_repo,
        "target_items": target_items,
        "min_diff_lines": min_diff_lines,
        "max_diff_lines": max_diff_lines,
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def test_stage1_produces_snapshots_and_resumes_without_rescanning_completed_repo(
    tmp_path,
):
    repos_path = tmp_path / "repos_snapshot.json"
    prs_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"

    repo_client = MagicMock()
    repo_client.search_repos.return_value = [
        {
            "full_name": "test/repo",
            "clone_url": "https://github.com/test/repo.git",
            "stars": 1234,
            "interop_type": "",
            "interop_layer": "",
            "languages": {"Go": 80, "C": 20},
            "default_branch": "main",
        }
    ]

    fetch_repos_args = Namespace(
        db=":memory:",
        interop_types="cgo",
        min_stars=1000,
        output=str(repos_path),
    )

    with (
        patch("main.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_repos.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_repos.GitHubClient", return_value=repo_client),
    ):
        repos = main.run_fetch_repos(fetch_repos_args)

    assert repos_path.exists()
    assert len(repos) == 1
    assert repos[0]["full_name"] == "test/repo"
    assert repos[0]["interop_type"] == "cgo"

    pr_client = MagicMock()
    pr_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add CGo bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        }
    ]
    pr_client.get_pr_files.return_value = [
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

    fetch_prs_args = Namespace(
        db=":memory:",
        input=str(repos_path),
        output=str(prs_path),
        review=False,
        thread_id="stage1-thread",
        max_prs_per_repo=10,
        min_stars=None,
    )

    with (
        patch("main.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=pr_client),
    ):
        prs = main.run_fetch_prs(fetch_prs_args)

    assert prs_path.exists()
    assert progress_path.exists()
    assert len(prs) == 1
    assert prs[0]["repo"] == "test/repo"
    assert prs[0]["head_sha"] == "sha-1"

    with open(progress_path, encoding="utf-8") as handle:
        progress = json.load(handle)
    assert progress["completed_repos"] == ["test/repo"]
    assert progress["scanned_pr_keys"] == ["test/repo@sha-1"]

    resumed_client = MagicMock()
    with (
        patch("main.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=resumed_client),
    ):
        resumed_prs = main.run_fetch_prs(fetch_prs_args)

    resumed_client.list_prs.assert_not_called()
    resumed_client.get_pr_files.assert_not_called()
    assert resumed_prs == prs


def test_run_fetch_prs_scans_past_300_candidates_when_no_target_cap_is_set(tmp_path):
    repo_count = 301
    repos = [
        {
            "full_name": f"test/repo-{idx}",
            "clone_url": f"https://github.com/test/repo-{idx}.git",
            "interop_type": "cgo",
            "interop_layer": "ffi",
            "stars": 1000,
            "default_branch": "main",
        }
        for idx in range(repo_count)
    ]

    repos_path = tmp_path / "repos_snapshot.json"
    prs_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    repos_path.write_text(json.dumps(repos), encoding="utf-8")

    pr_client = MagicMock()
    pr_client.list_prs.side_effect = lambda repo_name, max_n=None: [
        {
            "number": 7,
            "title": f"Add bridge for {repo_name}",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "base-sha",
            "head_sha": f"{repo_name}-head",
        }
    ]
    pr_client.get_pr_files.return_value = [
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

    fetch_prs_args = Namespace(
        db=":memory:",
        input=str(repos_path),
        output=str(prs_path),
        review=False,
        thread_id="stage1-thread-unbounded",
        max_prs_per_repo=10,
        min_stars=None,
        target_items=None,
    )

    with (
        patch("main.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=pr_client),
    ):
        prs = main.run_fetch_prs(fetch_prs_args)

    assert len(prs) == repo_count
    assert pr_client.list_prs.call_count == repo_count
    assert pr_client.get_pr_files.call_count == repo_count

    with open(progress_path, encoding="utf-8") as handle:
        progress = json.load(handle)
    assert len(progress["completed_repos"]) == repo_count


def test_run_fetch_prs_accepts_legacy_progress_fingerprint_for_old_300_default(tmp_path):
    repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }
    repos_path = tmp_path / "repos_snapshot.json"
    prs_path = tmp_path / "prs_snapshot.json"
    progress_path = tmp_path / "prs_snapshot.progress.json"
    repos_path.write_text(json.dumps([repo_info]), encoding="utf-8")
    prs_path.write_text("[]", encoding="utf-8")
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(repos_path),
                "output_path": str(prs_path),
                "completed_repos": [],
                "scanned_pr_keys": [],
                "config_fingerprint": _fingerprint_for_stage1(target_items=300),
            }
        ),
        encoding="utf-8",
    )

    pr_client = MagicMock()
    pr_client.list_prs.return_value = [
        {
            "number": 7,
            "title": "Add bridge",
            "merged_at": "2024-01-01T00:00:00",
            "base_sha": "abc",
            "head_sha": "sha-1",
        }
    ]
    pr_client.get_pr_files.return_value = [
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

    fetch_prs_args = Namespace(
        db=":memory:",
        input=str(repos_path),
        output=str(prs_path),
        review=False,
        thread_id="stage1-thread-legacy-progress",
        max_prs_per_repo=100,
        min_stars=None,
        target_items=None,
    )

    with (
        patch("main.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.get_github_tokens_from_env", return_value=["token"]),
        patch("nodes.fetch_prs.GitHubClient", return_value=pr_client),
    ):
        prs = main.run_fetch_prs(fetch_prs_args)

    assert len(prs) == 1
    with open(progress_path, encoding="utf-8") as handle:
        progress = json.load(handle)
    assert progress["config_fingerprint"] == _fingerprint_for_stage1(target_items=None)
