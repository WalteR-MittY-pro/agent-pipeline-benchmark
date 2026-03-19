# Agent Pipeline Benchmark

> GitHub multi-language repository miner — scans repositories for cross-language characteristics and candidate PRs

---

## 项目概述

本项目实现一个 **多 Agent 协作的 PR 筛选流水线**，核心能力：

- 🔍 **自动拉取** — 根据 configurable 规则从 GitHub 仓库拉取 PR
- 🐳 **容器隔离** — 每个 PR 在独立 Docker 容器中测试，确保环境一致性
- ✅ **智能筛选** — 根据测试结果、代码质量、性能指标筛选 PR
- 📊 **Benchmark 生成** — 输出结构化的基准测试报告

---

## 技术栈

| 组件 | 技术 | 说明 |
|-----|------|------|
| 语言 | Python 3.13 | 主开发语言 |
| GitHub API | PyGithub | `github` 包 |
| 容器 | Docker | 隔离测试环境 |
| 依赖管理 | pip / uv | 推荐使用 uv |

---

## 快速开始

```bash
# 1. 安装依赖
pip install PyGithub

# 2. 配置 GitHub Token (编辑 config/.config.json)
# 格式: {"github": {"PAT1": "ghp_xxx", "PAT2": "ghp_yyy"}}

# 3. 运行主程序
python src/cli_miner0311.py

# 4. 查看结果
cat data/fetcher/multilang_repos_pool.json
cat data/fetcher/multilang_repos_pool.csv
```

---

## 开发命令

### 运行测试
```bash
# 运行所有测试
pytest

# 运行单个测试文件
pytest test/test_miner.py

# 带详细输出
pytest -v

# 只运行失败的测试
pytest --lf

# 并行运行 (需安装 pytest-xdist)
pytest -n auto
```

### 代码质量
```bash
# 格式化代码 (需安装 ruff)
ruff format src/

# 检查代码风格
ruff check src/

# 自动修复可自动修复的问题
ruff check --fix src/

# 类型检查 (需安装 mypy)
mypy src/
```

### 一次性检查 (CI 模式)
```bash
ruff check src/ && ruff format --check src/ && mypy src/
```

---

## 代码风格

### Python PEP 8 + 项目规范

**格式化**:
- 使用 `ruff format` (或 black 作为替代)
- 行长度: 100 字符
- 使用双引号 `"`
- 尾随逗号 (trailing commas)

**Import 排序** (ruff 按 PEP 8 自动处理):
```python
# 标准库
import json
import csv
import time
from typing import Optional

# 第三方库
from github import Github
from github.GithubException import RateLimitExceededException
```

**命名规范**:
| 类型 | 规范 | 示例 |
|-----|------|------|
| 模块/文件名 | lowercase_with_underscores | `cli_miner0311.py` |
| 类名 | CapWords | `RepoAnalyzer` |
| 函数名 | snake_case | `analyze_repo_languages` |
| 常量 | UPPER_SNAKE_CASE | `CONFIG`, `MAX_REPOS` |
| 变量 | snake_case | `valid_repos_pool` |

**类型注解**:
```python
# 推荐使用类型注解
def analyze_repo_languages(repo) -> Optional[dict]:
    ...

# 使用 Optional 而非 Optional[X] | None
def get_config() -> Optional[dict]:
    ...

# 复杂类型使用 type alias
LanguagesDict = dict[str, float]
```

### 错误处理

```python
# 正确: 特定异常优先处理
try:
    result = analyze_repo_languages(repo)
except RateLimitExceededException:
    print("\n[!] 触发 API 速率限制，准备休眠...")
    raise
except Exception as e:
    print(f"  [!] 分析仓库 {repo.full_name} 语言时出错: {e}")
    return None

# 错误: 空 catch块
try:
    ...
except:
    pass  # 永远不要这样做
```

### 文档字符串

```python
def analyze_repo_languages(repo):
    """
    获取并分析仓库的语言分布。

    只统计主流语言（Python, Rust, C/C++, JS/TS, Go, Java, PHP）的占比。

    Args:
        repo: PyGithub Repository 对象

    Returns:
        如果满足跨语言条件，返回包含占比详情的 dict；否则返回 None。

    Raises:
        RateLimitExceededException: API 速率限制时
    """
```

---

## 项目结构

```
agent-pipeline-benchmark/
├── AGENTS.md                    # 本文件 - Agent 开发指南
├── README.md                    # 用户文档
├── prompt.txt                   # Scout Agent 提示词
│
├── config/
│   └── .config.json             # GitHub Token 配置 (不提交)
│
├── src/
│   └── cli_miner0311.py         # 主入口脚本
│
├── dockerfile/
│   └── nanobind/
│       └── Dockerfile           # 测试环境镜像
│
├── data/
│   └── fetcher/
│       ├── multilang_repos_pool.json   # 扫描结果 JSON
│       └── multilang_repos_pool.csv    # 扫描结果 CSV
│
├── test/                        # 测试目录 (待建立)
│   ├── unit/
│   └── integration/
│
└── .gitignore
```

---

## 配置说明

### config/.config.json
```json
{
    "github": {
        "PAT1": "ghp_xxx",
        "PAT2": "ghp_yyy"
    }
}
```

**注意**: 此文件包含敏感信息，已在 `.gitignore` 中忽略，切勿提交。

---

## GitHub API 使用注意

1. **速率限制**: Search API 每次最多返回 1000 结果，需分段搜索
2. **Token 轮换**: 建议配置多个 PAT 轮流使用
3. **休眠策略**: 适当 `time.sleep(0.5)` 防止触发 Abuse Detection
4. **超时设置**: `per_page=100, timeout=30`

---

## 扩展任务

1. **新增语言类别**: 修改 `CONFIG["mainstream_languages"]`
2. **调整阈值**: 修改 `language_ratio_threshold` 和 `min_languages_count`
3. **PR 筛选规则**: 参考 `prompt.txt` 实现 Scout Agent 逻辑
4. **测试用例**: 在 `test/` 目录添加单元测试

---

## 状态

- [x] Phase 0: 项目初始化
- [x] Phase 1: 多语言仓库扫描脚本
- [ ] Phase 2: PR 筛选 Scout Agent 实现
- [ ] Phase 3: Docker 隔离测试环境
- [ ] Phase 4: 完整测试 + 文档
