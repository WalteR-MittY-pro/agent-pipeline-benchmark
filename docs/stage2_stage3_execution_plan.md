# Stage 2/3 下一步执行方案

> 生成时间：2026-04-03 21:44 CST
> 目的：在不写代码的前提下，为“容器构建 + PR 有效性验证”提供一份可评审、可执行的下一阶段方案。

## 1. 当前现状

### 1.1 已完成部分

- Stage 1 已完成，可从 `prs_snapshot.json` 读取候选 PR。
- 当前快照共有 418 条 PR，说明 repo 召回和 PR 精筛已经形成可用输入。
- 当前样本主要集中在这些互操作类型：
  - `cgo`: 100
  - `python_cext`: 75
  - `ruby_cext`: 57
  - `wasm`: 44
  - `lua_c`: 39
  - `cffi`: 34
  - `rust_ffi`: 31
  - `v8_cpp`: 30
  - `ctypes`: 8
- `state.py` 已经预留了 Stage 2/3 所需的数据结构：
  - `EnvSpec`
  - `PRSubState`
  - `BenchmarkTask`
  - `TestResult`
  - `BenchmarkItem`

### 1.2 当前缺口

- 仓库里目前只有 Stage 1 节点：
  - `nodes/fetch_repos.py`
  - `nodes/fetch_prs.py`
  - `nodes/human_review.py`
- `graph.py` 和 `main.py` 当前也只接到了 Stage 1。
- Stage 2/3 设计里提到的以下节点尚未落地：
  - `infer_env`
  - `build_dockerfile`
  - `docker_build`
  - `compile_verify`
  - `construct_task`
  - `llm_generate`
  - `run_tests`
  - `score`
  - `aggregate`

### 1.3 一个非常关键的现实约束

- 当前 418 条 PR 的 `test_commands` 全部为空。
- 这意味着下一步不能直接依赖 Stage 1 的现成测试命令字段，而必须把“环境推断 + 测试命令推断”当成 Stage 2 的核心问题来做。
- 当前本地环境没有 `python` 命令，后续执行层面默认应以 `python3` 为准，避免实现或验证脚本时出现不必要的环境误差。

## 2. 下一步的真正目标

下一步不应该一上来就“跑完全部 418 条”，而应该先把下面这件事做扎实：

**建立一个可靠的 Stage 2 基线验证流水线，判断每条候选 PR 是否具备成为 benchmark 样本的最低条件。**

这里的“最低条件”建议定义为：

1. 能定位并拉取 PR 对应仓库与 commit。
2. 能推断出足够可信的容器环境。
3. 能构建出容器镜像。
4. 能在容器内完成 baseline 编译。
5. 能在容器内运行 baseline 测试。
6. baseline 测试结果稳定且可解析。

只要第 1-6 步不成立，该 PR 就还不能进入后续“mask 胶水代码并验证 benchmark 有效性”的 Stage 3。

## 3. 修正后的总体策略

核心建议仍然不变：**先做 Stage 2 baseline，再做 Stage 3；先小样本，再扩到全量。**

但在当前仓库状态下，Stage 2 最小闭环存在几个隐藏前置条件，必须提前纳入第一阶段：

1. `compile_verify` 依赖 parser 最小集。设计文档已明确 baseline test 要调用 `get_parser(env_spec["test_framework"]).parse(...)` 产出 `TestResult`，因此 parser 不是“第二优先级”，而是 `compile_verify` 的前置依赖。
2. `single-pr` 不是闭环后的附属验证动作，而是最小闭环的执行壳。当前仓库缺少 PR 子图接线、`main.py --mode single-pr` dispatch 和 fixture，必须与 Stage 2 核心节点一并推进。
3. 批量跑 418 条外部 PR 之前，必须先做运行环境和安全 guardrails 决策，否则后续的并发、缓存、磁盘和隔离策略都无法稳定收敛。

因此，修正后的路线应拆成 **5 个里程碑**，并在最前面增加一个“里程碑 0”。

