# nodes/fetch_prs.py
import os, sys, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import PRMetadata, DiffFile, BenchmarkState
from github_client import GitHubClient

logger = logging.getLogger(__name__)

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
    "wasm": ["#[wasm_bindgen]", "WebAssembly.instantiate", "wasm_bindgen"],
}

# Language pairs expected for each interop_type
INTEROP_LANG_PAIRS: dict[str, set] = {
    "cgo": {"Go", "C"},
    "jni": {"Java", "C"},
    "ctypes": {"Python", "C"},
    "cffi": {"Python", "C"},
    "rust_ffi": {"Rust", "C"},
    "node_napi": {"JavaScript", "C++"},
    "lua_c": {"C", "Lua"},
    "python_cext": {"C", "Python"},
    "ruby_cext": {"C", "Ruby"},
    "wasm": {"Rust", "JavaScript"},
}


def _has_interop_signal(diff_files: list[DiffFile], interop_type: str) -> bool:
    """Check if diff files contain cross-language call signals (language-level check)"""
    langs = set(f["lang"] for f in diff_files)
    expected_pair = INTEROP_LANG_PAIRS.get(interop_type, set())
    # At least 2 languages from expected pair
    return len(langs & expected_pair) >= 2


def fetch_prs(state: BenchmarkState) -> dict:
    """
    Node function: Scan repos for PRs with cross-language calls + test cases.

    Input: state["repos"], state["run_config"]
    Output: append to state["prs"] (Reducer auto-merges)
    """
    cfg = state["run_config"]
    max_prs_per_repo = cfg.get("max_prs_per_repo", 100)
    target_items = cfg.get("target_items", 300)
    min_diff_lines = cfg.get("min_diff_lines", 50)
    max_diff_lines = cfg.get("max_diff_lines", 2000)
    db_path = cfg.get("db_path", "benchmark_runs.db")

    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    client = GitHubClient(tokens, cache_db=db_path)

    found_prs: list[PRMetadata] = []

    for repo_info in state["repos"]:
        # Target-driven: stop if pool is full
        if len(found_prs) >= target_items:
            logger.info(f"Candidate pool reached target {target_items}, stopping")
            break

        repo_name = repo_info["full_name"]
        interop_type = repo_info["interop_type"]
        logger.info(f"Scanning {repo_name} [{interop_type}]...")

        raw_prs = client.list_prs(repo_name, max_n=max_prs_per_repo)

        for raw_pr in raw_prs:
            # C1: Already merged (list_prs filters this)
            diff_files = client.get_pr_files(repo_name, raw_pr["number"])
            if not diff_files:
                continue

            # C2: diff involves >= 2 languages
            langs = set(f["lang"] for f in diff_files)
            if len(langs) < 2:
                continue

            # C3: At least 1 test file
            if not any(f["is_test"] for f in diff_files):
                continue

            # C4: diff line count in reasonable range
            total_lines = sum(f["additions"] + f["deletions"] for f in diff_files)
            if not (min_diff_lines <= total_lines <= max_diff_lines):
                continue

            # C5: Cross-language call signal exists
            if not _has_interop_signal(diff_files, interop_type):
                continue

            # All filters passed
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
            found_prs.append(pr)
            logger.info(f"  ✓ PR #{raw_pr['number']}: {raw_pr['title'][:50]}")

    logger.info(f"fetch_prs complete: {len(found_prs)} candidate PRs found")
    return {"prs": found_prs}
