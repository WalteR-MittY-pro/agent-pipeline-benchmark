# state.py
"""
All TypedDict definitions for the cross-language benchmark system.
This is the single source of truth for data contracts across all modules.
"""

from typing import TypedDict, Annotated
import operator


# ─── 1. 仓库信息（fetch_repos 产出）────────────────────────
class RepoInfo(TypedDict):
    full_name: str  # "owner/repo"
    clone_url: str  # HTTPS clone URL
    stars: int  # star 数
    interop_type: str  # 如 "cgo"、"jni"
    interop_layer: str  # "ffi" | "runtime_embedding" | "wasm"
    languages: dict  # {"Go": 60, "C": 40}
    default_branch: str  # "main" 或 "master"


# ─── 2. diff 文件记录（fetch_prs 产出）──────────────────────
class DiffFile(TypedDict):
    path: str  # 相对路径
    lang: str  # "Go"、"C"、"Python" 等
    is_test: bool  # 是否为测试文件
    additions: int  # 新增行数
    deletions: int  # 删除行数
    status: str  # "added" | "modified" | "removed"


# ─── 3. PR 元数据（fetch_prs 产出，Stage 1 最终输出单元）────
class PRMetadata(TypedDict):
    repo: str  # "owner/repo"
    clone_url: str
    pr_id: int
    pr_title: str
    interop_type: str
    interop_layer: str
    base_sha: str
    head_sha: str
    diff_files: list  # list[DiffFile]
    diff_total_lines: int
    test_commands: object  # list[str] | None
    merged_at: str  # ISO 8601


# ─── 4. 构建环境规格（infer_env 产出）───────────────────────
class EnvSpec(TypedDict):
    source: str  # "repo_dockerfile"|"github_actions"|"llm"|"failed"
    base_image: str  # "golang:1.22"
    system_deps: list  # ["gcc", "libssl-dev"]
    build_cmds: list  # ["go build ./..."]
    test_cmds: list  # ["go test -v ./..."]
    test_framework: str  # "go_test"|"pytest"|"junit"|"cargo"|"jest"|"generic"
    dockerfile_content: object  # str | None


# ─── 5. Benchmark 题目（construct_task 产出）────────────────
class BenchmarkTask(TypedDict):
    task_id: str  # "cgo-owner-repo-pr1234-001"
    strategy: str  # "completion" | "generation"
    masked_code: str  # 含 <MASK> 的题目代码
    context_files: dict  # {文件路径: 文件内容}
    ground_truth: str  # 正确答案
    target_file_path: str  # 容器内注入路径，如 "/app/bridge.go"
    mask_ranges: list  # [(start_line, end_line), ...]
    difficulty: str  # "easy" | "medium" | "hard"
    host_lang: str  # "Go"
    target_lang: str  # "C"


# ─── 6. 测试执行结果（parser 产出）─────────────────────────
class TestResult(TypedDict):
    passed: int  # -1 表示无法解析
    failed: int
    errors: int
    total: int
    compile_success: bool
    exit_code: int  # -1 表示超时
    stdout_tail: str  # 最后 100 行


# ─── 7. Benchmark 条目（score 产出，最终输出单元）────────────
class BenchmarkItem(TypedDict):
    id: str
    pr_metadata: dict  # PRMetadata
    task: dict  # BenchmarkTask
    docker_image: str
    generated_code: str
    test_result: dict  # TestResult
    score_total: float  # 0-100
    score_test: float
    score_compile: float
    score_quality: float
    quality_notes: str
    created_at: str


# ─── 8. 主图全局状态（LangGraph BenchmarkState）─────────────
class BenchmarkState(TypedDict):
    run_config: dict  # 运行时配置，不可变
    repos: list  # list[RepoInfo]
    prs: Annotated[list, operator.add]  # Reducer: 并行追加
    benchmark_items: Annotated[list, operator.add]  # Reducer: 并行追加
    errors: Annotated[list, operator.add]  # Reducer: 并行收集


# ─── 9. PR 子图局部状态（PRSubState）────────────────────────
class PRSubState(TypedDict):
    pr: dict  # PRMetadata
    run_config: dict
    env_spec: object  # EnvSpec | None
    dockerfile_path: object  # str | None
    dockerfile_content: object  # str | None
    image_tag: object  # str | None
    build_status: object  # str | None
    build_retries: int
    build_log: object  # str | None
    compile_status: object  # str | None
    compile_repair_rounds: int
    compile_repair_log: object  # str | None
    baseline_test_result: object  # TestResult | None
    task: object  # BenchmarkTask | None
    generated_code: object  # str | None
    llm_tokens_used: int
    test_result: object  # TestResult | None
    benchmark_items: list  # list[BenchmarkItem]
    errors: list


# ─── interop_type 参考枚举（非强制，供查阅）─────────────────
INTEROP_TYPES = {
    "ffi": ["cgo", "jni", "ctypes", "cffi", "rust_ffi", "node_napi"],
    "runtime_embedding": ["lua_c", "python_cext", "ruby_cext", "v8_cpp"],
    "wasm": ["wasm"],
}

INTEROP_LAYER_MAP = {t: layer for layer, types in INTEROP_TYPES.items() for t in types}
