# OpenCode Plan Review

> 生成时间：2026-04-03
> 目的：记录 OpenCode agent 对 Stage 2/3 执行方案的审查结论，作为与 `docs/codex-plan.md` 对照收敛的基准版本。

---

## Verdict

原始 `docs/stage2_stage3_execution_plan.md` 的**战略方向正确**，但**不能直接作为实现顺序执行**。核心问题不是目标错了，而是把几个真实的前置依赖放到了后面，导致"Stage 2 最小闭环"在原表述下并不能真正闭环。

---

## Critical Issues（原方案必须修正的点）

### C1. Parser 最小集是 compile_verify 的硬前置，不应放在"第二优先级"

- **证据**：`plans/design.md:1104-1108` 明确要求 `compile_verify` 调用 `get_parser(env_spec["test_framework"]).parse(stdout, exit_code)` 产出 `baseline_test_result`。
- **现状**：`parsers/` 目录只有空的 `__init__.py`，零个 parser 实现。
- **结论**：parser 不是"第二优先级"，而是 `compile_verify` 能否闭环的前提。最少需要：
  - `parsers/base.py`
  - `parsers/generic_parser.py`
  - `parsers/go_parser.py`
  - `parsers/pytest_parser.py`
  - `tests/test_parsers.py`
  - `tests/fixtures/sample_go_test_output.txt`
  - `tests/fixtures/sample_pytest_output.txt`

### C2. `single-pr` 不是闭环后的验证动作，而是最小闭环的执行壳

- **证据**：`graph.py`（74 行）只有 Stage 1，缺少 `build_pr_subgraph`、`route_after_build`、`route_after_compile`、`fan_out_prs`（`plans/design.md:591-650`）。`main.py` 对 `build/single-pr/full` 模式未实现。
- **现状**：`tests/fixtures/` 为空，无 sample PR fixture。
- **结论**：`single-pr` 的真正前置条件至少包括：
  1. parser 最小集（C1）
  2. PR 子图接线（`build_pr_subgraph` + 两个 route 函数）
  3. `main.py` 的 `run_single_pr()` dispatch
  4. 至少 1-3 条真实 `PRMetadata` fixture

### C3. Dockerfile 模板是 build_dockerfile 的硬依赖

- **证据**：`plans/design.md:1003-1019` 要求读取 `dockerfiles/templates/{interop_type}.dockerfile.j2`。
- **现状**：`dockerfiles/templates/` 目录为空。
- **结论**：必须至少先创建主流类型的模板：
  - `cgo.dockerfile.j2`
  - `python_cext.dockerfile.j2`
  - `ruby_cext.dockerfile.j2`
  - `wasm.dockerfile.j2`

### C4. 失败 taxonomy 必须细化为 coarse status + reason code

- **原方案**只有 8 个高层状态（`env_inferred` / `dockerfile_rendered` / ... / `unsupported`）。
- **设计文档**（`plans/design.md:1799-1815`）已有 13+ 个 reason code。
- **结论**：Stage 2 结果必须同时保留 coarse status 和 reason code。建议沿用设计文档已有的 code，并补充：
  - `test_framework_unsupported`
  - `test_output_unparseable`
  - `baseline_timeout`
  - `network_blocked`
  - `submodule_missing`
  - `git_lfs_missing`
  - `private_dependency_unavailable`
  - `flaky_baseline`

### C5. 批量化前必须先做运行 Guardrails

- **原方案**没有显式处理以下问题：
  - 容器隔离策略（不可信 PR 代码）
  - 网络策略（构建/测试阶段是否允许联网）
  - 镜像与容器清理（磁盘占用：418 PR × ~500MB = ~200GB）
  - git submodule / Git LFS / 私有依赖
  - flaky baseline 检测
- **结论**：这些不是"扩容后再看"的运维细节，而是批量化前的 guardrails。

### C6. T-01 / T-03 是批量化前的硬前置决策

- **T-01** Docker 执行环境（本地 / CI / 云端）决定：权限模型、缓存策略、磁盘管理。
- **T-03** `MAX_CONCURRENT_DOCKER` 依赖 T-01 的机器规格。
- **结论**：这两个必须在"里程碑 0"中明确决策。

---

## 保留的细化判断

### T-02 被测 LLM 列表——是否阻塞取决于 Stage 2 范围

- 如果本轮 Stage 2 最小闭环**不启用 compile repair loop**，则 T-02 不是硬阻塞。
- 如果 `compile_verify` 首轮就包含 LLM repair，则 T-02 和 T-08 进入关键路径。
- **建议**：计划中显式写清"本轮 Stage 2 是否包含 compile repair loop"。

---

## 我建议的修正版执行顺序

### Phase 0：前置决策与 Guardrails
1. 确认 T-01（Docker 执行环境）、T-03（初始并发值，建议 2）
2. 写清运行 guardrails（隔离 / 网络 / 清理 / submodule / flaky）
3. 明确本轮是否启用 compile repair loop

### Phase 1：补齐最小基础设施
4. parser 最小集（base / generic / go / pytest）+ parser fixtures + `tests/test_parsers.py`
5. sample PR fixtures（至少 3 条：cgo / python_cext / wasm）
6. PR 子图接线（`build_pr_subgraph` / `route_after_build` / `route_after_compile`）
7. `main.py --mode single-pr` dispatch

### Phase 2：Stage 2 核心节点
8. `infer_env`
9. `build_dockerfile` + 主流 Docker templates（cgo / python_cext / ruby_cext / wasm）
10. `docker_build`
11. `compile_verify`

### Phase 3：验证与扩容
12. `single-pr` 打通 3 条不同 interop_type 样本
13. 扩到 12-20 条小样本
14. 扩到 20 / 50 / 100 / 418 条批跑

### Phase 4：Stage 3
15. 只把通过 Stage 2 baseline 的 PR 送入 Stage 3（construct_task → llm_generate → run_tests → score → aggregate）

---

## 共识标准

如果 `docs/codex-plan.md` 与我能达成以下几点一致，我认为双方已经形成实质共识：

1. **parser 最小集必须前置**（compile_verify 的硬依赖）
2. **`single-pr` 最小接线必须前置**（PR 子图 + main.py dispatch + fixtures）
3. **Stage 2 结果必须采用 coarse status + reason code**（不能只有成功/失败）
4. **T-01 / T-03 和运行 guardrails 必须在批量化前明确**
5. **Stage 2 baseline 通过后，才进入 Stage 3**
6. **执行顺序必须体现以上前置依赖**（不能 parser 和 single-pr 接线还在第二/第三优先级）

---

## 原方案中我认可的部分（不需要改）

- 先做 Stage 2 baseline，再做 Stage 3
- 先小样本，再逐批扩容（12-20 → 20 → 50 → 100 → 418）
- 把 `infer_env` 视为 Stage 2 最大风险
- Stage 3 入口必须建立在 baseline pass 上
- 三步有效性验证（baseline → mask-breaks → gt-restores）不可省略
