# AGENT.md — 跨语言能力 Benchmark 构建工作流

> 本文件是项目的核心规范文档，供 Agent / 开发者初始化上下文使用。
> 描述项目目标、架构决策、各阶段实现规范及关键接口契约。

---

## 一、项目目标

从 GitHub 公开仓库中自动筛选**具有跨语言 FFI 调用**且**包含测试用例**的 PR，构建一个高质量的跨语言代码生成 Benchmark，用于评测大模型在跨语言场景（如 CGo、JNI、Python C Extension、Rust FFI 等）的代码生成能力。

### 核心问题定义

给定一个真实 PR 的跨语言调用上下文（函数签名、头文件、接口定义），模型能否生成正确的胶水代码，使原有测试用例通过？

---

## 二、技术选型

| 维度 | 选择 | 理由 |
|---|---|---|
| Agent 框架 | **LangGraph** | 原生有状态流水线、内置 Checkpoint 断点续跑、Send() 原生 fan-out 并行、interrupt() 支持人工审核 |
| Checkpoint 存储 | SQLite（本地）/ Redis（生产） | 节点级快照，崩溃后从最后成功节点续跑 |
| Docker 执行 | 待定（本地 daemon / 云端） | 节点实现隔离，切换只需替换两个节点函数 |
| 语言 | Python 3.11+ | async 节点支持 asyncio，适合 Docker I/O 密集操作 |
| GitHub 访问 | 2 个 token 轮换 + SQLite 缓存 | 慢速运行可接受；缓存层避免重跑消耗 quota |

### 规模参数（已锁定）

| 参数 | 值 | 说明 |
|---|---|---|
| 目标用例数 | 200–300 | 与 HumanEval 同量级，垂直领域足够 |
| 仓库数 | 100 | 保守估计每仓库约 5 个有效 PR，合计刚好压线 200 |
| 每仓库扫描 PR 上限 | ~100 | 每仓库扫 100 个 PR，期望 5 个左右通过 FFI+测试过滤 |
| 预期转化率 | ~5%（100→5） | 保守估算，首次运行后校准实际值 |
| per-repo 用例上限 | 待定（首次运行后设置） | 防止单一仓库主导 benchmark 风格 |
| PR 扫描策略 | 目标驱动，候选池满即停 | 不做全量扫描，历史剩余 PR 作储备 |

---

## 三、整体架构

```

GitHub API
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                  Agent Orchestrator                 │
│              (LangGraph CompiledGraph)              │
│                                                     │
│  Stage 1 — Fetch Tool                               │
│  ┌─────────────┐   ┌─────────────┐   ┌────────────┐ │
│  │ fetch_repos │──▶│  fetch_prs  │──▶│human + LLM │ │
│  └─────────────┘   └─────────────┘   │  review    │ │
│                                      └────┬───────┘ │
│                                  Send() fan-out     │
│                         ┌──────────┬──────┴───────┐ │
│  Stage 2+3 — PR Subgraph (每个 PR 并行)            │  │
│  ┌──────────────────────────────────────────────┐  │  │
│  │ infer_env → build_dockerfile → docker_build  │  │  │
│  │          → construct_task → llm_generate     │  │  │
│  │          → run_tests → score                 │  │  │
│  └──────────────────────────────────────────────┘  │  │
│                         └──────────┴──────┬───────┘  │
│                                  Reducer 合并         │
│                              ┌──────────────────┐    │
│                              │ aggregate_results │    │
│                              └────────┬─────────┘    │
└───────────────────────────────────────┼─────────────┘
                                        ▼
                               Benchmark Dataset
                           (JSON + Markdown Report)
```

---

## 四、全局状态定义 (BenchmarkState)

