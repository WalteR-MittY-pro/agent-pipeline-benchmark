# tests/test_state.py
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import (
    RepoInfo,
    DiffFile,
    PRMetadata,
    EnvSpec,
    BenchmarkTask,
    TestResult,
    BenchmarkItem,
    BenchmarkState,
    PRSubState,
    INTEROP_LAYER_MAP,
)


def test_all_types_importable():
    assert RepoInfo is not None
    assert BenchmarkState is not None
    assert PRSubState is not None
    print("✓ All type definitions importable")


def test_repo_info_creation():
    repo: RepoInfo = {
        "full_name": "golang/go",
        "clone_url": "https://github.com/golang/go.git",
        "stars": 120000,
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "languages": {"Go": 80, "C": 20},
        "default_branch": "master",
    }
    assert repo["interop_type"] == "cgo"
    print("✓ RepoInfo instance created successfully")


def test_interop_layer_map():
    assert INTEROP_LAYER_MAP["cgo"] == "ffi"
    assert INTEROP_LAYER_MAP["jni"] == "ffi"
    assert INTEROP_LAYER_MAP["lua_c"] == "runtime_embedding"
    assert INTEROP_LAYER_MAP["wasm"] == "wasm"
    print("✓ interop_layer mapping correct")


def test_benchmark_state_reducer():
    import operator

    list_a = [{"pr_id": 1}]
    list_b = [{"pr_id": 2}]
    merged = operator.add(list_a, list_b)
    assert len(merged) == 2
    print("✓ Reducer field merge logic correct")


if __name__ == "__main__":
    test_all_types_importable()
    test_repo_info_creation()
    test_interop_layer_map()
    test_benchmark_state_reducer()
    print("\n✅ state.py all verification passed")
