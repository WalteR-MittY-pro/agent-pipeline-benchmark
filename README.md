# Agent Pipeline Benchmark

> PR 自动化筛选与基准测试流水线

自动从 GitHub 拉取 PR，在隔离容器中运行测试，筛选出符合基准的 PR 集合。

## 功能

- 🔍 **自动拉取** — 根据规则从 GitHub 仓库拉取 PR
- 🐳 **容器隔离** — 每个 PR 在独立 Docker 容器中测试
- ✅ **智能筛选** — 根据测试结果筛选 PR
- 📊 **Benchmark 生成** — 输出结构化报告

## 快速开始

```bash
# 安装依赖
npm install

# 配置 GitHub Token
export GITHUB_TOKEN="ghp_xxxx"

# 编辑配置
vim config.yaml
vim rules.yaml

# 运行流水线
npm run start

# 查看结果
cat output/benchmark-*.json
```

## 架构

```
Orchestrator (主控)
    │
    ├── PR-Fetcher      → 拉取符合条件的 PR
    ├── Container-Worker → 创建隔离测试环境
    ├── Test-Runner     → 执行测试并收集结果
    └── Result-Aggregator → 生成 Benchmark 报告
```

## 配置

### config.yaml

```yaml
repositories:
  - owner: "example"
    repo: "project-a"
    test_command: "npm test"
    timeout: 300

defaults:
  dockerfile: "./docker/default/Dockerfile"
  test_command: "make test"

resources:
  cpu_limit: "2"
  memory_limit: "4g"

concurrency:
  max_workers: 4
```

### rules.yaml

```yaml
pr_filters:
  state: "open"
  base: "main"
  labels:
    - "ready-for-testing"

pass_criteria:
  test_result: "pass"
  max_duration: 300
```

## 目录结构

```
├── src/
│   ├── orchestrator/   # 主控
│   ├── fetcher/        # PR 拉取
│   ├── worker/         # 容器管理
│   ├── runner/         # 测试执行
│   └── aggregator/     # 结果聚合
├── docker/             # Dockerfile 模板
├── data/               # 任务队列、结果存储
└── output/             # Benchmark 报告
```

## 状态

- [ ] Phase 1: 项目骨架 + 配置解析
- [ ] Phase 2: PR-Fetcher 实现
- [ ] Phase 3: Container-Worker 实现
- [ ] Phase 4: Test-Runner 实现
- [ ] Phase 5: Result-Aggregator 实现
- [ ] Phase 6: Orchestrator 集成
- [ ] Phase 7: 测试 + 文档

## License

MIT
