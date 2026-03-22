# DEVELOPER.md — 跨语言 Benchmark 系统开发手册

> **目标读者：** 参与本项目的开发人员，包括没有 LangGraph / Agent 开发经验的成员  
> **配套文档：** `DESIGN.md`（完整规范）、`AGENT.md`（架构决策）、`discussion.md`（学术论证）  
> **核心原则：** 每个步骤完成后必须能通过对应的验证用例，才能进入下一步

---

## 目录

- [开发环境准备](#零开发环境准备)
- [Phase 0：项目地基](#phase-0项目地基)
  - [0.1 目录骨架与依赖](#01-目录骨架与依赖)
  - [0.2 state.py — 数据类型定义](#02-statepy--数据类型定义)
  - [0.3 github_client.py — GitHub 访问层](#03-github_clientpy--github-访问层)
- [Phase 1：Stage 1 数据采集](#phase-1stage-1-数据采集)
  - [1.1 nodes/fetch_repos.py](#11-nodesfetch_repospy)
  - [1.2 nodes/fetch_prs.py](#12-nodesfetch_prspy)
  - [1.3 nodes/human_review.py](#13-nodeshuman_reviewpy)
  - [1.4 graph.py（Stage 1 部分）+ main.py（fetch 模式）](#14-graphpystage-1-部分--mainpyfetch-模式)
  - [1.5 Stage 1 集成验证](#15-stage-1-集成验证)
- [Phase 2：Stage 2 容器环境构建](#phase-2stage-2-容器环境构建)
  - [2.1 nodes/infer_env.py](#21-nodesinfer_envpy)
  - [2.2 nodes/build_dockerfile.py + 模板文件](#22-nodesbuild_dockerfilepy--模板文件)
  - [2.3 nodes/docker_build.py](#23-nodesdocker_buildpy)
  - [2.4 nodes/compile_verify.py](#24-nodescompile_verifypy)
  - [2.5 子图连线 + single-pr 模式验证](#25-子图连线--single-pr-模式验证)
- [Phase 3：Stage 3 题目构造与评估](#phase-3stage-3-题目构造与评估)
  - [3.1 parsers/ — 测试输出解析器](#31-parsers--测试输出解析器)
  - [3.2 nodes/construct_task.py](#32-nodesconstruct_taskpy)
  - [3.3 nodes/llm_generate.py](#33-nodesllm_generatepy)
  - [3.4 nodes/run_tests.py](#34-nodesrun_testspy)
  - [3.5 nodes/score.py](#35-nodesscore_py)
  - [3.6 nodes/aggregate.py](#36-nodesaggregatepy)
- [Phase 4：主图组装与完整流程](#phase-4主图组装与完整流程)
  - [4.1 graph.py — 完整主图](#41-graphpy--完整主图)
  - [4.2 main.py — 完整 CLI](#42-mainpy--完整-cli)
- [Phase 5：测试与验证](#phase-5测试与验证)
  - [5.1 单元测试](#51-单元测试)
  - [5.2 集成测试](#52-集成测试)
  - [5.3 全流程验证](#53-全流程验证)
- [附录：常见问题与排查](#附录常见问题与排查)

---

## 零、开发环境准备

### 0.1 必需软件

在开始写任何代码之前，确保以下软件已安装并可用：

```bash
# 检查 Python 版本，必须 >= 3.11
python --version

# 检查 Docker 是否运行
docker info

# 检查 Git
git --version
```

### 0.2 GitHub Token 准备

本项目需要 2 个 GitHub Personal Access Token（PAT），用于 API 限速轮换。

**创建步骤：**
1. 登录 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 点击 "Generate new token (classic)"
3. 权限选择：勾选 `public_repo`（只读公开仓库即可）
4. 重复以上步骤创建第二个 token
5. 将两个 token 保存到本地（只显示一次）

**配置到环境变量（每次开发前执行，或写入 `.env` 文件）：**

```bash
export GITHUB_TOKEN_1="ghp_your_first_token_here"
export GITHUB_TOKEN_2="ghp_your_second_token_here"
export TARGET_LLM_API_KEY="sk-ant-your_key_here"   # 被测 LLM 的 API Key
```

> ⚠️ **安全提示：** 不要把 token 提交到 git 仓库。在项目根目录创建 `.env` 文件，并在 `.gitignore` 中添加 `.env`。

### 0.3 验证环境准备完成

执行以下命令，全部输出正确则环境就绪：

```bash
python -c "import sys; assert sys.version_info >= (3, 11), 'Python 版本不足'"
docker run --rm hello-world   # 应看到 "Hello from Docker!"
echo $GITHUB_TOKEN_1 | cut -c1-4  # 应输出 "ghp_"（token 前缀）
```

---

## Phase 0：项目地基

> **目标：** 建立项目骨架，定义所有数据类型，实现 GitHub 访问层。  
> **完成标志：** `python -c "from state import BenchmarkState"` 不报错；`github_client` 能查询到仓库信息。

---

### 0.1 目录骨架与依赖

#### 要做什么

创建项目目录结构，安装所有依赖包。

#### 操作步骤

**步骤 1：** 创建项目目录

```bash
mkdir benchmark_agent
cd benchmark_agent

# 创建所有子目录
mkdir -p nodes parsers dockerfiles/templates output tests/fixtures
```

**步骤 2：** 创建 `requirements.txt`

```
# requirements.txt
langgraph>=0.2.0
langchain-core>=0.2.0
langchain-anthropic>=0.1.0
PyGithub>=2.1.0
docker>=7.0.0
Jinja2>=3.1.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
aiohttp>=3.9.0
pyyaml>=6.0.0
```

**步骤 3：** 安装依赖

```bash
pip install -r requirements.txt
```

**步骤 4：** 创建 `.gitignore`

```
# .gitignore
.env
*.db
output/
/tmp/
__pycache__/
*.pyc
.pytest_cache/
```

#### ✅ 验证步骤 0.1 成功

```bash
# 验证所有关键包都能导入
python -c "
import langgraph
import github
import docker
import jinja2
import yaml
print('✓ 所有依赖包安装成功')
print(f'  langgraph: {langgraph.__version__}')
"
```

**预期输出：**
```
✓ 所有依赖包安装成功
  langgraph: 0.2.x
```

---

### 0.2 `state.py` — 数据类型定义

#### 要做什么

定义系统中所有数据类型（TypedDict）。这是所有其他模块共同依赖的"合同文件"，必须最先完成。

**关键原则：** `state.py` 只包含类型定义，不包含任何逻辑代码。

#### 操作步骤

**步骤 1：** 创建 `state.py`，按以下顺序定义类型

```python
# state.py
from typing import TypedDict, Annotated
import operator


# ─── 1. 仓库信息（fetch_repos 产出）────────────────────────
class RepoInfo(TypedDict):
    full_name:      str           # "owner/repo"
    clone_url:      str           # HTTPS clone URL
    stars:          int           # star 数
    interop_type:   str           # 如 "cgo"、"jni"
    interop_layer:  str           # "ffi" | "runtime_embedding" | "wasm"
    languages:      dict          # {"Go": 60, "C": 40}
    default_branch: str           # "main" 或 "master"


# ─── 2. diff 文件记录（fetch_prs 产出）──────────────────────
class DiffFile(TypedDict):
    path:       str    # 相对路径
    lang:       str    # "Go"、"C"、"Python" 等
    is_test:    bool   # 是否为测试文件
    additions:  int    # 新增行数
    deletions:  int    # 删除行数
    status:     str    # "added" | "modified" | "removed"


# ─── 3. PR 元数据（fetch_prs 产出，Stage 1 最终输出单元）────
class PRMetadata(TypedDict):
    repo:            str           # "owner/repo"
    clone_url:       str
    pr_id:           int
    pr_title:        str
    interop_type:    str
    interop_layer:   str
    base_sha:        str
    head_sha:        str
    diff_files:      list          # list[DiffFile]
    diff_total_lines: int
    test_commands:   list          # list[str] | None
    merged_at:       str           # ISO 8601


# ─── 4. 构建环境规格（infer_env 产出）───────────────────────
class EnvSpec(TypedDict):
    source:             str        # "repo_dockerfile"|"github_actions"|"llm"|"failed"
    base_image:         str        # "golang:1.22"
    system_deps:        list       # ["gcc", "libssl-dev"]
    build_cmds:         list       # ["go build ./..."]
    test_cmds:          list       # ["go test -v ./..."]
    test_framework:     str        # "go_test"|"pytest"|"junit"|"cargo"|"jest"|"generic"
    dockerfile_content: object     # str | None


# ─── 5. Benchmark 题目（construct_task 产出）────────────────
class BenchmarkTask(TypedDict):
    task_id:          str          # "cgo-owner-repo-pr1234-001"
    strategy:         str          # "completion" | "generation"
    masked_code:      str          # 含 <MASK> 的题目代码
    context_files:    dict         # {文件路径: 文件内容}
    ground_truth:     str          # 正确答案
    target_file_path: str          # 容器内注入路径，如 "/app/bridge.go"
    mask_ranges:      list         # [(start_line, end_line), ...]
    difficulty:       str          # "easy" | "medium" | "hard"
    host_lang:        str          # "Go"
    target_lang:      str          # "C"


# ─── 6. 测试执行结果（parser 产出）─────────────────────────
class TestResult(TypedDict):
    passed:          int     # -1 表示无法解析
    failed:          int
    errors:          int
    total:           int
    compile_success: bool
    exit_code:       int     # -1 表示超时
    stdout_tail:     str     # 最后 100 行


# ─── 7. Benchmark 条目（score 产出，最终输出单元）────────────
class BenchmarkItem(TypedDict):
    id:              str
    pr_metadata:     dict          # PRMetadata
    task:            dict          # BenchmarkTask
    docker_image:    str
    generated_code:  str
    test_result:     dict          # TestResult
    score_total:     float         # 0-100
    score_test:      float
    score_compile:   float
    score_quality:   float
    quality_notes:   str
    created_at:      str


# ─── 8. 主图全局状态（LangGraph BenchmarkState）─────────────
class BenchmarkState(TypedDict):
    run_config:       dict                              # 运行时配置，不可变
    repos:            list                              # list[RepoInfo]
    prs:              Annotated[list, operator.add]     # Reducer: 并行追加
    benchmark_items:  Annotated[list, operator.add]     # Reducer: 并行追加
    errors:           Annotated[list, operator.add]     # Reducer: 并行收集


# ─── 9. PR 子图局部状态（PRSubState）────────────────────────
class PRSubState(TypedDict):
    pr:                     dict       # PRMetadata
    run_config:             dict
    env_spec:               object     # EnvSpec | None
    dockerfile_path:        object     # str | None
    dockerfile_content:     object     # str | None
    image_tag:              object     # str | None
    build_status:           object     # str | None
    build_retries:          int
    build_log:              object     # str | None
    compile_status:         object     # str | None
    compile_repair_rounds:  int
    compile_repair_log:     object     # str | None
    baseline_test_result:   object     # TestResult | None
    task:                   object     # BenchmarkTask | None
    generated_code:         object     # str | None
    llm_tokens_used:        int
    test_result:            object     # TestResult | None


# ─── interop_type 参考枚举（非强制，供查阅）─────────────────
INTEROP_TYPES = {
    "ffi": ["cgo", "jni", "ctypes", "cffi", "rust_ffi", "node_napi"],
    "runtime_embedding": ["lua_c", "python_cext", "ruby_cext", "v8_cpp"],
    "wasm": ["wasm"],
}

INTEROP_LAYER_MAP = {t: layer for layer, types in INTEROP_TYPES.items() for t in types}
```

#### ✅ 验证步骤 0.2 成功

创建并运行 `tests/test_state.py`：

```python
# tests/test_state.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import (
    RepoInfo, DiffFile, PRMetadata, EnvSpec,
    BenchmarkTask, TestResult, BenchmarkItem,
    BenchmarkState, PRSubState, INTEROP_LAYER_MAP
)


def test_all_types_importable():
    """所有 TypedDict 可以正常导入"""
    assert RepoInfo is not None
    assert BenchmarkState is not None
    assert PRSubState is not None
    print("✓ 所有类型定义可正常导入")


def test_repo_info_creation():
    """RepoInfo 可以正常创建实例"""
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
    print("✓ RepoInfo 实例创建成功")


def test_interop_layer_map():
    """interop_type 到 interop_layer 的映射正确"""
    assert INTEROP_LAYER_MAP["cgo"] == "ffi"
    assert INTEROP_LAYER_MAP["jni"] == "ffi"
    assert INTEROP_LAYER_MAP["lua_c"] == "runtime_embedding"
    assert INTEROP_LAYER_MAP["wasm"] == "wasm"
    print("✓ interop_layer 映射正确")


def test_benchmark_state_reducer():
    """BenchmarkState 的 Annotated Reducer 字段可以合并"""
    import operator
    list_a = [{"pr_id": 1}]
    list_b = [{"pr_id": 2}]
    merged = operator.add(list_a, list_b)
    assert len(merged) == 2
    print("✓ Reducer 字段合并逻辑正确")


if __name__ == "__main__":
    test_all_types_importable()
    test_repo_info_creation()
    test_interop_layer_map()
    test_benchmark_state_reducer()
    print("\n✅ state.py 全部验证通过")
```

```bash
python tests/test_state.py
```

**预期输出：**
```
✓ 所有类型定义可正常导入
✓ RepoInfo 实例创建成功
✓ interop_layer 映射正确
✓ Reducer 字段合并逻辑正确

✅ state.py 全部验证通过
```

---

### 0.3 `github_client.py` — GitHub 访问层

#### 要做什么

封装所有 GitHub API 调用，实现：
- 2 个 token 的轮换（超出限额时自动切换）
- SQLite 缓存（避免重复请求）
- 5 个核心 API 方法

**先实现哪个方法：** 按 `__init__` → `search_repos` → `list_prs` → `get_pr_files` → `get_file_content` → `get_repo_tree` → `list_workflow_files` 的顺序。

#### 操作步骤

**步骤 1：** 创建 `github_client.py` 基础结构

```python
# github_client.py
import os
import json
import sqlite3
import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from github import Github, GithubException, RateLimitExceededException

from state import RepoInfo, DiffFile

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API 封装：token 轮换 + SQLite 缓存"""

    def __init__(
        self,
        tokens: list[str],
        cache_db: str = "benchmark_runs.db",
        min_request_interval: float = 2.0,
    ):
        if not tokens:
            raise ValueError("至少需要提供 1 个 GitHub token")

        self._clients = [Github(t) for t in tokens]
        self._current_idx = 0
        self._min_interval = min_request_interval
        self._last_request_time = 0.0

        # 初始化 SQLite 缓存
        self._conn = sqlite3.connect(cache_db, check_same_thread=False)
        self._init_cache_tables()
        logger.info(f"GitHubClient 初始化完成，{len(tokens)} 个 token")

    def _init_cache_tables(self):
        """创建缓存表（如果不存在）"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS github_cache (
                cache_key   TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                ttl_hours   REAL NOT NULL
            );
        """)
        self._conn.commit()

    def _cache_get(self, key: str) -> Optional[any]:
        """从缓存读取，过期则返回 None"""
        row = self._conn.execute(
            "SELECT value, created_at, ttl_hours FROM github_cache WHERE cache_key = ?",
            (key,)
        ).fetchone()
        if not row:
            return None
        value, created_at, ttl_hours = row
        if ttl_hours >= 0:  # -1 表示永久有效
            expires = datetime.fromisoformat(created_at) + timedelta(hours=ttl_hours)
            if datetime.now() > expires:
                return None
        return json.loads(value)

    def _cache_set(self, key: str, value: any, ttl_hours: float = 24.0):
        """写入缓存"""
        self._conn.execute(
            "INSERT OR REPLACE INTO github_cache (cache_key, value, created_at, ttl_hours) "
            "VALUES (?, ?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str),
             datetime.now().isoformat(), ttl_hours)
        )
        self._conn.commit()

    def _client(self) -> Github:
        """返回当前活跃的 GitHub 客户端"""
        return self._clients[self._current_idx]

    def _rotate_token(self):
        """切换到下一个 token"""
        self._current_idx = (self._current_idx + 1) % len(self._clients)
        logger.warning(f"Token 切换到 idx={self._current_idx}")

    def _throttle(self):
        """限速：两次请求之间至少间隔 min_request_interval 秒"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _api_call(self, func, *args, max_retries: int = 3, **kwargs):
        """
        带重试的 API 调用包装器。
        自动处理 RateLimitExceededException，切换 token 后重试。
        """
        for attempt in range(max_retries):
            try:
                self._throttle()
                return func(*args, **kwargs)
            except RateLimitExceededException:
                logger.warning(f"Rate limit 触发，尝试切换 token（attempt {attempt+1}）")
                self._rotate_token()
                # 查询重置时间，等待
                try:
                    reset_time = self._client().get_rate_limit().core.reset
                    wait_secs = max(0, (reset_time - datetime.utcnow()).total_seconds()) + 10
                    wait_secs = min(wait_secs, 300)  # 最多等 5 分钟
                    logger.info(f"等待 {wait_secs:.0f} 秒后重试")
                    time.sleep(wait_secs)
                except Exception:
                    time.sleep(60)
            except GithubException as e:
                if e.status == 422:
                    raise ValueError(f"GitHub API 查询语法错误: {e.data}") from e
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"GitHub API 错误 {e.status}，重试中...")
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"API 调用在 {max_retries} 次重试后仍失败")

    # ─── 核心 API 方法 ──────────────────────────────────────

    def search_repos(
        self,
        query: str,
        min_stars: int = 50,
        max_results: int = 30,
    ) -> list[RepoInfo]:
        """搜索仓库，带 24 小时缓存"""
        cache_key = f"search:{hashlib.md5(f'{query}{min_stars}'.encode()).hexdigest()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug(f"缓存命中: search_repos({query!r})")
            return cached

        full_query = f"{query} stars:>={min_stars}"
        repos = []
        try:
            result = self._api_call(
                lambda: self._client().search_repositories(full_query, sort="stars")
            )
            for repo in result[:max_results]:
                repos.append({
                    "full_name":     repo.full_name,
                    "clone_url":     repo.clone_url,
                    "stars":         repo.stargazers_count,
                    "interop_type":  "",   # 由 fetch_repos 节点填充
                    "interop_layer": "",
                    "languages":     {},   # 按需获取，此处暂空
                    "default_branch": repo.default_branch or "main",
                })
        except Exception as e:
            logger.error(f"search_repos 失败: {e}")
            return []

        self._cache_set(cache_key, repos, ttl_hours=24.0)
        return repos

    def list_prs(
        self,
        repo_full_name: str,
        max_n: int = 100,
    ) -> list[dict]:
        """列出仓库的已合并 PR，6 小时缓存"""
        cache_key = f"prs:{repo_full_name}:{max_n}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        prs = []
        try:
            repo = self._api_call(
                lambda: self._client().get_repo(repo_full_name)
            )
            pulls = self._api_call(
                lambda: repo.get_pulls(state="closed", sort="updated", direction="desc")
            )
            for pr in pulls[:max_n]:
                if pr.merged_at is None:
                    continue
                prs.append({
                    "number":    pr.number,
                    "title":     pr.title,
                    "merged_at": pr.merged_at.isoformat(),
                    "base_sha":  pr.base.sha,
                    "head_sha":  pr.head.sha,
                })
                if len(prs) >= max_n:
                    break
        except GithubException as e:
            if e.status == 404:
                logger.warning(f"仓库不存在: {repo_full_name}")
                return []
            raise

        self._cache_set(cache_key, prs, ttl_hours=6.0)
        return prs

    def get_pr_files(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> list[DiffFile]:
        """获取 PR 的 diff 文件列表，永久缓存（PR 合并后不变）"""
        cache_key = f"pr_files:{repo_full_name}:{pr_number}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        files = []
        try:
            repo = self._api_call(
                lambda: self._client().get_repo(repo_full_name)
            )
            pr = self._api_call(
                lambda: repo.get_pull(pr_number)
            )
            for f in self._api_call(lambda: pr.get_files()):
                files.append({
                    "path":      f.filename,
                    "lang":      self._detect_lang(f.filename),
                    "is_test":   self._is_test_file(f.filename),
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "status":    f.status,
                })
        except GithubException as e:
            if e.status == 404:
                return []
            raise

        self._cache_set(cache_key, files, ttl_hours=-1)  # 永久
        return files

    def get_file_content(
        self,
        repo_full_name: str,
        sha: str,
        file_path: str,
    ) -> str:
        """获取指定 commit 下的文件内容，永久缓存"""
        cache_key = f"file:{repo_full_name}:{sha}:{file_path}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            repo = self._api_call(
                lambda: self._client().get_repo(repo_full_name)
            )
            content_file = self._api_call(
                lambda: repo.get_contents(file_path, ref=sha)
            )
            if isinstance(content_file, list):
                return ""  # 是目录，不是文件
            if content_file.size > 1_000_000:
                logger.warning(f"文件过大（{content_file.size} bytes），跳过: {file_path}")
                return ""
            decoded = content_file.decoded_content.decode("utf-8", errors="ignore")
        except GithubException as e:
            if e.status == 404:
                return ""
            raise
        except UnicodeDecodeError:
            return ""  # 二进制文件

        self._cache_set(cache_key, decoded, ttl_hours=-1)
        return decoded

    def get_repo_tree(self, repo_full_name: str, sha: str) -> list[str]:
        """获取仓库文件树（路径列表），永久缓存"""
        cache_key = f"tree:{repo_full_name}:{sha}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            repo = self._api_call(
                lambda: self._client().get_repo(repo_full_name)
            )
            tree = self._api_call(
                lambda: repo.get_git_tree(sha, recursive=True)
            )
            paths = [item.path for item in tree.tree if item.type == "blob"]
        except Exception as e:
            logger.error(f"get_repo_tree 失败: {e}")
            return []

        self._cache_set(cache_key, paths, ttl_hours=-1)
        return paths

    def list_workflow_files(self, repo_full_name: str, sha: str) -> list[str]:
        """获取 .github/workflows/ 下所有 YAML 文件内容，永久缓存"""
        cache_key = f"workflows:{repo_full_name}:{sha}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        tree = self.get_repo_tree(repo_full_name, sha)
        workflow_paths = [
            p for p in tree
            if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
        ]
        contents = []
        for path in workflow_paths:
            content = self.get_file_content(repo_full_name, sha, path)
            if content:
                contents.append(content)

        self._cache_set(cache_key, contents, ttl_hours=-1)
        return contents

    # ─── 辅助方法 ────────────────────────────────────────────

    @staticmethod
    def _detect_lang(file_path: str) -> str:
        """根据文件扩展名判断语言"""
        ext_map = {
            ".go": "Go", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
            ".java": "Java", ".kt": "Kotlin", ".py": "Python",
            ".rs": "Rust", ".js": "JavaScript", ".ts": "TypeScript",
            ".rb": "Ruby", ".lua": "Lua", ".wasm": "WASM",
        }
        ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        return ext_map.get(ext, "Other")

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        """判断是否为测试文件"""
        path_lower = file_path.lower()
        test_indicators = [
            "/test/", "/tests/", "/spec/", "/__tests__/",
            "_test.go", "_test.py", ".test.ts", ".test.js",
            ".spec.ts", ".spec.js", "test_", "/test",
        ]
        name = path_lower.split("/")[-1]
        return (
            any(ind in path_lower for ind in test_indicators)
            or name.startswith("test")
        )
```

#### ✅ 验证步骤 0.3 成功

创建并运行 `tests/test_github_client.py`：

```python
# tests/test_github_client.py
"""
测试 GitHubClient 的核心功能。
注意：此测试会发出真实的 GitHub API 请求（消耗 quota），
      建议运行一次后结果会被缓存，后续运行不再消耗 quota。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from github_client import GitHubClient


def get_client():
    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    return GitHubClient(tokens, cache_db=":memory:")  # 使用内存 DB，不污染真实缓存


def test_init():
    client = get_client()
    assert client is not None
    print("✓ GitHubClient 初始化成功")


def test_search_repos_returns_results():
    client = get_client()
    repos = client.search_repos(
        query='language:Go filename:*.c NOT path:vendor',
        min_stars=1000,
        max_results=3,
    )
    assert len(repos) > 0, "搜索应返回至少 1 个结果"
    assert "full_name" in repos[0]
    assert "clone_url" in repos[0]
    assert repos[0]["stars"] >= 1000
    print(f"✓ search_repos 返回 {len(repos)} 个结果，首个: {repos[0]['full_name']}")


def test_list_prs_returns_merged():
    client = get_client()
    # 使用一个已知的稳定仓库
    prs = client.list_prs("golang/go", max_n=5)
    assert len(prs) > 0
    assert all(pr.get("merged_at") is not None for pr in prs)
    print(f"✓ list_prs 返回 {len(prs)} 个 PR，均为 merged 状态")


def test_get_file_content():
    client = get_client()
    # 读取 golang/go 的 README
    content = client.get_file_content(
        "golang/go", "HEAD", "README.md"
    )
    assert len(content) > 100, "README 应有实质内容"
    print(f"✓ get_file_content 成功，内容长度: {len(content)} 字符")


def test_cache_works():
    client = get_client()
    # 第一次调用（真实请求）
    repos_1 = client.search_repos("language:Go", min_stars=10000, max_results=2)
    # 第二次调用（应命中缓存）
    repos_2 = client.search_repos("language:Go", min_stars=10000, max_results=2)
    assert repos_1 == repos_2
    print("✓ 缓存机制正常工作")


def test_detect_lang():
    assert GitHubClient._detect_lang("bridge.go") == "Go"
    assert GitHubClient._detect_lang("native.c") == "C"
    assert GitHubClient._detect_lang("Wrapper.java") == "Java"
    assert GitHubClient._detect_lang("lib.rs") == "Rust"
    print("✓ 语言检测正确")


def test_is_test_file():
    assert GitHubClient._is_test_file("bridge_test.go") == True
    assert GitHubClient._is_test_file("tests/test_bridge.py") == True
    assert GitHubClient._is_test_file("native.c") == False
    assert GitHubClient._is_test_file("bridge.go") == False
    print("✓ 测试文件判断正确")


if __name__ == "__main__":
    test_init()
    test_detect_lang()
    test_is_test_file()
    test_cache_works()
    test_search_repos_returns_results()
    test_list_prs_returns_merged()
    test_get_file_content()
    print("\n✅ github_client.py 全部验证通过")
```

```bash
python tests/test_github_client.py
```

**预期输出（首次运行，约 10-20 秒）：**
```
✓ GitHubClient 初始化成功
✓ 语言检测正确
✓ 测试文件判断正确
✓ 缓存机制正常工作
✓ search_repos 返回 3 个结果，首个: golang/go
✓ list_prs 返回 5 个 PR，均为 merged 状态
✓ get_file_content 成功，内容长度: xxxx 字符

✅ github_client.py 全部验证通过
```

---

## Phase 1：Stage 1 数据采集

> **目标：** 实现仓库筛选 → PR 筛选 → 人工审核的完整 Stage 1 流水线。  
> **完成标志：** `python main.py --mode fetch` 能产出 `prs_snapshot.json`，文件中至少有 1 条有效 PR。

---

### 1.1 `nodes/fetch_repos.py`

#### 要做什么

根据 `run_config` 中的 `interop_types` 列表，分别搜索 GitHub，合并、去重，返回仓库列表。

#### 关键搜索查询设计

每种 `interop_type` 对应一个 GitHub 搜索查询，这些查询是通过 GitHub 代码搜索语法精心设计的，用于找到含跨语言调用信号的仓库：

```python
# nodes/fetch_repos.py
import os, sys, math, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import RepoInfo, BenchmarkState, INTEROP_LAYER_MAP

logger = logging.getLogger(__name__)

# 每种 interop_type 对应的 GitHub Search Query
SEARCH_QUERIES: dict[str, str] = {
    # FFI 层
    "cgo":        'language:Go "import \\"C\\""',
    "jni":        'language:Java "JNIEnv" filename:*.c',
    "ctypes":     'language:Python "ctypes.CDLL" OR "ctypes.cdll"',
    "cffi":       'language:Python "ffi.cdef" OR "cffi.FFI"',
    "rust_ffi":   'language:Rust "extern \\"C\\""',
    "node_napi":  'language:C++ "Napi::" filename:binding.gyp',
    # 运行时嵌入层
    "lua_c":      'language:C "lua_State" "luaL_newstate"',
    "python_cext":'language:C "PyInit_" "PyArg_ParseTuple"',
    "ruby_cext":  'language:C "rb_define_method" "Init_"',
    # WASM 层
    "wasm":       'language:Rust "#[wasm_bindgen]"',
}


def fetch_repos(state: BenchmarkState) -> dict:
    """
    节点函数：搜索 GitHub，筛选含跨语言互操作调用的仓库。
    
    输入：state["run_config"]["interop_types"]，["min_stars"]，["target_repo_count"]
    输出：state["repos"] — list[RepoInfo]
    """
    from github_client import GitHubClient

    cfg = state["run_config"]
    interop_types: list[str] = cfg.get("interop_types", list(SEARCH_QUERIES.keys()))
    min_stars:     int       = cfg.get("min_stars", 50)
    target_count:  int       = cfg.get("target_repo_count", 100)

    # 初始化 client（token 从环境变量读取）
    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    client = GitHubClient(tokens, cache_db=cfg.get("db_path", "benchmark_runs.db"))

    # 每种类型分配的仓库配额
    per_type_quota = math.ceil(target_count / len(interop_types))

    all_repos: dict[str, RepoInfo] = {}  # key = full_name，用于去重

    for interop_type in interop_types:
        query = SEARCH_QUERIES.get(interop_type)
        if not query:
            logger.warning(f"未找到 {interop_type} 的搜索查询，跳过")
            continue

        logger.info(f"搜索 {interop_type} 仓库...")
        repos = client.search_repos(
            query=query,
            min_stars=min_stars,
            max_results=per_type_quota,
        )

        for repo in repos:
            if repo["full_name"] not in all_repos:
                repo["interop_type"]  = interop_type
                repo["interop_layer"] = INTEROP_LAYER_MAP.get(interop_type, "ffi")
                all_repos[repo["full_name"]] = repo

        logger.info(f"  {interop_type}: 找到 {len(repos)} 个仓库")

    # 按 stars 降序，截取 target_count
    result = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
    result = result[:target_count]

    logger.info(f"fetch_repos 完成：共 {len(result)} 个仓库")
    return {"repos": result}
```

#### ✅ 验证步骤 1.1 成功

```python
# tests/test_fetch_repos.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.fetch_repos import fetch_repos, SEARCH_QUERIES


def test_search_queries_coverage():
    """所有 interop_type 都有对应的搜索查询"""
    from state import INTEROP_TYPES
    all_types = [t for types in INTEROP_TYPES.values() for t in types]
    for t in all_types:
        assert t in SEARCH_QUERIES, f"缺少 {t} 的搜索查询"
    print(f"✓ 所有 {len(all_types)} 种 interop_type 均有搜索查询")


def test_fetch_repos_small_scale():
    """小规模搜索测试（只搜 cgo，max 3 个）"""
    initial_state = {
        "run_config": {
            "interop_types": ["cgo"],
            "min_stars": 1000,
            "target_repo_count": 3,
            "db_path": ":memory:",
        },
        "repos": [], "prs": [], "benchmark_items": [], "errors": []
    }
    result = fetch_repos(initial_state)
    repos = result["repos"]
    assert len(repos) > 0, "应找到至少 1 个 CGo 仓库"
    assert all(r["interop_type"] == "cgo" for r in repos)
    assert all(r["interop_layer"] == "ffi" for r in repos)
    assert all(r["stars"] >= 1000 for r in repos)
    print(f"✓ fetch_repos 返回 {len(repos)} 个仓库: {[r['full_name'] for r in repos]}")


if __name__ == "__main__":
    test_search_queries_coverage()
    test_fetch_repos_small_scale()
    print("\n✅ fetch_repos.py 验证通过")
```

```bash
python tests/test_fetch_repos.py
```

---

### 1.2 `nodes/fetch_prs.py`

#### 要做什么

对每个仓库扫描已合并的 PR，通过 5 个过滤条件筛选出含跨语言调用和测试用例的 PR。

```python
# nodes/fetch_prs.py
import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from state import PRMetadata, DiffFile, BenchmarkState

logger = logging.getLogger(__name__)

# 每种 interop_type 的跨语言调用信号关键字
INTEROP_KEYWORDS: dict[str, list[str]] = {
    "cgo":         ['import "C"', "CGO_ENABLED", "//export"],
    "jni":         ["JNIEnv", "JNIEXPORT", "jclass", "jobject"],
    "ctypes":      ["ctypes.cdll", "ctypes.CDLL", "CFUNCTYPE", "ctypes.c_"],
    "cffi":        ["ffi.cdef", "ffi.open", "ffi.new"],
    "rust_ffi":    ['#[no_mangle]', 'extern "C"'],
    "node_napi":   ["Napi::", "NODE_API_MODULE", "#include <napi.h>"],
    "lua_c":       ["lua_State", "luaL_newstate", "lua_pcall", "lua_pushstring"],
    "python_cext": ["PyInit_", "PyArg_ParseTuple", "Py_BuildValue", "PyObject"],
    "ruby_cext":   ["Init_", "rb_define_method", "VALUE", "rb_intern"],
    "wasm":        ["#[wasm_bindgen]", "WebAssembly.instantiate", "wasm_bindgen"],
}


def _has_interop_signal(diff_files: list[DiffFile], interop_type: str) -> bool:
    """检查 diff 文件中是否存在跨语言调用信号（关键字层面的快速判断）"""
    # 注意：此时 diff_files 只有元数据，没有文件内容
    # 通过文件扩展名和路径做初步判断，详细内容分析在 construct_task 中进行
    keywords = INTEROP_KEYWORDS.get(interop_type, [])
    # 简化策略：如果 diff 同时包含两种语言文件，认为有跨语言信号
    langs = set(f["lang"] for f in diff_files)
    interop_lang_pairs = {
        "cgo":         ({"Go", "C"}),
        "jni":         ({"Java", "C"}),
        "ctypes":      ({"Python", "C"}),
        "cffi":        ({"Python", "C"}),
        "rust_ffi":    ({"Rust", "C"}),
        "node_napi":   ({"JavaScript", "C++"}),
        "lua_c":       ({"C", "Lua"}),
        "python_cext": ({"C", "Python"}),
        "ruby_cext":   ({"C", "Ruby"}),
        "wasm":        ({"Rust", "JavaScript"}),
    }
    expected_pair = interop_lang_pairs.get(interop_type, set())
    # 至少包含期望语言对中的两种语言
    return len(langs & expected_pair) >= 2


def fetch_prs(state: BenchmarkState) -> dict:
    """
    节点函数：扫描仓库 PR，筛选含跨语言调用+测试用例的已合并 PR。
    
    输入：state["repos"]，state["run_config"]
    输出：追加到 state["prs"]（Reducer 自动合并）
    """
    from github_client import GitHubClient

    cfg = state["run_config"]
    max_prs_per_repo = cfg.get("max_prs_per_repo", 100)
    target_items     = cfg.get("target_items", 300)
    min_diff_lines   = cfg.get("min_diff_lines", 50)
    max_diff_lines   = cfg.get("max_diff_lines", 2000)

    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    client = GitHubClient(tokens, cache_db=cfg.get("db_path", "benchmark_runs.db"))

    found_prs: list[PRMetadata] = []

    for repo_info in state["repos"]:
        # 目标驱动：候选池已满则停止
        if len(found_prs) >= target_items:
            logger.info(f"候选池已达目标 {target_items}，停止扫描")
            break

        repo_name    = repo_info["full_name"]
        interop_type = repo_info["interop_type"]
        logger.info(f"扫描 {repo_name} [{interop_type}]...")

        raw_prs = client.list_prs(repo_name, max_n=max_prs_per_repo)

        for raw_pr in raw_prs:
            # C1: 已合并（list_prs 已过滤）
            diff_files = client.get_pr_files(repo_name, raw_pr["number"])
            if not diff_files:
                continue

            # C2: diff 涉及 >= 2 种语言
            langs = set(f["lang"] for f in diff_files)
            if len(langs) < 2:
                continue

            # C3: 至少 1 个测试文件
            if not any(f["is_test"] for f in diff_files):
                continue

            # C4: diff 行数在合理范围内
            total_lines = sum(f["additions"] + f["deletions"] for f in diff_files)
            if not (min_diff_lines <= total_lines <= max_diff_lines):
                continue

            # C5: 存在跨语言调用信号
            if not _has_interop_signal(diff_files, interop_type):
                continue

            # 通过所有过滤条件
            pr: PRMetadata = {
                "repo":             repo_name,
                "clone_url":        repo_info["clone_url"],
                "pr_id":            raw_pr["number"],
                "pr_title":         raw_pr["title"],
                "interop_type":     interop_type,
                "interop_layer":    repo_info["interop_layer"],
                "base_sha":         raw_pr["base_sha"],
                "head_sha":         raw_pr["head_sha"],
                "diff_files":       diff_files,
                "diff_total_lines": total_lines,
                "test_commands":    None,  # 由 infer_env 填充
                "merged_at":        raw_pr["merged_at"],
            }
            found_prs.append(pr)
            logger.info(f"  ✓ PR #{raw_pr['number']}: {raw_pr['title'][:50]}")

    logger.info(f"fetch_prs 完成：共找到 {len(found_prs)} 个候选 PR")
    return {"prs": found_prs}
```

#### ✅ 验证步骤 1.2 成功

```python
# tests/test_fetch_prs.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.fetch_prs import _has_interop_signal, fetch_prs


def test_interop_signal_detection():
    """跨语言调用信号检测逻辑"""
    # CGo: Go + C 文件 → 有信号
    diff_files = [
        {"path": "bridge.go", "lang": "Go", "is_test": False, "additions": 10, "deletions": 2, "status": "modified"},
        {"path": "native.c",  "lang": "C",  "is_test": False, "additions": 5,  "deletions": 1, "status": "modified"},
    ]
    assert _has_interop_signal(diff_files, "cgo") == True

    # 纯 Go 文件 → 无信号
    diff_files_go_only = [
        {"path": "main.go", "lang": "Go", "is_test": False, "additions": 10, "deletions": 0, "status": "modified"},
    ]
    assert _has_interop_signal(diff_files_go_only, "cgo") == False
    print("✓ 跨语言信号检测正确")


def test_fetch_prs_filters():
    """PR 筛选条件的边界测试（使用 mock）"""
    from unittest.mock import patch, MagicMock

    mock_repo_info = {
        "full_name": "test/repo",
        "clone_url": "https://github.com/test/repo.git",
        "interop_type": "cgo",
        "interop_layer": "ffi",
        "stars": 1000,
        "default_branch": "main",
    }

    # 构造一个通过所有过滤条件的 PR
    good_pr_files = [
        {"path": "bridge.go",      "lang": "Go", "is_test": False, "additions": 30, "deletions": 5, "status": "modified"},
        {"path": "native.c",       "lang": "C",  "is_test": False, "additions": 20, "deletions": 3, "status": "modified"},
        {"path": "bridge_test.go", "lang": "Go", "is_test": True,  "additions": 15, "deletions": 0, "status": "added"},
    ]

    with patch("nodes.fetch_prs.GitHubClient") as MockClient:
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.list_prs.return_value = [
            {"number": 1, "title": "Add CGo bridge", "merged_at": "2024-01-01T00:00:00",
             "base_sha": "abc", "head_sha": "def"}
        ]
        mock_instance.get_pr_files.return_value = good_pr_files

        result = fetch_prs({
            "repos": [mock_repo_info],
            "prs": [],
            "benchmark_items": [],
            "errors": [],
            "run_config": {
                "max_prs_per_repo": 10,
                "target_items": 5,
                "min_diff_lines": 10,
                "max_diff_lines": 500,
                "db_path": ":memory:",
            }
        })
        assert len(result["prs"]) == 1
        pr = result["prs"][0]
        assert pr["pr_id"] == 1
        assert pr["interop_type"] == "cgo"
        print("✓ fetch_prs 筛选逻辑正确")


if __name__ == "__main__":
    test_interop_signal_detection()
    test_fetch_prs_filters()
    print("\n✅ fetch_prs.py 验证通过")
```

```bash
python tests/test_fetch_prs.py
```

---

### 1.3 `nodes/human_review.py`

#### 要做什么

实现可选的人工审核节点。`skip_review=True` 时直接透传；否则使用 LangGraph 的 `interrupt()` 暂停图执行，等待外部注入审核结果。

```python
# nodes/human_review.py
import logging
from collections import Counter
from langgraph.types import interrupt
from state import BenchmarkState

logger = logging.getLogger(__name__)


def human_review(state: BenchmarkState) -> dict:
    """
    节点函数：可选人工审核节点。
    
    skip_review=True  → 直接透传，不修改 prs
    skip_review=False → 调用 interrupt() 暂停，等待人工确认
    """
    if state["run_config"].get("skip_review", False):
        logger.info(f"human_review: 跳过（skip_review=True），保留全部 {len(state['prs'])} 个 PR")
        return {}

    # 构造展示给人工审核者的统计信息
    prs = state["prs"]
    by_type  = Counter(p["interop_type"] for p in prs)
    by_layer = Counter(p["interop_layer"] for p in prs)

    logger.info(f"human_review: 暂停，等待人工审核 {len(prs)} 个 PR")

    # interrupt() 会暂停 Graph，将数据暴露给外部
    # 外部调用 app.update_state(config, {"approved_pr_ids": [...]}) 后继续
    decision = interrupt({
        "message":      "请审核以下 PR 列表，确认要保留哪些",
        "total_count":  len(prs),
        "by_interop_type":  dict(by_type),
        "by_interop_layer": dict(by_layer),
        "prs_summary":  [
            {"pr_id": p["pr_id"], "repo": p["repo"],
             "title": p["pr_title"], "type": p["interop_type"]}
            for p in prs
        ],
    })

    # 恢复后，从 decision 中读取审核结果
    approved_ids = decision.get("approved_pr_ids")
    if approved_ids is None:
        # 未提供则默认全部批准
        logger.info("human_review: 未提供 approved_pr_ids，全部批准")
        return {}

    approved_set = set(approved_ids)
    filtered = [p for p in prs if p["pr_id"] in approved_set]
    logger.info(f"human_review: 人工批准 {len(filtered)}/{len(prs)} 个 PR")
    return {"prs": filtered}
```

#### ✅ 验证步骤 1.3 成功

```python
# tests/test_human_review.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.human_review import human_review


SAMPLE_PRS = [
    {"pr_id": 1, "repo": "a/b", "pr_title": "Add CGo bridge",
     "interop_type": "cgo", "interop_layer": "ffi"},
    {"pr_id": 2, "repo": "c/d", "pr_title": "JNI wrapper",
     "interop_type": "jni", "interop_layer": "ffi"},
]

SAMPLE_STATE = {
    "prs": SAMPLE_PRS,
    "repos": [], "benchmark_items": [], "errors": [],
    "run_config": {}
}


def test_skip_review_passthrough():
    """skip_review=True 时直接返回空 dict，不修改 prs"""
    state = {**SAMPLE_STATE, "run_config": {"skip_review": True}}
    result = human_review(state)
    assert result == {}, f"应返回空 dict，实际: {result}"
    print("✓ skip_review=True 时正确跳过")


def test_human_review_requires_interrupt():
    """skip_review=False 时应调用 interrupt()（这里测试它会抛出特定异常）"""
    from langgraph.types import Interrupt
    state = {**SAMPLE_STATE, "run_config": {"skip_review": False}}
    try:
        human_review(state)
        assert False, "应该抛出 Interrupt 异常"
    except Exception as e:
        # LangGraph 的 interrupt() 会抛出特殊的 Interrupt 类型
        assert "interrupt" in type(e).__name__.lower() or "Interrupt" in str(type(e))
        print("✓ skip_review=False 时正确触发 interrupt()")


if __name__ == "__main__":
    test_skip_review_passthrough()
    test_human_review_requires_interrupt()
    print("\n✅ human_review.py 验证通过")
```

---

### 1.4 `graph.py`（Stage 1 部分）+ `main.py`（fetch 模式）

#### 要做什么

组装 Stage 1 图，实现 `fetch` 执行模式，让整个 Stage 1 可以独立运行并产出 `prs_snapshot.json`。

**步骤 1：** 创建 `graph.py` Stage 1 版本

```python
# graph.py
import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Send

from state import BenchmarkState, PRSubState
from nodes.fetch_repos   import fetch_repos
from nodes.fetch_prs     import fetch_prs
from nodes.human_review  import human_review

# 全局 Docker 并发信号量（在 Phase 2 中激活）
_DOCKER_SEMAPHORE: asyncio.Semaphore | None = None

def get_docker_semaphore(max_concurrent: int = 4) -> asyncio.Semaphore:
    global _DOCKER_SEMAPHORE
    if _DOCKER_SEMAPHORE is None:
        _DOCKER_SEMAPHORE = asyncio.Semaphore(max_concurrent)
    return _DOCKER_SEMAPHORE


def build_graph(db_path: str = "benchmark_runs.db") -> object:
    """构建并编译 LangGraph 主图"""
    g = StateGraph(BenchmarkState)

    # Stage 1 节点
    g.add_node("fetch_repos",  fetch_repos)
    g.add_node("fetch_prs",    fetch_prs)
    g.add_node("human_review", human_review)

    # TODO Phase 4: 添加 process_pr 和 aggregate 节点

    # 边连接
    g.add_edge(START, "fetch_repos")
    g.add_edge("fetch_repos", "fetch_prs")
    g.add_edge("fetch_prs", "human_review")
    g.add_edge("human_review", END)  # Phase 4 中改为 fan-out 到子图

    checkpointer = SqliteSaver.from_conn_string(db_path)
    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
```

**步骤 2：** 创建 `main.py` fetch 模式

```python
# main.py
import argparse, json, os, logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)

BASE_RUN_CONFIG = {
    "interop_types":      ["cgo", "jni", "ctypes", "rust_ffi", "node_napi",
                           "lua_c", "python_cext", "ruby_cext", "wasm"],
    "min_stars":          50,
    "max_prs_per_repo":   100,
    "target_items":       300,
    "target_repo_count":  100,
    "per_repo_cap":       None,
    "skip_review":        False,
    "task_strategy":      "completion",
    "target_llm":         "claude-sonnet-4-20250514",
    "judge_llm":          "claude-sonnet-4-20250514",
    "min_diff_lines":     50,
    "max_diff_lines":     2000,
    "max_concurrent_docker": 4,
}


def make_initial_state(run_config: dict) -> dict:
    return {
        "run_config": run_config,
        "repos": [], "prs": [], "benchmark_items": [], "errors": []
    }


def run_fetch(args):
    """只跑 Stage 1，结果保存到文件"""
    from graph import build_graph

    db_path   = args.db
    thread_id = args.thread_id or f"fetch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config    = {"configurable": {"thread_id": thread_id}}

    run_config = {**BASE_RUN_CONFIG,
                  "skip_review": True,  # fetch 模式默认跳过人工审核
                  "db_path": db_path}

    # 允许命令行覆盖部分参数
    if args.interop_types:
        run_config["interop_types"] = args.interop_types.split(",")
    if args.min_stars:
        run_config["min_stars"] = args.min_stars

    app    = build_graph(db_path=db_path)
    result = app.invoke(make_initial_state(run_config), config)

    prs         = result.get("prs", [])
    output_path = args.output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(prs, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ fetch 完成")
    print(f"   PR 数量：{len(prs)}")
    print(f"   输出文件：{output_path}")
    print(f"   thread_id：{thread_id}（续跑时使用）")


def run_resume(args):
    from graph import build_graph
    app    = build_graph(db_path=args.db)
    config = {"configurable": {"thread_id": args.thread_id}}
    result = app.invoke(None, config)
    print(f"✅ resume 完成，benchmark_items: {len(result.get('benchmark_items', []))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="跨语言 Benchmark 构建工具")
    parser.add_argument("--mode", choices=["full","fetch","build","single-pr","resume"],
                        default="fetch")
    parser.add_argument("--thread-id",    default=None)
    parser.add_argument("--input",        default="prs_snapshot.json")
    parser.add_argument("--output",       default="prs_snapshot.json")
    parser.add_argument("--pr-json",      default="tests/fixtures/sample_pr.json")
    parser.add_argument("--interop-types",default=None)
    parser.add_argument("--min-stars",    type=int, default=None)
    parser.add_argument("--skip-review",  action="store_true")
    parser.add_argument("--db",           default="benchmark_runs.db")
    args = parser.parse_args()

    dispatch = {
        "fetch":  run_fetch,
        "resume": run_resume,
        # full / build / single-pr 在 Phase 4 中实现
    }
    if args.mode in dispatch:
        dispatch[args.mode](args)
    else:
        print(f"模式 '{args.mode}' 将在 Phase 4 实现")
```

#### ✅ 验证步骤 1.4 成功

```bash
# 小规模测试：只搜 cgo，min_stars=5000，快速验证流程可跑通
python main.py \
  --mode fetch \
  --interop-types cgo \
  --min-stars 5000 \
  --output tests/fixtures/sample_prs.json
```

**预期输出：**
```
✅ fetch 完成
   PR 数量：X（至少 1 个）
   输出文件：tests/fixtures/sample_prs.json
   thread_id：fetch-YYYYMMDD-HHMMSS
```

```bash
# 验证输出文件格式正确
python -c "
import json
with open('tests/fixtures/sample_prs.json') as f:
    prs = json.load(f)
print(f'共 {len(prs)} 个 PR')
if prs:
    pr = prs[0]
    required = ['repo','pr_id','interop_type','head_sha','diff_files']
    for field in required:
        assert field in pr, f'缺少字段: {field}'
    print(f'第一个 PR: {pr[\"repo\"]}#{pr[\"pr_id\"]} [{pr[\"interop_type\"]}]')
    print('✓ 输出格式正确')
"
```

---

### 1.5 Stage 1 集成验证

在进入 Phase 2 之前，确保 Stage 1 端到端可用：

```python
# tests/test_stage1_integration.py
"""Stage 1 集成测试：从 fetch_repos 到 prs_snapshot.json"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_stage1_produces_valid_snapshot():
    """Stage 1 完整流程能产出格式正确的 PR 快照"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_path = f.name

    os.system(
        f"python main.py --mode fetch "
        f"--interop-types cgo --min-stars 10000 "
        f"--output {output_path} --db :memory: 2>/dev/null"
    )

    with open(output_path) as f:
        prs = json.load(f)

    assert isinstance(prs, list), "输出应为 JSON 数组"
    if prs:
        pr = prs[0]
        for field in ["repo", "pr_id", "interop_type", "interop_layer",
                      "head_sha", "diff_files", "merged_at"]:
            assert field in pr, f"PR 缺少必要字段: {field}"
        assert pr["interop_type"] == "cgo"
        assert len(pr["diff_files"]) > 0
        print(f"✓ Stage 1 产出 {len(prs)} 个有效 PR")
    else:
        print("⚠ 未找到 PR（可能是网络问题或搜索限制），但流程本身正常运行")

    os.unlink(output_path)


if __name__ == "__main__":
    test_stage1_produces_valid_snapshot()
    print("\n✅ Stage 1 集成验证通过")
```

---

## Phase 2：Stage 2 容器环境构建

> **目标：** 实现从 PR 元数据到可运行 Docker 容器的完整流程，包括环境推断、Dockerfile 生成、镜像构建和容器内编译验证。  
> **完成标志：** `python main.py --mode single-pr` 能对一个已知 CGo PR 成功构建容器并通过 baseline 测试。

---

### 2.1 `nodes/infer_env.py`

#### 要做什么

四层降级推断构建环境：仓库自带 Dockerfile → CI workflow 提取 → LLM 推断 → 跳过。

```python
# nodes/infer_env.py
import os, re, yaml, logging
from state import PRSubState, EnvSpec

logger = logging.getLogger(__name__)

# base image 映射表
BASE_IMAGE_MAP = {
    "cgo":         "golang:1.22",
    "jni":         "maven:3.9-jdk-17",
    "ctypes":      "python:3.11",
    "cffi":        "python:3.11",
    "rust_ffi":    "rust:1.77",
    "node_napi":   "node:20",
    "lua_c":       "gcc:13",
    "python_cext": "python:3.11",
    "ruby_cext":   "ruby:3.2",
    "wasm":        "node:20",
}

LANG_TO_SUFFIX = {
    "Go": ".go", "Python": ".py", "Java": ".java", "Rust": ".rs",
    "JavaScript": ".js", "TypeScript": ".ts", "C": ".c", "C++": ".cpp",
    "Ruby": ".rb", "Lua": ".lua",
}


def infer_env(state: PRSubState) -> dict:
    """
    节点函数：四层降级推断构建环境，输出 EnvSpec。
    """
    from github_client import GitHubClient
    cfg = state["run_config"]
    pr  = state["pr"]

    tokens = [
        os.environ["GITHUB_TOKEN_1"],
        os.environ.get("GITHUB_TOKEN_2", os.environ["GITHUB_TOKEN_1"]),
    ]
    client = GitHubClient(tokens, cache_db=cfg.get("db_path", "benchmark_runs.db"))

    repo_name    = pr["repo"]
    head_sha     = pr["head_sha"]
    interop_type = pr["interop_type"]

    # ── 第一层：仓库自带 Dockerfile ──────────────────────────
    env = _try_repo_dockerfile(client, repo_name, head_sha, interop_type)
    if env:
        logger.info(f"  [infer_env] 第一层命中: 仓库自带 Dockerfile")
        return {"env_spec": env}

    # ── 第二层：GitHub Actions workflow 提取 ─────────────────
    env = _try_github_actions(client, repo_name, head_sha, interop_type)
    if env:
        logger.info(f"  [infer_env] 第二层命中: GitHub Actions")
        return {"env_spec": env}

    # ── 第三层：LLM 推断 ─────────────────────────────────────
    env = _try_llm_inference(client, repo_name, head_sha, interop_type,
                              pr["diff_files"], cfg.get("llm_model", "claude-sonnet-4-20250514"))
    if env:
        logger.info(f"  [infer_env] 第三层命中: LLM 推断")
        return {"env_spec": env}

    # ── 第四层：跳过 ─────────────────────────────────────────
    logger.warning(f"  [infer_env] 所有层均失败，跳过 PR #{pr['pr_id']}")
    error = {
        "pr_id": pr["pr_id"], "repo": repo_name,
        "stage": "infer_env", "reason": "all_layers_failed",
        "message": "四层降级策略全部失败"
    }
    failed_env: EnvSpec = {
        "source": "failed", "base_image": "",
        "system_deps": [], "build_cmds": [], "test_cmds": [],
        "test_framework": "generic", "dockerfile_content": None,
    }
    return {"env_spec": failed_env, "build_status": "failed",
            "errors": [error]}  # 触发 route_after_build 的 END 分支


# ── 各层实现 ─────────────────────────────────────────────────

def _try_repo_dockerfile(client, repo_name: str, sha: str, interop_type: str) -> EnvSpec | None:
    """第一层：检查仓库是否自带 Dockerfile"""
    tree = client.get_repo_tree(repo_name, sha)
    candidates = ["Dockerfile", "docker/Dockerfile", ".docker/Dockerfile",
                  "Dockerfile.dev", "docker/Dockerfile.dev"]
    for path in candidates:
        if path in tree:
            content = client.get_file_content(repo_name, sha, path)
            if not content:
                continue
            # 替换 CMD/ENTRYPOINT 为测试命令
            test_cmds = _default_test_cmds(interop_type)
            patched = _patch_cmd_to_test(content, test_cmds)
            framework = _detect_framework(content, interop_type)
            return {
                "source": "repo_dockerfile",
                "base_image": _extract_base_image(content),
                "system_deps": [],
                "build_cmds":  _default_build_cmds(interop_type),
                "test_cmds":   test_cmds,
                "test_framework": framework,
                "dockerfile_content": patched,
            }
    return None


def _try_github_actions(client, repo_name: str, sha: str, interop_type: str) -> EnvSpec | None:
    """第二层：解析 GitHub Actions workflow 提取依赖和命令"""
    workflow_contents = client.list_workflow_files(repo_name, sha)
    for content in workflow_contents:
        try:
            wf = yaml.safe_load(content)
        except Exception:
            continue
        if not isinstance(wf, dict):
            continue

        deps  = _extract_apt_installs(content)
        build = _extract_run_steps(wf, kind="build")
        test  = _extract_run_steps(wf, kind="test")

        if test:
            framework = _detect_framework_from_cmds(test, interop_type)
            return {
                "source": "github_actions",
                "base_image": BASE_IMAGE_MAP.get(interop_type, "ubuntu:22.04"),
                "system_deps": deps,
                "build_cmds": build or _default_build_cmds(interop_type),
                "test_cmds": test,
                "test_framework": framework,
                "dockerfile_content": None,
            }
    return None


def _try_llm_inference(client, repo_name: str, sha: str, interop_type: str,
                       diff_files: list, model: str) -> EnvSpec | None:
    """第三层：LLM 综合推断"""
    # 收集上下文
    context_files = {}
    for fname in ["go.mod", "Cargo.toml", "pom.xml", "pyproject.toml",
                  "requirements.txt", "package.json", "Makefile", "README.md"]:
        tree = client.get_repo_tree(repo_name, sha)
        if fname in tree:
            content = client.get_file_content(repo_name, sha, fname)
            if content:
                context_files[fname] = content[:2000]  # 只取前 2000 字符

    if not context_files:
        return None

    prompt = f"""你是一个 Docker 专家。以下是一个 {interop_type} 跨语言项目的配置文件。
请生成一个能够让这个项目编译并运行测试的 Dockerfile。

项目文件：
{chr(10).join(f'### {name}{chr(10)}{content}' for name, content in context_files.items())}

只输出 Dockerfile 内容，不要解释。"""

    try:
        import anthropic
        client_llm = anthropic.Anthropic(api_key=os.environ.get("TARGET_LLM_API_KEY", ""))
        response = client_llm.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        dockerfile_content = response.content[0].text.strip()
        # 去除可能的 markdown 代码块
        if dockerfile_content.startswith("```"):
            lines = dockerfile_content.split("\n")
            dockerfile_content = "\n".join(lines[1:-1])

        test_cmds = _default_test_cmds(interop_type)
        return {
            "source": "llm",
            "base_image": BASE_IMAGE_MAP.get(interop_type, "ubuntu:22.04"),
            "system_deps": [],
            "build_cmds": _default_build_cmds(interop_type),
            "test_cmds": test_cmds,
            "test_framework": _detect_framework("", interop_type),
            "dockerfile_content": dockerfile_content,
        }
    except Exception as e:
        logger.warning(f"LLM 推断失败: {e}")
        return None


# ── 辅助函数 ─────────────────────────────────────────────────

def _patch_cmd_to_test(dockerfile: str, test_cmds: list[str]) -> str:
    """替换 Dockerfile 的 CMD/ENTRYPOINT 为测试命令"""
    lines = dockerfile.split("\n")
    new_lines = []
    test_cmd_line = f'CMD {json.dumps(test_cmds[0].split()) if test_cmds else "[]"}'
    replaced = False
    for line in reversed(lines):
        if not replaced and (line.strip().startswith("CMD") or
                             line.strip().startswith("ENTRYPOINT")):
            new_lines.insert(0, test_cmd_line)
            replaced = True
        else:
            new_lines.insert(0, line)
    if not replaced:
        new_lines.append(test_cmd_line)
    return "\n".join(new_lines)


def _extract_apt_installs(workflow_content: str) -> list[str]:
    """从 workflow 内容提取 apt-get install 的包名"""
    pattern = r'apt-get install\s+(?:-y\s+)?(.+)'
    deps = []
    for match in re.finditer(pattern, workflow_content):
        pkgs = match.group(1).replace("\\", "").split()
        deps.extend([p for p in pkgs if not p.startswith("-")])
    return list(dict.fromkeys(deps))  # 去重保序


def _extract_run_steps(wf: dict, kind: str) -> list[str]:
    """从 workflow dict 提取含 kind 关键字的 run 步骤"""
    cmds = []
    def _walk(obj):
        if isinstance(obj, dict):
            if "run" in obj:
                run_val = obj["run"]
                if isinstance(run_val, str) and kind in run_val.lower():
                    cmds.append(run_val.strip())
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(wf)
    return cmds[:3]  # 最多返回 3 条


def _extract_base_image(dockerfile: str) -> str:
    match = re.search(r'^FROM\s+(\S+)', dockerfile, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else "ubuntu:22.04"


def _default_build_cmds(interop_type: str) -> list[str]:
    return {
        "cgo":         ["go build ./..."],
        "jni":         ["mvn compile -q"],
        "ctypes":      ["pip install -e . -q"],
        "cffi":        ["pip install -e . -q"],
        "rust_ffi":    ["cargo build"],
        "node_napi":   ["npm install", "npm run build"],
        "lua_c":       ["make"],
        "python_cext": ["python setup.py build_ext --inplace"],
        "ruby_cext":   ["ruby extconf.rb", "make"],
        "wasm":        ["wasm-pack build"],
    }.get(interop_type, ["make"])


def _default_test_cmds(interop_type: str) -> list[str]:
    return {
        "cgo":         ["go test -v -json ./..."],
        "jni":         ["mvn test"],
        "ctypes":      ["pytest -q"],
        "cffi":        ["pytest -q"],
        "rust_ffi":    ["cargo test"],
        "node_napi":   ["npm test"],
        "lua_c":       ["make test"],
        "python_cext": ["pytest -q"],
        "ruby_cext":   ["ruby -Itest test/**/*_test.rb"],
        "wasm":        ["npm test"],
    }.get(interop_type, ["make test"])


def _detect_framework(content: str, interop_type: str) -> str:
    if interop_type in ("cgo",):           return "go_test"
    if interop_type in ("rust_ffi",):      return "cargo"
    if interop_type in ("ctypes","cffi","python_cext"): return "pytest"
    if interop_type in ("jni",):           return "junit"
    if interop_type in ("node_napi","wasm"): return "jest"
    return "generic"


def _detect_framework_from_cmds(cmds: list[str], interop_type: str) -> str:
    cmd_str = " ".join(cmds).lower()
    if "pytest" in cmd_str:  return "pytest"
    if "cargo test" in cmd_str: return "cargo"
    if "go test" in cmd_str: return "go_test"
    if "mvn test" in cmd_str or "gradle test" in cmd_str: return "junit"
    if "jest" in cmd_str or "npm test" in cmd_str: return "jest"
    return _detect_framework("", interop_type)


import json  # 补充 import（_patch_cmd_to_test 中用到）
```

#### ✅ 验证步骤 2.1 成功

```python
# tests/test_infer_env.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.infer_env import (
    _patch_cmd_to_test, _extract_apt_installs,
    _default_build_cmds, _default_test_cmds,
    _detect_framework, BASE_IMAGE_MAP
)


def test_patch_cmd_to_test():
    dockerfile = "FROM golang:1.22\nRUN go build ./...\nCMD [\"./myapp\"]"
    patched = _patch_cmd_to_test(dockerfile, ["go test ./..."])
    assert "go test" in patched
    assert "CMD" in patched
    print("✓ _patch_cmd_to_test 正确替换 CMD")


def test_extract_apt_installs():
    workflow = """
      - run: sudo apt-get install -y gcc libssl-dev libffi-dev
      - run: apt-get install -y build-essential
    """
    deps = _extract_apt_installs(workflow)
    assert "gcc" in deps
    assert "libssl-dev" in deps
    print(f"✓ _extract_apt_installs 提取到: {deps}")


def test_default_cmds_coverage():
    """所有 interop_type 都有默认构建和测试命令"""
    from state import INTEROP_TYPES
    all_types = [t for types in INTEROP_TYPES.values() for t in types]
    for t in all_types:
        build = _default_build_cmds(t)
        test  = _default_test_cmds(t)
        assert len(build) > 0
        assert len(test) > 0
    print(f"✓ 所有 {len(all_types)} 种类型均有默认命令")


def test_base_image_coverage():
    from state import INTEROP_TYPES
    all_types = [t for types in INTEROP_TYPES.values() for t in types]
    for t in all_types:
        assert t in BASE_IMAGE_MAP, f"缺少 {t} 的 base image"
    print("✓ BASE_IMAGE_MAP 覆盖所有 interop_type")


if __name__ == "__main__":
    test_patch_cmd_to_test()
    test_extract_apt_installs()
    test_default_cmds_coverage()
    test_base_image_coverage()
    print("\n✅ infer_env.py 验证通过")
```

---

### 2.2 `nodes/build_dockerfile.py` + 模板文件

#### 要做什么

根据 `EnvSpec` 生成最终 Dockerfile 并写入临时目录。第一层来源直接用 `dockerfile_content`；其他来源使用 Jinja2 模板渲染。

**步骤 1：** 创建 CGo Dockerfile 模板（其他模板类似，格式相同）

```dockerfile
{# dockerfiles/templates/cgo.dockerfile.j2 #}
FROM {{ base_image }}

RUN apt-get update && apt-get install -y \
    gcc \
    libc-dev \
    git \
    {% for dep in system_deps %}{{ dep }} \
    {% endfor %}
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone --depth=1 {{ clone_url }} . && git checkout {{ head_sha }}

RUN go mod download 2>/dev/null || true

{% for cmd in build_cmds %}
RUN {{ cmd }}
{% endfor %}

CMD {{ test_cmds | tojson }}
```

按相同格式创建其余模板：`jni.dockerfile.j2`、`ctypes.dockerfile.j2`、`rust_ffi.dockerfile.j2`、`node_napi.dockerfile.j2`、`lua_c.dockerfile.j2`、`python_cext.dockerfile.j2`、`ruby_cext.dockerfile.j2`、`wasm.dockerfile.j2`。

**步骤 2：** 创建 `build_dockerfile.py`

```python
# nodes/build_dockerfile.py
import os, json, tempfile, pathlib, logging
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from state import PRSubState

logger = logging.getLogger(__name__)

TEMPLATE_DIR = pathlib.Path(__file__).parent.parent / "dockerfiles" / "templates"


def build_dockerfile(state: PRSubState) -> dict:
    """
    节点函数：根据 EnvSpec 生成 Dockerfile 并写入临时目录。
    
    输入：state["pr"]（interop_type, clone_url, head_sha），state["env_spec"]
    输出：state["dockerfile_path"]，state["dockerfile_content"]，state["image_tag"]
    """
    pr      = state["pr"]
    env     = state["env_spec"]

    # 生成 image tag（全小写，只含字母数字和连字符）
    repo_slug = pr["repo"].replace("/", "-").lower()
    image_tag = f"benchmark-{repo_slug}-pr{pr['pr_id']}"
    image_tag = "".join(c if c.isalnum() or c == "-" else "-" for c in image_tag)

    # ── 第一层来源：直接使用已 patch 的 Dockerfile 内容 ──────
    if env["source"] == "repo_dockerfile" and env.get("dockerfile_content"):
        content = env["dockerfile_content"]
    else:
        # ── 其他来源：渲染 Jinja2 模板 ──────────────────────
        try:
            jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
            template  = jinja_env.get_template(f"{pr['interop_type']}.dockerfile.j2")
            content   = template.render(
                base_image  = env["base_image"],
                system_deps = env["system_deps"],
                clone_url   = pr["clone_url"],
                head_sha    = pr["head_sha"],
                build_cmds  = env["build_cmds"],
                test_cmds   = env["test_cmds"],
            )
        except TemplateNotFound:
            logger.error(f"模板不存在: {pr['interop_type']}.dockerfile.j2")
            error = {
                "pr_id": pr["pr_id"], "repo": pr["repo"],
                "stage": "build_dockerfile", "reason": "template_not_found",
                "message": f"模板文件 {pr['interop_type']}.dockerfile.j2 不存在"
            }
            return {"build_status": "failed", "errors": [error]}

    # ── 写入临时目录 ─────────────────────────────────────────
    tmp_dir = pathlib.Path(tempfile.gettempdir()) / "benchmark" / image_tag
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = str(tmp_dir / "Dockerfile")
    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"  [build_dockerfile] 生成完成: {dockerfile_path}")
    return {
        "dockerfile_path":    dockerfile_path,
        "dockerfile_content": content,
        "image_tag":          image_tag,
    }
```

#### ✅ 验证步骤 2.2 成功

```python
# tests/test_build_dockerfile.py
import sys, os, pathlib, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nodes.build_dockerfile import build_dockerfile
from state import INTEROP_LAYER_MAP


SAMPLE_PR = {
    "repo": "test/myrepo", "clone_url": "https://github.com/test/myrepo.git",
    "pr_id": 42, "pr_title": "Test PR", "interop_type": "cgo",
    "interop_layer": "ffi", "head_sha": "abc123",
    "base_sha": "def456", "diff_files": [], "diff_total_lines": 100,
    "test_commands": None, "merged_at": "2024-01-01T00:00:00",
}

SAMPLE_ENV = {
    "source": "github_actions",
    "base_image": "golang:1.22",
    "system_deps": ["libssl-dev"],
    "build_cmds": ["go build ./..."],
    "test_cmds":  ["go test -v -json ./..."],
    "test_framework": "go_test",
    "dockerfile_content": None,
}


def test_dockerfile_generated():
    state = {
        "pr": SAMPLE_PR, "env_spec": SAMPLE_ENV,
        "run_config": {}, "build_retries": 0,
    }
    result = build_dockerfile(state)
    assert "dockerfile_path" in result
    assert "image_tag" in result

    dockerfile_path = result["dockerfile_path"]
    assert os.path.exists(dockerfile_path)

    with open(dockerfile_path) as f:
        content = f.read()
    assert "golang:1.22" in content
    assert "abc123" in content         # head_sha 在 git checkout 命令中
    assert "go build" in content
    assert "libssl-dev" in content
    print(f"✓ Dockerfile 生成成功: {dockerfile_path}")
    print(f"  image_tag: {result['image_tag']}")


def test_image_tag_format():
    state = {"pr": SAMPLE_PR, "env_spec": SAMPLE_ENV, "run_config": {}, "build_retries": 0}
    result = build_dockerfile(state)
    tag = result["image_tag"]
    assert tag.startswith("benchmark-")
    assert "test-myrepo-pr42" in tag
    assert all(c.isalnum() or c == "-" for c in tag)
    print(f"✓ image_tag 格式正确: {tag}")


def test_first_layer_passthrough():
    """第一层来源直接使用已有 Dockerfile 内容，不渲染模板"""
    env_with_content = {
        **SAMPLE_ENV,
        "source": "repo_dockerfile",
        "dockerfile_content": "FROM golang:1.22\nCMD [\"go\", \"test\", \"./...\"]"
    }
    state = {"pr": SAMPLE_PR, "env_spec": env_with_content, "run_config": {}, "build_retries": 0}
    result = build_dockerfile(state)
    with open(result["dockerfile_path"]) as f:
        content = f.read()
    assert "FROM golang:1.22" in content
    assert "go test" in content
    print("✓ 第一层来源直接使用 dockerfile_content")


if __name__ == "__main__":
    test_dockerfile_generated()
    test_image_tag_format()
    test_first_layer_passthrough()
    print("\n✅ build_dockerfile.py 验证通过")
```

---

### 2.3 `nodes/docker_build.py`

#### 要做什么

执行 `docker build` 命令，带重试逻辑。注意这里只构建镜像，不编译源码。

```python
# nodes/docker_build.py
import asyncio, os, logging, pathlib
from state import PRSubState

logger = logging.getLogger(__name__)


async def docker_build(state: PRSubState) -> dict:
    """
    异步节点函数：执行 docker build，构建镜像（不编译源码）。
    
    最多重试 3 次，失败则路由到 END。
    受全局 DOCKER_SEMAPHORE 控制并发数。
    """
    from graph import get_docker_semaphore
    semaphore = get_docker_semaphore(
        state["run_config"].get("max_concurrent_docker", 4)
    )

    pr             = state["pr"]
    dockerfile_path = state["dockerfile_path"]
    image_tag       = state["image_tag"]
    retries         = state.get("build_retries", 0)

    async with semaphore:
        build_context = str(pathlib.Path(dockerfile_path).parent)
        cmd = [
            "docker", "build",
            "-t", image_tag,
            "-f", dockerfile_path,
            "--no-cache",
            build_context,
        ]
        logger.info(f"  [docker_build] 构建镜像: {image_tag}（attempt {retries + 1}）")

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                ),
                timeout=600,  # 10 分钟超时
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
            log_text = stdout.decode("utf-8", errors="ignore") if stdout else ""
            # 取最后 50 行日志
            build_log = "\n".join(log_text.splitlines()[-50:])

            if proc.returncode == 0:
                logger.info(f"  [docker_build] ✓ 构建成功: {image_tag}")
                return {"build_status": "success", "build_log": build_log,
                        "build_retries": retries + 1}
            else:
                logger.warning(f"  [docker_build] ✗ 构建失败（exit {proc.returncode}）")
                error = {
                    "pr_id": pr["pr_id"], "repo": pr["repo"],
                    "stage": "docker_build",
                    "reason": "docker_build_failed",
                    "message": f"attempt {retries + 1}，exit_code={proc.returncode}",
                }
                return {"build_status": "failed", "build_log": build_log,
                        "build_retries": retries + 1, "errors": [error]}

        except asyncio.TimeoutError:
            logger.error(f"  [docker_build] 超时（>10 分钟）")
            return {"build_status": "failed", "build_retries": retries + 1,
                    "build_log": "TIMEOUT",
                    "errors": [{"pr_id": pr["pr_id"], "repo": pr["repo"],
                                 "stage": "docker_build", "reason": "docker_build_failed",
                                 "message": "构建超时"}]}
```

#### ✅ 验证步骤 2.3 成功

```python
# tests/test_docker_build.py
"""测试 docker_build 节点。需要有运行中的 Docker daemon。"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_docker_daemon_available():
    """确认 Docker 可用"""
    result = os.system("docker info > /dev/null 2>&1")
    assert result == 0, "Docker daemon 未运行"
    print("✓ Docker daemon 可用")


def test_build_simple_image():
    """构建一个简单的测试 Dockerfile，验证 docker_build 节点基本功能"""
    import tempfile, pathlib

    # 创建最简单的 Dockerfile
    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    dockerfile = tmp_dir / "Dockerfile"
    dockerfile.write_text("FROM alpine:latest\nCMD [\"echo\", \"hello\"]")

    # 构造测试 state
    state = {
        "pr": {"pr_id": 999, "repo": "test/test"},
        "dockerfile_path": str(dockerfile),
        "image_tag": "benchmark-test-pr999",
        "build_retries": 0,
        "run_config": {"max_concurrent_docker": 2},
    }

    from nodes.docker_build import docker_build
    result = asyncio.run(docker_build(state))

    assert result["build_status"] == "success", f"构建失败: {result.get('build_log','')}"
    print(f"✓ docker_build 成功构建测试镜像")

    # 清理
    os.system("docker rmi benchmark-test-pr999 -f > /dev/null 2>&1")


def test_build_failure_recorded():
    """构建失败时 errors 被正确记录"""
    import tempfile, pathlib

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    dockerfile = tmp_dir / "Dockerfile"
    dockerfile.write_text("FROM nonexistent_image_xyz_12345:latest")

    state = {
        "pr": {"pr_id": 998, "repo": "test/fail"},
        "dockerfile_path": str(dockerfile),
        "image_tag": "benchmark-test-fail-pr998",
        "build_retries": 0,
        "run_config": {"max_concurrent_docker": 2},
    }

    from nodes.docker_build import docker_build
    result = asyncio.run(docker_build(state))

    assert result["build_status"] == "failed"
    assert len(result.get("errors", [])) > 0
    assert result["errors"][0]["reason"] == "docker_build_failed"
    print("✓ 构建失败时 errors 正确记录")


if __name__ == "__main__":
    test_docker_daemon_available()
    test_build_simple_image()
    test_build_failure_recorded()
    print("\n✅ docker_build.py 验证通过")
```

---

### 2.4 `nodes/compile_verify.py`

#### 要做什么

在已构建的镜像中运行容器，验证源码可以编译，且 HEAD 状态的测试全部通过（baseline）。若编译失败，启动 LLM 修复循环（最多 2 轮）。

```python
# nodes/compile_verify.py
import asyncio, os, tempfile, pathlib, logging
from state import PRSubState, TestResult

logger = logging.getLogger(__name__)


async def compile_verify(state: PRSubState) -> dict:
    """
    异步节点函数：容器内编译验证 + baseline 测试 + LLM 修复循环。
    
    成功条件：源码编译通过 + HEAD 状态所有测试通过
    失败处理：LLM 修复 Dockerfile，最多 2 轮
    """
    from graph import get_docker_semaphore
    semaphore = get_docker_semaphore(
        state["run_config"].get("max_concurrent_docker", 4)
    )

    pr          = state["pr"]
    env         = state["env_spec"]
    image_tag   = state["image_tag"]
    repair_rounds = state.get("compile_repair_rounds", 0)

    async with semaphore:
        container_id = None
        try:
            # 步骤 1：启动容器
            container_id = await _start_container(image_tag)

            # 步骤 2：执行编译命令
            for build_cmd in env["build_cmds"]:
                stdout, exit_code = await _exec_in_container(container_id, build_cmd, timeout=120)
                if exit_code != 0:
                    logger.warning(f"  [compile_verify] 编译失败: {build_cmd}")
                    # 进入 LLM 修复逻辑
                    return await _handle_compile_failure(
                        state, stdout, repair_rounds
                    )

            # 步骤 3：执行 baseline 测试
            test_cmd  = " && ".join(env["test_cmds"])
            stdout, exit_code = await _exec_in_container(container_id, test_cmd, timeout=300)

            from parsers import get_parser
            parser  = get_parser(env["test_framework"])
            baseline = parser.parse(stdout, exit_code)
            baseline["compile_success"] = True

            if baseline["failed"] > 0:
                logger.warning(f"  [compile_verify] Baseline 测试有 {baseline['failed']} 个失败")
                error = {
                    "pr_id": pr["pr_id"], "repo": pr["repo"],
                    "stage": "compile_verify",
                    "reason": "baseline_tests_failing",
                    "message": f"HEAD 状态测试失败: {baseline['failed']} failed / {baseline['total']} total"
                }
                return {
                    "compile_status": "failed",
                    "baseline_test_result": baseline,
                    "errors": [error],
                }

            logger.info(f"  [compile_verify] ✓ 编译成功，baseline {baseline['passed']}/{baseline['total']} 通过")
            return {
                "compile_status":       "success",
                "baseline_test_result": baseline,
                "compile_repair_log":   state.get("compile_repair_log", ""),
            }

        finally:
            if container_id:
                await _stop_container(container_id)


async def _handle_compile_failure(state: PRSubState, error_output: str, repair_rounds: int) -> dict:
    """LLM 修复循环处理逻辑"""
    pr = state["pr"]

    if repair_rounds >= 2:
        logger.error(f"  [compile_verify] LLM 修复 {repair_rounds} 轮后仍失败，放弃")
        error = {
            "pr_id": pr["pr_id"], "repo": pr["repo"],
            "stage": "compile_verify",
            "reason": "compile_unrecoverable",
            "message": f"经过 {repair_rounds} 轮 LLM 修复后仍无法编译"
        }
        return {
            "compile_status": "failed",
            "compile_repair_rounds": repair_rounds,
            "errors": [error],
        }

    # 调用 LLM 修复 Dockerfile
    new_dockerfile = await _llm_repair_dockerfile(
        state["dockerfile_content"],
        error_output,
        pr["interop_type"],
        state["run_config"].get("llm_model", "claude-sonnet-4-20250514"),
        repair_rounds + 1,
    )

    if not new_dockerfile:
        return {
            "compile_status": "failed",
            "compile_repair_rounds": repair_rounds + 1,
            "errors": [{"pr_id": pr["pr_id"], "repo": pr["repo"],
                        "stage": "compile_verify", "reason": "compile_unrecoverable",
                        "message": "LLM 修复失败（LLM 返回空内容）"}],
        }

    # 重新 build 镜像（用修复后的 Dockerfile）
    dockerfile_path = state["dockerfile_path"]
    with open(dockerfile_path, "w") as f:
        f.write(new_dockerfile)

    repair_log = (state.get("compile_repair_log") or "") + f"\n[轮次 {repair_rounds + 1}] 修复并重新 build"
    logger.info(f"  [compile_verify] LLM 修复完成，触发重新 build（轮次 {repair_rounds + 1}）")

    return {
        "compile_status":        "repaired",
        "compile_repair_rounds": repair_rounds + 1,
        "compile_repair_log":    repair_log,
        "dockerfile_content":    new_dockerfile,
        "build_status":          None,   # 触发重新 build
    }


async def _llm_repair_dockerfile(
    current_dockerfile: str,
    error_output: str,
    interop_type: str,
    model: str,
    round_num: int,
) -> str | None:
    """调用 LLM 修复 Dockerfile"""
    prompt = f"""以下 Dockerfile 构建后，在容器内编译 {interop_type} 项目时报错。
请修改 Dockerfile（只能修改系统依赖安装或构建参数，不能修改源码相关内容）。
只返回修复后的完整 Dockerfile，不要解释，不要用代码块包裹。

错误信息（最后 50 行）：
{chr(10).join(error_output.splitlines()[-50:])}

当前 Dockerfile：
{current_dockerfile}
"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("TARGET_LLM_API_KEY", ""))
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"LLM 修复调用失败: {e}")
        return None


async def _start_container(image_tag: str) -> str:
    """启动容器，返回 container_id"""
    proc = await asyncio.create_subprocess_exec(
        "docker", "run", "-d", "--rm", image_tag, "sleep", "infinity",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


async def _stop_container(container_id: str):
    """停止并清理容器"""
    proc = await asyncio.create_subprocess_exec(
        "docker", "stop", container_id,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


async def _exec_in_container(container_id: str, cmd: str, timeout: int = 60) -> tuple[str, int]:
    """在容器内执行命令，返回 (stdout+stderr, exit_code)"""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "docker", "exec", container_id, "sh", "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            ),
            timeout=timeout,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="ignore"), proc.returncode
    except asyncio.TimeoutError:
        return "TIMEOUT", -1
```

---

### 2.5 子图连线 + `single-pr` 模式验证

**更新 `graph.py`，加入 Stage 2 节点和路由函数：**

```python
# 在 graph.py 中追加以下内容（已有的部分不删除）

from nodes.infer_env         import infer_env
from nodes.build_dockerfile  import build_dockerfile
from nodes.docker_build      import docker_build
from nodes.compile_verify    import compile_verify


def route_after_build(state: PRSubState) -> str:
    """docker_build 的条件边路由"""
    if state.get("build_status") == "success":
        return "compile_verify"
    if state.get("build_retries", 0) < 3:
        return "docker_build"   # 重试
    return "__end__"            # 放弃


def route_after_compile(state: PRSubState) -> str:
    """compile_verify 的条件边路由"""
    if state.get("compile_status") in ("success", "repaired"):
        return "construct_task"
    if state.get("compile_repair_rounds", 0) < 2:
        # 修复后需要重新 build，先回到 build_dockerfile 更新文件
        if state.get("compile_status") == "repaired":
            return "docker_build"   # 用修复后的 Dockerfile 重新 build
        return "compile_verify"     # 直接重试编译验证
    return "__end__"                # 放弃


def build_pr_subgraph() -> object:
    """构建 PR 处理子图（Stage 2+3）"""
    from langgraph.graph import StateGraph, START, END

    sg = StateGraph(PRSubState)
    sg.add_node("infer_env",        infer_env)
    sg.add_node("build_dockerfile", build_dockerfile)
    sg.add_node("docker_build",     docker_build)
    sg.add_node("compile_verify",   compile_verify)
    # construct_task / llm_generate / run_tests / score 在 Phase 3 添加

    sg.add_edge(START, "infer_env")
    sg.add_edge("infer_env", "build_dockerfile")
    sg.add_edge("build_dockerfile", "docker_build")
    sg.add_conditional_edges("docker_build",    route_after_build)
    sg.add_conditional_edges("compile_verify",  route_after_compile)
    # TODO: 连接 construct_task → ... → END

    return sg.compile()
```

**更新 `main.py`，加入 `single-pr` 模式：**

```python
# 在 main.py 中添加 run_single_pr 函数

def run_single_pr(args):
    """读取单条 PR JSON，直接运行 PR 子图（用于节点调试）"""
    import asyncio, json
    from graph import build_pr_subgraph

    with open(args.pr_json, "r") as f:
        pr = json.load(f)

    subgraph = build_pr_subgraph()
    initial_sub_state = {
        "pr": pr,
        "run_config": {**BASE_RUN_CONFIG, "db_path": args.db},
        "env_spec": None, "dockerfile_path": None, "dockerfile_content": None,
        "image_tag": None, "build_status": None, "build_retries": 0,
        "build_log": None, "compile_status": None, "compile_repair_rounds": 0,
        "compile_repair_log": None, "baseline_test_result": None,
        "task": None, "generated_code": None, "llm_tokens_used": 0,
        "test_result": None,
    }

    result = asyncio.run(subgraph.ainvoke(initial_sub_state))
    print(f"\n=== single-pr 运行结果 ===")
    print(f"  build_status:    {result.get('build_status')}")
    print(f"  compile_status:  {result.get('compile_status')}")
    print(f"  baseline_tests:  {result.get('baseline_test_result')}")
    print(f"  errors:          {result.get('errors', [])}")
```

#### ✅ 验证步骤 2.5 成功

首先创建一个测试用的 PR fixture（用真实数据）：

```bash
# 生成一个样本 PR fixture（使用 Stage 1 产出的 snapshot）
python -c "
import json
with open('tests/fixtures/sample_prs.json') as f:
    prs = json.load(f)
if prs:
    # 取第一个 PR
    with open('tests/fixtures/sample_pr.json', 'w') as f:
        json.dump(prs[0], f, indent=2, default=str)
    print(f'✓ 创建 fixture: {prs[0][\"repo\"]}#{prs[0][\"pr_id\"]}')
else:
    print('⚠ 没有 PR 可用，请先运行 fetch 模式')
"
```

然后运行 `single-pr` 模式验证：

```bash
python main.py --mode single-pr --pr-json tests/fixtures/sample_pr.json
```

**预期输出：**
```
=== single-pr 运行结果 ===
  build_status:    success
  compile_status:  success
  baseline_tests:  {'passed': N, 'failed': 0, ...}
  errors:          []
```

---

## Phase 3：Stage 3 题目构造与评估

> **目标：** 实现 Parsers、题目构造、LLM 生成、测试运行、评分的完整 Stage 3 流水线。  
> **完成标志：** `single-pr` 模式能完整跑通，产出 `BenchmarkItem`，包含有效分数。

---

### 3.1 `parsers/` — 测试输出解析器

#### 要做什么

实现 6 个 parser（`BaseParser` + 5 个语言专用 + 1 个通用兜底），统一的 `parse(stdout, exit_code) -> TestResult` 接口。

**这是优先级最高的单元测试对象，因为每个 parser 的逻辑完全独立，可以用样本输出来验证。**

**步骤 1：** 创建 `parsers/base.py`

```python
# parsers/base.py
from state import TestResult


class BaseParser:
    """所有 parser 的抽象基类"""

    def parse(self, stdout: str, exit_code: int) -> TestResult:
        raise NotImplementedError

    @staticmethod
    def _tail(text: str, n: int = 100) -> str:
        return "\n".join(text.splitlines()[-n:])
```

**步骤 2：** 创建 `parsers/go_parser.py`

```python
# parsers/go_parser.py
import json, re
from .base import BaseParser
from state import TestResult


class GoParser(BaseParser):
    """解析 go test -json 的流式输出"""

    def parse(self, stdout: str, exit_code: int) -> TestResult:
        passed = failed = errors_count = total = 0
        compile_success = True

        if "build failed" in stdout.lower() or "[build failed]" in stdout:
            compile_success = False
            return TestResult(
                passed=0, failed=0, errors=0, total=0,
                compile_success=False, exit_code=exit_code,
                stdout_tail=self._tail(stdout)
            )

        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            action = event.get("Action", "")
            test   = event.get("Test", "")
            if not test:   # 跳过包级别事件
                continue
            if action == "run":
                total += 1
            elif action == "pass":
                passed += 1
            elif action == "fail":
                failed += 1

        return TestResult(
            passed=passed, failed=failed, errors=errors_count, total=total,
            compile_success=compile_success, exit_code=exit_code,
            stdout_tail=self._tail(stdout)
        )
```

**步骤 3：** 创建其余 parser（`pytest_parser.py`、`junit_xml_parser.py`、`cargo_parser.py`、`jest_parser.py`、`generic_parser.py`）——参照 DESIGN.md §七的实现要点，结构与 `GoParser` 相同。

**步骤 4：** 创建 `parsers/__init__.py`

```python
# parsers/__init__.py
from .go_parser       import GoParser
from .pytest_parser   import PytestParser
from .junit_xml_parser import JUnitXmlParser
from .cargo_parser    import CargoParser
from .jest_parser     import JestParser
from .generic_parser  import GenericParser
from state import TestResult

PARSER_MAP = {
    "go_test": GoParser(),
    "pytest":  PytestParser(),
    "junit":   JUnitXmlParser(),
    "cargo":   CargoParser(),
    "jest":    JestParser(),
}

def get_parser(framework: str) -> "BaseParser":
    return PARSER_MAP.get(framework, GenericParser())
```

#### ✅ 验证步骤 3.1 成功

**优先编写 parser 测试，这是整个 Phase 3 最容易验证的部分：**

```python
# tests/test_parsers.py
"""Parser 单元测试——每个 parser 三种情形：全通过、部分失败、编译失败"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parsers import get_parser


# ── GoParser ──────────────────────────────────────────────────

GO_TEST_ALL_PASS = """
{"Action":"run","Test":"TestAdd"}
{"Action":"run","Test":"TestMul"}
{"Action":"pass","Test":"TestAdd","Elapsed":0.01}
{"Action":"pass","Test":"TestMul","Elapsed":0.02}
{"Action":"pass","Elapsed":0.03}
"""

GO_TEST_PARTIAL_FAIL = """
{"Action":"run","Test":"TestAdd"}
{"Action":"run","Test":"TestMul"}
{"Action":"pass","Test":"TestAdd"}
{"Action":"fail","Test":"TestMul","Output":"got 4 want 6"}
"""

GO_TEST_COMPILE_FAIL = """
# main.go:5:2: undefined: C.bad_func
[build failed]
FAIL    github.com/test/repo [build failed]
"""


def test_go_parser_all_pass():
    p = get_parser("go_test")
    r = p.parse(GO_TEST_ALL_PASS, 0)
    assert r["passed"] == 2
    assert r["failed"] == 0
    assert r["compile_success"] == True
    print(f"✓ GoParser 全通过: {r['passed']}/{r['total']}")


def test_go_parser_partial_fail():
    p = get_parser("go_test")
    r = p.parse(GO_TEST_PARTIAL_FAIL, 1)
    assert r["passed"] == 1
    assert r["failed"] == 1
    assert r["compile_success"] == True
    print(f"✓ GoParser 部分失败: {r['passed']} passed, {r['failed']} failed")


def test_go_parser_compile_fail():
    p = get_parser("go_test")
    r = p.parse(GO_TEST_COMPILE_FAIL, 1)
    assert r["compile_success"] == False
    assert r["passed"] == 0
    print("✓ GoParser 编译失败正确识别")


# ── PytestParser ─────────────────────────────────────────────

PYTEST_ALL_PASS   = "....\n4 passed in 0.42s"
PYTEST_PART_FAIL  = "...F\n3 passed, 1 failed in 0.55s\nFAILED test_bridge.py::test_null"
PYTEST_IMPORT_ERR = "E   ImportError: cannot import name 'bridge' from 'mymodule'\n0 passed in 0.01s"


def test_pytest_parser():
    p = get_parser("pytest")
    r1 = p.parse(PYTEST_ALL_PASS, 0)
    assert r1["passed"] == 4 and r1["failed"] == 0 and r1["compile_success"]

    r2 = p.parse(PYTEST_PART_FAIL, 1)
    assert r2["passed"] == 3 and r2["failed"] == 1

    r3 = p.parse(PYTEST_IMPORT_ERR, 1)
    assert r3["compile_success"] == False
    print("✓ PytestParser 三种情形全部正确")


# ── CargoParser ──────────────────────────────────────────────

CARGO_PASS = "running 3 tests\ntest ffi::test_add ... ok\ntest result: ok. 3 passed; 0 failed"
CARGO_FAIL = "running 2 tests\ntest ffi::test_null ... FAILED\ntest result: FAILED. 1 passed; 1 failed"
CARGO_ERR  = "error[E0425]: cannot find function `bad_func` in module `ffi`\nerror: aborting due to previous error"


def test_cargo_parser():
    p = get_parser("cargo")
    r1 = p.parse(CARGO_PASS, 0)
    assert r1["passed"] == 3 and r1["failed"] == 0

    r2 = p.parse(CARGO_FAIL, 101)
    assert r2["passed"] == 1 and r2["failed"] == 1

    r3 = p.parse(CARGO_ERR, 1)
    assert r3["compile_success"] == False
    print("✓ CargoParser 三种情形全部正确")


# ── GenericParser ────────────────────────────────────────────

def test_generic_parser_fallback():
    p = get_parser("generic")
    r = p.parse("5 passed, 2 failed in 1.2s", 1)
    assert r["passed"] == 5
    assert r["failed"] == 2
    print(f"✓ GenericParser 通用模式: {r['passed']} passed, {r['failed']} failed")


def test_generic_parser_unparseable():
    p = get_parser("generic")
    r = p.parse("some random output with no test info", 0)
    assert r["passed"] == -1   # 无法解析时返回 -1
    assert r["exit_code"] == 0
    print("✓ GenericParser 无法解析时返回 -1")


if __name__ == "__main__":
    test_go_parser_all_pass()
    test_go_parser_partial_fail()
    test_go_parser_compile_fail()
    test_pytest_parser()
    test_cargo_parser()
    test_generic_parser_fallback()
    test_generic_parser_unparseable()
    print("\n✅ parsers/ 全部验证通过")
```

```bash
python tests/test_parsers.py
```

---

### 3.2 ~ 3.6 剩余 Stage 3 节点

按照 DESIGN.md §6.8（`construct_task`）、§6.9（`llm_generate`）、§6.10（`run_tests`）、§6.11（`score`）、§6.12（`aggregate`）逐一实现，每个节点的验证方式与上述相同：写独立的测试文件，mock 外部依赖（Docker、LLM API），只测节点自身的逻辑。

详细实现参考 `DESIGN.md` 中对应章节的函数规范（输入/输出字段已完整定义）。

---

## Phase 4：主图组装与完整流程

### 4.1 `graph.py` — 完整主图

将 Stage 3 节点全部加入子图，完成主图的 fan-out 连线：

```python
# graph.py 新增（在已有代码基础上追加）

from nodes.construct_task import construct_task
from nodes.llm_generate   import llm_generate
from nodes.run_tests      import run_tests
from nodes.score          import score
from nodes.aggregate      import aggregate_results


def build_pr_subgraph() -> object:
    """完整的 PR 处理子图（Stage 2+3）"""
    from langgraph.graph import StateGraph, START, END
    sg = StateGraph(PRSubState)

    # 注册所有节点
    for name, fn in [
        ("infer_env",        infer_env),
        ("build_dockerfile", build_dockerfile),
        ("docker_build",     docker_build),
        ("compile_verify",   compile_verify),
        ("construct_task",   construct_task),
        ("llm_generate",     llm_generate),
        ("run_tests",        run_tests),
        ("score",            score),
    ]:
        sg.add_node(name, fn)

    # 连接各节点
    sg.add_edge(START, "infer_env")
    sg.add_edge("infer_env", "build_dockerfile")
    sg.add_edge("build_dockerfile", "docker_build")
    sg.add_conditional_edges("docker_build",   route_after_build)
    sg.add_conditional_edges("compile_verify", route_after_compile)
    sg.add_edge("construct_task", "llm_generate")
    sg.add_edge("llm_generate",   "run_tests")
    sg.add_edge("run_tests",      "score")
    sg.add_edge("score",          END)

    return sg.compile()


def build_graph(db_path: str = "benchmark_runs.db") -> object:
    """完整主图（覆盖 Phase 1 的版本）"""
    from langgraph.graph import StateGraph, START, END
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

    # 边连接
    g.add_edge(START, "fetch_repos")
    g.add_edge("fetch_repos", "fetch_prs")
    g.add_edge("fetch_prs", "human_review")
    g.add_conditional_edges(
        "human_review",
        lambda state: [
            Send("process_pr", {
                "pr": pr,
                "run_config": state["run_config"],
                "env_spec": None, "dockerfile_path": None, "dockerfile_content": None,
                "image_tag": None, "build_status": None, "build_retries": 0,
                "build_log": None, "compile_status": None, "compile_repair_rounds": 0,
                "compile_repair_log": None, "baseline_test_result": None,
                "task": None, "generated_code": None, "llm_tokens_used": 0,
                "test_result": None,
            })
            for pr in state["prs"]
        ]
    )
    g.add_edge("process_pr", "aggregate")
    g.add_edge("aggregate", END)

    checkpointer = SqliteSaver.from_conn_string(db_path)
    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
```

---

## Phase 5：测试与验证

> **目标：** 验证系统整体可靠性，包含单元测试、集成测试和全流程验证。

### 5.1 运行所有单元测试

```bash
# 运行所有已完成的测试
pytest tests/ -v --tb=short -m "not docker and not integration"

# 期望输出：所有测试 PASSED
```

### 5.2 集成测试

```bash
# 测试 single-pr 完整流程（需要 Docker）
pytest tests/test_e2e_single.py -v -m docker
```

### 5.3 全流程验证

```bash
# 小规模全流程（只搜 cgo，最多 5 个 PR，跳过人工审核）
python main.py \
  --mode full \
  --interop-types cgo \
  --min-stars 5000 \
  --skip-review \
  --thread-id full-test-001

# 验证产出文件
python -c "
import json
with open('output/benchmark_dataset.json') as f:
    items = json.load(f)
print(f'Benchmark 数据集: {len(items)} 条用例')
if items:
    item = items[0]
    print(f'首条: {item[\"id\"]}')
    print(f'  难度: {item[\"task\"][\"difficulty\"]}')
    print(f'  得分: {item[\"score_total\"]:.1f}')
    print(f'  测试: {item[\"test_result\"][\"passed\"]}/{item[\"test_result\"][\"total\"]} 通过')
"
```

---

## 附录：常见问题与排查

### A. `RateLimitExceededException`

```
症状：github_client 报 Rate Limit 错误
原因：两个 token 都达到 5000 次/小时上限
解法：等待 1 小时（自动重置），或增加更多 token
快速验证：python -c "from github import Github; g = Github('YOUR_TOKEN'); print(g.get_rate_limit().core)"
```

### B. Docker build 网络超时

```
症状：docker build 在 RUN apt-get install 阶段超时
原因：拉取 apt 包时网络不稳定
解法：
  1. 重试（最多 3 次，系统会自动重试）
  2. 如果持续失败，检查 Docker 的 DNS 配置
  3. 在 Dockerfile 中使用国内镜像源（修改模板）
```

### C. `interrupt()` 导致程序卡住

```
症状：运行 fetch 模式时程序卡在 human_review 节点
原因：skip_review=False 且未提供 approved_pr_ids
解法：
  1. 使用 --skip-review 参数跳过审核
  2. 或者在另一个终端执行：
     python -c "
     from graph import build_graph
     import json
     app = build_graph()
     config = {'configurable': {'thread_id': 'YOUR_THREAD_ID'}}
     state = app.get_state(config)
     pr_ids = [p['pr_id'] for p in state.values['prs']]
     app.update_state(config, {'approved_pr_ids': pr_ids})
     "
     然后重新运行: python main.py --mode resume --thread-id YOUR_THREAD_ID
```

### D. `compile_verify` 循环失败

```
症状：某个 PR 的 compile_verify 始终失败
原因：项目依赖特殊版本的系统库，LLM 无法正确推断
解法：
  1. 查看 errors 中的 "compile_unrecoverable" 记录
  2. 手动分析该 PR 的依赖（查看仓库的 CI 配置）
  3. 如果是普遍问题，更新 infer_env 的规则层
```

### E. 测试文件找不到

```
症状：tests/fixtures/sample_prs.json 不存在
解法：先运行 Stage 1：
  python main.py --mode fetch --interop-types cgo --min-stars 5000 \
    --output tests/fixtures/sample_prs.json
```

---

*开发手册结束*  
*如有问题，请参考 DESIGN.md（完整规范）或提 Issue*