```python
# state.py
from typing import TypedDict, Annotated
import operator

class PRMetadata(TypedDict):
    repo: str           # "owner/repo"
    pr_id: int
    ffi_type: str       # "cgo" | "jni" | "ctypes" | "rust_ffi" | "wasm"
    base_sha: str
    head_sha: str
    diff_files: list[dict]   # {path, lang, is_test}
    test_commands: list[str] | None

class BenchmarkItem(TypedDict):
    pr_metadata: PRMetadata
    docker_image: str
    masked_code: str      # 给 LLM 的题目（跨语言片段被 mask）
    ground_truth: str     # 正确答案（原始 PR 代码）
    difficulty: str       # "easy" | "medium" | "hard"
    test_result: dict | None

class BenchmarkState(TypedDict):
    # 运行时配置（不可变）
    run_config: dict      # ffi_types, min_stars, max_prs, skip_review, etc.

    # Stage 1 输出
    repos: list[dict]
    prs:   Annotated[list[PRMetadata], operator.add]

    # Stage 2+3 输出（Reducer 自动合并并行子图的写入）
    benchmark_items: Annotated[list[BenchmarkItem], operator.add]
    errors:          Annotated[list[dict], operator.add]
```

**Reducer 说明：** `prs`、`benchmark_items`、`errors` 使用 `operator.add` reducer，多个并行子图各自 append，框架自动合并，不会覆盖。

---

## 五、Stage 1 — Fetch Tool

### 5.1 节点：`fetch_repos`

**职责：** 通过 GitHub Search API 筛选含跨语言 FFI 的仓库。

**筛选策略：**

```python
# 组合信号推断"跨语言仓库"
SEARCH_QUERIES = {
    "cgo":       "language:Go filename:*.c NOT filename:vendor",
    "jni":       "language:Java filename:*.c filename:jni",
    "ctypes":    "language:Python filename:*.c topic:ffi",
    "rust_ffi":  "language:Rust filename:*.c topic:ffi",
}
# 附加过滤：stars >= run_config["min_stars"]（默认 50）
# 附加过滤：同时存在多语言构建文件（go.mod+*.c, pom.xml+*.c, etc.）
```

**输出字段：** 更新 `state["repos"]`

### 5.2 节点：`fetch_prs`

**职责：** 对每个仓库遍历近期 PR，筛选满足条件的。

**PR 筛选条件：**
- diff 中同时涉及 ≥2 种语言的文件变更
- diff 文件路径中包含测试标记：`test/`、`*_test.go`、`*spec*`、`__tests__`、`*_test.py`
- PR 状态为 merged（已合并，代表有效修改）
- diff 行数在合理范围内（50–2000 行，过大过小都跳过）

**输出数据结构（PRMetadata）：**

```json
{
  "repo": "owner/repo",
  "pr_id": 1234,
  "ffi_type": "cgo",
  "base_sha": "abc...",
  "head_sha": "def...",
  "diff_files": [
    {"path": "bridge.go",      "lang": "Go", "is_test": false},
    {"path": "native.c",       "lang": "C",  "is_test": false},
    {"path": "bridge_test.go", "lang": "Go", "is_test": true}
  ],
  "test_commands": null
}
```

**输出字段：** append 到 `state["prs"]`

### 5.3 节点：`human_review` *(可选，受 run_config 控制)*

**职责：** 暂停 Graph，等待人工确认 PR 列表质量。

```python
from langgraph.types import interrupt

def human_review(state: BenchmarkState) -> dict:
    if state["run_config"].get("skip_review", False):
        return {}   # 自动跳过
    decision = interrupt({"prs": state["prs"], "count": len(state["prs"])})
    approved_ids = decision.get("approved_pr_ids", [p["pr_id"] for p in state["prs"]])
    filtered = [p for p in state["prs"] if p["pr_id"] in approved_ids]
    return {"prs": filtered}

# 外部恢复方式：
# app.update_state(config, {"approved_pr_ids": [1, 3, 5]})
# app.invoke(None, config)
```

---

## 六、Stage 2+3 — PR Subgraph

每个 PR 通过 `Send()` 触发一个独立子图实例，并行执行以下节点：

```
infer_env → build_dockerfile → docker_build
                                    │ (条件边：成功/重试/放弃)
                                    ▼
                            construct_task → llm_generate → run_tests → score
```

### 6.1 节点：`infer_env`

**职责：** 推断仓库构建环境，输出 `EnvSpec`（base image、系统依赖、构建命令、测试命令、测试框架）。

**C/C++ 的角色：** 在所有 FFI 场景中，C/C++ 几乎永远是"被调用方"，测试框架运行在宿主语言侧。`infer_env` 只需关注宿主语言的构建工具链，C/C++ 的编译器（gcc/clang）作为系统依赖项注入即可。

**四层降级策略（按优先级顺序执行，命中即返回）：**

