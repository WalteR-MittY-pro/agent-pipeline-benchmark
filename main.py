# main.py
import argparse, json, os, logging
from datetime import datetime

try:
    from langgraph.types import Command
except ImportError:  # pragma: no cover - lightweight fallback for tests/docs
    class Command:  # type: ignore[override]
        def __init__(self, resume):
            self.resume = resume


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

BASE_RUN_CONFIG = {
    "interop_types": [
        "cgo",
        "jni",
        "ctypes",
        "cffi",
        "rust_ffi",
        "node_napi",
        "lua_c",
        "python_cext",
        "ruby_cext",
        "v8_cpp",
        "wasm",
    ],
    "min_stars": 50,
    "max_prs_per_repo": 100,
    "target_items": 300,
    "target_repo_count": 100,
    "per_repo_cap": None,
    "skip_review": True,
    "task_strategy": "completion",
    "target_llm": "claude-sonnet-4-20250514",
    "judge_llm": "claude-sonnet-4-20250514",
    "min_diff_lines": 50,
    "max_diff_lines": 2000,
    "max_concurrent_docker": 4,
}


def make_initial_state(run_config: dict) -> dict:
    return {
        "run_config": run_config,
        "repos": [],
        "prs": [],
        "benchmark_items": [],
        "errors": [],
    }


def prompt_review(prs_summary: list[dict]) -> list[str] | None:
    """Collect a one-shot in-process review decision from stdin."""
    print("\n=== Human Review ===")
    for idx, item in enumerate(prs_summary, start=1):
        print(f"{idx:>3}. [{item['review_key']}] {item['title']}")

    raw = input("输入保留编号（逗号分隔，回车=全部保留，0=全部丢弃）: ").strip()
    if raw == "":
        return None
    if raw == "0":
        return []

    chosen = set()
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(prs_summary):
                chosen.add(idx - 1)

    return [prs_summary[i]["review_key"] for i in sorted(chosen)]


def run_fetch(args):
    """Run Stage 1 only, save results to file"""
    from graph import build_graph

    db_path = args.db
    thread_id = args.thread_id or f"fetch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config = {"configurable": {"thread_id": thread_id}}

    review_enabled = getattr(args, "review", False)
    run_config = {
        **BASE_RUN_CONFIG,
        "skip_review": not review_enabled,
        "db_path": db_path,
    }

    # Allow CLI override of some params
    if args.interop_types:
        run_config["interop_types"] = args.interop_types.split(",")
    if args.min_stars:
        run_config["min_stars"] = args.min_stars

    app = build_graph(db_path=db_path)
    result = app.invoke(make_initial_state(run_config), config)

    if review_enabled and "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        payload = interrupt_obj.value
        approved_keys = prompt_review(payload["prs_summary"])
        resume_payload = (
            {} if approved_keys is None else {"approved_pr_keys": approved_keys}
        )
        result = app.invoke(Command(resume=resume_payload), config)

    prs = result.get("prs", [])
    output_path = args.output or "prs_snapshot.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(prs, f, ensure_ascii=False, indent=2, default=str)

    logging.info(f"Stage 1 complete: {len(prs)} PRs saved to {output_path}")
    return prs


def main():
    parser = argparse.ArgumentParser(description="Cross-language Benchmark Pipeline")
    parser.add_argument(
        "--mode",
        choices=["fetch", "build", "single-pr", "resume", "full"],
        default="fetch",
        help="Execution mode",
    )
    parser.add_argument(
        "--db",
        default="benchmark_runs.db",
        help="SQLite database path for checkpointing",
    )
    parser.add_argument(
        "--thread-id",
        help="Thread ID for checkpointing/resuming",
    )
    parser.add_argument(
        "--interop-types",
        help="Comma-separated interop types (e.g., cgo,jni)",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        help="Minimum stars for repo search",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for fetch mode",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Enable a one-shot in-process human review step",
    )

    args = parser.parse_args()

    if args.mode == "fetch":
        run_fetch(args)
    else:
        logging.error(f"Mode {args.mode} not yet implemented (Phase 2+)")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
