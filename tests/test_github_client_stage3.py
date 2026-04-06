import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from github_client import GitHubClient


def test_get_pr_file_details_includes_patch():
    client = object.__new__(GitHubClient)
    client._cache_get = lambda key: None
    client._cache_set = lambda key, value, ttl_hours=24.0: None
    client._api_call = lambda func, *args, **kwargs: func()

    files = [
        SimpleNamespace(
            filename="src/module.c",
            additions=4,
            deletions=1,
            status="modified",
            patch="@@ -1 +1 @@\n-old\n+new\n",
        )
    ]
    pr = SimpleNamespace(get_files=lambda: files)
    repo = SimpleNamespace(get_pull=lambda pr_number: pr)
    client._client = lambda: SimpleNamespace(get_repo=lambda repo_full_name: repo)

    details = client.get_pr_file_details("owner/repo", 123)
    assert details[0]["path"] == "src/module.c"
    assert details[0]["patch"].startswith("@@")
