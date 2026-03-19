"""Scout Agent - PR scanning and filtering for multi-language repositories."""

from .filters import (
    FileChange,
    FilterResult,
    filter_pr,
    detect_languages,
    detect_test_files,
)
from .dedup import PRDeduplicationManager, PRKey, make_pr_key, parse_pr_key
from .worker import ScoutWorker, CandidatePR, shutdown_event
from .orchestrator import ScoutOrchestrator, run_scout

__all__ = [
    # Filters
    "FileChange",
    "FilterResult",
    "filter_pr",
    "detect_languages",
    "detect_test_files",
    # Deduplication
    "PRDeduplicationManager",
    "PRKey",
    "make_pr_key",
    "parse_pr_key",
    # Worker
    "ScoutWorker",
    "CandidatePR",
    "shutdown_event",
    # Orchestrator
    "ScoutOrchestrator",
    "run_scout",
]
