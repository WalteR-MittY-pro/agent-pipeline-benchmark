# 近三个月 Coding Agent Benchmark 调研

更新时间：2026-03-24  
调研时间窗：**2025-12-24 至 2026-03-24**

## 1. 调研范围与筛选标准

本文聚焦近三个月内**首次公开发布**或**首次公开论文化**的、与 coding agent 或 agentic software engineering 直接相关的 benchmark。纳入标准如下：

- Benchmark 的核心目标是评测 coding agent、software engineering agent，或其关键子能力。
- 发布时间位于 2025-12-24 到 2026-03-24 之间。
- 优先采用**官方一手来源**：论文摘要页、官方 benchmark 网站、官方 GitHub 仓库、官方 Hugging Face 数据集页。
- 优先纳入**可执行验证**、**真实仓库**、**repo-level**、**process-level** 这类更贴近真实工程实践的 benchmark。

未纳入：

- 仅评测静态代码补全、单函数生成、竞赛编程的通用代码 benchmark。
- 仅有二手新闻报道、缺少官方说明页或论文摘要的一次性榜单。
- 发布时间早于 2025-12-24 的旧 benchmark，即使其近期仍在被频繁引用。

## 2. 执行摘要

近三个月内，coding agent benchmark 的演化方向非常清晰：**从单点 bug fixing，转向 repo-level、process-level、maintenance-level 和 capability-factorized evaluation**。可以概括为 5 个趋势：

1. **从“修一个 issue”转向“维护一个仓库”**  
   SWE-CI、RepoMod-Bench、FeatureBench 都不再满足于单轮补丁生成，而是评估 agent 在更长时间跨度、更多上下文依赖和更复杂目标下的表现。

2. **从“最终是否通过”转向“中间过程是否合理”**  
   ContextBench 直接把 context retrieval 单独拆出来，说明研究者开始认为“最后做对”不足以解释 agent 为什么失败或成功。

3. **从单一任务转向任务谱系化评测**  
   OmniCode 把 bug fixing、test generation、review response、style fixing 放进同一框架，强调 agent 需要覆盖完整的软件开发活动，而不是只会补补丁。

4. **从功能正确性转向工程可维护性与泛化能力**  
   SWE-Refactor、SWE-CI、RepoMod-Bench 都强调“即使代码能跑，也未必代表 agent 真正具备长期工程价值”。

5. **当前最强 agent 仍存在明显能力断层**  
   这些 benchmark 的共同结论是：在更真实、更长程、更大规模的任务上，现有 agent 的成功率远低于在 SWE-bench 这类经典任务上的表现。

## 3. 横向总览

| Benchmark | 首次公开时间 | 核心能力 | 规模 | 评测方式 | 最值得关注的结论 |
|---|---:|---|---|---|---|
| FeatureBench | 2026-02-11 | 端到端功能开发 | 200 tasks, 3825 envs, 24 repos | 执行式、feature-oriented | Claude 4.5 Opus 在 SWE-bench 74.4%，到这里仅 11.0% |
| ContextBench | 2026-02-05 | 上下文检索与利用 | 1136 tasks, 66 repos, 8 languages | 过程追踪 + gold context | agent scaffold 对 context retrieval 的提升很有限 |
| OmniCode | 2026-02-02 | 多软件工程活动泛化 | 1794 tasks, 3 languages, 4 task families | 多任务统一评测 | agent 在测试生成、Java/C++ 上明显掉队 |
| SWE-Refactor | 2026-02-03 | 语义保持型重构 | 1099 refactorings, 18 Java projects | 编译 + 测试 + refactoring detector | compound refactoring 仍然非常难 |
| RepoMod-Bench | 2026-02-26 | 仓库现代化迁移 | 21 repos, 8 languages, 1.6M LOC | implementation-agnostic hidden tests | 项目规模一大，成功率断崖式下降 |
| Rust-SWE-bench | 2026-02-26 | Rust 仓库级 issue resolution | 500 tasks, 34 repos | repo-level issue fixing | Rust 语义约束与 issue reproduction 是主要瓶颈 |
| SWE-CI | 2026-03-04 | 长期维护与 CI 循环 | 100 tasks, avg 233 days / 71 commits | 多轮 CI-loop, ANC 指标 | 评测目标从 correctness 转向 maintainability |
| SWE-Skills-Bench | 2026-03-16 | skill 注入的边际价值 | 49 skills, paper 中约 565 task instances | paired evaluation: with-skill vs no-skill | 39/49 skill 没有带来 pass-rate 提升 |