## 4. 里程碑 0：前置决策与运行 Guardrails

### 目标

先确认会影响 Stage 2 设计边界和批量运行稳定性的前置事项，避免实现一半后再返工。

### 必须前置确认的事项

- `T-01` Docker 执行环境：
  - 本地 daemon、专用构建机还是 CI runner
  - 是否允许 privileged 能力
  - 镜像缓存放在哪里
  - 磁盘配额和清理策略如何制定
- `T-03` `MAX_CONCURRENT_DOCKER`：
  - 必须依赖 `T-01` 的机器规格来定
  - 建议先以 1 到 2 的保守值起步，再通过 20 条样本压测校准
- `T-02` 被测 LLM 列表：
  - 如果本阶段只做 baseline compile/test，不启用 repair loop 和 Stage 3，则它不是 Stage 2 最小闭环的硬阻塞
  - 如果要求 `compile_verify` 首轮就包含 LLM repair，则 `T-02` 和 `T-08` 会进入关键路径

### 批量执行前必须写入方案的 Guardrails

- 隔离策略：
  - 外部 PR 代码视为不可信代码
  - 明确容器权限、挂载策略、CPU/内存限制、运行超时
- 网络策略：
  - 是否允许构建阶段联网
  - 是否允许测试阶段联网
  - 如果限制联网，如何处理需要在线拉依赖的构建
- 清理策略：
  - 容器执行后立即删除
  - 镜像按批次或按 tag 周期性 prune
  - 临时工作目录和日志目录的保留时间
- 依赖边界：
  - 如何处理 git submodule
  - 如何处理 Git LFS
  - 如何处理私有依赖和认证失败
  - 如何处理测试过程中的额外下载
- 基线稳定性：
  - baseline 失败时如何区分真实失败与 flaky
  - 是否允许重跑 1 次确认

### 这一里程碑的产物

- 一份 Stage 2 preflight checklist
- 一份运行 guardrails 说明
- 一份“本阶段是否启用 compile repair loop”的范围决议

## 5. 里程碑 1：补齐 Stage 2 最小基础设施

### 目标

先补足 `compile_verify` 和 `single-pr` 真正依赖的基础设施，让后续节点有可运行的最小壳。

### 第一批必须完成的内容

- parser 最小集：
  - `parsers/base.py`
  - `parsers/generic_parser.py`
  - `parsers/go_parser.py`
  - `parsers/pytest_parser.py`
- parser 测试和 fixtures：
  - `tests/test_parsers.py`
  - `tests/fixtures/sample_go_test_output.txt`
  - `tests/fixtures/sample_pytest_output.txt`
- single-pr fixtures：
  - 至少 1 个 `sample_pr_cgo.json`
  - 至少 1 个 `sample_pr_python_cext.json` 或等价样本
- PR 子图和 CLI 最小接线：
  - `build_pr_subgraph`
  - `route_after_build`
  - `route_after_compile`
  - `main.py --mode single-pr`

### 为什么这一层必须提前

- 没有 parser，`compile_verify` 不能完整产出 `baseline_test_result`。
- 没有 PR 子图和 `single-pr` dispatch，就没有最小成本的端到端调试入口。
- 没有 fixture，就无法稳定做回归测试，也无法让其他 agent 低成本复核。

### 这一里程碑的验收标准

- `tests/test_parsers.py` 能覆盖 go 和 pytest 的通过、失败、编译失败场景。
- `single-pr` 可以读取 fixture，并通过 PR 子图运行到至少 `docker_build` / `compile_verify` 之前的节点。
- 项目里出现最小可用的 `tests/fixtures/` 样本集，而不是完全空目录。

## 6. 里程碑 2：实现 Stage 2 核心节点

### 目标

在最小基础设施齐备后，再实现真正决定 baseline 是否可跑通的 Stage 2 节点。

### 推荐实现顺序

1. `infer_env`
2. `build_dockerfile`
3. Docker templates
4. `docker_build`
5. `compile_verify`

### 各模块建议职责

