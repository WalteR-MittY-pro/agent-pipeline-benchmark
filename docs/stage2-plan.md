# Stage 2 Implementation Plan

> 日期：2026-04-04
> 目的：将当前已达成共识的 Stage 2 方案整理为一份可直接执行的实施计划。
> 范围：以 Stage 2 baseline 验证闭环为核心，明确前置依赖、实现顺序、交付物和验收标准。

## 1. 目标与边界

### 1.1 本阶段目标

本阶段的目标不是立刻跑完全部 418 条 PR，而是先建立一个稳定的 Stage 2 baseline 验证闭环，使每条候选 PR 都可以被判定为：

1. 是否能推断出可运行环境
2. 是否能构建出镜像
3. 是否能在容器内完成 baseline 编译
4. 是否能在容器内完成 baseline 测试
5. 是否具备进入 Stage 3 的资格

### 1.2 本阶段不追求的目标

- 不在第一轮就完成全部 Stage 3 节点
- 不在第一轮就覆盖所有长尾 interop 类型
- 不在第一轮就做全量 418 条批跑

### 1.3 当前共识

以下判断已在 `docs/codex-plan.md` 和 `docs/opencode-plan.md` 中达成实质共识：

1. parser 最小集必须前置
2. `single-pr` 最小接线必须前置
3. `build_dockerfile` 依赖主流 Docker templates，模板不能后补
4. Stage 2 结果必须采用 `coarse status + reason code`
5. `T-01` / `T-03` 与运行 guardrails 必须在批量化前明确
6. Stage 2 baseline 通过后，才进入 Stage 3

## 2. 总体执行顺序

按依赖关系，推荐的实现顺序如下：

1. 确认运行前置决策与 guardrails
2. 补齐 parser 最小集与 parser 测试
3. 补齐 sample PR fixtures
4. 补齐 PR 子图与 `single-pr` 最小接线
5. 实现 `infer_env`
6. 实现 `build_dockerfile` 与主流模板
7. 实现 `docker_build`
8. 实现 `compile_verify`
9. 用 `single-pr` 打通真实样本
10. 扩到小样本批量验证
11. 输出结构化 Stage 2 结果
12. 仅将 baseline 通过样本送入 Stage 3

## 3. Phase 0：前置决策与 Guardrails

### 3.1 目标

在开始 Stage 2 编码前，先确认会影响实现方式的前置事项。

### 3.2 需要明确的决策

#### T-01 Docker 执行环境

需要明确：

- 使用本地 Docker daemon、专用机器还是 CI runner
- 容器权限边界
- 镜像缓存位置
- 磁盘上限
- 日志和临时目录保留策略

#### T-03 `MAX_CONCURRENT_DOCKER`

建议：

- 初始值先设为 `2`
- 在 20 条样本批跑后再校准

#### T-02 被测 LLM 列表

本阶段建议明确一条范围决议：

- Stage 2 第一轮默认只做 baseline compile/test
- 默认不启用 compile repair loop

这样 `T-02` 不会阻塞 Stage 2 最小闭环。

### 3.3 必须写入方案的 Guardrails

- 外部 PR 代码按不可信代码处理
- 容器必须有 CPU / 内存 / 超时限制
- 明确构建阶段是否允许联网
- 明确测试阶段是否允许联网
- 明确镜像清理和容器清理策略
- 明确 `git submodule` / Git LFS / 私有依赖失败的处理策略
- baseline 失败时允许重跑 1 次，用于区分 flaky

### 3.4 交付物

- `docs/stage2-preflight-checklist.md`
- `docs/stage2-guardrails.md`

### 3.5 验收标准

- 团队明确知道 Stage 2 第一轮是否启用 repair loop
- Docker 运行环境和初始并发值已确认
- 运行 guardrails 已写成文档，而不是口头约定

## 4. Phase 1：最小基础设施

### 4.1 目标

先补齐 `compile_verify` 和 `single-pr` 所依赖的最小壳。

### 4.2 必须实现的文件

#### Parser 最小集

- `parsers/base.py`
- `parsers/generic_parser.py`
- `parsers/go_parser.py`
- `parsers/pytest_parser.py`

#### Parser 测试与 fixtures

- `tests/test_parsers.py`
- `tests/fixtures/sample_go_test_output.txt`
- `tests/fixtures/sample_pytest_output.txt`

#### Sample PR fixtures

至少准备 3 条 `PRMetadata` fixture：

- `tests/fixtures/sample_pr_cgo.json`
- `tests/fixtures/sample_pr_python_cext.json`
- `tests/fixtures/sample_pr_wasm.json`