## 4. 逐项整理

### 4.1 FeatureBench

- 发布时间：2026-02-11
- 官方定位：评测 agent 在**复杂功能开发**上的端到端能力，而非单个 PR 内的 bug fix。

#### Benchmark 构成

- 第一版包含 **200 个任务**、**3825 个可执行环境**、覆盖 **24 个开源仓库**。
- 数据构造方法是**测试驱动**的：从单元测试出发，沿依赖图追踪功能相关代码，再把一个 feature 级别的开发任务从仓库历史中抽离出来。
- 任务可以跨越多个 commit 和 PR，而不是局限于一个 issue 或一个补丁。

#### 测什么

- 功能开发能力，而不是局部修补能力。
- 多文件、多模块联动实现。
- 在引入新功能时是否还能保证其他功能正常。

#### 怎么测

- 采用**execution-based evaluation**。
- 任务构造本身包含可执行验证，确保任务可复现、可持续扩展、可更新，以降低 benchmark 泄漏风险。
- 官方网站还提供 full / lite 等拆分，并公开 leaderboard。

#### 论文与官方给出的结论

- 这是我看到的近三个月内最能说明“**SWE-bench 成绩高，不代表真实 feature 开发也强**”的 benchmark。
- 论文给出的代表性结果是：**Claude 4.5 Opus 在 SWE-bench 上可达 74.4% resolved rate，但在 FeatureBench 上只有 11.0%**。
- 这意味着 agent 在真实功能开发上的瓶颈，不再只是“能否写出一个 patch”，而是：
  - 能否理解 feature 边界。
  - 能否跨越较长历史和较大上下文组织实现。
  - 能否在引入改动后维持系统其余部分的正确性。

#### 价值与局限

- 价值：它把 benchmark 重点从“修 bug”推进到“做 feature”，更接近真实研发工作流。
- 局限：它依然主要围绕单仓库内部的功能开发，不直接覆盖跨仓库协作、长程维护和多轮回归治理。

### 4.2 ContextBench

- 发布时间：2026-02-05
- 官方定位：评测 coding agent 的**context retrieval**，也就是 agent 能否找到、筛选、真正利用解决问题所需的代码上下文。

#### Benchmark 构成

- **1136 个 issue-resolution 任务**。
- 覆盖 **66 个仓库**、**8 种编程语言**。
- 每个任务都带有**人工标注的 gold context**。
- 官方评估了 **4 个 frontier LLM** 和 **5 个 coding agents**。

#### 测什么

- agent 找上下文的能力，而不只是最终 patch 是否通过测试。
- context recall、precision、efficiency。
- agent “探索过的上下文”和“最终真正使用的上下文”之间是否存在鸿沟。

#### 怎么测

- 它会跟踪 agent 的问题解决轨迹。
- 在 issue resolution 过程中统计：
  - 找到了多少关键上下文。
  - 找到的上下文里有多少是有效的。
  - 为找到这些上下文付出了多少搜索代价。

#### 论文与官方给出的结论

- 这是一个非常重要的信号：**复杂 agent scaffold 对 context retrieval 的提升只有边际收益**，作者把它称为 coding agents 上的 “Bitter Lesson”。
- 当前模型普遍**偏 recall，不擅长 precision**，也就是宁可找很多，也不擅长精准找对。
- 存在显著的 **explored context 与 utilized context 脱节**：agent 看了很多代码，但真正转化为有效推理的比例不高。

#### 价值与局限