#### 第一层：仓库自带 Dockerfile（覆盖约 30% 仓库）

```python
# 检查根目录及常见路径
dockerfile_candidates = ["Dockerfile", "docker/Dockerfile", ".docker/Dockerfile"]
if any(path in repo_file_tree for path in dockerfile_candidates):
    content = github_client.get_file_content(repo, head_sha, matched_path)
    # 只替换 CMD/ENTRYPOINT 为测试命令，其余原样保留
    patched = patch_cmd_to_test(content, test_cmds)
    return EnvSpec(source="repo_dockerfile", dockerfile_content=patched)
```

优点：依赖 100% 完整，构建成功率最高。代价：需要识别并替换 CMD/ENTRYPOINT。

#### 第二层：GitHub Actions workflow 提取（覆盖约 50% 仓库）

```python
# 解析 .github/workflows/*.yml
# 提取 apt-get install / brew install 命令 → system_deps
# 提取 run: 步骤中的 build/test 命令
workflow_files = github_client.list_files(repo, head_sha, ".github/workflows/")
for wf in workflow_files:
    deps  = extract_apt_installs(wf)    # ["libssl-dev", "libffi-dev"]
    build = extract_run_steps(wf, kind="build")
    test  = extract_run_steps(wf, kind="test")
    if test:
        return EnvSpec(source="github_actions", system_deps=deps,
                       build_cmds=build, test_cmds=test)
```

优点：依赖列表来自官方 CI，覆盖率高，纯规则解析无需 LLM。
注意：matrix build 需选一个目标环境（取第一个 OS/版本组合）。

#### 第三层：LLM 综合推断（覆盖约 12% 仓库）

对第一、二层均失败的仓库，将以下上下文喂给 LLM，要求直接输出 Dockerfile：

```python
context = {
    "lang_config_files": ["go.mod", "Cargo.toml", "pom.xml", "pyproject.toml"],
    "makefile": makefile_content,            # build/test target
    "readme_build_section": readme_excerpt,  # Building / Installation 章节
    "pr_diff_summary": diff_file_list,       # PR 涉及哪些文件
}
# 要求 LLM 输出完整 Dockerfile，不解释
# 基础镜像和依赖列表由 LLM 根据上下文自行决定
```

成功率约 60–70%，消耗 LLM token，作为兜底手段。

#### 第四层：跳过（剩余约 8% 仓库）

LLM 推断也失败时，写入 `state["errors"]`（reason: `"infer_env_failed"`），跳过该 PR，不中断其他并行任务。元数据保留，供后续人工补录。

**base image 映射表（第二、三层使用的骨架参考）：**

| 宿主语言 | FFI 类型 | Base Image | 最小系统依赖 |
|---|---|---|---|
| Go | CGo | `golang:1.22` | `gcc libc-dev` |
| Java | JNI | `maven:3.9-jdk-17` | `gcc` |
| Python | ctypes / C ext | `python:3.11` | `gcc python3-dev` |
| Rust | rust_ffi | `rust:1.77` | `gcc` |
| JS/TS | N-API / WASM | `node:20` | `gcc python3 make` |

**`EnvSpec` 输出结构：**

```python
class EnvSpec(TypedDict):
    source:             str          # "repo_dockerfile"|"github_actions"|"llm"|"failed"
    base_image:         str          # "golang:1.22"
    system_deps:        list[str]    # ["gcc","libssl-dev"]
    build_cmds:         list[str]    # ["go build ./..."]
    test_cmds:          list[str]    # ["go test ./..."]
    test_framework:     str          # "go_test"|"pytest"|"junit"|"cargo"|"jest"
    dockerfile_content: str | None   # 第一层直接填充，其余层由 build_dockerfile 生成
```

`test_framework` 字段在此处一并检测（检查依赖文件中是否含 pytest/jest/junit 等），供 `run_tests` 节点选择对应 parser 使用。

### 6.2 节点：`build_dockerfile`

**职责：** 根据 `EnvSpec` 生成最终 Dockerfile 文件，写入临时目录。

**分支逻辑：**

