# Agent Pipeline Benchmark

> PR 自动化筛选与基准测试流水线 — 自动从 GitHub 拉取 PR，在隔离容器中运行测试，筛选出符合基准的 PR 集合

---

## 项目概述

本项目实现一个 **多 Agent 协作的 PR 筛选流水线**，核心能力：

- 🔍 **自动拉取** — 根据 configurable 规则从 GitHub 仓库拉取 PR
- 🐳 **容器隔离** — 每个 PR 在独立 Docker 容器中测试，确保环境一致性
- ✅ **智能筛选** — 根据测试结果、代码质量、性能指标筛选 PR
- 📊 **Benchmark 生成** — 输出结构化的基准测试报告

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ORCHESTRATOR (主控)                             │
│  职责: 读取配置、调度任务、汇总结果、生成报告                                │
│  文件: src/orchestrator/                                                 │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                    │
         ▼                    ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  PR-FETCHER     │  │  CONTAINER-     │  │  TEST-RUNNER    │  │  RESULT-        │
│  ─────────────  │  │  WORKER         │  │  ─────────────  │  │  AGGREGATOR     │
│                 │  │  ─────────────  │  │                 │  │  ─────────────  │
│  - gh CLI 封装  │  │  - Docker API   │  │  - 执行测试命令  │  │  - 解析结果     │
│  - 过滤条件     │  │  - 容器生命周期 │  │  - 超时控制     │  │  - 筛选逻辑     │
│  - PR 元数据    │  │  - 资源配额     │  │  - 日志收集     │  │  - 生成 benchmark│
│                 │  │                 │  │                 │  │                 │
│  src/fetcher/   │  │  src/worker/    │  │  src/runner/    │  │  src/aggregator/│
└─────────────────┘  └─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │                    │
         └────────────────────┴────────────────────┴────────────────────┘
                                      │
                                      ▼
                         ┌─────────────────────┐
                         │     DATA LAYER      │
                         │  ─────────────────  │
                         │  - 任务队列         │
                         │  - 结果存储         │
                         │  - 配置管理         │
                         │                     │
                         │  data/              │
                         └─────────────────────┘
```

---

## Agent 定义

### 1. Orchestrator (主控 Agent)

**职责**: 整体流程编排、任务调度、结果汇总

**输入**:
- 配置文件 (config.yaml)
- 筛选规则 (rules.yaml)

**输出**:
- 任务执行计划
- 最终 Benchmark 报告

**关键行为**:
- 读取并验证配置
- 调用 PR-Fetcher 获取候选 PR 列表
- 为每个 PR 创建 Worker 任务
- 收集所有 Worker 结果
- 调用 Aggregator 生成最终报告

**实现路径**: `src/orchestrator/`

---

### 2. PR-Fetcher (PR 拉取 Agent)

**职责**: 从 GitHub 拉取符合条件 PR

**输入**:
- 目标仓库 (owner/repo)
- 筛选条件 (labels, authors, date range, base branch)

**输出**:
- PR 列表 (含元数据: number, title, author, commits, files changed)

**关键行为**:
- 使用 `gh pr list --json` 获取 PR 列表
- 应用筛选条件过滤
- 存储到任务队列

**实现路径**: `src/fetcher/`

---

### 3. Container-Worker (容器工作 Agent)

**职责**: 为每个 PR 创建隔离测试环境

**输入**:
- PR 信息 (repo, branch, commit sha)
- 环境配置 (Dockerfile, resource limits)

**输出**:
- 运行中的容器实例
- 容器 ID 和访问信息

**关键行为**:
- 根据仓库类型选择/构建 Docker 镜像
- 创建容器 (设置 CPU/内存限制、网络隔离)
- 在容器内克隆仓库
- Checkout 到 PR 分支/commit

**实现路径**: `src/worker/`

---

### 4. Test-Runner (测试执行 Agent)

**职责**: 在容器内执行测试并收集结果

**输入**:
- 容器 ID
- 测试命令 (来自配置)
- 超时设置

**输出**:
- 测试结果 (pass/fail)
- 日志输出 (stdout/stderr)
- 性能指标 (可选)

**关键行为**:
- `docker exec` 执行测试命令
- 超时强制终止
- 捕获并解析输出
- 上传日志到结果存储

**实现路径**: `src/runner/`

---

### 5. Result-Aggregator (结果聚合 Agent)

**职责**: 分析所有测试结果，生成 Benchmark 报告

**输入**:
- 所有 PR 的测试结果
- 筛选规则 (通过条件)

**输出**:
- Benchmark 报告 (JSON/YAML/Markdown)
- 通过/失败 PR 列表

**关键行为**:
- 应用筛选规则 (如: 必须通过所有测试)
- 计算统计信息 (通过率、平均耗时)
- 生成多格式报告

**实现路径**: `src/aggregator/`

---

## 工作流程

```
┌──────────────────────────────────────────────────────────────────┐
│                        MAIN PIPELINE                              │
└──────────────────────────────────────────────────────────────────┘