- 价值：它把 coding agent 中最常见但最不透明的失败模式拆开了。
- 局限：它测的是 issue-resolution 过程中的 context 使用，不直接评估长期维护、跨迭代回归控制等能力。

### 4.3 OmniCode

- 发布时间：2026-02-02
- 官方定位：构建一个覆盖**多种软件工程活动**的统一 benchmark，而不只盯着 patch generation。

#### Benchmark 构成

- **1794 个任务**。
- 覆盖 **Python、Java、C++** 三种语言。
- 包含 4 类任务：
  - bug fixing
  - test generation
  - code review fixing / review response
  - style fixing
- 官方强调任务经过**人工校验**，并且部分是**synthetically crafted** 或近期整理，以减少数据泄漏。

#### 测什么

- bug 修复是否最小且正确。
- 是否能生成能区分正确/错误实现的测试。
- 是否能根据 reviewer feedback 改进失败 patch。
- 是否能修复 style issue 而不破坏功能。

#### 怎么测

- 不同任务族使用不同的验证方式：
  - bug fixing：相关测试是否通过。
  - test generation：生成测试是否能 fail bad implementation、pass good implementation。
  - style review：style violation 是否下降，同时功能不回归。
  - review response：在已有失败 patch 与 review 评论基础上能否修出更好的版本。

#### 论文与官方给出的结论

- 现有 agent 在 Python bug fixing 上可能还有一定竞争力，但**在测试生成、Java/C++ 等设置下明显变差**。
- 论文给出的代表性结果是：**SWE-Agent 在 Java Test Generation 上的最好成绩只有 20.9%**。
- 这说明“会修 bug”并不自动等价于“会做测试、会吸收 review、会处理风格治理”。

#### 价值与局限

- 价值：最适合作为“软件工程活动广度” benchmark，而不是某单一能力 benchmark。
- 局限：虽然任务种类更全，但每一类任务的深度仍然不如为单一能力专门设计的 benchmark 那么细。

### 4.4 SWE-Refactor

- 发布时间：2026-02-03
- 官方定位：评测 LLM/agent 的**真实仓库级语义保持重构能力**。

#### Benchmark 构成

- **1099 个**开发者真实提交的、**behavior-preserving** 重构实例。
- 来源于 **18 个 Java 项目**。
- 其中：
  - **922 个 atomic refactoring**
  - **177 个 compound refactoring**

#### 测什么

- 能否在不改变外部行为的前提下改进程序结构。
- 是否能处理复杂、组合式的重构，而不只是单点重命名或简单提取。

#### 怎么测

- 每个实例都经过：
  - 编译验证
  - 测试执行
  - 自动 refactoring detection 工具确认
- 官方评估了 **9 个主流模型**，包含 GPT-4o-mini、DeepSeek-V3、CodeLLaMa 等。

#### 论文与官方给出的结论

- **复杂重构与 compound refactoring 是当前 agent 的主要失败来源**。
- 论文中一个很典型的数字是：**OpenAI Codex agent 在 compound refactoring 上只有 39.4% success**。
- 这说明即使 agent 在 bug fix 上看起来不错，一旦目标变成“保持语义不变但优化结构”，难度会明显上升。

#### 价值与局限

- 价值：它补上了 bug-fixing benchmark 长期忽视的一块，即“工程质量改善”。
- 局限：语言目前集中在 Java，跨语言与跨生态泛化能力仍需额外 benchmark 补齐。

### 4.5 RepoMod-Bench

- 发布时间：2026-02-26
- 官方定位：评测 agent 的**repository modernization** 能力，即在大规模代码库中完成现代化迁移或自动翻译类任务。

#### Benchmark 构成

- **21 个真实仓库**。
- 覆盖 **8 种语言**。
- 总量达到 **1.6M LOC**。
- 包含 **11,616 个测试**。
- 单仓库规模从 **14 LOC 到 211K LOC** 不等。

#### 测什么

- 在仓库级改造或现代化迁移任务中，agent 是否能保持功能等价。
- 能否在大规模代码库里稳定工作，而不是只在小样例上表现良好。