#### `infer_env`

按设计文档中的 4 层回退执行：

1. 仓库已有 Dockerfile
2. GitHub Actions / CI workflow
3. LLM 推断
4. 推断失败则标记跳过

额外要求：

- 必须输出推断证据链：
  - 命中的 Dockerfile 路径
  - 命中的 workflow 文件路径
  - 推断出的 runtime 版本
  - build/test 命令来源
- 对“无法判定测试命令”的情况给出明确 reason code，而不是只记为通用失败。

#### `build_dockerfile` 和 Docker templates

- 先覆盖最可能先试跑的主流类型：
  - `cgo`
  - `python_cext`
  - `ruby_cext`
  - `wasm`
- 模板优先保证可调试、可复现，不追求镜像最小化。
- 模板内保留关键调试上下文：
  - 工作目录
  - checkout 的 commit
  - 安装的系统依赖
  - build/test 执行入口

#### `docker_build`

- 每个 PR 独立镜像 tag。
- 必须把失败区分为：
  - 基础镜像拉取失败
  - 依赖安装失败
  - Dockerfile 渲染或逻辑错误
  - 超时
- 重试策略建议仅用于基础设施类失败，不对逻辑性错误盲目重试。

#### `compile_verify`

这是 Stage 2 的核心节点，但它默认依赖里程碑 1 的 parser 最小集。

节点内部至少分为两个子阶段：

1. baseline compile
2. baseline test + parser 解析

输出中至少应包含：

- 编译是否成功
- 测试是否成功
- 测试是否可解析
- `TestResult`
- stdout/stderr tail
- 耗时
- coarse status
- reason code

### 这一里程碑的验收标准

- 至少能在 `single-pr` 模式下稳定跑通 3 条不同类型 PR。
- `compile_verify` 可以对 go / pytest 场景返回结构化 `TestResult`，而不是只有原始日志。

## 7. Stage 2 结果模型与失败 Taxonomy

### 原则

Stage 2 结果不能只保留“成功/失败”，必须同时保留：

- 粗粒度阶段状态
- 细粒度 reason code

### 建议的粗粒度阶段状态

- `env_inferred`
- `dockerfile_rendered`
- `image_built`
- `compile_passed`
- `baseline_test_passed`
- `skipped`
- `failed`

### 建议的细粒度 reason code

设计文档已经明确的 code，建议直接沿用：

- `infer_env_failed`
- `docker_build_failed`
- `compile_unrecoverable`
- `baseline_tests_failing`
- `mask_ineffective`
- `ground_truth_invalid`

Stage 2 还建议补充以下 reason code，避免 triage 时把不同问题混在一起：

- `test_framework_unsupported`
- `test_output_unparseable`
- `baseline_timeout`
- `network_blocked`
- `submodule_missing`
- `git_lfs_missing`
- `private_dependency_unavailable`
- `flaky_baseline`

### 输出建议

- `stage2_results.jsonl` 里每条记录至少包含：
  - PR 标识
  - `interop_type`
  - coarse status
  - reason code
  - 推断证据链
  - build/test 命令
  - 关键日志 tail
  - 耗时

## 8. 里程碑 3：single-pr 小样本验证

### 目标

利用 `single-pr` 作为最小调试入口，先用少量真实样本打磨 Stage 2。

### 小样本选择建议

- 总量 12 到 20 条。
- 按互操作类型分层抽样，优先覆盖：
  - `cgo`
  - `python_cext`
  - `ruby_cext`
  - `wasm`
  - `lua_c`
  - `rust_ffi`
- 每类先取 2 到 4 条。
- 优先选择：
  - CI 痕迹明显的仓库
  - diff 聚焦的 PR
  - 改动文件数较少的 PR

### 这一里程碑的目标不是

- 不是追求一开始就拿到很高通过率
- 不是一上来覆盖所有长尾 interop 类型
- 不是马上进入 Stage 3

### 这一里程碑的真正价值