Step 1: 初始化
    Orchestrator 读取 config.yaml + rules.yaml
    │
    ▼
Step 2: 获取 PR 列表
    PR-Fetcher.pull(repo, filters) → PR[]
    │
    ▼
Step 3: 创建任务队列
    for each PR:
        Queue.enqueue({pr, config})
    │
    ▼
Step 4: 并行执行 (N workers)
    ┌─────────────────────────────────────────────────┐
    │  Worker Thread:                                 │
    │    4.1 Container-Worker.create(pr)              │
    │    4.2 Test-Runner.execute(container, cmd)      │
    │    4.3 Container-Worker.destroy(container)      │
    │    4.4 上报结果到 Aggregator                     │
    └─────────────────────────────────────────────────┘
    │
    ▼
Step 5: 生成报告
    Result-Aggregator.generate(all_results) → Report
    │
    ▼
Step 6: 输出
    保存到 output/benchmark-{timestamp}.json
```

---

## 配置规范

### config.yaml (主配置)

```yaml
# 目标仓库
repositories:
  - owner: "example"
    repo: "project-a"
    # 可选: 仓库专属配置覆盖
    dockerfile: "./docker/project-a/Dockerfile"
    test_command: "npm test"
    timeout: 300  # 秒

  - owner: "example"
    repo: "project-b"
    dockerfile: "./docker/project-b/Dockerfile"
    test_command: "cargo test"
    timeout: 600

# 全局默认配置
defaults:
  dockerfile: "./docker/default/Dockerfile"
  test_command: "make test"
  timeout: 300
  
# 容器资源配置
resources:
  cpu_limit: "2"
  memory_limit: "4g"
  network: "none"  # 网络隔离

# 并发控制
concurrency:
  max_workers: 4
  rate_limit: 10  # 每分钟最多处理 10 个 PR

# 输出配置
output:
  format: "json"  # json | yaml | markdown
  path: "./output"
```

### rules.yaml (筛选规则)

```yaml
# PR 筛选条件
pr_filters:
  # 基础过滤
  state: "open"
  base: "main"
  
  # 可选: 标签过滤
  labels:
    - "ready-for-testing"
    - "benchmark-candidate"
  
  # 可选: 作者白名单
  authors: null  # null = 不限制
  
  # 时间范围
  created_after: "2024-01-01"
  
  # 文件变更过滤
  files_changed:
    include:
      - "src/**/*.ts"
      - "lib/**/*.rs"
    exclude:
      - "**/*.md"
      - "docs/**"

# 测试通过条件
pass_criteria:
  # 必须通过测试
  test_result: "pass"
  
  # 可选: 超时限制
  max_duration: 300  # 秒
  
  # 可选: 代码覆盖率阈值
  coverage_threshold: null  # null = 不检查

# Benchmark 输出规则
benchmark:
  # 只包含通过的 PR
  include_failures: false
  
  # 附加信息
  include_metadata:
    - "author"
    - "commits_count"
    - "files_changed"
    - "test_duration"
