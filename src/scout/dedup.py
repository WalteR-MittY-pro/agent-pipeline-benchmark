"""Thread-safe PR deduplication for Scout Agent."""

import json
import threading
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "scout"


class PRKey(NamedTuple):
    """Unique identifier for a PR."""

    repo_name: str
    pr_number: int

    def __str__(self) -> str:
        return f"{self.repo_name}#{self.pr_number}"


class PRDeduplicationManager:
    """
    Thread-safe manager for tracking scanned PRs.

    Deduplication key format: "{repo_name}#{pr_number}"
    Example: "owner/repo#123"
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._scanned_prs: set[str] = set()
        self._total_scanned = 0
        self._total_skipped = 0

    def is_scanned(self, repo_name: str, pr_number: int) -> bool:
        """Check if PR has already been scanned."""
        key = make_pr_key(repo_name, pr_number)
        with self._lock:
            return key in self._scanned_prs

    def mark_scanned(self, repo_name: str, pr_number: int) -> None:
        """Mark PR as scanned."""
        key = make_pr_key(repo_name, pr_number)
        with self._lock:
            self._scanned_prs.add(key)
            self._total_scanned += 1

    def get_stats(self) -> dict:
        """Return scanning statistics."""
        with self._lock:
            return {
                "total_scanned": self._total_scanned,
                "total_skipped": self._total_skipped,
                "unique_prs": len(self._scanned_prs),
            }

    def load_existing_prs(self, output_path: Path | None = None) -> int:
        """
        Load existing PRs from output file for resume support.

        Args:
            output_path: Path to JSON file with existing PR candidates

        Returns:
            Number of PRs loaded
        """
        if output_path is None:
            output_path = DATA_DIR / "candidate_prs.json"

        if not output_path.exists():
            return 0

        try:
            with open(output_path, "r", encoding="utf-8") as f:
                candidates = json.load(f)
        except (json.JSONDecodeError, IOError):
            return 0

        loaded_count = 0
        with self._lock:
            for candidate in candidates:
                repo_name = candidate.get("repo_name")
                pr_number = candidate.get("pr_number")
                if repo_name and pr_number:
                    key = make_pr_key(repo_name, pr_number)
                    self._scanned_prs.add(key)
                    loaded_count += 1

        return loaded_count

    def save_progress(
        self, candidates: list[dict], output_path: Path | None = None
    ) -> None:
        """
        Save current PR candidates to file.

        Args:
            candidates: List of PR candidate dicts
            output_path: Path to save JSON file
        """
        if output_path is None:
            output_path = DATA_DIR / "candidate_prs.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(candidates, f, indent=2, ensure_ascii=False)


def make_pr_key(repo_name: str, pr_number: int) -> str:
    """Create deduplication key from repo name and PR number."""
    return f"{repo_name}#{pr_number}"


def parse_pr_key(key: str) -> PRKey:
    """Parse deduplication key into components."""
    repo_name, pr_number = key.rsplit("#", 1)
    return PRKey(repo_name, int(pr_number))