#### PR 子图与 CLI 最小接线

- `graph.py`
  - `build_pr_subgraph`
  - `route_after_build`
  - `route_after_compile`
- `main.py`
  - `run_single_pr(args)`
  - `--mode single-pr` dispatch

### 4.3 实现要求

- parser 的 `parse()` 不得抛异常
- parser 必须返回完整 `TestResult`
- `single-pr` 必须能读取单个 fixture 并触发 PR 子图
- `python3` 作为默认命令假设

### 4.4 验收标准

- `tests/test_parsers.py` 覆盖 go/pytest 的通过、失败、编译失败场景
- `single-pr` 命令能够读取 fixture 并开始执行 PR 子图
- `tests/fixtures/` 不再为空目录

## 5. Phase 2：Stage 2 核心节点

### 5.1 实现顺序

1. `infer_env`
2. `build_dockerfile`
3. Docker templates
4. `docker_build`
5. `compile_verify`

### 5.2 `infer_env`

#### 输入

- `PRMetadata`
- 仓库源码
- CI / workflow 文件

#### 回退顺序

1. 仓库已有 Dockerfile
2. GitHub Actions / CI workflow
3. LLM 推断
4. 失败则标记 `infer_env_failed`

#### 输出要求

- `EnvSpec`
- 推断证据链
- build/test 命令来源
- `test_framework`
- 失败时的 reason code

#### 重点实现点

- 识别运行时版本
- 识别系统依赖
- 识别 baseline test 命令
- 对“无法判定测试命令”给出明确失败原因

### 5.3 `build_dockerfile`

#### 必须准备的模板

- `dockerfiles/templates/cgo.dockerfile.j2`
- `dockerfiles/templates/python_cext.dockerfile.j2`
- `dockerfiles/templates/ruby_cext.dockerfile.j2`
- `dockerfiles/templates/wasm.dockerfile.j2`

#### 输出要求

- 渲染后的 Dockerfile 内容
- Dockerfile 路径
- 构建上下文可调试

#### 模板要求

- 优先可复现、可调试
- 保留 checkout commit、系统依赖、build/test 入口
- 不追求第一轮镜像最小化

### 5.4 `docker_build`

#### 输出要求

- 镜像 tag
- build 状态
- build 日志 tail
- reason code

#### 失败分类

- `docker_build_failed`
- 拉取基础镜像失败
- 安装依赖失败
- Dockerfile 逻辑错误
- timeout

#### 实现要求

- 每个 PR 独立 tag
- 仅对基础设施类问题做有限重试
- 不对明显逻辑错误盲目重试

### 5.5 `compile_verify`

#### 子阶段

1. baseline compile
2. baseline test
3. parser 解析

#### 输出要求

- `compile_status`
- `baseline_test_result`
- `stdout_tail`
- 执行耗时
- coarse status
- reason code

#### 关键依赖

- parser 最小集必须已存在
- `single-pr` 必须能作为调试入口

#### 第一轮范围建议

- 默认不启用 compile repair loop
- 先把 baseline compile/test 路径打稳

### 5.6 Phase 2 验收标准

- 至少支持 `cgo`、`python_cext` 两类样本跑通 baseline
- `compile_verify` 可返回结构化 `TestResult`
- 失败能够落到明确 reason code，而不是笼统的失败日志

## 6. Stage 2 结果模型

### 6.1 结果记录格式

Stage 2 每条样本都必须同时记录：

- coarse status
- reason code
- 推断证据链
- build/test 命令
- 关键日志 tail
- 耗时

### 6.2 建议的 coarse status

- `env_inferred`
- `dockerfile_rendered`
- `image_built`
- `compile_passed`
- `baseline_test_passed`
- `skipped`
- `failed`

### 6.3 必须支持的 reason code

至少先支持：

- `infer_env_failed`
- `docker_build_failed`
- `compile_unrecoverable`
- `baseline_tests_failing`
- `test_framework_unsupported`
- `test_output_unparseable`
- `baseline_timeout`
- `network_blocked`
- `submodule_missing`
- `git_lfs_missing`
- `private_dependency_unavailable`
- `flaky_baseline`

## 7. Phase 3：`single-pr` 样本打通

### 7.1 目标

用真实样本而不是空 fixture 验证 Stage 2 端到端是否可运行。

### 7.2 实施步骤

1. 选 3 条真实样本：
   - `cgo`
   - `python_cext`
   - `wasm`
