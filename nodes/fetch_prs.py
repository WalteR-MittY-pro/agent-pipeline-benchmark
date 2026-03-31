# nodes/fetch_prs.py
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import PRMetadata, DiffFile, BenchmarkState
from github_client import GitHubClient, get_github_tokens_from_env

logger = logging.getLogger(__name__)
PROGRESS_LOG_INTERVAL = 10

# Keywords for each interop_type to detect cross-language calls
INTEROP_KEYWORDS: dict[str, list[str]] = {
    "cgo": ['import "C"', "CGO_ENABLED", "//export"],
    "jni": ["JNIEnv", "JNIEXPORT", "jclass", "jobject"],
    "ctypes": ["ctypes.cdll", "ctypes.CDLL", "CFUNCTYPE", "ctypes.c_"],
    "cffi": ["ffi.cdef", "ffi.open", "ffi.new"],
    "rust_ffi": ["#[no_mangle]", 'extern "C"'],
    "node_napi": ["Napi::", "NODE_API_MODULE", "#include <napi.h>"],
    "lua_c": ["lua_State", "luaL_newstate", "lua_pcall", "lua_pushstring"],
    "python_cext": ["PyInit_", "PyArg_ParseTuple", "Py_BuildValue", "PyObject"],
    "ruby_cext": ["Init_", "rb_define_method", "VALUE", "rb_intern"],
    "v8_cpp": ["v8::", "Isolate", "FunctionTemplate"],
    "wasm": ["#[wasm_bindgen]", "WebAssembly.instantiate", "wasm_bindgen"],
}

# Host and target language sets expected for each interop_type.
# Stage 1 only has file metadata, so this is a lightweight language-pair check.
INTEROP_LANG_PAIRS: dict[str, tuple[set[str], set[str]]] = {
    "cgo": ({"Go"}, {"C", "C++"}),
    "jni": ({"Java", "Kotlin"}, {"C", "C++"}),
    "ctypes": ({"Python"}, {"C"}),
    "cffi": ({"Python"}, {"C"}),
    "rust_ffi": ({"Rust"}, {"C"}),
    "node_napi": ({"JavaScript", "TypeScript"}, {"C++"}),
    "lua_c": ({"C", "C++"}, {"Lua"}),
    "python_cext": ({"C"}, {"Python"}),
    "ruby_cext": ({"C"}, {"Ruby"}),
    "v8_cpp": ({"C++"}, {"JavaScript", "TypeScript"}),
    "wasm": ({"Rust", "C"}, {"JavaScript", "TypeScript"}),
}


def _has_interop_signal(diff_files: list[DiffFile], interop_type: str) -> bool:
    """Check whether diff files hit the expected host/target language pair."""
    langs = set(f["lang"] for f in diff_files)
    host_langs, target_langs = INTEROP_LANG_PAIRS.get(interop_type, (set(), set()))
    return bool(langs & host_langs) and bool(langs & target_langs)


def _scan_key(repo: str, head_sha: str) -> str:
    """Stable resume key for one evaluated PR head."""
    return f"{repo}@{head_sha}"


