# Codex Plan Review

> 时间：2026-04-03
> 目标：记录我对 Stage 2/3 执行方案的当前审查结论，并作为与 `docs/opencode-plan.md` 对照收敛的基准版本。

## 当前结论

我认可此前主审意见的总体判断：原始方案的战略方向是对的，但还不能直接作为实现顺序执行。最大问题不是目标错了，而是把几个真实的前置依赖放到了后面，导致“Stage 2 最小闭环”在原表述下并不能真正闭环。

## 我同意的关键结论

### 1. Parser 不应后置

- 我同意把 parser 最小集提升到第一阶段。
- 原因是 `compile_verify` 的 baseline test 依赖 `get_parser(env_spec["test_framework"]).parse(...)` 产出 `TestResult`。
- 因此 parser 不是“第二优先级”，而是 `compile_verify` 的前置依赖。

### 2. `single-pr` 不是后置验证动作

- 我同意把 `single-pr` 所依赖的最小执行壳提前。
- 这包括：
  - PR 子图接线
  - `main.py --mode single-pr`
  - 至少一个 sample PR fixture
- 没有这些内容，就没有最低成本的端到端调试入口。

### 3. 失败 taxonomy 必须更细

- 我同意 Stage 2 结果不能只保留“成功/失败”。
- 更合理的方式是同时保留：
  - coarse status
  - reason code
- 设计文档已有的 `infer_env_failed`、`docker_build_failed`、`compile_unrecoverable`、`baseline_tests_failing` 等 code 应直接沿用。

### 4. Dockerfile 模板是 `build_dockerfile` 的硬依赖

- 我同意这一点也应提升到第一阶段依赖图里。
- `build_dockerfile` 不是只写一个节点函数就能工作，它还依赖 `dockerfiles/templates/{interop_type}.dockerfile.j2`。
- 因此主流类型的模板至少要跟 Stage 2 核心节点同步准备：
  - `cgo.dockerfile.j2`
  - `python_cext.dockerfile.j2`
  - `ruby_cext.dockerfile.j2`
  - `wasm.dockerfile.j2`

### 5. 批量化前必须先补运行 guardrails

- 我同意外部 PR 批量执行前，必须显式处理：
  - 容器隔离
  - 网络策略
  - 镜像与容器清理
  - submodule / Git LFS / 私有依赖
  - flaky baseline
- 这些不是“运维细节”，而是 Stage 2 批量化前的 guardrails。

### 6. 先 Stage 2 baseline，再 Stage 3

- 我仍然完全同意：
  - 先做 Stage 2 baseline 验证
  - 再做 Stage 3 benchmark 有效性验证
- 也同意：
  - 先小样本
  - 再扩到 20 / 50 / 100 / 418

## 我保留的一个细化判断

### `T-02` 是否阻塞本阶段，要看 Stage 2 范围定义

- `T-01` Docker 执行环境
- `T-03` `MAX_CONCURRENT_DOCKER`

这两个我认为是批量化前的硬前置事项。

但 `T-02` 被测 LLM 列表，我认为需要分情况看：

- 如果本阶段只做 baseline compile/test，不启用 repair loop，那么 `T-02` 不是 Stage 2 最小闭环的硬阻塞。
- 如果要求 `compile_verify` 首轮就包含 LLM repair，那么 `T-02` 会进入关键路径。

所以我建议在计划中显式写清：

- 本轮 Stage 2 最小闭环是否包含 compile repair loop

只有这个范围先定下来，`T-02` 的优先级判断才不会摇摆。

## 我建议的实现顺序

1. 先确认 `T-01`、`T-03`，并写清运行 guardrails。
2. 补齐 parser 最小集、parser fixtures、`tests/test_parsers.py`。
3. 补齐 sample PR fixtures，至少覆盖 `cgo` / `python_cext` / `wasm` 三类。
4. 补齐 PR 子图接线和 `main.py --mode single-pr`。
5. 实现 `infer_env`。
6. 实现 `build_dockerfile` 和主流 Docker templates。
7. 实现 `docker_build`。
8. 实现 `compile_verify`。
9. 用 `single-pr` 打通 3 条不同 interop_type 样本。
10. 扩到 12 到 20 条小样本。
11. 再扩到 20 / 50 / 100 / 418 条批跑。
12. 只把通过 Stage 2 baseline 的 PR 送入 Stage 3。

## 当前 verdict

Verdict：方案方向正确，但原版本不能直接作为实现顺序。  
修正后的可执行版本应当把 parser、fixtures、PR 子图 / `single-pr` 接线、失败 taxonomy 和运行 guardrails 提前到第一阶段。

## 与 OpenCode 的对照结果

我已对照 `docs/opencode-plan.md`。当前双方在以下关键点上已形成实质共识：

1. parser 最小集必须前置。
2. `single-pr` 最小接线必须前置。
3. `build_dockerfile` 依赖主流 Docker templates，模板不能后补。
4. Stage 2 结果必须采用 coarse status + reason code。
5. `T-01` / `T-03` 和运行 guardrails 必须在批量化前明确。
6. Stage 2 baseline 通过后，才进入 Stage 3。
7. 执行顺序必须真实体现这些前置依赖，而不是只在文字上认可。

我认为这已经构成“实质共识”，剩余差异只在表述颗粒度上，不影响执行顺序判断。

## 收敛标准

如果 `docs/opencode-plan.md` 与我能达成以下几点一致，我认为双方已经形成实质共识：

1. parser 最小集必须前置。
2. `single-pr` 最小接线必须前置。
3. `build_dockerfile` 对主流 Docker templates 的依赖必须前置体现。
4. Stage 2 结果必须采用 coarse status + reason code。
5. `T-01` / `T-03` 和运行 guardrails 必须在批量化前明确。
6. Stage 2 baseline 通过后，才进入 Stage 3。
7. 执行顺序必须体现以上前置依赖。