2. 使用 `single-pr` 分别运行
3. 收集：
   - 环境推断是否成功
   - Docker 构建是否成功
   - baseline compile/test 是否成功
   - reason code 是否合理

### 7.3 验收标准

- 至少 3 条不同 interop_type 样本可执行到 `compile_verify`
- 至少 2 条样本可产生结构化 baseline 结果
- 失败样本也能落到明确 reason code

## 8. Phase 4：小样本批跑

### 8.1 目标

在 `single-pr` 打通后，扩到 12 到 20 条样本，验证批量稳定性。

### 8.2 样本选择建议

- 优先覆盖：
  - `cgo`
  - `python_cext`
  - `ruby_cext`
  - `wasm`
  - `lua_c`
  - `rust_ffi`
- 每类 2 到 4 条
- 优先选择 CI 痕迹明显、diff 聚焦的 PR

### 8.3 必须输出的产物

- `output/stage2_results.jsonl`
- `output/stage2_summary.md`
- `output/stage2_failures_top.md`

### 8.4 关注指标

- `env_inference_success_rate`
- `docker_build_success_rate`
- `compile_success_rate`
- `baseline_test_pass_rate`
- `parse_success_rate`
- 按 interop_type 的通过率
- 镜像缓存命中情况
- 磁盘占用增长

### 8.5 验收标准

- 20 条样本可稳定执行
- 失败分布可按 reason code 聚合
- 并发值 `2` 下资源占用可接受

## 9. Phase 5：扩容到 50 / 100 / 418

### 9.1 原则

- 只有在 20 条样本批跑稳定后，才扩到更大批次
- 每次扩容前先看失败分布，而不是直接盲目加量

### 9.2 扩容步骤

1. 20 条
2. 50 条
3. 100 条
4. 418 条

### 9.3 每一批都要复核

- 运行 guardrails 是否仍成立
- reason code 是否足够区分主要失败模式
- 并发值是否需要调整
- 磁盘和镜像清理策略是否有效

## 10. 与 Stage 3 的衔接

只有满足以下条件的样本，才进入 Stage 3：

1. baseline 编译通过
2. baseline 测试通过
3. 测试输出可解析
4. 已能定位候选胶水代码文件
5. `target_file_path` 能映射为容器内绝对路径

Stage 3 仍必须执行三步有效性验证：

1. baseline 通过
2. mask 后失败
3. ground truth 恢复后重新通过

## 11. 模块级 Checklist

### Phase 0 Checklist

- [ ] 明确 Docker 执行环境
- [ ] 明确初始并发值
- [ ] 明确是否启用 repair loop
- [ ] 写出 preflight checklist
- [ ] 写出 guardrails 文档

### Phase 1 Checklist

- [ ] `parsers/base.py`
- [ ] `parsers/generic_parser.py`
- [ ] `parsers/go_parser.py`
- [ ] `parsers/pytest_parser.py`
- [ ] `tests/test_parsers.py`
- [ ] `tests/fixtures/sample_go_test_output.txt`
- [ ] `tests/fixtures/sample_pytest_output.txt`
- [ ] `tests/fixtures/sample_pr_cgo.json`
- [ ] `tests/fixtures/sample_pr_python_cext.json`
- [ ] `tests/fixtures/sample_pr_wasm.json`
- [ ] `graph.py` PR 子图接线
- [ ] `main.py --mode single-pr`

### Phase 2 Checklist

- [ ] `nodes/infer_env.py`
- [ ] `nodes/build_dockerfile.py`
- [ ] `dockerfiles/templates/cgo.dockerfile.j2`
- [ ] `dockerfiles/templates/python_cext.dockerfile.j2`
- [ ] `dockerfiles/templates/ruby_cext.dockerfile.j2`
- [ ] `dockerfiles/templates/wasm.dockerfile.j2`
- [ ] `nodes/docker_build.py`
- [ ] `nodes/compile_verify.py`

### Phase 3/4 Checklist

- [ ] 3 条 `single-pr` 样本打通
- [ ] 12 到 20 条小样本批跑
- [ ] `output/stage2_results.jsonl`
- [ ] `output/stage2_summary.md`
- [ ] `output/stage2_failures_top.md`

## 12. 最终执行原则

本任务的核心不是“尽快把 418 条 PR 都跑掉”，而是：

- 先确保 Stage 2 闭环真实可运行
- 先确保依赖顺序正确
- 先确保失败可分类、可调试、可扩容

如果上述三点没有成立，就不应进入全量批跑，更不应提前推进 Stage 3。
