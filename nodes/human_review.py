# nodes/human_review.py
import logging
from collections import Counter
from langgraph.types import interrupt

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import BenchmarkState

logger = logging.getLogger(__name__)


def human_review(state: BenchmarkState) -> dict:
    """
    Optional human review node.

    skip_review=True  → pass through, don't modify prs
    skip_review=False → call interrupt() to pause, wait for external approval
    """
    if state["run_config"].get("skip_review", False):
        logger.info(
            f"human_review: skipped (skip_review=True), keeping all {len(state['prs'])} PRs"
        )
        return {}

    # Build summary for human reviewer
    prs = state["prs"]
    by_type = Counter(p["interop_type"] for p in prs)
    by_layer = Counter(p["interop_layer"] for p in prs)

    logger.info(f"human_review: pausing for review of {len(prs)} PRs")

    # interrupt() pauses the Graph, exposes data externally
    # External caller: app.update_state(config, {"approved_pr_ids": [...]}) then continue
    decision = interrupt(
        {
            "message": "Please review the PR list and confirm which to keep",
            "total_count": len(prs),
            "by_interop_type": dict(by_type),
            "by_interop_layer": dict(by_layer),
            "prs_summary": [
                {
                    "pr_id": p["pr_id"],
                    "repo": p["repo"],
                    "title": p["pr_title"],
                    "type": p["interop_type"],
                }
                for p in prs
            ],
        }
    )

    # After resume, read approval result from decision
    approved_ids = decision.get("approved_pr_ids")
    if approved_ids is None:
        # No approval list provided, approve all by default
        logger.info("human_review: no approved_pr_ids provided, approving all")
        return {}

    approved_set = set(approved_ids)
    filtered = [p for p in prs if p["pr_id"] in approved_set]
    logger.info(f"human_review: human approved {len(filtered)}/{len(prs)} PRs")
    return {"prs": filtered}