```python
def build_dockerfile(state: PRSubState) -> dict:
    env = state["env_spec"]

    if env["source"] == "repo_dockerfile":
        # 第一层：直接使用已 patch 的内容，无需渲染模板
        content = env["dockerfile_content"]
    else:
        # 第二/三层：用模板骨架 + EnvSpec 注入依赖
        content = render_template(
            template_path=f"dockerfiles/templates/{state['pr']['ffi_type']}.dockerfile.j2",
            context={
                "base_image":   env["base_image"],
                "system_deps":  env["system_deps"],   # 来自 CI 或 LLM，非模板硬编码
                "clone_url":    state["pr"]["clone_url"],
                "head_sha":     state["pr"]["head_sha"],
                "build_cmds":   env["build_cmds"],
                "test_cmds":    env["test_cmds"],
            }
        )

    path = f"/tmp/benchmark/{state['image_tag']}/Dockerfile"
    write_file(path, content)
    return {"dockerfile_path": path, "dockerfile_content": content}
```

**模板设计原则：** 模板只提供结构骨架，`system_deps` 字段永远从仓库自身的配置（CI workflow / LLM 推断）注入，模板本身不硬编码任何业务依赖。

```dockerfile
{# dockerfiles/templates/cgo.dockerfile.j2 #}
FROM {{ base_image }}
RUN apt-get update && apt-get install -y \
    gcc libc-dev \
    {% for dep in system_deps %}{{ dep }} {% endfor %}
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN git clone --depth=1 {{ clone_url }} . && git checkout {{ head_sha }}
RUN go mod download
{% for cmd in build_cmds %}RUN {{ cmd }}
{% endfor %}
CMD {{ test_cmds | tojson }}
```

**关键细节：**
- `git clone --depth=1` 避免拉取全部历史，加速构建
- `system_deps` 来自 `EnvSpec`，模板本身只保留 `gcc libc-dev` 作为 CGo 的最小必要依赖
- 写入路径：`/tmp/benchmark/{image_tag}/Dockerfile`，运行结束后清理

### 6.3 节点：`docker_build`

**职责：** 执行 `docker build`，带重试逻辑。

**重试策略：**
- 最多重试 3 次，指数退避（1s → 2s → 4s）
- 失败原因写入 `state["errors"]`
- 3 次均失败则走条件边 `skip`，整个 PR 跳过但不中断其他并行任务

```python
async def docker_build(state: PRSubState) -> dict:
    for attempt in range(3):
        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", state["image_tag"], "-f", state["dockerfile_path"], "."
        )
        if await proc.wait() == 0:
            return {"docker_image": state["image_tag"], "build_status": "success"}
        await asyncio.sleep(2 ** attempt)
    return {"build_status": "failed"}
```

### 6.4 节点：`construct_task`

**职责：** 将 PR diff 转化为 Benchmark 题目。

**两种构题策略：**

- **策略 A（Code Completion）：** Mask 跨语言调用片段，让 LLM 填充。适合入门难度，天然有标准答案。
- **策略 B（Code Generation）：** 给定接口定义，从头生成胶水代码。考察更全面，适合高难度题。

**难度分级：**
- `easy`：单函数调用，签名简单，无内存管理
- `medium`：多函数、涉及类型转换
- `hard`：内存管理、回调函数、错误传递

### 6.5 节点：`llm_generate`

**职责：** 调用被测 LLM，生成跨语言代码。

**Prompt 结构：**
```
[系统提示] 你是一个跨语言代码专家...
[上下文]   以下是仓库的相关文件：<接口定义、头文件、调用方代码>
[题目]     请补全以下 <masked> 部分：<masked_code>
[约束]     只输出代码，不要解释
```

### 6.6 节点：`run_tests`

**职责：** 在 Docker 容器中注入 LLM 生成的代码并运行测试，通过对应 parser 将输出转为结构化 `TestResult`。

**执行流程：**

```python
async def run_tests(state: PRSubState) -> dict:
    # 1. 将生成代码注入容器（docker cp）
    inject_code(state["image_tag"], state["generated_code"],
                state["task"]["target_file_path"])

    # 2. 执行测试命令，捕获 stdout/stderr
    stdout, exit_code = await run_docker_cmd(
        state["image_tag"], state["env_spec"]["test_cmds"]
    )

    # 3. 按 test_framework 选择对应 parser
    parser = get_parser(state["env_spec"]["test_framework"])
    test_result = parser.parse(stdout, exit_code)

    return {"test_result": test_result}
```

