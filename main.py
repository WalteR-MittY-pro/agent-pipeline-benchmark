# main.py
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from github_client import get_github_tokens_from_env
from pr_registry import load_pr_key_set, make_pr_key

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
    "target_items": None,
    "target_repo_count": 200,
    "per_repo_cap": None,
    "skip_review": True,
    "task_strategy": "completion",
    "target_llm": "claude-sonnet-4-20250514",
    "judge_llm": "claude-sonnet-4-20250514",
    "min_diff_lines": 50,
    "max_diff_lines": 2000,
    "max_concurrent_docker": 4,
    "enable_compile_repair": False,
    "excluded_prs_path": "excluded_prs.json",
}


def _normalize_target_items(value: int | None) -> int | None:
    if value is None:
        return None
    return value if value > 0 else None


def _atomic_write_json(path: str, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False
    ) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = tmp.name
    os.replace(temp_path, target)


def derive_progress_path(output_path: str) -> str:
    path = Path(output_path)
    if path.suffix == ".json":
        return str(path.with_name(f"{path.stem}.progress.json"))
    return f"{output_path}.progress.json"


def load_json_array(path_str: str) -> list[dict]:
    path = Path(path_str)
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    data = json.loads(raw)
    if not isinstance(data, list):
        raise SystemExit(f"{path_str} must be a JSON array")
    return data


