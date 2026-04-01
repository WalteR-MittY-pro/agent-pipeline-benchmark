# DESIGN.md — 跨语言能力 Benchmark 系统开发设计文档

> **文档版本：** v0.1  
> **状态：** 草稿，待专家评审  
> **用途：** 供开发人员实现各功能模块、供专家评审系统设计合理性  
> **配套文档：** `AGENT.md`（项目规范）、`discussion.md`（学术论证）

---

## 目录

1. [系统概述](#一系统概述)
2. [数据类型规范](#二数据类型规范)
3. [模块：`state.py`](#三模块statepy)
4. [模块：`github_client.py`](#四模块github_clientpy)
5. [模块：`graph.py`](#五模块graphpy)（含并发控制）
6. [模块组：`nodes/`](#六模块组nodes)（含 `compile_verify` 新节点）
7. [模块组：`parsers/`](#七模块组parsers)
8. [模块：`main.py`](#八模块mainpy)
9. [配置参考](#九配置参考)
10. [错误处理策略](#十错误处理策略)
11. [模块间接口契约](#十一模块间接口契约)
12. [测试规范](#十二测试规范)
13. [待定事项](#十三待定事项)

---

## 一、系统概述

### 1.1 系统目标

自动从 GitHub 公开仓库中筛选含**进程内跨语言互操作调用**且**带有测试用例**的 PR，构建一个用于评测大语言模型跨语言代码生成能力的 Benchmark 数据集。

### 1.2 核心评测问题

给定真实 PR 的跨语言调用上下文（函数签名、头文件、接口定义、运行时 API），目标模型能否生成正确的胶水代码，使原有测试用例通过？

### 1.3 系统边界

**纳入范围（进程内互操作，三层）：**

| 层次 | interop_layer | 代表技术 |
|---|---|---|
| ABI 层 | `ffi` | CGo、JNI、ctypes/cffi、Rust FFI、Node N-API |
| 运行时层 | `runtime_embedding` | Lua↔C、Python C Extension、Ruby C Extension |
| 字节码层 | `wasm` | Rust/C → .wasm + JS host |

**排除范围：** gRPC/REST/Thrift（协议层）、Subprocess/IPC（系统层）、JVM/CLR 多语言（同一运行时）。

### 1.4 技术栈

| 组件 | 技术选择 |
|---|---|
| Agent 编排框架 | LangGraph 0.2+ |
| 语言运行时 | Python 3.11+ |
| Checkpoint 存储 | SQLite（本地开发）|
| GitHub 访问 | PyGithub + 2 token 轮换 + SQLite 缓存 |
| 容器构建 | Docker CLI（asyncio 异步调用）|
| Dockerfile 模板 | Jinja2 |
| 测试框架 | pytest |

### 1.5 整体数据流

```
GitHub API
    │
    ▼
fetch_repos ──► fetch_prs ──► human_review
                                   │ Send() × N（每个 PR 一个并行实例）
                                   │ 并发数受 DOCKER_SEMAPHORE 限制（默认 4）
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              [PR 子图 A]    [PR 子图 B]    [PR 子图 C...]
              infer_env      infer_env      infer_env
              build_dockerfile              ...
              docker_build         ← 只构建镜像，不编译源码
              compile_verify       ← 容器内编译+测试baseline，含LLM修复循环
              construct_task       ← mask胶水代码，三步有效性验证
              llm_generate
              run_tests            ← 注入生成代码，重新编译，执行测试
              score
                    │              │              │
                    └──────────────┼──────────────┘
                                   │ Reducer 合并
                                   ▼
                            aggregate_results
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
        benchmark_dataset.json          summary_report.md
```

### 1.6 Stage 1 的两层筛选职责

Stage 1 必须明确分成两层，避免把 repo 查询条件和 PR 查询条件混在一起：

- **Repo 层（`fetch_repos`）= 粗召回**
  - 目标：找到“仓库层面疑似存在某类跨语言互操作代码”的候选仓库。
  - 手段：使用 `SEARCH_QUERIES` 这类**源码搜索信号**回收仓库；这些 query 是 repo-level recall signal，不是 PR-level filter。
  - 输出：`RepoInfo` 列表，只回答“这个仓库值不值得继续扫描 PR”。

- **PR 层（`fetch_prs`）= 精筛**
  - 目标：在候选仓库中找到真正适合作为 benchmark 样本的 merged PR。
  - 手段：检查 merged 状态、测试文件、diff 行数、跨语言信号等。
  - 输出：`PRMetadata` 列表，作为 Stage 1 的最终产物。

- **人工审核层（`human_review`）= 可选后置过滤**
  - 目标：让研究者在写出 `prs_snapshot.json` 之前，手动排除明显噪音样本。
  - 手段：仅在显式开启 review 时暂停一次；默认关闭。

### 1.7 Stage 1 分阶段执行、增量持久化与断点恢复

Stage 1 改为两个显式步骤执行，而不是一次 `fetch` 把 repo 召回和 PR 精筛绑在一起：

- **步骤 A：`fetch-repos`**
  - 负责 repo-level 粗召回。
  - 输出 `repos_snapshot.json`，格式为 `list[RepoInfo]`。
  - 这是 `fetch-prs` 的唯一输入来源。

- **步骤 B：`fetch-prs`**
  - 负责读取 `repos_snapshot.json`，逐仓库扫描 merged PR 并做 PR-level 精筛。
  - 输出 `prs_snapshot.json`，格式保持为 `list[PRMetadata]`。
  - 每当发现 1 条符合条件的 PR，都要立即原子写回 `prs_snapshot.json`，不能等整个进程结束后再统一写出。

`fetch-prs` 的长时恢复依赖一个 sidecar 进度文件，例如 `prs_snapshot.progress.json`：

- **进度文件字段**
  - `input_path`：本次 PR 扫描所用的 `repos_snapshot.json`
  - `output_path`：本次累计输出的 `prs_snapshot.json`
  - `completed_repos`：已经完整扫描完的 repo 名称列表
  - `scanned_pr_keys`：已经判定过的 PR 键集合
  - `config_fingerprint`：与筛选参数绑定的指纹，防止换参数后误续跑
  - `updated_at`：最近一次落盘时间

- **PR 去重 / 恢复键**
  - 键格式：`"{repo}@{head_sha}"`。
  - 即“repo 名称 + PR head commit id”，例如 `owner/repo@abc123...`。
  - 该键用于表示“这个 repo 的这个 PR 版本已经评估过”，无论最终是否通过筛选，都可安全跳过。

- **落盘顺序**
  - PR 通过筛选：
    1. 先把 `PRMetadata` 追加到 `prs_snapshot.json`
    2. 再把 `repo@head_sha` 写入 `scanned_pr_keys`
  - PR 未通过筛选：
    1. 不改 `prs_snapshot.json`
    2. 只把 `repo@head_sha` 写入 `scanned_pr_keys`
  - 某个 repo 全部 PR 扫描结束后，再把 repo 名称写入 `completed_repos`

- **为什么必须按这个顺序**
  - 若进程在“PR 已写入快照，但进度还没更新”时中断，下次启动仍可通过读取 `prs_snapshot.json` 的现有 `head_sha` 去重，避免重复写入。
  - 若先写进度、后写快照，则一旦中断，可能会把一个本应保留的 PR 永久跳过。

- **恢复规则**
  - 重复执行 `python main.py --mode fetch-prs --input repos_snapshot.json --output prs_snapshot.json` 时：
    - `completed_repos` 中的 repo 直接跳过
    - 未完成 repo 会重新取一次 `list_prs(repo)`，但已存在于 `scanned_pr_keys` 的 `repo@head_sha` 直接跳过
    - 已存在于 `prs_snapshot.json` 的 `repo@head_sha` 也必须参与去重，避免“快照已写、进度未写”导致重复追加
    - 若 `config_fingerprint` 仅因历史默认值从 `target_items=300` 升级为“默认无上限”而不同，允许自动兼容迁移并继续扫描

### 1.8 新方案与上一版方案对比

上一版方案是“单一 `fetch` + repo 粒度 sidecar”；新方案是“`fetch-repos` / `fetch-prs` 分阶段执行 + `repo@head_sha` 粒度恢复”。

| 对比项 | 旧方案：repo 粒度 | 新方案：repo+commit 粒度 |
|---|---|---|
| Stage 1 执行方式 | 一个 `fetch` 包办 repo + PR | `fetch-repos` 和 `fetch-prs` 分开执行 |
| 中断后恢复粒度 | 只能跳过已完成 repo | 可跳过已完成 repo，也可跳过 repo 内已扫描过的 PR commit |
| 中断时重复工作 | 若在大 repo 中途失败，整 repo 常常要重扫 | 仅重扫未处理到的 `head_sha` |
| 产物复用 | repo 召回结果不易单独复用 | `repos_snapshot.json` 可反复用于不同的 PR 扫描轮次 |
| 复杂度 | 较低 | 略高，需要维护 `completed_repos` + `scanned_pr_keys` |

**可行性判断：高。**

原因：
- 当前项目已经有独立的 `fetch_repos` 和 `fetch_prs` 节点，实现上天然适合拆开执行。
- `list_prs()` 当前已经返回 `head_sha`，足以直接构造 `repo@head_sha` 键。
- 当前已有 JSON 落盘和 SQLite 缓存基础设施，只需把“单次最终写出”改成“分阶段输入输出 + 增量落盘 + sidecar 续跑”。

**相对上一版的主要优势：**
- 更适合长时间扫描任务，尤其是 PR 数量很多的大 repo。
- `fetch-repos` 和 `fetch-prs` 职责更清晰，方便单独复用和调试。
- `repo@head_sha` 的恢复粒度更细，中断成本明显更低。

**代价：**
- 文档、CLI 和进度文件管理会更复杂。
- 若更改了 `fetch-prs` 的筛选参数，通常必须基于 `config_fingerprint` 拒绝错误续跑或要求用户清理旧 progress。
- 当前仅对一条历史兼容路径做特判：保存的 progress 若来自旧默认 `target_items=300`，而当前运行使用新的“默认无上限”，则允许自动迁移。

---

## 二、数据类型规范

所有核心数据类型定义在 `state.py`，本节为完整规范，包含每个字段的类型、取值约束和语义说明。

### 2.1 `RepoInfo`

仓库筛选结果，由 `fetch_repos` 生成。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `full_name` | `str` | ✅ | `"owner/repo"` 格式 |
| `clone_url` | `str` | ✅ | HTTPS clone URL |
| `stars` | `int` | ✅ | Star 数量，用于质量过滤 |
| `interop_type` | `str` | ✅ | 触发该仓库的搜索查询类型，见 §2.5 |
| `interop_layer` | `str` | ✅ | `"ffi"` \| `"runtime_embedding"` \| `"wasm"` |
| `languages` | `dict[str, int]` | ✅ | 各语言代码占比，如 `{"Go": 60, "C": 40}` |
| `default_branch` | `str` | ✅ | 默认分支名，通常为 `"main"` 或 `"master"` |

### 2.2 `DiffFile`

PR diff 中的单个文件记录，由 `fetch_prs` 生成。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `path` | `str` | ✅ | 文件路径，相对于仓库根目录 |
| `lang` | `str` | ✅ | 文件语言，如 `"Go"` `"C"` `"Python"` |
| `is_test` | `bool` | ✅ | 是否为测试文件（按路径和命名规则判断） |
| `additions` | `int` | ✅ | 新增行数 |
| `deletions` | `int` | ✅ | 删除行数 |
| `status` | `str` | ✅ | `"added"` \| `"modified"` \| `"removed"` |

### 2.3 `PRMetadata`

筛选后的 PR 完整元数据，Stage 1 的最终输出单元。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `repo` | `str` | ✅ | `"owner/repo"` |
| `clone_url` | `str` | ✅ | HTTPS clone URL |
| `pr_id` | `int` | ✅ | GitHub PR number |
| `pr_title` | `str` | ✅ | PR 标题，用于人工审核参考 |
| `interop_type` | `str` | ✅ | 具体互操作技术，见 §2.5 |
| `interop_layer` | `str` | ✅ | `"ffi"` \| `"runtime_embedding"` \| `"wasm"` |
| `base_sha` | `str` | ✅ | PR 基础 commit SHA（修改前） |
| `head_sha` | `str` | ✅ | PR 头部 commit SHA（修改后） |
| `diff_files` | `list[DiffFile]` | ✅ | diff 涉及的所有文件 |
| `diff_total_lines` | `int` | ✅ | diff 总行数（additions + deletions） |
| `test_commands` | `list[str] \| None` | ❌ | 已知的测试命令（来自 CI 或 README），None 表示未知 |
| `merged_at` | `str` | ✅ | ISO 8601 格式，如 `"2024-03-01T10:00:00Z"` |

### 2.4 `EnvSpec`

构建环境推断结果，由 `infer_env` 生成，供 `build_dockerfile` 和 `run_tests` 使用。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | `str` | ✅ | `"repo_dockerfile"` \| `"github_actions"` \| `"llm"` \| `"failed"` |
| `base_image` | `str` | ✅ | Docker base image，如 `"golang:1.22"` |
| `system_deps` | `list[str]` | ✅ | apt-get 依赖列表，如 `["gcc", "libssl-dev"]` |
| `build_cmds` | `list[str]` | ✅ | 构建命令列表，如 `["go build ./..."]` |
| `test_cmds` | `list[str]` | ✅ | 测试命令列表，如 `["go test -v ./..."]` |
| `test_framework` | `str` | ✅ | `"go_test"` \| `"pytest"` \| `"junit"` \| `"cargo"` \| `"jest"` \| `"generic"` |
| `dockerfile_content` | `str \| None` | ❌ | 仅 `source="repo_dockerfile"` 时有值，其余为 None |

### 2.5 `interop_type` 取值枚举

| `interop_type` | `interop_layer` | 宿主语言 | 被调用方 |
|---|---|---|---|
| `"cgo"` | `"ffi"` | Go | C/C++ |
| `"jni"` | `"ffi"` | Java/Kotlin | C/C++ |
| `"ctypes"` | `"ffi"` | Python | C |
| `"cffi"` | `"ffi"` | Python | C |
| `"rust_ffi"` | `"ffi"` | Rust | C |
| `"node_napi"` | `"ffi"` | Node.js | C++ |
| `"lua_c"` | `"runtime_embedding"` | C/C++ | Lua VM |
| `"python_cext"` | `"runtime_embedding"` | C/C++ | CPython |
| `"ruby_cext"` | `"runtime_embedding"` | C | CRuby MRI |
| `"wasm"` | `"wasm"` | JavaScript | Rust/C (.wasm) |

### 2.6 `BenchmarkTask`

从 PR diff 构造的 benchmark 题目，由 `construct_task` 生成。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | `str` | ✅ | 唯一标识，格式：`"{interop_type}-{repo_slug}-pr{pr_id}-{seq}"` |
| `strategy` | `str` | ✅ | `"completion"` \| `"generation"` |
| `masked_code` | `str` | ✅ | 给 LLM 的题目，跨语言调用片段被 `<MASK>` 替换 |
| `context_files` | `dict[str, str]` | ✅ | 上下文文件内容，`{文件路径: 文件内容}` |
| `ground_truth` | `str` | ✅ | 原始 PR 中的正确代码（head_sha 对应版本） |
| `target_file_path` | `str` | ✅ | 容器内需注入代码的文件路径 |
| `mask_ranges` | `list[tuple[int,int]]` | ✅ | 被遮盖的行号范围列表，如 `[(12, 18), (24, 24)]` |
| `difficulty` | `str` | ✅ | `"easy"` \| `"medium"` \| `"hard"` |
| `host_lang` | `str` | ✅ | 宿主语言，如 `"Go"` |
| `target_lang` | `str` | ✅ | 被调用方语言，如 `"C"` |

**难度判定规则：**

| 难度 | 条件 |
|---|---|
| `easy` | mask 行数 ≤ 10，单函数调用，无内存管理关键字 |
| `medium` | mask 行数 11–30，或涉及类型转换，或多函数调用 |
| `hard` | mask 行数 > 30，或包含内存管理（`free`/`malloc`/`unsafe`），或涉及回调/错误传递 |

### 2.7 `TestResult`

测试执行结果，由 parser 生成，供 `score` 使用。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `passed` | `int` | ✅ | 通过的测试用例数，-1 表示无法解析 |
| `failed` | `int` | ✅ | 失败的测试用例数，-1 表示无法解析 |
| `errors` | `int` | ✅ | 错误的测试用例数（运行时崩溃），-1 表示无法解析 |
| `total` | `int` | ✅ | 总测试用例数，-1 表示无法解析 |
| `compile_success` | `bool` | ✅ | 是否编译/构建成功 |
| `exit_code` | `int` | ✅ | 容器进程退出码，0=成功，-1=超时 |
| `stdout_tail` | `str` | ✅ | 测试输出的最后 100 行，用于调试 |

### 2.8 `BenchmarkItem`

完整的 benchmark 条目，Stage 2+3 的最终输出单元，写入 `benchmark_dataset.json`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | `str` | ✅ | 与 `task_id` 相同 |
| `pr_metadata` | `PRMetadata` | ✅ | 完整 PR 元数据 |
| `task` | `BenchmarkTask` | ✅ | 题目内容 |
| `docker_image` | `str` | ✅ | 已构建的 Docker 镜像 tag |
| `generated_code` | `str` | ✅ | 目标 LLM 生成的代码 |
| `test_result` | `TestResult` | ✅ | 测试执行结果 |
| `score_total` | `float` | ✅ | 综合得分 0–100 |
| `score_test` | `float` | ✅ | 测试通过率得分 0–100（权重 60%）|
| `score_compile` | `float` | ✅ | 编译成功得分 0 或 100（权重 20%）|
| `score_quality` | `float` | ✅ | 代码质量得分 0–100（权重 20%，LLM-as-judge）|
| `quality_notes` | `str` | ✅ | LLM judge 的评语 |
| `created_at` | `str` | ✅ | ISO 8601 生成时间 |

### 2.9 `BenchmarkState`（主图状态）

LangGraph 主图的全局共享状态，各节点通过读写此对象交换数据。

| 字段 | 类型 | Reducer | 说明 |
|---|---|---|---|
| `run_config` | `dict` | 无（不可变） | 运行时配置，见 §九 |
| `repos` | `list[RepoInfo]` | 无（覆盖） | fetch_repos 产出 |
| `prs` | `list[PRMetadata]` | `operator.add` | 支持并行追加 |
| `benchmark_items` | `list[BenchmarkItem]` | `operator.add` | 支持并行子图追加 |
| `errors` | `list[dict]` | `operator.add` | 支持并行错误收集 |

### 2.10 `PRSubState`（子图状态）

每个 PR 子图实例的局部状态，不与主图直接共享，通过 `Send()` 初始化，通过 Reducer 回写主图。

| 字段 | 类型 | 初始值 | 说明 |
|---|---|---|---|
| `pr` | `PRMetadata` | Send() 注入 | 当前处理的 PR |
| `run_config` | `dict` | Send() 注入 | 运行时配置 |
| `env_spec` | `EnvSpec \| None` | None | infer_env 填充 |
| `dockerfile_path` | `str \| None` | None | build_dockerfile 填充 |
| `dockerfile_content` | `str \| None` | None | build_dockerfile 填充 |
| `image_tag` | `str \| None` | None | 格式：`"benchmark-{repo_slug}-pr{pr_id}"` |
| `build_status` | `str \| None` | None | `"success"` \| `"failed"` |
| `build_retries` | `int` | 0 | 已重试次数 |
| `build_log` | `str \| None` | None | 最后 50 行构建日志 |
| `compile_status` | `str \| None` | None | `"success"` \| `"failed"` \| `"repaired"` |
| `compile_repair_rounds` | `int` | 0 | LLM 修复循环已执行轮数（最多 2）|
| `compile_repair_log` | `str \| None` | None | 修复过程日志，供调试 |
| `baseline_test_result` | `TestResult \| None` | None | HEAD 完整代码的基线测试结果 |
| `task` | `BenchmarkTask \| None` | None | construct_task 填充 |
| `generated_code` | `str \| None` | None | llm_generate 填充 |
| `llm_tokens_used` | `int` | 0 | token 用量统计 |
| `test_result` | `TestResult \| None` | None | run_tests 填充 |

---

## 三、模块：`state.py`

**职责：** 定义系统中所有数据类型，是其他所有模块共同依赖的唯一数据契约文件。

**无函数，只有类型定义。** 所有 TypedDict 子类见 §二。

**引用关系：** 被所有节点、`github_client.py`、`graph.py`、`main.py`、parsers 导入。

```
state.py
  ├── RepoInfo
  ├── DiffFile
  ├── PRMetadata
  ├── EnvSpec
  ├── BenchmarkTask
  ├── TestResult
  ├── BenchmarkItem
  ├── BenchmarkState
  └── PRSubState
```

---

## 四、模块：`github_client.py`

**职责：** 封装所有 GitHub API 访问逻辑，对上层节点屏蔽 token 轮换、限速、缓存细节。节点只调用此模块的方法，不直接操作 GitHub API。

### 4.1 类：`GitHubClient`

#### `__init__`

```
输入：
  tokens: list[str]       — GitHub Personal Access Token 列表（至少 1 个）
  cache_db: str           — SQLite 缓存数据库路径，默认 "benchmark_runs.db"
  min_request_interval: float — 两次请求之间的最小间隔秒数，默认 2.0
  
输出：
  GitHubClient 实例
  
副作用：
  初始化 PyGithub 客户端列表
  初始化 SQLite 缓存连接（若不存在则建表）
  初始化 token 轮换计数器
```

#### `search_repos`

```
功能：根据源码搜索信号回收候选仓库，带缓存

输入：
  query: str              — GitHub 代码搜索查询字符串（repo-level recall signal，不是 PR 条件）
  min_stars: int          — 最低 star 数过滤，默认 50
  max_results: int        — 最多返回结果数，默认 30
  
输出：
  list[RepoInfo]          — 仓库列表，按 star 数降序

实现要求：
  对 query 执行代码搜索（或等价的“按源码命中回收仓库”逻辑），
  从命中的文件项中提取所属 repo，按 full_name 去重，
  再应用 min_stars 过滤与排序。
  
缓存策略：
  key = hash(query + min_stars)
  TTL = 24 小时
  命中缓存则直接返回，不消耗 API quota
  
错误处理：
  RateLimitExceededException → 自动切换到下一个 token，sleep 60s 后重试
  GithubException(status=422) → 查询语法错误，raise ValueError
  连续 3 次失败 → 返回空列表，写入错误日志
```

#### `list_prs`

```
功能：列出仓库的已合并 PR，按 merged_at 倒序

输入：
  repo_full_name: str     — "owner/repo"
  max_n: int              — 最多返回数量，默认 100
  
输出：
  list[dict]              — GitHub PR 原始数据列表（未转换为 PRMetadata）
  字段包含：number, title, merged_at, base.sha, head.sha
  
缓存策略：
  key = f"prs:{repo_full_name}"
  TTL = 6 小时
  
错误处理：
  404 → 仓库不存在或无权限，返回空列表
  RateLimitExceededException → token 轮换，重试
```

#### `get_pr_files`

```
功能：获取指定 PR 的 diff 文件列表

输入：
  repo_full_name: str     — "owner/repo"
  pr_number: int          — PR number
  
输出：
  list[DiffFile]          — diff 文件列表
  
缓存策略：
  key = f"pr_files:{repo_full_name}:{pr_number}"
  TTL = 永久（PR merge 后不变）
  
错误处理：
  404 → 返回空列表
```

#### `get_file_content`

```
功能：获取指定 commit 下某文件的内容

输入：
  repo_full_name: str     — "owner/repo"
  sha: str                — commit SHA
  file_path: str          — 文件路径（相对于仓库根目录）
  
输出：
  str                     — 文件内容（UTF-8 解码）
  
缓存策略：
  key = f"file:{repo_full_name}:{sha}:{file_path}"
  TTL = 永久（内容由 sha 唯一确定，不可变）
  
错误处理：
  404 → 文件不存在，返回空字符串 ""
  文件过大（> 1MB）→ 返回空字符串，写入警告日志
  二进制文件（解码失败）→ 返回空字符串
```

#### `get_repo_tree`

```
功能：获取仓库在某 commit 下的文件树（只含路径列表，不含内容）

输入：
  repo_full_name: str     — "owner/repo"
  sha: str                — commit SHA
  
输出：
  list[str]               — 文件路径列表，相对于仓库根目录
  
缓存策略：
  key = f"tree:{repo_full_name}:{sha}"
  TTL = 永久
  
错误处理：
  超时（> 30s）→ 返回空列表
```

#### `list_workflow_files`

```
功能：列出仓库 .github/workflows/ 目录下的所有 YAML 文件内容

输入：
  repo_full_name: str     — "owner/repo"
  sha: str                — commit SHA
  
输出：
  list[str]               — 每个 workflow 文件的内容字符串列表
  
缓存策略：
  key = f"workflows:{repo_full_name}:{sha}"
  TTL = 永久
```

### 4.2 Token 轮换内部机制

```
内部状态：
  _tokens: list[Github]    — PyGithub 客户端列表
  _current_idx: int        — 当前使用的 token 索引
  _request_counts: list[int] — 各 token 本小时请求次数

轮换触发条件：
  1. 收到 RateLimitExceededException
  2. 当前 token 请求数超过阈值（4800/5000，留 200 余量）

轮换逻辑：
  _current_idx = (_current_idx + 1) % len(_tokens)
  如果轮换一圈后仍受限，sleep min(remaining_reset_time, 300)
```

---

## 五、模块：`graph.py`

**职责：** 定义并编译 LangGraph 主图和 PR 子图，是系统的编排层。

### 5.1 函数：`build_graph`

```
功能：构建并编译 LangGraph 主图

输入：
  db_path: str            — checkpoint 数据库路径，默认 "benchmark_runs.db"
  
输出：
  CompiledGraph           — 已编译的主图，可直接调用 invoke/stream

图结构：
  节点：fetch_repos → fetch_prs → human_review → process_pr（×N，并行）→ aggregate
  条件边：human_review 通过 Send() fan-out 到每个 PR 的子图实例
  
编译参数：
  checkpointer = SqliteSaver.from_conn_string(db_path)
  不设置 interrupt_before
  human_review 节点内部的 interrupt() 是唯一人工审核暂停点
  `full` 模式仍可使用主图串联 Stage 1 → Stage 2+3
  但日常 Stage 1 推荐使用分离的 `fetch-repos` / `fetch-prs` CLI
  `fetch-prs` 的长时恢复优先依赖 `repos_snapshot.json` + `prs_snapshot.json` + progress sidecar
  checkpointer 主要保留给人工审核和后续阶段，不再是 Stage 1 唯一恢复手段
```

### 5.2 函数：`build_pr_subgraph`

```
功能：构建并编译单个 PR 处理子图

输入：无

输出：
  CompiledGraph           — PR 子图，接受 PRSubState 作为初始状态

图结构：
  infer_env → build_dockerfile → docker_build
                                      │
                              route_after_build（条件边）
                              ├── "compile_verify" → compile_verify
                              ├── "docker_build"   → docker_build（重试）
                              └── END              → 跳过（镜像构建失败）

  compile_verify
      │
  route_after_compile（条件边）
  ├── "construct_task" → construct_task（编译+baseline测试通过）
  ├── "compile_verify" → compile_verify（LLM修复后重试，最多2轮）
  └── END             → 跳过（编译无法修复）

  construct_task → llm_generate → run_tests → score → END
```

### 5.3 函数：`route_after_build`

```
功能：docker_build 节点的条件边路由函数（镜像构建层）

输入：
  state: PRSubState
  
输出：
  str                     — 下一节点名称或 END
  
路由逻辑：
  state["build_status"] == "success"        → "compile_verify"
  state["build_retries"] < 3                → "docker_build"（重试构建镜像）
  else                                      → END（放弃，计入 errors）
```

### 5.4 函数：`route_after_compile`

```
功能：compile_verify 节点的条件边路由函数（容器内编译层）

输入：
  state: PRSubState
  
输出：
  str                     — 下一节点名称或 END
  
路由逻辑：
  state["compile_status"] in ["success","repaired"]  → "construct_task"
  state["compile_repair_rounds"] < 2                 → "compile_verify"（LLM修复重试）
  else                                               → END（放弃，计入 errors）
```

### 5.5 函数：`fan_out_prs`

```
功能：human_review 节点的条件边函数，将 PR 列表分发为并行子任务

输入：
  state: BenchmarkState
  
输出：
  list[Send]              — 每个 PR 对应一个 Send("process_pr", pr_sub_state)
  
说明：
  每个 Send 的初始 state 包含：
    pr: PRMetadata         — 对应 PR 的元数据
    run_config: dict       — 完整运行时配置
    其余 PRSubState 字段   — 各字段初始化为 None / 0
```

### 5.6 全局并发控制：`DOCKER_SEMAPHORE`

```
背景：
  LangGraph 的 Send() 会启动 N 个并行子图实例（N = PR 数量）。
  若不加限制，数百个实例同时执行 docker build 和 docker run，
  本地资源（CPU、内存、磁盘 I/O）会立即耗尽。

设计：
  在 graph.py 模块级别定义全局异步信号量：
    DOCKER_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOCKER)
  
  MAX_CONCURRENT_DOCKER 默认值建议：
    本地开发机（8 核 16GB）  → 3
    专用构建机（16 核 64GB） → 6
    云端实例（待定）         → 10–20
  通过 run_config["max_concurrent_docker"] 覆盖默认值。

使用范围（所有 Docker 操作必须在此 Semaphore 下执行）：
  docker_build.py  — docker build 命令
  compile_verify.py — docker run（容器内编译）
  run_tests.py     — docker run（测试执行）

使用方式：
  async with DOCKER_SEMAPHORE:
      proc = await asyncio.create_subprocess_exec("docker", ...)

注意：
  infer_env、construct_task、llm_generate 不需要此 Semaphore（无 Docker 操作）。
  Semaphore 限制的是"同时活跃的 Docker 操作数"，
  不影响其他阶段的并行性——LangGraph 仍然并行处理所有 PR 的 infer_env。
```

---

## 六、模块组：`nodes/`

**说明：** 每个节点函数的签名统一为 `def node_name(state: XState) -> dict`，返回的 dict 只包含需要更新的字段。

---

### 6.1 `nodes/fetch_repos.py`

#### 函数：`fetch_repos`

```
功能：通过 GitHub 代码搜索做 repo-level 粗召回，筛选“仓库层面疑似包含跨语言互操作代码”的候选仓库

输入（从 state 读取）：
  state["run_config"]["interop_types"]   list[str]  — 目标类型列表
  state["run_config"]["min_stars"]       int        — 最低 star 数，默认 50
  state["run_config"]["target_repo_count"] int      — 目标仓库数，默认 100

输出（写入 state）：
  state["repos"]  list[RepoInfo]  — 所有类型合并、去重后的仓库列表

处理逻辑：
  1. 遍历 run_config["interop_types"]，每种类型构造对应 search query
  2. 对每种类型执行**源码搜索**，从命中的代码文件回收所属仓库；每种类型最多取 ceil(target/len(types)) 个
  3. 按 full_name 去重（同一仓库可能被多个 query 命中）
  4. 按 stars 降序排列
  5. 截取前 target_repo_count 个返回

职责边界：
  fetch_repos 只负责 repo-level 粗召回，不判断某个具体 PR 是否可做 benchmark。
  测试文件、merged 状态、diff 行数、PR 级 interop 信号都由 fetch_prs 负责。

作为独立 CLI 步骤时：
  `fetch-repos` 模式会将返回结果原子写入 `repos_snapshot.json`
  该文件可被后续多次 `fetch-prs` 复用，无需重复做 repo 搜索

异常处理：
  所有查询失败 → raise RuntimeError("fetch_repos: all queries failed")
  部分查询失败 → 继续其他查询，失败的写入日志

预期耗时：约 5–15 分钟（受 API 限速影响）
```

---

### 6.2 `nodes/fetch_prs.py`

#### 函数：`fetch_prs`

```
功能：对候选仓库扫描 merged PR，做 PR-level 精筛，筛选含跨语言调用+测试用例的样本

输入（从 state 读取）：
  state["repos"]                          list[RepoInfo]
  state["run_config"]["max_prs_per_repo"] int   — 每仓库最多扫描数，默认 100
  state["run_config"]["target_items"]     int | None — 候选池目标总数；默认 None（无上限）
  state["run_config"]["min_diff_lines"]   int   — diff 最少行数，默认 50
  state["run_config"]["max_diff_lines"]   int   — diff 最多行数，默认 2000
  state["run_config"]["input_path"]       str   — `repos_snapshot.json` 路径
  state["run_config"]["output_path"]      str   — `prs_snapshot.json` 路径
  state["run_config"]["progress_path"]    str   — `fetch-prs` 进度 sidecar 路径
  state["run_config"]["config_fingerprint"] str — 当前筛选参数指纹

输出（写入 state）：
  state["prs"]  list[PRMetadata]  — 本次运行新发现的 PR 列表（append）

副作用（PR 粒度持久化）：
  每完成 1 个 PR 的判定：
    1. 若通过筛选，立即将该 `PRMetadata` 原子追加到 output_path
    2. 无论通过与否，都将 `repo@head_sha` 写入 progress_path.scanned_pr_keys
  每完成 1 个 repo 的扫描：
    1. 将 repo_name 写入 progress_path.completed_repos

PR 筛选条件（全部满足才通过）：
  C1: PR 状态为 merged
  C2: diff 涉及 ≥ 2 种不同语言的文件
  C3: diff 文件中至少 1 个 is_test=True（测试文件判定见下）
  C4: diff 总行数在 [min_diff_lines, max_diff_lines] 范围内
  C5: diff 中存在轻量跨语言调用信号（至少命中该 interop_type 的宿主/目标语言组合；如成本可接受，可再结合路径/关键字做补强）

测试文件判定规则（满足任一即为 is_test=True）：
  - 路径包含 "test/" 或 "tests/" 或 "spec/"
  - 文件名匹配 *_test.go、*_test.py、*.test.ts、*.spec.js、Test*.java
  - 路径包含 "__tests__"

跨语言调用信号关键字（按 interop_type）：
  cgo:         "import \"C\"", "CGO_ENABLED", "//export"
  jni:         "JNIEnv", "JNIEXPORT", "jclass", "jobject"
  ctypes:      "ctypes.cdll", "ctypes.CDLL", "CFUNCTYPE"
  cffi:        "ffi.cdef", "ffi.open", "ffi.new"
  rust_ffi:    "#[no_mangle]", "extern \"C\"", "unsafe"
  node_napi:   "Napi::", "NODE_API_MODULE", "#include <napi.h>"
  lua_c:       "lua_State", "luaL_newstate", "lua_pcall"
  python_cext: "PyInit_", "PyArg_ParseTuple", "Py_BuildValue"
  ruby_cext:   "Init_", "rb_define_method", "VALUE"
  v8_cpp:      "v8::", "Isolate", "FunctionTemplate"
  wasm:        "#[wasm_bindgen]", "WebAssembly.instantiate"

Stage 1 宿主/目标语言对（用于轻量信号判断）：
  cgo       → Go + C/C++
  jni       → Java/Kotlin + C/C++
  ctypes    → Python + C
  cffi      → Python + C
  rust_ffi  → Rust + C
  node_napi → JavaScript/TypeScript + C++
  lua_c     → C/C++ + Lua
  python_cext → C + Python
  ruby_cext → C + Ruby
  v8_cpp    → C++ + JavaScript/TypeScript
  wasm      → Rust/C + JavaScript/TypeScript

目标驱动停止逻辑：
  仅当 target_items is not None 且全局候选池 >= target_items 时停止扫描，剩余仓库跳过
  每个仓库达到 per_repo_cap（待定，暂不限制）时跳过该仓库

断点续扫逻辑：
  run_fetch_prs 启动时先读取 input_path 对应的 `repos_snapshot.json`
  同时读取已有 output_path，并将其中已有 PR 的 `repo@head_sha` 纳入去重集合
  fetch_prs 启动时读取 progress_path.completed_repos 和 progress_path.scanned_pr_keys
  completed_repos 中的 repo 直接跳过
  未完成 repo 中，命中 `repo@head_sha` 的 PR 直接跳过
  若 progress_path.config_fingerprint 与当前参数不一致，通常必须拒绝续跑并提示清理或重建 progress
  唯一兼容例外：若保存的 fingerprint 对应旧默认 `target_items=300`，而当前运行使用新的默认无上限模式，则允许自动继续，并在下一次保存 progress 时升级到新 fingerprint
  build 模式只读取 `prs_snapshot.json`；progress sidecar 仅供 `fetch-prs` 使用

职责边界：
  fetch_prs 负责把 repo 候选池收缩为“真正可进入后续阶段的 PR 候选池”。
  它是 Stage 1 的主要精筛步骤；human_review 只是可选的人工后置过滤。

输出字段（PRMetadata）字段填充来源：
  repo, clone_url           — 来自 RepoInfo
  pr_id, pr_title           — 来自 GitHub PR API
  interop_type/layer        — 继承自 RepoInfo
  base_sha, head_sha        — 来自 GitHub PR API
  diff_files                — 来自 github_client.get_pr_files()
  diff_total_lines          — 计算自 diff_files
  test_commands             — 暂设为 None（由 infer_env 填充）
  merged_at                 — 来自 GitHub PR API

预期耗时：约 2–6 小时（100 仓库 × 100 PR）
```

---

### 6.3 `nodes/human_review.py`

#### 函数：`human_review`

```
功能：可选的人工审核节点，默认关闭；开启时在节点内部暂停一次，等待同一进程内的人类确认 PR 列表

输入（从 state 读取）：
  state["prs"]                            list[PRMetadata]
  state["run_config"]["skip_review"]      bool  — True 时直接跳过（默认值）

输出（写入 state）：
  state["prs"]  list[PRMetadata]  — 过滤后的 PR 列表
  （若 skip_review=True 则 return {}，state 不变）

interrupt 暴露的数据：
  {
    "message": str,                — 人工审核提示
    "total_count": int,            — 总数
    "by_interop_type": dict,       — 按类型分组的统计
    "by_interop_layer": dict,      — 按层次分组的统计
    "prs_summary": [
      {
        "review_key": str,         — 复合唯一键，格式 "owner/repo#123"
        "repo": str,
        "pr_id": int,
        "title": str,
        "type": str
      }, ...
    ]
  }

恢复方式（同进程一次性审核）：
  from langgraph.types import Command
  app.invoke(Command(resume={"approved_pr_keys": ["owner/repo#123", ...]}), config)

若 approved_pr_keys 未提供 → 默认全部批准（保持原列表不变）

约束：
  不再在 compile() 中配置 interrupt_before=["human_review"]；
  human_review 节点内部的 interrupt() 是唯一暂停点，避免重复中断。
```

---

### 6.4 `nodes/infer_env.py`

#### 函数：`infer_env`

```
功能：推断 PR 对应仓库的构建环境，按四层降级策略输出 EnvSpec

输入（从 state 读取）：
  state["pr"]             PRMetadata
  state["run_config"]["llm_model"]  str  — 用于第三层 LLM 推断的模型

输出（写入 state）：
  state["env_spec"]  EnvSpec

四层降级策略（按顺序尝试，命中即返回）：

  第一层 — 仓库自带 Dockerfile（预期覆盖 ~30%）：
    检查路径：["Dockerfile", "docker/Dockerfile", ".docker/Dockerfile"]
    命中后：
      - 读取 Dockerfile 内容
      - 调用 patch_cmd_to_test() 替换 CMD/ENTRYPOINT
      - 设置 source="repo_dockerfile", dockerfile_content=patched_content
      - 从 Dockerfile 内容提取 test_framework（正则匹配 pytest/cargo/jest 等）
      - 返回 EnvSpec

  第二层 — GitHub Actions workflow 提取（预期覆盖 ~50%）：
    读取 .github/workflows/*.yml 所有文件
    解析规则：
      - 提取所有 "run: apt-get install" 步骤 → system_deps
      - 提取含 "build" 关键字的 run 步骤 → build_cmds
      - 提取含 "test" 关键字的 run 步骤 → test_cmds
    命中条件：test_cmds 非空
    matrix build 处理：取 matrix.os 列表第一个 ubuntu 版本

  第三层 — LLM 综合推断（预期覆盖 ~12%）：
    构造 prompt context：
      {
        "interop_type": state["pr"]["interop_type"],
        "lang_config_files": {文件名: 文件内容},  # go.mod/Cargo.toml/pom.xml/pyproject.toml
        "makefile": makefile_content 或 None,
        "readme_build_section": readme 中 Build/Install 章节（前 200 行）,
        "diff_file_list": [path for f in diff_files]
      }
    Prompt 要求 LLM 输出 JSON 格式的 EnvSpec，字段含义见 §2.4
    设置 source="llm"
    LLM 返回解析失败 → 进入第四层

  第四层 — 跳过：
    写入 state["errors"]：
      {"pr_id": ..., "repo": ..., "stage": "infer_env", "reason": "all_layers_failed"}
    返回 {"env_spec": EnvSpec(source="failed", ...), "build_status": "failed"}
    子图将在 route_after_build 处走 END 分支

辅助函数（模块内部）：

  patch_cmd_to_test(dockerfile_content: str, test_cmds: list[str]) -> str
    输入：Dockerfile 原始内容，测试命令列表
    输出：替换了 CMD/ENTRYPOINT 行的 Dockerfile 内容
    逻辑：找到最后一个 CMD 或 ENTRYPOINT 行，替换为 CMD test_cmds[0]
          若未找到，在末尾追加 CMD

  extract_apt_installs(workflow_content: str) -> list[str]
    输入：workflow YAML 文件内容
    输出：所有 apt-get install 的包名列表，去重
    正则：r'apt-get install -y (.+)'，提取并分割空格

  extract_run_steps(workflow_content: str, kind: str) -> list[str]
    输入：workflow YAML 内容，kind 为 "build" 或 "test"
    输出：包含 kind 关键字的 run 步骤命令列表

  detect_test_framework(content: str, interop_type: str) -> str
    输入：配置文件内容（go.mod/requirements.txt/pom.xml 等），interop_type
    输出：test_framework 字符串
    规则：
      interop_type in [cgo, rust_ffi]       → 无需检测，直接返回 "go_test"/"cargo"
      Python 类型：检测 requirements/pyproject 中 pytest/unittest → "pytest"/"generic"
      Java 类型：检测 pom.xml/build.gradle 中 junit/testng → "junit"
      node_napi：检测 package.json 中 jest/mocha → "jest"/"generic"
      wasm：默认 "jest"
      未检测到 → "generic"
```

---

### 6.5 `nodes/build_dockerfile.py`

#### 函数：`build_dockerfile`

```
功能：根据 EnvSpec 生成 Dockerfile 文件并写入临时目录

输入（从 state 读取）：
  state["pr"]             PRMetadata  — 提供 interop_type, clone_url, head_sha
  state["env_spec"]       EnvSpec     — 提供 source, base_image, system_deps 等

输出（写入 state）：
  state["dockerfile_path"]     str    — Dockerfile 文件的绝对路径
  state["dockerfile_content"]  str    — Dockerfile 文本内容
  state["image_tag"]           str    — Docker 镜像 tag

image_tag 格式：
  "benchmark-{owner}-{repo}-pr{pr_id}".lower().replace("/", "-")
  示例："benchmark-golang-go-pr12345"

分支逻辑：
  env_spec["source"] == "repo_dockerfile"：
    → dockerfile_content = env_spec["dockerfile_content"]（已在 infer_env 中 patch）
  
  其他 source：
    → 读取 dockerfiles/templates/{interop_type}.dockerfile.j2
    → 渲染 Jinja2 模板，传入以下变量：
        base_image:  env_spec["base_image"]
        system_deps: env_spec["system_deps"]
        clone_url:   pr["clone_url"]
        head_sha:    pr["head_sha"]
        build_cmds:  env_spec["build_cmds"]
        test_cmds:   env_spec["test_cmds"]

写入路径：
  /tmp/benchmark/{image_tag}/Dockerfile
  若目录不存在则创建

错误处理：
  模板文件不存在 → raise FileNotFoundError，写入 errors，跳过该 PR
  Jinja2 渲染失败 → raise，写入 errors，跳过该 PR
```

---

### 6.6 `nodes/docker_build.py`

#### 异步函数：`docker_build`

```
功能：执行 docker build 命令，带重试和日志捕获

输入（从 state 读取）：
  state["dockerfile_path"]  str
  state["image_tag"]        str
  state["build_retries"]    int  — 已重试次数

输出（写入 state）：
  state["build_status"]     str  — "success" | "failed"
  state["build_retries"]    int  — 递增后的重试次数
  state["build_log"]        str  — 最后 50 行构建日志

执行命令：
  docker build \
    -t {image_tag} \
    -f {dockerfile_path} \
    --no-cache \
    $(dirname {dockerfile_path})

超时：600 秒（10 分钟）

成功条件：
  exit_code == 0

失败处理：
  exit_code != 0 → build_status = "failed", build_retries += 1
  写入 errors：
    {"pr_id":..., "repo":..., "stage":"docker_build",
     "attempt": build_retries, "log_tail": build_log[-2000:]}

注意：重试逻辑由 route_after_build 控制（见 §5.3），本节点本身不循环。
路由函数检测 build_retries < 3 时回到本节点，实现最多 3 次重试。
```

---

### 6.7 `nodes/compile_verify.py` *(新增节点)*

#### 异步函数：`compile_verify`

```
功能：在已构建的 Docker 镜像中执行源码编译和 baseline 测试，验证 HEAD 状态完全可用。
      若编译失败，启动 LLM 修复循环（最多 2 轮），修复 Dockerfile 并重新 build。

背景：
  docker_build 成功仅代表 Docker 镜像构建完成（依赖安装正常）。
  本节点进一步验证：
    1. 仓库源码在容器内能否正确编译
    2. HEAD 状态下的测试用例是否全部通过（baseline）
  两者都通过，才能进入 construct_task 构建题目。

输入（从 state 读取）：
  state["image_tag"]                str
  state["env_spec"]                 EnvSpec   — build_cmds, test_cmds, test_framework
  state["compile_repair_rounds"]    int       — 已修复轮数，初始 0
  state["dockerfile_content"]       str       — 当前 Dockerfile 内容（修复时需要修改）
  state["run_config"]["llm_model"]  str       — LLM 修复用的模型

输出（写入 state）：
  state["compile_status"]           str       — "success" | "failed" | "repaired"
  state["compile_repair_rounds"]    int       — 递增
  state["compile_repair_log"]       str       — 修复过程记录
  state["baseline_test_result"]     TestResult — HEAD 完整代码的测试结果
  state["dockerfile_content"]       str       — 修复后的 Dockerfile（若发生修复）

执行流程：

  步骤 1 — 容器内编译（async，受 DOCKER_SEMAPHORE 控制）：
    container_id = docker run -d --rm {image_tag} sleep infinity
    for cmd in env_spec["build_cmds"]:
        stdout, exit_code = await exec_in_container(container_id, cmd)
        if exit_code != 0:
            编译失败 → 进入 LLM 修复逻辑（步骤 3）
    docker stop {container_id}

  步骤 2 — 容器内 baseline 测试（编译成功后）：
    container_id = docker run -d --rm {image_tag} sleep infinity
    stdout, exit_code = await exec_in_container(container_id, env_spec["test_cmds"])
    baseline_test_result = get_parser(env_spec["test_framework"]).parse(stdout, exit_code)
    docker stop {container_id}
    
    if baseline_test_result["failed"] > 0:
        写入 errors（reason: "baseline_tests_failing"）
        compile_status = "failed"
        → route_after_compile 将走 END
    else:
        compile_status = "success"
        → route_after_compile 将走 construct_task

  步骤 3 — LLM 修复循环（编译失败时）：
    if compile_repair_rounds >= 2:
        写入 errors（reason: "compile_unrecoverable"）
        compile_status = "failed"
        return  # route_after_compile 将走 END
    
    将以下内容喂给 LLM：
      {
        "error_message": 编译 stderr（最后 100 行）,
        "current_dockerfile": state["dockerfile_content"],
        "interop_type": state["pr"]["interop_type"],
        "round": compile_repair_rounds + 1
      }
    Prompt：
      以下 Dockerfile 构建后，在容器内执行 {build_cmd} 时报错。
      请修改 Dockerfile（只能修改系统依赖安装或构建参数，不能修改源码）。
      只返回修复后的完整 Dockerfile，不要解释。
      错误信息：{error_message}
      当前 Dockerfile：{current_dockerfile}
    
    LLM 输出 → 新的 Dockerfile 内容
    重新执行 docker build（使用新 Dockerfile）
    compile_repair_rounds += 1
    
    若 docker build 成功 → compile_status = "repaired"，回到步骤 1 验证编译
    若 docker build 失败 → compile_status = "failed"，route 走 compile_verify 再试一轮

关键约束：
  LLM 修复只允许修改 Dockerfile 中的系统依赖和构建参数。
  不允许修改仓库源码（不能注入 git patch）。
  修复的本质是调整构建环境，而非修改被测代码。
```

---

### 6.8 `nodes/construct_task.py` *(已更新)*

#### 函数：`construct_task`

```
功能：将 PR 的跨语言胶水代码 mask 掉，构造 BenchmarkTask。
      包含三步有效性验证，确保每道题目的质量。

核心原则：
  只 mask 胶水代码（桥接代码），不 mask 业务逻辑。
  判断标准：mask 范围内必须包含 FFI/互操作关键字（见 §6.2 信号关键字表）。
  详细学术论证见 discussion.md §五。

输入（从 state 读取）：
  state["pr"]                              PRMetadata
  state["env_spec"]                        EnvSpec
  state["image_tag"]                       str        — 已通过 compile_verify 的镜像
  state["baseline_test_result"]            TestResult — compile_verify 产出的基线结果
  state["run_config"]["task_strategy"]     str        — "completion" | "generation"

输出（写入 state）：
  state["task"]  BenchmarkTask | None
  （若验证失败则 task = None，route 到 END）

=== 三步有效性验证（任一步失败则跳过该 PR）===

  验证步骤 0 — 确认 baseline 已通过（前置条件）：
    使用 compile_verify 产出的 baseline_test_result
    baseline_test_result["failed"] > 0 → 不应到达此处（compile_verify 已过滤）
    baseline_passed = baseline_test_result["passed"]

  验证步骤 1 — 识别胶水代码，生成 masked_code：
    扫描 diff 涉及的非测试文件，按 interop_type 的关键字列表定位桥接函数
    提取 mask_ranges（需遮盖的行号范围）
    
    质量检查：
      mask_ranges 覆盖的代码行中，含 FFI 关键字的行占比 >= 50%
      否则判定为业务逻辑代码，换更窄的 mask 范围重试
      仍不满足 → skip（reason: "mask_not_interop_code"）
    
    生成 masked_code：将 mask_ranges 对应代码替换为 "<MASK>"

  验证步骤 2 — 注入 masked_code，确认测试失败：
    启动容器，将 masked_code 注入 target_file_path（替换原文件）
    重新编译（build_cmds）
    运行测试（test_cmds）
    
    期望：测试失败（masked_result["passed"] < baseline_passed）
    若测试仍全部通过 → mask 的代码不在关键路径上，尝试更大粒度 mask
    两次尝试仍通过 → skip（reason: "mask_ineffective"）
    若编译失败 → mask 破坏了语法，调整 mask 边界，重试一次
    编译仍失败 → skip（reason: "mask_breaks_compilation"）

  验证步骤 3 — 注入 ground_truth，确认测试恢复通过（健全性检查）：
    将原始 head_sha 代码注入容器，重新编译，运行测试
    期望：passed == baseline_passed
    若不一致 → 数据异常，skip（reason: "ground_truth_invalid"）

=== 仅三步全部通过才生成 BenchmarkTask ===

BenchmarkTask 字段填充：
  task_id        = "{interop_type}-{owner}-{repo}-pr{pr_id}-{seq:03d}"
  strategy       = run_config["task_strategy"]
  masked_code    = 步骤 1 生成的带 <MASK> 的代码
  context_files  = {
      "*.h 头文件": 内容,            ← 提供 C/C++ 接口定义
      "测试文件":   内容,            ← 让模型理解预期行为
      "接口定义文件": 内容（若有）   ← .proto/.idl 等
  }
  ground_truth   = head_sha 对应文件中 mask_ranges 的原始代码
  target_file_path = 容器内需注入的文件绝对路径（如 "/app/bridge.go"）
  mask_ranges    = 步骤 1 确定的行号范围
  difficulty     = 按 §2.6 规则计算
  host_lang      = 宿主语言
  target_lang    = 被调用方语言

异常处理：
  验证失败的 PR 写入 errors，reason 见上方各步骤说明
  所有失败都不中断其他并行 PR 的处理
```

---

### 6.8 `nodes/llm_generate.py`

#### 异步函数：`llm_generate`

```
功能：构造 Prompt 并调用被测 LLM，获取跨语言代码生成结果

输入（从 state 读取）：
  state["task"]                           BenchmarkTask
  state["run_config"]["target_llm"]       str  — 被测模型标识，如 "claude-sonnet-4-20250514"
  state["run_config"]["target_llm_key"]   str  — API Key（从环境变量读取）

输出（写入 state）：
  state["generated_code"]   str   — 提取后的纯代码（去除 markdown 代码块标记）
  state["llm_tokens_used"]  int   — 本次调用消耗的 token 数

Prompt 结构：

  [System]
  你是一位跨语言系统编程专家，精通 {host_lang} 与 {target_lang} 的互操作编程。
  你的任务是补全给定代码中的 <MASK> 部分。只输出需要填入的代码，不要解释，不要包含其他内容。

  [User]
  ## 上下文文件
  {for path, content in context_files.items()}
  ### {path}
  ```
  {content}
  ```
  {endfor}

  ## 待补全代码
  ```{host_lang_lower}
  {masked_code}
  ```

  请直接输出 <MASK> 部分的代码内容：

输出后处理：
  1. 提取 ```...``` 代码块内容（若存在）
  2. 去除首尾空白行
  3. 若无代码块标记，取完整响应内容

超时：60 秒
温度：0（保证可重复性）
max_tokens：2048

错误处理：
  超时或 API 错误 → generated_code = ""，写入 errors
  generated_code 为空 → 写入 errors（reason: "empty_generation"）

注意：
  本节点的模型标识通过 run_config 注入，切换被测模型只需修改配置，无需改代码。
  API Key 从环境变量读取：TARGET_LLM_API_KEY（不进 run_config，避免日志泄露）。
```

---

### 6.9 `nodes/run_tests.py` *(已更新)*

#### 异步函数：`run_tests`

```
功能：将 LLM 生成的代码注入 Docker 容器中的正确源文件路径，
      重新编译，执行测试，返回结构化结果。

重要说明：
  注入的是源文件（如 bridge.go），不是二进制文件。
  注入后必须重新编译，因为替换的是源码，编译产物需要更新。
  编译失败和测试失败是两种不同结果，需要分别记录。

输入（从 state 读取）：
  state["image_tag"]             str
  state["generated_code"]        str        — LLM 生成的纯代码（已去除 markdown 标记）
  state["task"]                  BenchmarkTask  — 提供 target_file_path, host_lang
  state["env_spec"]              EnvSpec    — 提供 build_cmds, test_cmds, test_framework

输出（写入 state）：
  state["test_result"]  TestResult

执行流程（整体受 DOCKER_SEMAPHORE 控制）：

  步骤 1 — 启动容器（detach 模式，保持运行等待注入）：
    container_id = await run_cmd(
        f"docker run -d --rm {image_tag} sleep infinity"
    )

  步骤 2 — 将生成代码写入本地临时文件（使用正确扩展名）：
    suffix = LANG_TO_SUFFIX[state["task"]["host_lang"]]
    # 例：Go → ".go"，Python → ".py"，Java → ".java"，Rust → ".rs"
    local_tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    local_tmp.write(state["generated_code"].encode("utf-8"))
    local_tmp.close()

  步骤 3 — docker cp 注入到容器内的原始源文件路径（完全替换）：
    target_path = state["task"]["target_file_path"]
    # 例："/app/bridge.go" 或 "/app/src/ffi/wrapper.py"
    await run_cmd(f"docker cp {local_tmp.name} {container_id}:{target_path}")
    os.unlink(local_tmp.name)

  步骤 4 — 容器内重新编译（必须，源文件已被替换）：
    for cmd in env_spec["build_cmds"]:
        stdout, exit_code = await exec_in_container(container_id, cmd, timeout=120)
        if exit_code != 0:
            编译失败 → 直接返回：
            TestResult(
                compile_success=False, exit_code=exit_code,
                passed=0, failed=0, errors=0, total=0,
                stdout_tail=last_100_lines(stdout)
            )
            docker stop {container_id}
            return

  步骤 5 — 执行测试命令（编译成功后）：
    test_cmd = " && ".join(env_spec["test_cmds"])
    stdout, exit_code = await exec_in_container(
        container_id, test_cmd, timeout=300
    )

  步骤 6 — Parser 解析测试结果：
    parser = get_parser(env_spec["test_framework"])
    test_result = parser.parse(stdout, exit_code)
    test_result["compile_success"] = True  # 走到这里说明编译成功

  步骤 7 — 清理容器：
    await run_cmd(f"docker stop {container_id}")
    # --rm 参数确保容器停止后自动删除

整体超时：420 秒（含编译 120s + 测试 300s）
超时处理：
  docker stop {container_id}
  返回 TestResult(compile_success=False, exit_code=-1, ...)

辅助常量：
  LANG_TO_SUFFIX = {
      "Go": ".go", "Python": ".py", "Java": ".java",
      "Rust": ".rs", "JavaScript": ".js", "TypeScript": ".ts",
      "C": ".c", "C++": ".cpp", "Ruby": ".rb", "Lua": ".lua"
  }

辅助函数：

  exec_in_container(container_id: str, cmd: str, timeout: int) -> tuple[str, int]
    输入：容器 ID，单条命令字符串，超时秒数
    输出：(stdout + stderr 合并, exit_code)
    实现：docker exec -i {container_id} sh -c "{cmd}"
    超时后 kill exec 进程，返回 exit_code=-1

  last_100_lines(text: str) -> str
    输入：任意文本
    输出：最后 100 行，用于 stdout_tail 字段
```

---

### 6.10 `nodes/score.py`

#### 函数：`score`

```
功能：综合评分，生成最终 BenchmarkItem 并写入主图状态

输入（从 state 读取）：
  state["pr"]                           PRMetadata
  state["task"]                         BenchmarkTask
  state["generated_code"]               str
  state["test_result"]                  TestResult
  state["image_tag"]                    str
  state["run_config"]["judge_llm"]      str  — 评分模型标识
  state["run_config"]["judge_llm_key"]  str  — 从环境变量读取

输出（写入 state）：
  追加到主图的 state["benchmark_items"]  list[BenchmarkItem]

评分计算：

  score_compile:
    100.0  if test_result["compile_success"]
    0.0    otherwise

  score_test:
    0.0    if test_result["total"] <= 0
    (test_result["passed"] / test_result["total"]) * 100.0  otherwise
    若 total == -1（无法解析）→ 0.0

  score_quality（LLM-as-judge）：
    Prompt：
      评估以下 {interop_type} 跨语言代码的质量，从三个维度各给 0-100 分：
      1. 内存安全性（是否正确处理内存分配/释放/所有权）
      2. 错误处理（是否处理了可能的错误返回值）
      3. 代码规范（是否符合目标语言的惯用写法）
      代码：{generated_code}
      只返回 JSON：{"memory": int, "error_handling": int, "style": int}
    score_quality = (memory + error_handling + style) / 3.0
    
    judge 调用失败 → score_quality = 50.0（中性分，不影响测试结果的排名）

  score_total:
    score_test * 0.6 + score_compile * 0.2 + score_quality * 0.2

BenchmarkItem 组装：
  id               = task["task_id"]
  pr_metadata      = state["pr"]
  task             = state["task"]
  docker_image     = state["image_tag"]
  generated_code   = state["generated_code"]
  test_result      = state["test_result"]
  score_total      = 计算结果
  score_test       = 计算结果
  score_compile    = 计算结果
  score_quality    = 计算结果
  quality_notes    = LLM judge 的完整评语
  created_at       = datetime.utcnow().isoformat() + "Z"
```

---

### 6.11 `nodes/aggregate.py`

#### 函数：`aggregate_results`

```
功能：汇总所有 PR 子图结果，执行去重和质量过滤，写出最终文件

输入（从 state 读取）：
  state["benchmark_items"]  list[BenchmarkItem]
  state["errors"]           list[dict]
  state["prs"]              list[PRMetadata]
  state["run_config"]       dict

输出（写入 state）：
  state["benchmark_items"]  list[BenchmarkItem]  — 过滤后的最终列表

副作用（写出文件）：
  output/benchmark_dataset.json    — 最终数据集
  output/summary_report.md         — 构建报告

处理逻辑：

  步骤 1 — 过滤无效条目：
    过滤条件（满足任一则移除）：
      - generated_code 为空字符串
      - test_result["total"] == 0（无测试用例被执行）
      - task["ground_truth"] 为空字符串
    记录过滤数量

  步骤 2 — 去重：
    使用 task["id"] 去重（理论上不应出现重复，但防御性处理）
    若发现重复 id，保留 score_total 较高的那个

  步骤 3 — 多样性控制（per_repo_cap）：
    若 run_config["per_repo_cap"] 已设置：
      按 pr["repo"] 分组，每组最多保留 per_repo_cap 个条目
      同组内按 score_total 降序保留
    若未设置（待定）：跳过此步骤

  步骤 4 — 排序：
    主键：interop_layer（ffi → runtime_embedding → wasm）
    次键：interop_type（字母序）
    三键：difficulty（easy → medium → hard）
    四键：score_total 降序

  步骤 5 — 写出 benchmark_dataset.json：
    格式：JSON 数组，每个元素为 BenchmarkItem
    写出前将所有 TypedDict 转为 dict（递归）

  步骤 6 — 写出 summary_report.md：
    包含内容：
      - 总览（扫描数、候选数、最终数、转化率）
      - 按 interop_type 分布表
      - 按 interop_layer 分布表
      - 按难度分布表
      - 构建失败统计（按失败阶段分组）
      - 错误清单 Top 10
      - 平均分统计
```

---

## 七、模块组：`parsers/`

### 7.1 `parsers/base.py`

#### 类：`BaseParser`（抽象基类）

```
方法：parse(stdout: str, exit_code: int) -> TestResult
  输入：
    stdout: str     — 测试命令的完整 stdout + stderr 输出
    exit_code: int  — 进程退出码（-1 表示超时）
  输出：
    TestResult      — 见 §2.7
```

---

### 7.2 `parsers/go_parser.py`

#### 类：`GoParser(BaseParser)`

```
覆盖框架：go test（使用 -json -v flag）
输出格式：每行一个 JSON 事件对象（streaming JSON）

parse 实现逻辑：
  逐行解析，遇到 JSON 解析失败的行跳过
  统计规则：
    {"Action":"pass","Test":"<name>"} → passed += 1（Test 字段非空才统计，避免统计包级别的 pass）
    {"Action":"fail","Test":"<name>"} → failed += 1
    {"Action":"run"}                  → total += 1（开始运行的用例数）
  
  compile_success 判定：
    stdout 中不含 "build failed" 且 不含 "[build failed]" → True
    否则 → False，passed/failed/total 全设为 0
  
  特殊情况：
    stdout 为空且 exit_code != 0 → compile_success=False，其余 -1
    无任何测试函数被执行（total=0）→ passed=0, failed=0, total=0
```

---

### 7.3 `parsers/pytest_parser.py`

#### 类：`PytestParser(BaseParser)`

```
覆盖框架：pytest（使用 -q 或 --tb=short flag）
输出格式：纯文本，末尾有汇总行

parse 实现逻辑：
  从 stdout 末尾提取汇总行，格式示例：
    "3 passed, 1 failed, 2 errors in 0.42s"
    "5 passed in 1.23s"
    "no tests ran"
  
  正则模式（顺序尝试）：
    r"(\d+) passed"   → passed
    r"(\d+) failed"   → failed
    r"(\d+) error"    → errors（注意是 error 不是 errors）
    r"(\d+) warning"  → 忽略
  
  compile_success 判定：
    stdout 包含 "ImportError" 或 "ModuleNotFoundError" 或 "SyntaxError" → False
    否则 → True
  
  total = passed + failed + errors
  "no tests ran" → total=0, passed=0, failed=0
```

---

### 7.4 `parsers/junit_xml_parser.py`

#### 类：`JUnitXmlParser(BaseParser)`

```
覆盖框架：JUnit 4/5（通过 Maven Surefire 或 Gradle 生成 XML 报告）
输出格式：XML 文件，路径 target/surefire-reports/*.xml 或 build/test-results/**/*.xml

parse 实现逻辑：
  注意：stdout 本身可能不是 XML，XML 报告文件在容器内磁盘上
  
  两步策略：
  1. 若 stdout 包含完整 XML（部分框架直接输出到 stdout）→ 直接解析
  2. 若 stdout 不含 XML → 从文本输出提取（降级到 generic 模式）
  
  XML 解析：
    找到所有 <testsuite> 元素，累加属性：
      tests     → total
      failures  → failed  
      errors    → errors
    passed = total - failed - errors
  
  compile_success 判定：
    stdout 不含 "BUILD FAILURE" 且 不含 "COMPILATION ERROR" → True
    exit_code == 0 也可作为辅助判断
```

---

### 7.5 `parsers/cargo_parser.py`

#### 类：`CargoParser(BaseParser)`

```
覆盖框架：cargo test
输出格式：纯文本，末尾有汇总行

parse 实现逻辑：
  从 stdout 提取汇总行，格式：
    "test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured"
    "test result: FAILED. 3 passed; 2 failed"
  
  正则：r"test result: \w+\. (\d+) passed; (\d+) failed"
  errors = 0（cargo test 不区分 error 和 failure）
  total = passed + failed
  
  compile_success 判定：
    stdout 不含 "error[E" 且 不含 "error: aborting" → True
    注意：编译错误时 passed/failed 都是 0，需通过 compile_success 区分
```

---

### 7.6 `parsers/jest_parser.py`

#### 类：`JestParser(BaseParser)`

```
覆盖框架：Jest（使用 --json flag）
输出格式：JSON 对象（单个，不是流式）

parse 实现逻辑：
  尝试从 stdout 中提取 JSON 对象（可能前面有非 JSON 的输出）：
    从第一个 "{" 到最后一个 "}" 提取
  
  关键字段：
    numPassedTests  → passed
    numFailedTests  → failed
    numTotalTests   → total
    testResults[*].status 为 "failed" 的数量作为辅助验证
  
  errors = total - passed - failed（若为负数则设为 0）
  
  compile_success 判定：
    JSON 中 success 字段为 True 或 numFailedTests == 0 且 exit_code == 0
    stdout 含 "SyntaxError" 或 "Cannot find module" → False
  
  JSON 解析失败 → 退化为 GenericParser 处理
```

---

### 7.7 `parsers/generic_parser.py`

#### 类：`GenericParser(BaseParser)`

```
覆盖框架：任意（兜底）
输出格式：任意文本

parse 实现逻辑：
  按顺序尝试以下正则模式（使用最后一个匹配成功的结果）：
  
    模式 1：r"(\d+) passed[,;]? (\d+) failed"        → passed, failed
    模式 2：r"Tests run: (\d+), Failures: (\d+)"      → total, failed（Maven 控制台输出）
    模式 3：r"(\d+) tests?, (\d+) failures?"           → total, failed
    模式 4：r"OK \((\d+) tests?\)"                    → total=passed, failed=0
    模式 5：r"FAILED \((\d+) errors?, (\d+) failures?" → errors, failed
  
  所有模式均未匹配 → passed=-1, failed=-1, errors=-1, total=-1
  
  compile_success 判定（通用规则）：
    exit_code == 0 → True
    stdout 含任意编译错误关键字（error, undefined reference, cannot find, fatal error）→ False
    否则 → exit_code == 0
  
  stdout_tail = "\n".join(stdout.splitlines()[-100:])
```

---

## 八、模块：`main.py`

**职责：** CLI 入口，解析命令行参数，调度对应的执行模式。

### 8.1 常量：`BASE_RUN_CONFIG`

```python
{
    "interop_types":      list[str]  — 目标类型，默认全部 10 种
    "min_stars":          int        — 默认 50
    "max_prs_per_repo":   int        — 默认 100
    "target_items":       int | None — 候选池目标；默认 None（无上限）
    "per_repo_cap":       int | None — 默认 None（待定）
    "skip_review":        bool       — 默认 True（默认关闭人工审核）
    "task_strategy":      str        — "completion"，默认
    "target_llm":         str        — 默认 "claude-sonnet-4-20250514"
    "judge_llm":          str        — 默认 "claude-sonnet-4-20250514"
    "min_diff_lines":     int        — 默认 50
    "max_diff_lines":     int        — 默认 2000
    "input_path":         str | None — 当前模式输入路径（如 repos_snapshot.json）
    "output_path":        str | None — 当前模式输出路径（如 repos_snapshot.json / prs_snapshot.json）
    "progress_path":      str | None — `fetch-prs` 进度 sidecar 路径
    "config_fingerprint": str | None — `fetch-prs` 筛选参数指纹
}
```

### 8.2 执行模式

| 模式 | 函数 | 核心行为 |
|---|---|---|
| `full` | `run_full(args)` | 构建主图，完整运行 Stage 1 → Stage 2+3 → 聚合 |
| `fetch-repos` | `run_fetch_repos(args)` | 执行 repo-level 粗召回，并将结果写入 `repos_snapshot.json` |
| `fetch-prs` | `run_fetch_prs(args)` | 读取 `repos_snapshot.json`，逐仓库扫描 PR；每发现 1 条有效 PR 立即写入 `prs_snapshot.json`；通过 `repo@head_sha` progress sidecar 支持断点恢复 |
| `build` | `run_build(args)` | 读取 `--input` PR 文件，直接进入 Stage 2+3（不依赖 human_review 前的 checkpoint） |
| `single-pr` | `run_single_pr(args)` | 读取 `--pr-json` 单条 PR，直接 invoke PR 子图，打印 test_result |
| `resume` | `run_resume(args)` | 用 `--thread-id` 恢复已有 checkpoint；主要保留给 Stage 2+3 或人工审核后的图执行续跑，Stage 1 的常规续跑优先通过重复执行 `fetch-prs` + 同一个输入输出路径完成 |

### 8.3 命令行参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--mode` | str | `full` | 执行模式 |
| `--thread-id` | str | 自动生成 | Checkpoint key，续跑时手动指定 |
| `--input` | str | 模式相关 | `fetch-prs` 读取 `repos_snapshot.json`；`build` 读取 `prs_snapshot.json` |
| `--output` | str | 模式相关 | `fetch-repos` 输出 `repos_snapshot.json`；`fetch-prs` 输出 `prs_snapshot.json` |
| `--pr-json` | str | `test_pr.json` | `single-pr` 模式的单条 PR 文件 |
| `--interop-types` | str | 全部 | 逗号分隔，如 `"cgo,jni"` |
| `--min-stars` | int | 50 | 覆盖 BASE_RUN_CONFIG |
| `--target-items` | int | None | 仅在需要提前停止时设置候选 PR 上限；省略或传 `0` 表示无上限 |
| `--review` | flag | False | 开启一次性人工审核；默认不审核 |
| `--target-llm` | str | 见配置 | 被测模型 |
| `--db` | str | `benchmark_runs.db` | Checkpoint 数据库路径 |

说明：
  `fetch-prs` 模式会从 `--output` 自动派生一个 sidecar 路径。
  若 `--output=prs_snapshot.json`，则进度文件为 `prs_snapshot.progress.json`。
  该 sidecar 仅用于 Stage 1 跳过已扫描 PR commit / repo，不作为 `build` 模式输入。

---

## 九、配置参考

### 9.1 环境变量

| 变量名 | 必填 | 说明 |
|---|---|---|
| `GITHUB_TOKEN_1` | ✅ | 第一个 GitHub PAT |
| `GITHUB_TOKEN_2` | ✅ | 第二个 GitHub PAT（轮换用） |
| `TARGET_LLM_API_KEY` | ✅ | 被测 LLM 的 API Key |
| `JUDGE_LLM_API_KEY` | ⚠️ | Judge LLM 的 API Key，若与 TARGET 相同可不设 |

### 9.2 `run_config` 完整字段说明

见 §8.1，通过 CLI 参数或直接修改 `BASE_RUN_CONFIG` 覆盖默认值。

---

## 十、错误处理策略

### 10.1 错误分级

| 级别 | 行为 | 示例 |
|---|---|---|
| **FATAL** | 中止整个流程，抛出异常 | GitHub Token 全部失效，search query 语法错误 |
| **PR_SKIP** | 跳过当前 PR，记录 error，继续其他 PR | docker_build 3 次失败，infer_env 全层失败 |
| **WARN** | 降级处理，继续执行 | LLM judge 失败（使用默认分），parser 降级到 generic |

### 10.2 `errors` 记录格式

```python
{
    "repo":    str,         # "owner/repo"
    "pr_id":   int,
    "stage":   str,         # "fetch_prs" | "infer_env" | "docker_build" | ...
    "reason":  str,         # 机器可读的错误原因码
    "message": str,         # 人类可读的错误描述
    "timestamp": str        # ISO 8601
}
```

### 10.3 常见 reason 码

| reason | 触发阶段 | 说明 |
|---|---|---|
| `"no_interop_signal"` | construct_task | diff 中未检测到跨语言调用信号 |
| `"mask_not_interop_code"` | construct_task | mask 范围内 FFI 关键字占比 < 50%，判定为业务逻辑 |
| `"mask_ineffective"` | construct_task | 注入 masked_code 后测试仍全部通过，mask 未命中关键路径 |
| `"mask_breaks_compilation"` | construct_task | masked_code 破坏语法，调整后仍无法编译 |
| `"ground_truth_invalid"` | construct_task | ground_truth 注入后测试结果与 baseline 不一致 |
| `"infer_env_failed"` | infer_env | 四层降级全部失败 |
| `"docker_build_failed"` | docker_build | 3 次重试全部失败（镜像层） |
| `"compile_unrecoverable"` | compile_verify | LLM 修复 2 轮后容器内编译仍失败 |
| `"baseline_tests_failing"` | compile_verify | HEAD 完整代码的测试用例本身不通过 |
| `"empty_generation"` | llm_generate | LLM 返回空代码 |
| `"llm_timeout"` | llm_generate | LLM 调用超时 |
| `"test_timeout"` | run_tests | 测试执行超时（> 420 秒）|
| `"no_test_files"` | fetch_prs | PR diff 中无测试文件 |

---

## 十一、模块间接口契约

### 11.1 `fetch-repos` → `fetch-prs` 契约

**接口文件：** `repos_snapshot.json`

**格式：** `list[RepoInfo]`（JSON 数组）

**约束：**
- 每个 `RepoInfo.full_name` 必须唯一
- 每个 `RepoInfo.clone_url` 必须是可公开访问的 HTTPS URL
- `interop_type` / `interop_layer` 必须已经填充完整，`fetch-prs` 不再重新推断

**生产方：** `fetch_repos` 节点  
**消费方：** `fetch_prs` 节点（或 `run_fetch_prs` 装载后的初始状态）

---

### 11.2 Stage 1 → Stage 2+3 契约

**接口文件：** `prs_snapshot.json`

**格式：** `list[PRMetadata]`（JSON 数组）

**约束：**
- 每个 `PRMetadata` 的 `diff_files` 中至少有一个 `is_test=True`
- `head_sha` 必须是有效的 commit SHA
- `clone_url` 必须是可公开访问的 HTTPS URL
- `prs_snapshot.progress.json` 不是该接口的一部分；Stage 2+3 不读取该 sidecar

**生产方：** `fetch_prs` 节点  
**消费方：** `infer_env` 节点（通过 PRSubState 接收）

---

### 11.3 `infer_env` → `build_dockerfile` 契约

**接口对象：** `EnvSpec`

**约束：**
- `source` 为 `"repo_dockerfile"` 时，`dockerfile_content` 必须非空
- `source` 为其他值时，`base_image`、`build_cmds`、`test_cmds` 必须非空
- `test_framework` 必须是 parser 支持的值或 `"generic"`

---

### 11.4 `run_tests` → `parsers` 契约

**接口：** `BaseParser.parse(stdout: str, exit_code: int) -> TestResult`

**约束：**
- 所有 parser 必须实现此接口，不得修改签名
- `parse()` 不得抛出异常（内部 try/except，失败退化为 GenericParser 行为）
- `stdout_tail` 始终为输出的最后 100 行，即使解析失败

---

## 十二、测试规范

### 12.1 测试目录结构

```
tests/
├── fixtures/
│   ├── sample_pr_cgo.json        — CGo PR 的 PRMetadata 示例
│   ├── sample_pr_jni.json        — JNI PR 示例
│   ├── sample_go_test_output.txt — go test -json 输出示例
│   ├── sample_pytest_output.txt  — pytest 输出示例
│   └── sample_junit.xml          — JUnit XML 报告示例
├── test_nodes.py                 — 单节点单元测试
├── test_parsers.py               — parser 单元测试
├── test_github_client.py         — GitHubClient 测试（mock API）
├── test_e2e_single.py            — 单 PR 端到端集成测试
└── test_full_run.py              — 小规模全流程验证
```

### 12.2 各测试文件职责

**`test_parsers.py`（优先实现）：**
- 每个 parser 至少 3 个测试用例：全部通过、部分失败、编译失败
- 使用 fixtures 中的示例输出，不依赖真实容器

**`test_nodes.py`：**
- 使用 `unittest.mock` mock 所有外部调用（GitHub API、Docker、LLM）
- 重点测试：`infer_env` 四层降级逻辑、`fetch_prs` 筛选条件、`score` 计算公式

**`test_github_client.py`：**
- 使用 `responses` 库 mock HTTP 请求
- 重点测试：token 轮换触发条件、缓存命中逻辑

**`test_e2e_single.py`：**
- 硬编码一个已知的 CGo PR（如 golang/go 的某个历史 PR）
- 验证从 infer_env 到 score 的完整子图可运行
- 仅在有 Docker daemon 的环境执行（可用 pytest mark 标记）

**`test_full_run.py`：**
- 参数：ffi_types=["cgo"]，max_prs_per_repo=5，target_items=10
- 验证主图端到端可运行
- 验证 Checkpoint 断点续跑：人为 kill 后重启，确认从中断点继续

---

## 十三、待定事项

以下事项在实现前需要确认，影响对应模块的实现方式：

| 编号 | 事项 | 影响模块 | 优先级 |
|---|---|---|---|
| T-01 | Docker 执行环境（本地 daemon / 云端 / CI） | `docker_build.py`、`compile_verify.py`、`run_tests.py` | 高 |
| T-02 | 被测 LLM 列表（影响 API 客户端选择） | `llm_generate.py` | 高 |
| T-03 | `MAX_CONCURRENT_DOCKER` 具体值（依赖 T-01 执行环境） | `graph.py` | 高 |
| T-04 | LLM-as-judge 模型选择 | `score.py` | 中 |
| T-05 | `per_repo_cap` 具体数值（首次运行后校准） | `aggregate.py` | 低 |
| T-06 | WASM 测试框架（jest / node --test / 待定） | `infer_env.py`、wasm parser | 低 |
| T-07 | 策略 B（Code Generation）的具体实现细节 | `construct_task.py` | 低 |
| T-08 | compile_verify LLM 修复使用的模型（专用还是复用 judge_llm） | `compile_verify.py` | 低 |

---

*文档结束 — 如有疑问请联系项目负责人*