执行超时：5 分钟。超时视为失败，`exit_code = -1`。

### 6.7 节点：`score`

**职责：** 综合评分，写入 `BenchmarkItem`。

```
最终分 = 测试通过率(60%) + 编译成功率(20%) + 代码质量评分(20%)
```

代码质量评分通过 **LLM-as-judge** 实现：检查内存安全、错误处理、代码风格。

---

## 七、Parsers 层设计

### 7.1 设计原则

**C/C++ 不需要 parser。** 在所有 FFI 场景里，C/C++ 只作被调用方，测试始终由宿主语言的框架驱动。Parser 只覆盖 5 种宿主语言的测试框架输出。

**每种语言覆盖最主流的一个框架，加一个通用兜底。** 覆盖率约 85%，其余退化到 `generic_parser`。

### 7.2 Parser 映射表

| Parser 文件 | 覆盖框架 | 输出格式 | 说明 |
|---|---|---|---|
| `go_parser.py` | `go test` | JSON（`-json` flag） | Go 唯一标准，格式极规范 |
| `pytest_parser.py` | pytest | 文本（`-q --tb=short`） | Python 最主流框架 |
| `junit_xml_parser.py` | JUnit 4/5、Maven Surefire、Gradle | XML（`target/surefire-reports/*.xml`） | 一个 XML parser 覆盖 Java 全部主流构建工具 |
| `cargo_parser.py` | `cargo test` | 文本 | Rust 唯一标准 |
| `jest_parser.py` | Jest | JSON（`--json` flag） | JS/TS 最主流框架 |
| `generic_parser.py` | 任意框架 | 文本正则匹配 | 兜底，提取 "X passed / X failed" 等通用模式 |

### 7.3 统一接口契约

所有 parser 实现同一个接口，`run_tests.py` 只调用 `parse()`，不感知具体格式：

```python
# parsers/__init__.py
from .go_parser       import GoParser
from .pytest_parser   import PytestParser
from .junit_xml_parser import JUnitXmlParser
from .cargo_parser    import CargoParser
from .jest_parser     import JestParser
from .generic_parser  import GenericParser

PARSER_MAP = {
    "go_test": GoParser(),
    "pytest":  PytestParser(),
    "junit":   JUnitXmlParser(),
    "cargo":   CargoParser(),
    "jest":    JestParser(),
}

def get_parser(framework: str) -> BaseParser:
    return PARSER_MAP.get(framework, GenericParser())
```

```python
# parsers/base.py
class BaseParser:
    def parse(self, stdout: str, exit_code: int) -> TestResult:
        raise NotImplementedError

# TestResult（定义在 state.py）
class TestResult(TypedDict):
    passed:          int
    failed:          int
    errors:          int
    total:           int
    compile_success: bool
    exit_code:       int
    stdout_tail:     str   # 最后 100 行，用于调试
```

### 7.4 各 Parser 实现要点

**`go_parser.py`：** 解析 `go test -json` 的流式 JSON，每行一个事件对象，统计 `"Action":"pass"` 和 `"Action":"fail"` 的 `Test` 字段数量。`compile_success` 通过检测是否出现 `"build failed"` 判定。

**`pytest_parser.py`：** 匹配末尾汇总行 `(\d+) passed`、`(\d+) failed`、`(\d+) error`。`compile_success` 通过检测是否出现 `ImportError` / `ModuleNotFoundError` 判定。

**`junit_xml_parser.py`：** 解析 `<testsuite tests="X" failures="Y" errors="Z">` XML 属性。Maven/Gradle 均输出此格式，无需区分构建工具。

**`cargo_parser.py`：** 匹配末尾汇总行 `test result: ... X passed; Y failed`。`compile_success` 通过检测是否出现 `error[E` 判定。

**`jest_parser.py`：** 解析 `jest --json` 输出的 JSON，读取 `numPassedTests` / `numFailedTests` 字段。

**`generic_parser.py`：** 正则依次尝试匹配常见模式，所有模式都失败时只返回 `exit_code` 和 `stdout_tail`，`passed/failed` 填 -1 表示"无法解析"。

---

## 八、Stage 聚合 — `aggregate_results`