```

---

## 目录结构

```
agent-pipeline-benchmark/
├── AGENTS.md                    # 本文件 - Agent 定义与架构
├── README.md                    # 用户指南
├── config.yaml                  # 主配置文件
├── rules.yaml                   # 筛选规则
│
├── src/
│   ├── orchestrator/            # 主控 Agent
│   │   ├── index.ts
│   │   ├── scheduler.ts
│   │   └── types.ts
│   │
│   ├── fetcher/                 # PR 拉取 Agent
│   │   ├── index.ts
│   │   ├── github-client.ts
│   │   └── filters.ts
│   │
│   ├── worker/                  # 容器工作 Agent
│   │   ├── index.ts
│   │   ├── docker-client.ts
│   │   └── resource-manager.ts
│   │
│   ├── runner/                  # 测试执行 Agent
│   │   ├── index.ts
│   │   ├── executor.ts
│   │   └── logger.ts
│   │
│   ├── aggregator/              # 结果聚合 Agent
│   │   ├── index.ts
│   │   ├── analyzer.ts
│   │   └── reporter.ts
│   │
│   ├── types/                   # 共享类型定义
│   │   └── index.ts
│   │
│   └── utils/                   # 工具函数
│       ├── config-loader.ts
│       └── logger.ts
│
├── docker/                      # Docker 镜像定义
│   ├── default/
│   │   └── Dockerfile
│   └── templates/               # 各语言模板
│       ├── nodejs/
│       ├── rust/
│       └── python/
│
├── data/                        # 数据存储
│   ├── queue/                   # 任务队列
│   ├── results/                 # 测试结果
│   └── cache/                   # 缓存
│
├── output/                      # 输出报告
│   └── .gitkeep
│
├── scripts/                     # 脚本
│   ├── setup.sh                 # 环境初始化
│   └── run.sh                   # 启动流水线
│
├── tests/                       # 测试
│   ├── unit/
│   └── integration/
│
├── package.json
├── tsconfig.json
└── .gitignore
```

---

## 技术选型

| 组件 | 技术选择 | 理由 |
|-----|---------|-----|
| 语言 | TypeScript | 类型安全、生态丰富、适合 CLI 工具 |
| 运行时 | Node.js 20+ | 原生异步、Docker API 支持好 |
| GitHub API | `gh` CLI + @octokit/rest | 官方工具、API 完整 |
| 容器 | Docker + dockerode | 成熟稳定、Node.js SDK |
| 任务队列 | BullMQ (Redis) | 可靠、支持并发控制 |
| 配置解析 | yaml + zod | 类型安全的配置验证 |
| 日志 | pino | 高性能结构化日志 |
| 测试 | vitest | 快速、现代 |

---

## 快速开始

```bash
# 1. 安装依赖
npm install

# 2. 配置 GitHub Token
export GITHUB_TOKEN="ghp_xxxx"

# 3. 编辑配置
vim config.yaml
vim rules.yaml

# 4. 运行流水线
npm run start

# 5. 查看结果
cat output/benchmark-*.json
```

---

## 安全考虑

1. **网络隔离**: 容器默认 `network: none`，防止恶意代码外连
2. **资源限制**: CPU/内存配额防止资源耗尽攻击
3. **超时终止**: 所有操作有超时，防止无限挂起
4. **只读挂载**: 敏感配置文件只读挂载
5. **Token 保护**: GitHub Token 不进入容器环境

---

## 扩展点

1. **新增仓库类型**: 在 `docker/templates/` 添加新 Dockerfile
2. **自定义筛选器**: 实现 `src/fetcher/filters.ts` 中的接口
3. **额外测试指标**: 扩展 `src/runner/` 收集更多数据
4. **报告格式**: 在 `src/aggregator/reporter.ts` 添加新格式
5. **远程执行**: 可扩展为 GitHub Actions / 自托管 Runner

---

## 状态

- [ ] Phase 1: 项目骨架 + 配置解析
- [ ] Phase 2: PR-Fetcher 实现
- [ ] Phase 3: Container-Worker 实现
- [ ] Phase 4: Test-Runner 实现
- [ ] Phase 5: Result-Aggregator 实现
- [ ] Phase 6: Orchestrator 集成
- [ ] Phase 7: 测试 + 文档