def _atomic_write_json(path: str, payload: object) -> None:
    """Atomically replace a JSON file so interrupted writes do not corrupt it."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = tmp.name

    os.replace(temp_path, target)


def _load_progress(progress_path: str | None) -> dict:
    defaults = {
        "completed_repos": [],
        "scanned_pr_keys": [],
        "config_fingerprint": None,
        "input_path": None,
        "output_path": None,
    }
    if not progress_path:
        return defaults

    path = Path(progress_path)
    if not path.exists():
        return defaults

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return defaults

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{progress_path} is not a valid progress JSON object")

    return {
        **defaults,
        **data,
        "completed_repos": list(data.get("completed_repos", [])),
        "scanned_pr_keys": list(data.get("scanned_pr_keys", [])),
    }


def _build_config_fingerprint(cfg: dict) -> str:
    """Fingerprint the PR scan parameters that affect filtering."""
    relevant = {
        "max_prs_per_repo": cfg.get("max_prs_per_repo"),
        "target_items": _normalize_target_items(cfg.get("target_items")),
        "min_diff_lines": cfg.get("min_diff_lines"),
        "max_diff_lines": cfg.get("max_diff_lines"),
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalize_target_items(value: object) -> int | None:
    if value is None:
        return None
    try:
        target_items = int(value)
    except (TypeError, ValueError):
        return None
    return target_items if target_items > 0 else None


def _format_candidate_progress(candidate_count: int, target_items: int | None) -> str:
    if target_items is None:
        return f"{candidate_count} (unbounded)"
    return f"{candidate_count}/{target_items}"


def _has_reached_target_items(candidate_count: int, target_items: int | None) -> bool:
    return target_items is not None and candidate_count >= target_items


def _allows_legacy_default_target_items_migration(
    saved_fingerprint: str | None,
    cfg: dict,
) -> bool:
    if not saved_fingerprint or _normalize_target_items(cfg.get("target_items")) is not None:
        return False

    legacy_cfg = dict(cfg)
    legacy_cfg["target_items"] = 300
    return saved_fingerprint == _build_config_fingerprint(legacy_cfg)


def _save_progress(
    progress_path: str | None,
    input_path: str | None,
    output_path: str | None,
    completed_repos: list[str],
    scanned_pr_keys: list[str],
    config_fingerprint: str,
) -> None:
    if not progress_path:
        return

    _atomic_write_json(
        progress_path,
        {
            "input_path": input_path,
            "output_path": output_path,
            "completed_repos": completed_repos,
            "scanned_pr_keys": scanned_pr_keys,
            "config_fingerprint": config_fingerprint,
            "updated_at": datetime.now().isoformat(),
        },
    )


def _percentage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return (numerator / denominator) * 100.0


def _render_progress_bar(percent: float, width: int = 20) -> str:
    clamped = max(0.0, min(100.0, percent))
    filled = min(width, max(0, round((clamped / 100.0) * width)))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _log_scan_progress(
    repo_name: str,
    total_repos: int,
    completed_repo_count: int,
    repo_pr_done: int,
    repo_pr_total: int,
    candidate_count: int,
    target_items: int | None,
) -> None:
    overall_units_done = completed_repo_count
    if repo_pr_total > 0:
        overall_units_done += repo_pr_done / repo_pr_total
    overall_percent = _percentage(overall_units_done, total_repos)
    repo_percent = _percentage(repo_pr_done, repo_pr_total)
    logger.info(
        "Progress %s %.1f%% | repos %s/%s complete | current repo %s %s %.1f%% "
        "(PRs %s/%s) | candidates %s",
        _render_progress_bar(overall_percent, width=24),
        overall_percent,
        completed_repo_count,
        total_repos,
        repo_name,
        _render_progress_bar(repo_percent, width=16),
        repo_percent,
        repo_pr_done,
        repo_pr_total,
        _format_candidate_progress(candidate_count, target_items),
    )


def _should_log_repo_progress(repo_pr_done: int, repo_pr_total: int) -> bool:
    if repo_pr_total <= 0:
        return False
    return (
        repo_pr_done == 1
        or repo_pr_done == repo_pr_total
        or repo_pr_done % PROGRESS_LOG_INTERVAL == 0
    )


def fetch_prs(state: BenchmarkState) -> dict:
    """
    Node function: Scan repos for PRs with cross-language calls + test cases.

    Input: state["repos"], state["run_config"]
    Output: append only newly found PRs to state["prs"] (Reducer auto-merges)
    """
    cfg = state["run_config"]
    max_prs_per_repo = cfg.get("max_prs_per_repo", 100)
    target_items = _normalize_target_items(cfg.get("target_items"))
    min_diff_lines = cfg.get("min_diff_lines", 50)
    max_diff_lines = cfg.get("max_diff_lines", 2000)
    db_path = cfg.get("db_path", "benchmark_runs.db")
    input_path = cfg.get("input_path")
    output_path = cfg.get("output_path")
    progress_path = cfg.get("progress_path")
    config_fingerprint = cfg.get("config_fingerprint") or _build_config_fingerprint(cfg)

    progress = _load_progress(progress_path)
    saved_fingerprint = progress.get("config_fingerprint")
    if saved_fingerprint not in (None, config_fingerprint):
        if _allows_legacy_default_target_items_migration(saved_fingerprint, cfg):
            logger.info(
                "Upgrading fetch-prs progress file from the legacy default "
                "target_items=300 fingerprint to the new unbounded default"
            )
        else:
            raise RuntimeError(
                "Current fetch-prs parameters do not match the existing progress file. "
                "Remove the old progress file or choose a new output path."
            )

    saved_input_path = progress.get("input_path")
    if saved_input_path not in (None, "", input_path):
        raise RuntimeError(
            "Current fetch-prs input path does not match the existing progress file."
        )

    saved_output_path = progress.get("output_path")
    if saved_output_path not in (None, "", output_path):
        raise RuntimeError(
            "Current fetch-prs output path does not match the existing progress file."
        )

    completed_repos = list(progress.get("completed_repos", []))
    completed_repo_set = set(completed_repos)
    scanned_pr_keys = list(progress.get("scanned_pr_keys", []))
    scanned_pr_key_set = set(scanned_pr_keys)

    persisted_prs: list[PRMetadata] = list(state.get("prs", []))
    persisted_pr_keys = {
        _scan_key(pr["repo"], pr["head_sha"]) for pr in persisted_prs
    }
    total_repos = len(state["repos"])

    logger.info(
        "fetch-prs start: total repos %s | resumed %s %.1f%% (%s/%s repos) | "
        "scanned PR commits %s | existing candidates %s",
        total_repos,
        _render_progress_bar(_percentage(len(completed_repo_set), total_repos), width=24),
        _percentage(len(completed_repo_set), total_repos),
        len(completed_repo_set),
        total_repos,
        len(scanned_pr_key_set | persisted_pr_keys),
        _format_candidate_progress(len(persisted_prs), target_items),
    )

    _save_progress(
        progress_path,
        input_path,
        output_path,
        completed_repos,
        scanned_pr_keys,
        config_fingerprint,
    )

    if _has_reached_target_items(len(persisted_prs), target_items):
        logger.info(
            "Candidate pool already has %s PRs, reaching target %s",
            len(persisted_prs),
            target_items,
        )
        return {"prs": []}

    tokens = get_github_tokens_from_env()
    client = GitHubClient(tokens, cache_db=db_path)

    found_prs: list[PRMetadata] = []
    stop_scanning = False

    for repo_info in state["repos"]:
        if stop_scanning:
            break

        # Target-driven: stop if pool is full
        if _has_reached_target_items(len(persisted_prs), target_items):
            logger.info("Candidate pool reached target %s, stopping", target_items)
            break

        repo_name = repo_info["full_name"]
        if repo_name in completed_repo_set:
            logger.info("Skipping completed repo %s", repo_name)
            continue

        interop_type = repo_info["interop_type"]
        logger.info(
            "Scanning %s [%s]... overall %s %.1f%% (%s/%s repos complete)",
            repo_name,
            interop_type,
            _render_progress_bar(_percentage(len(completed_repo_set), total_repos), width=24),
            _percentage(len(completed_repo_set), total_repos),
            len(completed_repo_set),
            total_repos,
        )

        raw_prs = client.list_prs(repo_name, max_n=max_prs_per_repo)
        repo_completed = True
        repo_pr_total = len(raw_prs)
        repo_pr_done = 0

        if repo_pr_total == 0:
            logger.info(
                "Repo %s has 0 merged PRs to inspect under current max_prs_per_repo=%s",
                repo_name,
                max_prs_per_repo,
            )

        for raw_pr in raw_prs:
            repo_pr_done += 1
            scan_key = _scan_key(repo_name, raw_pr["head_sha"])
            if scan_key in scanned_pr_key_set or scan_key in persisted_pr_keys:
                if _should_log_repo_progress(repo_pr_done, repo_pr_total):
                    _log_scan_progress(
                        repo_name,
                        total_repos,
                        len(completed_repo_set),
                        repo_pr_done,
                        repo_pr_total,
                        len(persisted_prs),
                        target_items,
                    )
                continue

            # C1: Already merged (list_prs filters this)
            diff_files = client.get_pr_files(repo_name, raw_pr["number"])
            passed = False
            total_lines = 0
            if diff_files:
                langs = set(f["lang"] for f in diff_files)
                total_lines = sum(f["additions"] + f["deletions"] for f in diff_files)
                passed = (
                    len(langs) >= 2
                    and any(f["is_test"] for f in diff_files)
                    and min_diff_lines <= total_lines <= max_diff_lines
                    and _has_interop_signal(diff_files, interop_type)
                )

            if passed:
                pr: PRMetadata = {
                    "repo": repo_name,
                    "clone_url": repo_info["clone_url"],
                    "pr_id": raw_pr["number"],
                    "pr_title": raw_pr["title"],
                    "interop_type": interop_type,
                    "interop_layer": repo_info["interop_layer"],
                    "base_sha": raw_pr["base_sha"],
                    "head_sha": raw_pr["head_sha"],
                    "diff_files": diff_files,
                    "diff_total_lines": total_lines,
                    "test_commands": None,  # Filled by infer_env
                    "merged_at": raw_pr["merged_at"],
                }
                persisted_prs.append(pr)
                found_prs.append(pr)
                persisted_pr_keys.add(scan_key)
                if output_path:
                    _atomic_write_json(output_path, persisted_prs)
                logger.info(
                    "  ✓ PR #%s matched and was written to the snapshot",
                    raw_pr["number"],
                )

            scanned_pr_keys.append(scan_key)
            scanned_pr_key_set.add(scan_key)
            _save_progress(
                progress_path,
                input_path,
                output_path,
                completed_repos,
                scanned_pr_keys,
                config_fingerprint,
            )

            if _should_log_repo_progress(repo_pr_done, repo_pr_total):
                _log_scan_progress(
                    repo_name,
                    total_repos,
                    len(completed_repo_set),
                    repo_pr_done,
                    repo_pr_total,
                    len(persisted_prs),
                    target_items,
                )

            if _has_reached_target_items(len(persisted_prs), target_items):
                repo_completed = False
                stop_scanning = True
                break

        if repo_completed and repo_name not in completed_repo_set:
            completed_repos.append(repo_name)
            completed_repo_set.add(repo_name)
            _save_progress(
                progress_path,
                input_path,
                output_path,
                completed_repos,
                scanned_pr_keys,
                config_fingerprint,
            )
            logger.info(
                "Completed repo %s: %s %.1f%% overall (%s/%s repos complete), "
                "candidates %s",
                repo_name,
                _render_progress_bar(
                    _percentage(len(completed_repo_set), total_repos), width=24
                ),
                _percentage(len(completed_repo_set), total_repos),
                len(completed_repo_set),
                total_repos,
                _format_candidate_progress(len(persisted_prs), target_items),
            )

    logger.info(f"fetch_prs complete: {len(found_prs)} candidate PRs found")
    return {"prs": found_prs}