**职责：** 汇总所有 PR 子图的结果，输出最终 Benchmark 数据集。

**处理逻辑：**
- 按 `ffi_type` 分组，确保各类型有足够覆盖
- 按难度分级排序
- 去重（相似 diff 的 PR 保留一个）
- 过滤质量不达标的条目（测试覆盖率过低的 PR）
- 输出 `benchmark_dataset.json` + `summary_report.md`

---

## 九、Graph 编排代码骨架

```python
# graph.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Send

def build_graph():
    g = StateGraph(BenchmarkState)

    # Stage 1
    g.add_node("fetch_repos",  fetch_repos)
    g.add_node("fetch_prs",    fetch_prs)
    g.add_node("human_review", human_review)

    # Stage 2+3 子图
    pr_subgraph = build_pr_subgraph()
    g.add_node("process_pr", pr_subgraph)

    # 聚合
    g.add_node("aggregate", aggregate_results)

    # 边
    g.add_edge(START, "fetch_repos")
    g.add_edge("fetch_repos", "fetch_prs")
    g.add_edge("fetch_prs", "human_review")
    g.add_conditional_edges(
        "human_review",
        lambda state: [
            Send("process_pr", {"pr": pr, "run_config": state["run_config"]})
            for pr in state["prs"]
        ]
    )
    g.add_edge("process_pr", "aggregate")
    g.add_edge("aggregate", END)

    checkpointer = SqliteSaver.from_conn_string("./benchmark_runs.db")
    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"]  # 编译时声明，节点内部可跳过
    )


def build_pr_subgraph():
    from langgraph.graph import StateGraph, START, END
    sg = StateGraph(PRSubState)

    sg.add_node("infer_env",        infer_env)
    sg.add_node("build_dockerfile", build_dockerfile)
    sg.add_node("docker_build",     docker_build)
    sg.add_node("construct_task",   construct_task)
    sg.add_node("llm_generate",     llm_generate)
    sg.add_node("run_tests",        run_tests)
    sg.add_node("score",            score)

    sg.add_edge(START, "infer_env")
    sg.add_edge("infer_env", "build_dockerfile")
    sg.add_edge("build_dockerfile", "docker_build")
    sg.add_conditional_edges("docker_build", route_after_build)
    sg.add_edge("construct_task", "llm_generate")
    sg.add_edge("llm_generate", "run_tests")
    sg.add_edge("run_tests", "score")
    sg.add_edge("score", END)

    return sg.compile()


def route_after_build(state: PRSubState) -> str:
    if state["build_status"] == "success":
        return "construct_task"
    elif state.get("build_retries", 0) < 3:
        return "docker_build"   # 重试
    else:
        return END              # 跳过该 PR


# 运行入口
if __name__ == "__main__":
    app = build_graph()
    result = app.invoke(
        {
            "run_config": {
                "ffi_types":    ["cgo", "jni", "ctypes"],
                "min_stars":    50,
                "max_prs":      200,
                "skip_review":  False,
            },
            "repos": [], "prs": [], "benchmark_items": [], "errors": []
        },
        config={"configurable": {"thread_id": "run-001"}}
    )
```

---

## 十、Checkpoint 策略

| 节点 | Checkpoint 时机 | 续跑收益 |
|---|---|---|
| `fetch_repos` 完成后 | 自动（LangGraph 默认） | Stage 2 失败不重爬 GitHub |
| `human_review` 完成后 | 自动 | 人工确认结果持久化 |
| `docker_build` 成功后 | 自动 | build 成功后 LLM 失败，只重跑 llm_generate |
| `aggregate` 完成后 | 自动 | 最终结果持久化 |

续跑方式：

```python
# 相同 thread_id，LangGraph 从最后一个成功 checkpoint 继续
app.invoke(None, config={"configurable": {"thread_id": "run-001"}})
```

---

## 十一、目录结构

