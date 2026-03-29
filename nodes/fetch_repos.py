# nodes/fetch_repos.py
import os, sys, math, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import RepoInfo, BenchmarkState, INTEROP_LAYER_MAP
from github_client import GitHubClient, get_github_tokens_from_env

logger = logging.getLogger(__name__)

# SEARCH_QUERIES for each interop_type:
SEARCH_QUERIES: dict[str, str] = {
    # FFI layer
    "cgo": 'language:Go "import \\"C\\""',
    "jni": 'language:Java "JNIEnv" filename:*.c',
    "ctypes": 'language:Python "ctypes.CDLL" OR "ctypes.cdll"',
    "cffi": 'language:Python "ffi.cdef" OR "cffi.FFI"',
    "rust_ffi": 'language:Rust "extern \\"C\\""',
    "node_napi": 'language:C++ "Napi::" filename:binding.gyp',
    # Runtime embedding layer
    "lua_c": 'language:C "lua_State" "luaL_newstate"',
    "python_cext": 'language:C "PyInit_" "PyArg_ParseTuple"',
    "ruby_cext": 'language:C "rb_define_method" "Init_"',
    "v8_cpp": 'language:C++ "v8::" "8::" OR "Isolate"',
    "wasm": 'language:Rust "#[wasm_bindgen]"',
}


def fetch_repos(state: BenchmarkState) -> dict:
    """
    Node function: Search GitHub for repos with cross-language interop calls.

    Input: state["run_config"]["interop_types"], ["min_stars"], ["target_repo_count"]
    Output: state["repos"] — list[RepoInfo]
    """
    cfg = state["run_config"]
    interop_types: list[str] = cfg.get("interop_types", list(SEARCH_QUERIES.keys()))
    min_stars: int = cfg.get("min_stars", 50)
    target_count: int = cfg.get("target_repo_count", 200)
    db_path: str = cfg.get("db_path", "benchmark_runs.db")
    max_search_passes: int = cfg.get("repo_search_passes", 3)

    # Initialize client (tokens from env vars)
    tokens = get_github_tokens_from_env()
    client = GitHubClient(tokens, cache_db=db_path)

    if not interop_types:
        logger.warning("No interop types configured, fetch_repos returning empty set")
        return {"repos": []}

    # We intentionally over-fetch and retry with larger per-type quotas because
    # cross-type dedup can otherwise leave us well below the requested target.
    base_quota = max(1, math.ceil(target_count / len(interop_types)))
    all_repos: dict[str, RepoInfo] = {}  # key = full_name for dedup

    for pass_idx in range(max_search_passes):
        per_type_quota = min(target_count, base_quota * (2**pass_idx))
        before_count = len(all_repos)
        logger.info(
            "Repo search pass %s/%s with per-type quota %s (target=%s, current=%s)",
            pass_idx + 1,
            max_search_passes,
            per_type_quota,
            target_count,
            before_count,
        )

        for interop_type in interop_types:
            query = SEARCH_QUERIES.get(interop_type)
            if not query:
                logger.warning(f"No search query for {interop_type}, skipping")
                continue

            logger.info(f"Searching {interop_type} repos...")
            repos = client.search_repos(
                query=query,
                min_stars=min_stars,
                max_results=per_type_quota,
            )

            for repo in repos:
                if repo["full_name"] not in all_repos:
                    repo["interop_type"] = interop_type
                    repo["interop_layer"] = INTEROP_LAYER_MAP.get(interop_type, "ffi")
                    all_repos[repo["full_name"]] = repo

            logger.info(
                "  %s: found %s repos this pass, %s unique total",
                interop_type,
                len(repos),
                len(all_repos),
            )

        if len(all_repos) >= target_count:
            logger.info("Reached repo target %s after pass %s", target_count, pass_idx + 1)
            break
        if len(all_repos) == before_count:
            logger.info(
                "Repo search plateaued at %s unique repos after pass %s",
                len(all_repos),
                pass_idx + 1,
            )
            break

    # Sort by stars descending, take top target_count
    result = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
    result = result[:target_count]

    logger.info(f"fetch_repos complete: {len(result)} repos total")
    return {"repos": result}
