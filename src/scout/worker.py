"""Scout Worker - scans PRs from a repository using PyGithub."""

import json
import threading
from pathlib import Path
from typing import NamedTuple

from github import Github, Auth
from github.GithubException import RateLimitExceededException, GithubException
from github.GithubRetry import GithubRetry

from .filters import FileChange, FilterResult, filter_pr
from .dedup import PRDeduplicationManager

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "scout.json"
TOKENS_PATH = PROJECT_ROOT / "config" / ".config.json"

# Global shutdown event (set by signal handler in orchestrator)
shutdown_event = threading.Event()


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_tokens() -> list[str]:
    with open(TOKENS_PATH, encoding="utf-8") as f:
        secrets = json.load(f)
    return [secrets["github"]["PAT1"], secrets["github"]["PAT2"]]


_CONFIG = _load_config()
_TOKENS = _load_tokens()


class CandidatePR(NamedTuple):
    """PR candidate that passed all filters."""

    repository: str
    pr_number: int
    pr_url: str
    pr_title: str
    total_files_changed: int
    languages_detected: list[str]
    test_files_detected: list[str]
    reason: str


class ScoutWorker:
    """
    Worker that scans PRs from repositories.

    Each worker creates its own Github() instance (PyGithub is NOT thread-safe).
    """

    def __init__(
        self,
        token: str,
        token_idx: int,
        dedup_manager: PRDeduplicationManager,
    ):
        """
        Initialize worker with its own Github instance.

        Args:
            token: GitHub Personal Access Token
            token_idx: Index of this token (for logging)
            dedup_manager: Shared deduplication manager
        """
        self.token = token
        self.token_idx = token_idx
        self.dedup = dedup_manager

        # Create own Github instance (NOT shared across threads!)
        retry = GithubRetry(
            total=_CONFIG["api"]["retry_total"],
            secondary_rate_wait=_CONFIG["api"]["secondary_rate_wait"],
        )
        self.github = Github(
            auth=Auth.Token(token),
            retry=retry,
            seconds_between_requests=_CONFIG["api"]["sleep_interval"],
        )

    def scan_repository(self, repo_name: str) -> list[CandidatePR]:
        """
        Scan all PRs in a repository and filter candidates.

        Args:
            repo_name: Repository in format "owner/repo"

        Returns:
            List of CandidatePR objects that passed filters
        """
        candidates = []

        if shutdown_event.is_set():
            return candidates

        try:
            repo = self.github.get_repo(repo_name)
            pr_filter = _CONFIG["pr_filter"]

            pulls = repo.get_pulls(
                state=pr_filter["state"],
                sort=pr_filter["sort"],
                direction=pr_filter["direction"],
            )

            limit = pr_filter.get("limit_per_repo", 100)
            count = 0

            for pr in pulls:
                if shutdown_event.is_set():
                    break
                if count >= limit:
                    break

                # Check deduplication BEFORE fetching files
                if self.dedup.is_scanned(repo_name, pr.number):
                    continue

                # Get changed files
                try:
                    files = pr.get_files()
                    file_changes = [
                        FileChange(
                            filename=f.filename,
                            status=f.status,
                            additions=f.additions,
                            deletions=f.deletions,
                        )
                        for f in files
                    ]
                except GithubException as e:
                    print(
                        f"  [PAT{self.token_idx + 1}] Error getting files for PR #{pr.number}: {e}"
                    )
                    self.dedup.mark_scanned(
                        repo_name, pr.number
                    )  # Mark as scanned to avoid retry
                    continue

                # Apply filter rules
                result = filter_pr(file_changes)

                # Mark as scanned (regardless of pass/fail)
                self.dedup.mark_scanned(repo_name, pr.number)
                count += 1

                if result.passed:
                    candidate = CandidatePR(
                        repository=repo_name,
                        pr_number=pr.number,
                        pr_url=pr.html_url,
                        pr_title=pr.title,
                        total_files_changed=result.total_files,
                        languages_detected=sorted(result.languages_detected),
                        test_files_detected=result.test_files_detected,
                        reason=result.reason,
                    )
                    candidates.append(candidate)
                    print(
                        f"[PAT{self.token_idx + 1}] [CANDIDATE] {repo_name}#{pr.number}: {pr.title[:50]}"
                    )
                else:
                    # Optional: log skipped PRs
                    pass

        except RateLimitExceededException:
            print(f"[PAT{self.token_idx + 1}] Rate limit exceeded, propagating...")
            raise
        except GithubException as e:
            print(f"[PAT{self.token_idx + 1}] Error scanning {repo_name}: {e}")
        except Exception as e:
            print(
                f"[PAT{self.token_idx + 1}] Unexpected error scanning {repo_name}: {e}"
            )

        return candidates

    def scan_repositories(
        self,
        repo_names: list[str],
    ):
        """
        Scan multiple repositories, yielding candidates as found.

        Args:
            repo_names: List of repository names in "owner/repo" format

        Yields:
            CandidatePR objects as they are found
        """
        for repo_name in repo_names:
            if shutdown_event.is_set():
                break
            for candidate in self.scan_repository(repo_name):
                yield candidate