```
benchmark_agent/
├── AGENT.md                        # 本文件
├── main.py                         # CLI 入口
├── state.py                        # 所有 TypedDict：BenchmarkState, PRMetadata,
│                                   #   EnvSpec, BenchmarkItem, TestResult, PRSubState
├── graph.py                        # build_graph(), build_pr_subgraph()
├── github_client.py                # Token 轮换 + 限速 + SQLite 缓存
├── requirements.txt
├── benchmark_runs.db               # LangGraph Checkpoint（运行时生成）
│
├── nodes/                          # 每个 LangGraph 节点一个文件
│   ├── fetch_repos.py              # Stage 1：仓库筛选
│   ├── fetch_prs.py                # Stage 1：PR 筛选（目标驱动）
│   ├── human_review.py             # Stage 1：人工审核（可跳过）
│   ├── infer_env.py                # Stage 2：四层降级环境推断
│   ├── build_dockerfile.py         # Stage 2：Dockerfile 生成
│   ├── docker_build.py             # Stage 2：异步构建 + 重试
│   ├── construct_task.py           # Stage 3：构题（mask 策略 A/B）
│   ├── llm_generate.py             # Stage 3：被测 LLM 调用
│   ├── run_tests.py                # Stage 3：容器内执行 + 调用 parser
│   ├── score.py                    # Stage 3：评分 + LLM-as-judge
│   └── aggregate.py                # 聚合：去重 + 分级 + 输出报告
│
├── parsers/                        # 测试输出解析器
│   ├── __init__.py                 # get_parser(framework) 工厂函数
│   ├── base.py                     # BaseParser 抽象类
│   ├── go_parser.py                # go test -json
│   ├── pytest_parser.py            # pytest -q
│   ├── junit_xml_parser.py         # JUnit XML（Maven / Gradle 均适用）
│   ├── cargo_parser.py             # cargo test
│   ├── jest_parser.py              # Jest --json
│   └── generic_parser.py           # 兜底正则匹配
│
├── dockerfiles/
│   └── templates/                  # Jinja2 骨架模板（依赖从 EnvSpec 注入）
│       ├── cgo.dockerfile.j2
│       ├── jni.dockerfile.j2
│       ├── ctypes.dockerfile.j2
│       ├── rust_ffi.dockerfile.j2
│       └── node_napi.dockerfile.j2
│
├── output/                         # 最终产物（运行时生成，不进 git）
│   ├── benchmark_dataset.json
│   └── summary_report.md
│
└── tests/
    ├── test_nodes.py               # 单节点单元测试
    ├── test_parsers.py             # 各 parser 单元测试
    ├── test_e2e_single.py          # 单 PR 集成测试
    └── test_full_run.py            # 小规模全流程验证
```

---

## 十二、待决策项

| 状态 | 项目 | 说明 |
|---|---|---|
| ✅ 已锁定 | GitHub 访问层 | 2 个 token 轮换 + SQLite 缓存，慢速运行 |
| ✅ 已锁定 | Benchmark 规模 | 200–300 用例，100 仓库，每仓库扫 ~100 个 PR，预期转化率 ~5% |
| ✅ 已锁定 | per-repo 用例上限 | 待首次运行后根据实际分布设置，占位字段已在 run_config 中预留 |
| ✅ 已锁定 | Dockerfile 生成策略 | 四层降级：仓库 Dockerfile → CI workflow → LLM → skip |
| ✅ 已锁定 | Parser 架构 | 5 种宿主语言框架 + generic 兜底，统一 BaseParser 接口 |
| ⏳ 待定 | Docker 执行环境 | 本地 daemon / 云端，影响安全隔离方案 |
| ⏳ 待定 | 被测 LLM 列表 | 评测哪些模型（GPT-4o、Claude、Gemini、开源） |
| ⏳ 待定 | LLM-as-judge 模型 | 质量评分使用哪个模型 |

---

## 十三、LangGraph 核心概念速查

| 概念 | 一句话 | 本项目用途 |
|---|---|---|
| `State` | 所有节点共享的数据字典 | `BenchmarkState` |
| `Node` | 接收 State、返回更新字典的函数 | 每个处理步骤 |
| `Edge` | 节点间的固定走向 | Stage 内串行步骤 |
| `ConditionalEdge` | 根据 State 动态路由 | Docker build 重试/跳过 |
| `Send()` | 动态 fan-out，触发并行子任务 | 每个 PR 并行处理 |
| `interrupt()` | 暂停 Graph 等待外部输入 | 人工审核 PR 列表 |
| `Checkpoint` | 节点级状态快照 | 断点续跑 |
| `thread_id` | Checkpoint 的唯一 key | 区分不同运行批次 |