#### 怎么测

- 其核心设计是 **implementation-agnostic testing**。
- 通过标准化接口，用**黑盒测试**检验 source implementation 与 target implementation 的功能等价性。
- 官方特别强调：**测试对 agent 隐藏**，避免模型通过读取 unit tests 过拟合。

#### 论文与官方给出的结论

- 这是近三个月里对“**规模扩张会让 agent 能力快速崩塌**”描述最明确的 benchmark。
- 论文结果显示：在小于 **10K LOC** 的项目上，平均 pass rate 可达 **91.3%**；一旦项目规模超过 **50K LOC**，平均 pass rate 下降到 **15.3%**。
- 这说明大型仓库现代化仍然远远没有被解决。

#### 价值与局限

- 价值：非常适合检验 repo-scale agent 是否真的具备“工业级迁移能力”。
- 局限：任务形态偏 modernization / translation，不完全等同于开放式 feature 开发或 issue 修复。

### 4.6 Rust-SWE-bench

- 发布时间：2026-02-26
- 官方定位：面向 Rust 生态的**仓库级 issue resolution** benchmark。

#### Benchmark 构成

- **500 个真实任务**。
- 来自 **34 个 Rust 仓库**。
- 官方用 **4 个 agent** 与 **4 个 SOTA LLM** 做了系统评测。

#### 测什么

- agent 在 Rust 仓库中解决真实 issue 的能力。
- 是否能理解 repo-wide structure。
- 是否能处理 Rust 特有的严格类型系统与 trait 语义。
- 是否具备可靠的 issue reproduction 能力。

#### 怎么测

- 任务是真实仓库级软件工程任务，不是合成的单文件 Rust 题。
- 基于 issue resolution 工作流进行执行式验证。
- 论文还提出了配套 agent 方法 RUSTFORGER，用于改进 issue reproduction 和动态分析。

#### 论文与官方给出的结论

- 最强 ReAct 风格 baseline 的 resolved rate 只有 **21.2%**。
- 作者认为两大核心障碍是：
  - **仓库级结构理解不足**
  - **Rust 类型与 trait 语义带来的实现约束**
- 他们进一步发现：**issue reproduction 对任务成功至关重要**。
- 在此基础上，RUSTFORGER + Claude Sonnet 3.7 可达 **28.6%**，相对最强 baseline 提升 **34.9%**。

#### 价值与局限

- 价值：它证明了语言生态差异会显著改变 benchmark 难度，Rust 不是简单把 Python benchmark 平移过去。
- 局限：它强调的是 Rust 生态专有难点，不一定能代表其他语言的 agent 表现。

### 4.7 SWE-CI

- 发布时间：2026-03-04
- 官方定位：评测 agent 在**持续集成循环中的代码维护能力**，核心关键词是 **maintainability**。

#### Benchmark 构成

- **100 个任务**。
- 每个任务平均对应 **233 天** 的代码演化跨度和 **71 个连续 commits**。
- 官方仓库 README 将数据组织描述为 **100 对 base commit / reference commit**。
- 引入一个非常有代表性的**双 agent 协作工作流**：
  - Architect Agent
  - Programmer Agent

#### 测什么

- 不是“单次把代码改对”，而是“能否在多轮迭代中持续保持功能正确性”。
- 是否能在 CI 反馈下逐步生成需求、定位问题、修改代码并持续演进。
- 本质上评测的是**长期维护能力**而不是一次性修补能力。

#### 怎么测

- 采用闭环流程：**Run Tests -> Define Requirements -> Modify Code**。
- 目标是从 base commit 出发，逐步逼近 reference commit 对应的测试通过状态。
- 指标采用 **ANC, Average Normalized Change**，衡量整个维护周期内功能正确性的变化。

#### 论文与官方给出的结论

