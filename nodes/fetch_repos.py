# nodes/fetch_repos.py
import os, sys, math, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import RepoInfo, BenchmarkState, INTEROP_LAYER_MAP
from github_client import GitHubClient

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
    target_count: int = cfg.get("target_repo_count", 100)
    db_path: str = cfg.get("db_path", "benchmark_runs.db")

    # Initialize client (tokens from env vars)
    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    client = GitHubClient(tokens, cache_db=db_path)

    # Quota per type
    per_type_quota = math.ceil(target_count / len(interop_types))
    all_repos: dict[str, RepoInfo] = {}  # key = full_name for dedup

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

        logger.info(f"  {interop_type}: found {len(repos)} repos")

    # Sort by stars descending, take top target_count
    result = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
    result = result[:target_count]

    logger.info(f"fetch_repos complete: {len(result)} repos total")
    return {"repos": result}
