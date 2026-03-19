"""Parallel Orchestrator for Scout Agent."""

import csv
import json
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .worker import ScoutWorker, CandidatePR, shutdown_event
from .dedup import PRDeduplicationManager

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "scout.json"
TOKENS_PATH = PROJECT_ROOT / "config" / ".config.json"
DATA_DIR = PROJECT_ROOT / "data" / "scout"
REPOS_POOL_PATH = PROJECT_ROOT / "data" / "fetcher" / "multilang_repos_pool.json"


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_tokens() -> list[str]:
    with open(TOKENS_PATH, encoding="utf-8") as f:
        secrets = json.load(f)
    return [secrets["github"]["PAT1"], secrets["github"]["PAT2"]]


def _load_repositories() -> list[str]:
    """Load repository names from the pool file."""
    with open(REPOS_POOL_PATH, encoding="utf-8") as f:
        repos = json.load(f)
    return [repo["repo_name"] for repo in repos]


_CONFIG = _load_config()
_TOKENS = _load_tokens()


class ScoutOrchestrator:
    """
    Orchestrates parallel PR scanning across multiple workers.

    Features:
    - Thread pool with 1 worker per token
    - Graceful shutdown on SIGINT
    - Periodic result flushing
    - Progress reporting
    """

    def __init__(self):
        self.dedup = PRDeduplicationManager()
        self.all_candidates: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._signal_handler_installed = False

    def _signal_handler(self, signum, frame):
        """Handle SIGINT for graceful shutdown."""
        print("\n[!] 收到中断信号，正在保存进度...")
        shutdown_event.set()

    def _install_signal_handler(self):
        """Install signal handler (only once)."""
        if not self._signal_handler_installed:
            signal.signal(signal.SIGINT, self._signal_handler)
            self._signal_handler_installed = True

    def _allocate_repos(self, repos: list[str], num_workers: int) -> list[list[str]]:
        """Distribute repos across workers (round-robin)."""
        allocations = [[] for _ in range(num_workers)]
        for i, repo in enumerate(repos):
            allocations[i % num_workers].append(repo)
        return allocations

    def _worker_task(
        self,
        token: str,
        token_idx: int,
        repos: list[str],
    ) -> list[dict[str, Any]]:
        """
        Task executed by each worker thread.

        Args:
            token: GitHub PAT
            token_idx: Index of this token
            repos: List of repos to scan

        Returns:
            List of candidate PR dicts
        """
        worker = ScoutWorker(token, token_idx, self.dedup)
        candidates = []

        for repo in repos:
            if shutdown_event.is_set():
                break
            for candidate in worker.scan_repository(repo):
                with self._lock:
                    self.all_candidates.append(candidate._asdict())
                candidates.append(candidate._asdict())

        return candidates

    def run(self, repos: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Run parallel PR scanning.

        Args:
            repos: List of repo names (default: load from pool)

        Returns:
            List of candidate PR dicts
        """
        self._install_signal_handler()

        if repos is None:
            repos = _load_repositories()

        # Load existing PRs for deduplication
        output_path = DATA_DIR / "candidate_prs.json"
        loaded = self.dedup.load_existing_prs(output_path)
        if loaded > 0:
            print(f"[*] 已加载 {loaded} 个已扫描的 PR")

        # Allocate repos to workers
        allocations = self._allocate_repos(repos, len(_TOKENS))

        print(f"[*] 开始并行扫描，使用 {len(_TOKENS)} 个 Token")
        print(f"[*] 仓库总数: {len(repos)}")
        for i, alloc in enumerate(allocations):
            print(f"    PAT{i + 1}: {len(alloc)} 个仓库")

        # Run parallel scanning
        with ThreadPoolExecutor(max_workers=len(_TOKENS)) as executor:
            futures = []
            for token_idx, (token, worker_repos) in enumerate(
                zip(_TOKENS, allocations)
            ):
                future = executor.submit(
                    self._worker_task,
                    token,
                    token_idx,
                    worker_repos,
                )
                futures.append(future)

            for future in as_completed(futures):
                if shutdown_event.is_set():
                    break
                try:
                    candidates = future.result()
                    # Already added to all_candidates in worker
                except Exception as e:
                    print(f"[!] Worker 任务出错: {e}")

        # Save final results
        self._save_results()

        return self.all_candidates

    def _save_results(self):
        """Save candidates to JSON and CSV."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Save JSON
        json_path = DATA_DIR / "candidate_prs.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.all_candidates, f, indent=2, ensure_ascii=False)

        # Save CSV
        csv_path = DATA_DIR / "candidate_prs.csv"
        fieldnames = [
            "repository",
            "pr_number",
            "pr_url",
            "pr_title",
            "total_files_changed",
            "languages_detected",
            "test_files_detected",
            "reason",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in self.all_candidates:
                row = item.copy()
                row["languages_detected"] = str(row["languages_detected"])
                row["test_files_detected"] = str(row["test_files_detected"])
                writer.writerow(row)

        print(f"\n[*] 结果已保存:")
        print(f"  - JSON: {json_path}")
        print(f"  - CSV: {csv_path}")
        print(f"  - 候选 PR 总数: {len(self.all_candidates)}")


def run_scout(repos: list[str] | None = None) -> list[dict[str, Any]]:
    """
    Convenience function to run Scout Agent.

    Args:
        repos: Optional list of repo names

    Returns:
        List of candidate PR dicts
    """
    orchestrator = ScoutOrchestrator()
    return orchestrator.run(repos)