- 这是一个范式转移型 benchmark：它明确提出评测重点应从**短期 functional correctness** 转向**长期 maintainability**。
- 它的意义不只在于得分，而在于重新定义“什么样的 coding agent 才算工程上真正有用”。
- 从运行成本也能看出它的复杂度明显更高：官方 README 给出的默认评测成本大约是 **48 小时**。

#### 价值与局限

- 价值：非常适合研究 agent 在长程维护中的退化、回归、恢复与协作。
- 局限：部署和运行成本高，不适合高频快速回归；同时 benchmark 更偏维护，不是 feature innovation benchmark。

### 4.8 SWE-Skills-Bench

- 发布时间：2026-03-16
- 官方定位：评测在真实软件工程任务中，**skill 注入是否真的有用**。

#### Benchmark 构成

- 论文层面：**49 个公开 SWE skills**，展开后约 **565 个 task instances**，覆盖 **6 个 SWE 子领域**。
- 仓库当前公开数据集层面：README 展示的 Hugging Face train split 是 **49 条任务行**。
- 以下解释是我基于论文摘要与仓库 README 口径差异做出的**推断**：仓库暴露的是 skill-centered task 配置，而论文中的评测统计将其展开成更细粒度的 paired instances。

#### 测什么

- skill 文档注入对 agent 成功率的边际提升。
- skill 是否带来 token 成本和时间成本。
- skill 与项目上下文是否兼容。

#### 怎么测

- 采用**paired evaluation**：
  - with skill
  - without skill
- 每个任务配套：
  - 固定 commit 的真实 GitHub 仓库
  - requirement document
  - acceptance criteria
  - execution-based tests
- 官方提供了比较 pass rate、失败测试、token 与 duration 的脚本。

#### 论文与官方给出的结论

- 这是近三个月里最“反直觉”的 benchmark 之一。
- 论文核心结论非常明确：
  - **49 个 skill 中有 39 个没有带来任何 pass-rate 提升**
  - 平均提升只有 **+1.2%**
  - 只有 **7 个 specialized skills** 带来有意义的收益，最高约 **+30%**
  - 还有 **3 个 skill 会让表现下降**，最高约 **-10%**
  - token overhead 最夸张可到 **+451%**
- 这说明 skill 并不是通用增益项，它高度依赖：
  - domain fit
  - 抽象层级
  - 与当前项目上下文的兼容性

#### 价值与局限

- 价值：它第一次把“skill 到底有没有用”从经验判断变成了系统 benchmark。
- 局限：它评测的是 skill intervention 的边际价值，而不是 agent 的完整能力上限。

## 5. 综合结论

### 5.1 最近三个月 benchmark 的共同结论

1. **SWE-bench 式成功率不能再代表 coding agent 的真实工程能力**  
   FeatureBench、SWE-CI、RepoMod-Bench 都给出了一致信号：一旦任务升级为 feature 开发、长期维护或大仓库演化，成绩会显著下跌。

2. **上下文获取与利用仍然是 agent 的基础瓶颈**  
   ContextBench 表明，agent 经常“看了很多，但真正用得上的不多”。这会直接影响 repo-level 任务表现。

3. **规模是最强压力测试之一**  
   RepoMod-Bench 的结果最典型：项目规模一旦上来，成功率会断崖式下降。

4. **任务种类一扩展，agent 能力会快速失衡**  
   OmniCode 显示 agent 并不是“会修 bug 就会做测试、吸收 review、治理 style”。

5. **长期维护与工程质量优化仍然很难**  
   SWE-CI 和 SWE-Refactor 表明，agent 在 maintainability 和 refactoring 上离“可靠工程同事”还有明显差距。

6. **外部提示增强不是银弹**  
   SWE-Skills-Bench 直接证明，skill injection 通常不能稳定提升结果，甚至可能产生负收益。

### 5.2 我对这一波 benchmark 走向的判断

- 2026 年 Q1 的 benchmark 主题已经明显从“agent 能不能写代码”转向“agent 能不能像工程团队成员那样工作”。
- 未来更有价值的 benchmark，大概率会继续沿着下面几个方向演进：
  - process-aware
  - repository-scale
  - hidden-test / black-box verification
  - maintenance-oriented
  - capability factorization
  - leakage-resistant automatic refresh