def build_config_fingerprint(run_config: dict) -> str:
    relevant = {
        "max_prs_per_repo": run_config["max_prs_per_repo"],
        "target_items": _normalize_target_items(run_config.get("target_items")),
        "min_diff_lines": run_config["min_diff_lines"],
        "max_diff_lines": run_config["max_diff_lines"],
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def filter_excluded_prs(
    prs: list[dict], excluded_prs_path: str | None
) -> tuple[list[dict], list[dict]]:
    excluded_keys = load_pr_key_set(excluded_prs_path)
    if not excluded_keys:
        return list(prs), []

    kept: list[dict] = []
    skipped: list[dict] = []
    for pr in prs:
        pr_key = make_pr_key(pr["repo"], pr["pr_id"])
        if pr_key in excluded_keys:
            skipped.append(pr)
        else:
            kept.append(pr)

    return kept, skipped


def make_initial_state(
    run_config: dict,
    repos: list[dict] | None = None,
    existing_prs: list[dict] | None = None,
) -> dict:
    return {
        "run_config": run_config,
        "repos": list(repos or []),
        "prs": list(existing_prs or []),
        "benchmark_items": [],
        "errors": [],
    }


def make_initial_pr_state(pr: dict, run_config: dict) -> dict:
    return {
        "pr": pr,
        "run_config": run_config,
        "env_spec": None,
        "dockerfile_path": None,
        "dockerfile_content": None,
        "image_tag": None,
        "build_status": None,
        "build_retries": 0,
        "build_log": None,
        "compile_status": None,
        "compile_repair_rounds": 0,
        "compile_repair_log": None,
        "baseline_test_result": None,
        "task": None,
        "generated_code": None,
        "llm_tokens_used": 0,
        "test_result": None,
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


def run_fetch_repos(args):
    """Run repo-level recall and save repos_snapshot.json."""
    from nodes.fetch_repos import fetch_repos

    output_path = args.output or "repos_snapshot.json"
    run_config = {
        **BASE_RUN_CONFIG,
        "db_path": args.db,
        "output_path": output_path,
    }

    if args.interop_types:
        run_config["interop_types"] = [
            item.strip() for item in args.interop_types.split(",") if item.strip()
        ]
    if args.min_stars is not None:
        run_config["min_stars"] = args.min_stars
    if getattr(args, "target_repo_count", None) is not None:
        run_config["target_repo_count"] = args.target_repo_count

    try:
        get_github_tokens_from_env()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    result = fetch_repos(make_initial_state(run_config))
    repos = result.get("repos", [])
    _atomic_write_json(output_path, repos)

    logging.info("fetch-repos complete: %s repos saved to %s", len(repos), output_path)
    return repos


def run_fetch_prs(args):
    """Run PR-level filtering with incremental writes and sidecar-based resume."""
    from graph import build_stage1_pr_graph

    db_path = args.db
    input_path = args.input or "repos_snapshot.json"
    output_path = args.output or "prs_snapshot.json"
    progress_path = derive_progress_path(output_path)
    thread_id = args.thread_id or f"fetch-prs-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config = {"configurable": {"thread_id": thread_id}}

    if not Path(input_path).exists():
        raise SystemExit(f"Input file not found: {input_path}")

    try:
        get_github_tokens_from_env()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    repos = load_json_array(input_path)
    existing_prs = load_json_array(output_path)
    if not Path(output_path).exists():
        _atomic_write_json(output_path, existing_prs)

    run_config = {
        **BASE_RUN_CONFIG,
        "skip_review": not getattr(args, "review", False),
        "db_path": db_path,
        "input_path": input_path,
        "output_path": output_path,
        "progress_path": progress_path,
        "thread_id": thread_id,
        "excluded_prs_path": getattr(args, "excluded_prs", None)
        or BASE_RUN_CONFIG["excluded_prs_path"],
    }

    if getattr(args, "max_prs_per_repo", None) is not None:
        run_config["max_prs_per_repo"] = args.max_prs_per_repo
    if getattr(args, "target_items", None) is not None:
        run_config["target_items"] = _normalize_target_items(args.target_items)
    if args.min_stars is not None:
        run_config["min_stars"] = args.min_stars
    run_config["config_fingerprint"] = build_config_fingerprint(run_config)

    app = build_stage1_pr_graph(db_path=db_path)
    result = app.invoke(make_initial_state(run_config, repos, existing_prs), config)

    approved_keys: list[str] | None = None
    if getattr(args, "review", False) and "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        payload = interrupt_obj.value
        approved_keys = prompt_review(payload["prs_summary"])
        resume_payload = (
            {} if approved_keys is None else {"approved_pr_keys": approved_keys}
        )
        app.invoke(Command(resume=resume_payload), config)

    prs = load_json_array(output_path)
    prs, skipped_prs = filter_excluded_prs(prs, run_config["excluded_prs_path"])
    if skipped_prs:
        _atomic_write_json(output_path, prs)
        logging.info(
            "fetch-prs removed %s excluded PRs from %s",
            len(skipped_prs),
            output_path,
        )
    if getattr(args, "review", False):
        if approved_keys is not None:
            approved_set = set(approved_keys)
            prs = [
                pr for pr in prs if f"{pr['repo']}#{pr['pr_id']}" in approved_set
            ]
        _atomic_write_json(output_path, prs)

    logging.info(
        "fetch-prs complete: %s PRs saved to %s (%s)",
        len(prs),
        output_path,
        progress_path,
    )
    return prs


def run_resume(args):
    """Resume a checkpointed Stage 1 review flow if needed."""
    from graph import build_stage1_pr_graph

    if not args.thread_id:
        raise SystemExit("--thread-id is required for resume mode")

    app = build_stage1_pr_graph(db_path=args.db)
    config = {"configurable": {"thread_id": args.thread_id}}
    return app.invoke(None, config)


def run_single_pr(args):
    from graph import build_pr_subgraph
    from nodes.stage2_utils import summarize_stage2_state

    if not args.pr_json:
        raise SystemExit("--pr-json is required for single-pr mode")

    pr_path = Path(args.pr_json)
    if not pr_path.exists():
        raise SystemExit(f"PR JSON file not found: {args.pr_json}")

    pr = json.loads(pr_path.read_text(encoding="utf-8"))
    excluded_prs_path = getattr(args, "excluded_prs", None) or BASE_RUN_CONFIG["excluded_prs_path"]
    if make_pr_key(pr["repo"], pr["pr_id"]) in load_pr_key_set(excluded_prs_path):
        raise SystemExit(
            f"PR {pr['repo']}#{pr['pr_id']} is marked excluded in {excluded_prs_path}"
        )
    run_config = {
        **BASE_RUN_CONFIG,
        "db_path": args.db,
        "thread_id": args.thread_id or f"single-pr-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "stage2_only": True,
        "enable_compile_repair": False,
        "excluded_prs_path": excluded_prs_path,
    }

    app = build_pr_subgraph(db_path=args.db, stage2_only=True)
    result = asyncio.run(
        app.ainvoke(
            make_initial_pr_state(pr, run_config),
            {"configurable": {"thread_id": run_config["thread_id"]}},
        )
    )
    summary = summarize_stage2_state(result)
    logging.info(
        "single-pr complete: repo=%s pr=%s status=%s reason=%s",
        pr.get("repo"),
        pr.get("pr_id"),
        summary["coarse_status"],
        summary["reason_code"],
    )
    return result


def run_build(args):
    from graph import build_pr_subgraph
    from nodes.stage2_utils import summarize_stage2_state

    input_path = args.input or "prs_snapshot.json"
    output_path = args.output or "output/stage2_results.jsonl"
    prs = load_json_array(input_path)
    excluded_prs_path = getattr(args, "excluded_prs", None) or BASE_RUN_CONFIG["excluded_prs_path"]
    prs, skipped_prs = filter_excluded_prs(prs, excluded_prs_path)
    if skipped_prs:
        logging.info(
            "build skipped %s excluded PRs based on %s",
            len(skipped_prs),
            excluded_prs_path,
        )
    run_config = {
        **BASE_RUN_CONFIG,
        "db_path": args.db,
        "thread_id": args.thread_id or f"build-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "stage2_only": True,
        "enable_compile_repair": False,
        "excluded_prs_path": excluded_prs_path,
    }

    app = build_pr_subgraph(db_path=args.db, stage2_only=True)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    with output_file.open("w", encoding="utf-8") as handle:
        for pr in prs:
            result = asyncio.run(
                app.ainvoke(
                    make_initial_pr_state(pr, run_config),
                    {
                        "configurable": {
                            "thread_id": f"{run_config['thread_id']}-pr{pr['pr_id']}"
                        }
                    },
                )
            )
            summary = summarize_stage2_state(result)
            summaries.append(summary)
            handle.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")

    logging.info("build complete: %s PRs processed into %s", len(summaries), output_path)
    return summaries


def main():
    parser = argparse.ArgumentParser(description="Cross-language Benchmark Pipeline")
    parser.add_argument(
        "--mode",
        choices=["fetch-repos", "fetch-prs", "build", "single-pr", "resume", "full"],
        default="fetch-repos",
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
        "--input",
        help="Input file path for fetch-prs/build modes",
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
        "--target-repo-count",
        type=int,
        help="Target number of candidate repos to collect in fetch-repos mode",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for fetch-repos/fetch-prs modes",
    )
    parser.add_argument(
        "--max-prs-per-repo",
        type=int,
        help="Maximum merged PRs to inspect per repo in fetch-prs mode",
    )
    parser.add_argument(
        "--target-items",
        type=int,
        help="Stop fetch-prs after collecting this many candidate PRs (omit or use 0 for no cap)",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Enable a one-shot in-process human review step",
    )
    parser.add_argument(
        "--pr-json",
        help="Single PR metadata JSON file for single-pr mode",
    )
    parser.add_argument(
        "--excluded-prs",
        help="JSON array file of PRs to permanently exclude; defaults to excluded_prs.json",
    )

    args = parser.parse_args()

    dispatch = {
        "fetch-repos": run_fetch_repos,
        "fetch-prs": run_fetch_prs,
        "build": run_build,
        "single-pr": run_single_pr,
        "resume": run_resume,
    }

    if args.mode in dispatch:
        dispatch[args.mode](args)
        return

    logging.error("Mode %s not yet implemented (Phase 2+)", args.mode)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