- 尽快暴露环境推断失败模式
- 尽快暴露容器和依赖问题
- 尽快校准 reason code 是否足够细

## 9. 里程碑 4：批量运行与结构化产物

### 目标

在 `single-pr` 和 12 到 20 条样本稳定后，再扩到批量运行。

### 批量扩容节奏

- 第 1 批：20 条
- 第 2 批：50 条
- 第 3 批：100 条
- 最后：全量 418 条

### 每一批都必须输出的产物

- `stage2_results.jsonl`
- `stage2_summary.md`
- `stage2_failures_top.md`

### 每一批都必须重点观察的指标

- `env_inference_success_rate`
- `docker_build_success_rate`
- `compile_success_rate`
- `baseline_test_pass_rate`
- `parse_success_rate`
- 平均单 PR 耗时
- 按 `interop_type` 的通过率
- 镜像缓存命中情况
- 磁盘占用增长

## 10. 里程碑 5：Stage 3 benchmark 有效性验证

### 目标

只有通过 Stage 2 baseline 验证的 PR，才进入真正的 benchmark 构造流程。

### Stage 3 的入口条件

一条 PR 至少满足以下条件，才进入 `construct_task`：

1. baseline 编译通过
2. baseline 测试通过
3. 测试输出可解析
4. 确认存在候选胶水代码文件
5. 可以把目标文件映射到容器内绝对路径

### Stage 3 的有效性定义

必须坚持设计文档中的三步验证，不能省略：

1. baseline 通过
2. mask 之后失败
3. ground truth 恢复后重新通过

任何一步不成立，该 PR 都不能进入最终 benchmark 数据集。

## 11. 修正后的具体开发顺序

如果目标是“尽快得到一个真实可闭环、可调试、可扩容的 Stage 2”，更合理的顺序应是：

1. 先确认 `T-01`、`T-03`，并给出运行 guardrails。
2. 补齐 parser 最小集、parser fixtures 和 `tests/test_parsers.py`。
3. 补齐 sample PR fixtures。
4. 补齐 PR 子图接线和 `main.py --mode single-pr`。
5. 实现 `infer_env`。
6. 实现 `build_dockerfile` 和主流 Docker templates。
7. 实现 `docker_build`。
8. 实现 `compile_verify`。
9. 用 `single-pr` 打通 3 条不同 interop_type 样本。
10. 扩到 12 到 20 条小样本。
11. 再扩到 20 / 50 / 100 / 418 条批跑。
12. 只把通过 Stage 2 baseline 的 PR 送入 Stage 3。

## 12. 对评审者最值得重点看的问题

建议其他 agent 重点评审以下 7 点：

1. 是否同意把 parser 最小集和 `single-pr` 接线提升到第一阶段。
2. 是否同意把 `T-01` / `T-03` 作为批量化前的硬前置事项。
3. `T-02` 是否阻塞本阶段，还是通过“先不启用 repair loop”移出关键路径。
4. Stage 2 的 coarse status + reason code 设计是否足够支撑 triage。
5. guardrails 是否已经覆盖外部 PR 执行的主要运维/安全风险。
6. 小样本抽样策略是否合理。
7. 全量前分批扩容的节奏是否合理。

## 13. 修正后的推荐结论

基于当前仓库状态，**下一步最合理的目标依然不是“立刻全量跑 418 条 PR”，而是“先补齐最小基础设施，再实现并验证 Stage 2 最小闭环”**。

更具体地说：

- parser 最小集、fixtures、PR 子图和 `single-pr` 接线要进入第一阶段，而不是后置。
- `infer_env` 仍然是最核心的系统性风险点。
- 失败 taxonomy 必须采用“coarse status + reason code”双层结构。
- `T-01`、`T-03` 和运行 guardrails 必须在批量化前明确。
- 只有通过 Stage 2 baseline 的 PR，才送入 Stage 3 做真正的 benchmark 有效性验证。

这版路线图比上一版更接近“可以直接照着执行”，也更符合当前代码库与设计文档之间的真实依赖关系。