## 6. 对本项目的直接启发

你的项目是一个**cross-language interoperability benchmark**，核心评测对象是 FFI、runtime embedding、WASM 等 glue code 生成能力。结合上面这批 benchmark，我认为最值得直接借鉴的设计点有 6 个：

1. **保留 execution-based verification，并尽量做成黑盒或半黑盒**  
   RepoMod-Bench 的经验说明，隐藏测试或至少隐藏完整验证逻辑，对防止 agent 走 test-driven shortcut 很关键。

2. **不要只看最终 pass/fail，增加过程指标**  
   可以借鉴 ContextBench 和 SWE-CI，加上：
   - compile round 数
   - context retrieval 命中率
   - regression 次数
   - baseline 到 target 的演化曲线

3. **把任务家族拆开，而不是只做一种 glue code 题型**  
   例如把跨语言任务拆成：
   - bridge repair
   - bridge feature addition
   - API binding migration
   - test restoration after masking
   - build/CI recovery

4. **控制 benchmark 泄漏，优先自动化刷新任务池**  
   FeatureBench 的自动任务构造思路很值得借鉴。你们现在从 GitHub PR 自动采集，本身就很契合这个方向。

5. **显式区分“小仓库可做”和“大仓库真难”**  
   RepoMod-Bench 的规模分层值得参考。你们可以把任务按：
   - repo size
   - changed files
   - languages involved
   - bridge surface area
   做分桶分析。

6. **把“可维护的 glue code”单独作为一类评分维度**  
   受 SWE-CI 和 SWE-Refactor 启发，除了测试通过，还可以加：
   - 生成代码是否符合目标语言 idiom
   - 是否引入额外 unsafe boundary
   - 是否增加不必要 coupling
   - 是否保留边界错误处理与资源释放语义

## 7. 推荐优先阅读顺序

如果你是为了给当前 benchmark 项目吸收设计灵感，我建议优先阅读顺序如下：

1. **FeatureBench**  
   看它如何把任务从 bug fix 提升到 feature-level development。

2. **ContextBench**  
   看它如何把 context retrieval 从黑箱拆成可量化指标。

3. **RepoMod-Bench**  
   看它如何用 hidden black-box tests 避免 agent 走捷径。

4. **SWE-CI**  
   看它如何把 maintainability 形式化为长期评测对象。

5. **OmniCode**  
   看它如何把多软件工程活动放到同一 benchmark 中。

6. **SWE-Skills-Bench**  
   看它如何做 intervention-style benchmark，即评测某种 agent 增强手段是否真的有效。

## 8. 参考来源

以下均为本次整理实际采用的一手来源：

- FeatureBench 论文摘要页：<https://arxiv.org/abs/2602.10975>
- FeatureBench 官方站点：<https://libercoders.github.io/FeatureBench/>
- ContextBench 论文摘要页：<https://arxiv.org/abs/2602.05892>
- OmniCode 论文摘要页：<https://arxiv.org/abs/2602.02262>
- OmniCode 官方仓库：<https://github.com/seal-research/OmniCode>
- SWE-Refactor 论文摘要页：<https://arxiv.org/abs/2602.03712>
- RepoMod-Bench 论文摘要页：<https://arxiv.org/abs/2602.22518>
- RepoMod-Bench 官方仓库：<https://github.com/Modelcode-ai/mcode-benchmark>
- Rust-SWE-bench 论文摘要页：<https://arxiv.org/abs/2602.22764>
- SWE-CI 论文摘要页：<https://arxiv.org/abs/2603.03823>
- SWE-CI 官方仓库：<https://github.com/SKYLENAGE-AI/SWE-CI>
- SWE-Skills-Bench 论文摘要页：<https://arxiv.org/abs/2603.15401>
- SWE-Skills-Bench 官方仓库：<https://github.com/GeniusHTX/SWE-Skills-Bench>
