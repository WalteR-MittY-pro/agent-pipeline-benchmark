# discussion.md — 跨语言互操作分类分析与 Benchmark Scope 论证

> 本文件记录 benchmark 设计决策的学术论证过程，用于应对审稿人对 scope 选择的质疑。
> 所有决策结论已同步至 AGENT.md；本文件保留完整的推理链路。

---

## 一、跨语言调用的完整分类体系

### 1.1 两个正交维度

跨语言调用可以沿两个维度独立分析：

**维度 A：地址空间边界**

- **进程内（In-process）**：调用双方共享同一虚拟地址空间，可以直接传递指针，数据零拷贝
- **进程间（Cross-process）**：调用双方运行在隔离的地址空间，数据必须经过序列化/反序列化或操作系统 IPC 机制传递

**维度 B：耦合层次**

从最底层到最高层依次为：

```
ABI 层       — 直接操作机器码调用约定（calling convention）和内存布局
运行时层     — 通过语言运行时提供的 C API 进行交互
字节码层     — 通过中间字节码/沙箱进行交互（如 WASM）
协议层       — 通过序列化协议（protobuf、JSON）进行交互
系统调用层   — 通过操作系统原语（pipe、socket、文件）进行交互
```

### 1.2 完整分类矩阵

|  | 进程内 | 进程间 |
|---|---|---|
| **ABI 层** | FFI 直接调用（CGo、JNI、ctypes、Rust FFI、N-API）<br>共享库动态加载（dlopen） | — |
| **运行时层** | 运行时嵌入（Lua↔C、Python.h API、Ruby C ext、V8↔C++） | 语言服务器协议（LSP，工具链通信，非应用层） |
| **字节码层** | WebAssembly（沙箱隔离但共享进程内存页） | JVM/CLR 多语言（Kotlin/Scala/Groovy，同一运行时） |
| **协议层** | 进程内 Actor 消息（Erlang/Elixir，语言特定） | gRPC / Thrift / JSON-RPC / REST |
| **系统调用层** | — | Subprocess / pipe / socket / 共享文件 |

---

## 二、各类型深度分析

### 2.1 FFI / ABI 直接调用

**机制：** 调用方通过 C ABI（或平台 ABI）直接调用被调用方的函数。要求调用方理解目标语言的类型在内存中的表示方式，并负责维护内存生命周期。

**代表技术：**

| 技术 | 宿主语言 | 被调用语言 | 核心挑战 |
|---|---|---|---|
| CGo | Go | C/C++ | Go 的 GC 与 C 内存的交互，指针传递限制 |
| JNI | Java/Kotlin | C/C++ | JNI 引用类型（LocalRef/GlobalRef），JNIEnv 线程绑定 |
| ctypes / cffi | Python | C | Python 对象与 C 类型的转换，GIL 影响 |
| Rust FFI | Rust | C | unsafe 块，所有权边界，生命周期标注 |
| Node N-API | Node.js | C++ | V8 Handle scope，异步回调，libuv 集成 |

**对 LLM 的挑战：** 模型需要同时掌握两种语言的类型系统，并理解跨越边界时类型转换和内存管理的正确方式。错误后果通常是段错误或内存泄漏，不是编译错误，难以通过静态分析发现。

**GitHub 样本可得性：** 高。CGo、JNI、Python C Extension 是工业界成熟技术，拥有大量高星级仓库。

**结论：核心层，必须覆盖。**

---

### 2.2 运行时嵌入（Runtime Embedding）

**机制：** 宿主程序（通常是 C/C++ 应用）将另一种语言的完整运行时嵌入自身进程，通过该运行时提供的 C API 执行脚本或调用函数。调用方不操作 ABI，而是操作运行时的"栈"或"堆"。

**代表技术：**

| 技术 | 宿主语言 | 嵌入运行时 | 典型应用场景 |
|---|---|---|---|
| Lua C API | C/C++ | Lua VM | 游戏引擎脚本（Unreal、Redis 插件） |
| Python.h / CPython API | C/C++ | CPython | Python 扩展模块、C 程序调用 Python 脚本 |
| Ruby C Extension API | C | CRuby MRI | Ruby gem 的原生扩展 |
| V8 C++ API | C++ | V8 JS Engine | Node.js 本身的实现方式、Electron |

**与 FFI 的本质区别：**

FFI 是"我去调你的函数"——直接按 ABI 约定压栈、跳转。  
运行时嵌入是"我管理你的整个运行环境"——推入值到运行时栈、触发 GC、管理脚本执行上下文。

前者要求理解类型映射；后者要求理解运行时内部状态机（如 Lua 的栈式 API、Python 的引用计数与 GIL、Ruby 的 VALUE 类型系统）。两者的认知要求是正交的，合并在同一 benchmark 中可以更全面地考察跨语言理解能力。

**对 LLM 的挑战：** 运行时 API 往往反直觉（如 Lua 的栈操作需要精确计算栈偏移量），且 API 文档稀疏，是模型容易产生幻觉的场景。

**GitHub 样本可得性：** 中等。Lua↔C 在游戏引擎领域有稳定的仓库群；Python C Extension 样本丰富；Ruby C ext 较少。

**结论：有效补充层，纳入 benchmark。**

---

### 2.3 WebAssembly（WASM）

**机制：** 将 Rust/C/C++ 源码编译为 `.wasm` 字节码，由 JavaScript 宿主（浏览器或 Node.js）通过 WebAssembly API 加载和调用。WASM 模块运行在沙箱中，但与 JS 宿主共享进程地址空间（通过线性内存 buffer）。

**与 FFI 的关键差异：**
- FFI 是直接内存共享，WASM 是通过显式线性内存（`ArrayBuffer`）共享数据
- WASM 有类型系统的"边界检查"，而 FFI 没有
- WASM 调用需要处理 JS ↔ WASM 的类型转换（`wasm-bindgen` 或手动编码）

**对 LLM 的挑战：** 需要理解 WASM 内存模型（线性内存、指针编码为 i32 offset）、bindings 生成工具（wasm-bindgen、emscripten）、以及 JS 端的 TypedArray 操作。

**GitHub 样本可得性：** 低。WASM 是相对新兴的技术，高质量的含测试的 PR 样本数量有限。

**结论：补充层，样本稀少，有几个就纳入，不强求数量。**

---

### 2.4 gRPC / Thrift / REST（排除）

**排除理由：**

> **核心论点：协议层调用考察的是 schema 遵从能力，而非跨语言理解能力。**

gRPC 调用的正确性完全由 `.proto` 文件决定。给定 proto 定义，任何语言的 client stub 都是机械生成的——模型只需要理解"如何调用生成的 stub API"，而不需要理解目标语言的运行时特性。

FFI 和运行时嵌入恰恰相反：模型必须理解内存所有权（Rust 的借用检查器在 FFI 边界处失效）、GC 暂停对 JNI 指针的影响、Python GIL 在 C 扩展中的释放时机——这些是语言特定的深层知识，不是接口契约能表达的内容。

**补充论点：gRPC 两侧代码完全解耦。**

在 gRPC 场景中，客户端语言和服务端语言互不感知——Python client 完全不需要知道 Go server 的任何实现细节。这意味着"跨语言 PR"在 gRPC 仓库中很难真正考察到跨语言能力：一个 PR 要么改了 client 侧，要么改了 server 侧，很少同时改两侧且含有真正的跨语言胶水代码。

**结论：排除。**

---

### 2.5 Subprocess / pipe / REST（排除）

**排除理由：**

这类调用本质上将语言差异完全抽象掉了——调用方看到的只是字节流或 HTTP 请求，与对端语言无关。

- `subprocess.run(["./go_binary", "--input", data])` 考察的是命令行参数解析，不是跨语言
- `requests.get("http://java-service/api/data")` 考察的是 HTTP 客户端用法，不是跨语言

将这类用例纳入 benchmark 会稀释评测信号，使 benchmark 退化为通用 API 调用能力测试。

**结论：排除。**

---

### 2.6 JVM/CLR 多语言（排除）

**排除理由：**

Kotlin、Scala、Groovy 在 JVM 上互调，或 F#、VB.NET 在 CLR 上互调，本质上是**同一运行时内的多语言**。它们共享同一套类型系统（JVM 类型/CLR 类型），不存在 ABI 边界，不需要手动类型转换，GC 对所有语言一视同仁。这不是"跨语言"，而是"多语法"。

**结论：排除。**

---

## 三、最终 Scope 决策

### 3.1 纳入范围

```
进程内跨语言互操作（In-process Cross-Language Interoperability）
│
├── FFI / ABI 层（核心，预期 ~70% 用例）
│   ├── CGo（Go ↔ C/C++）
│   ├── JNI（Java/Kotlin ↔ C/C++）
│   ├── ctypes / cffi（Python ↔ C）
│   ├── Rust FFI（Rust ↔ C）
│   └── Node N-API（Node.js ↔ C++）
│
├── 运行时嵌入层（补充，预期 ~25% 用例）
│   ├── Lua C API（C/C++ 嵌入 Lua VM）
│   ├── Python C Extension API（C/C++ 嵌入 CPython）
│   └── Ruby C Extension API（C 嵌入 CRuby MRI）
│
└── WASM 层（少量，预期 ~5% 用例，有即纳入）
    └── Rust/C → .wasm + JavaScript host
```

### 3.2 预期用例分布

| interop_layer | 预期占比 | 预期用例数 | 说明 |
|---|---|---|---|
| ffi | 70% | 140–210 | 样本丰富，难度高，核心考察点 |
| runtime_embedding | 25% | 50–75 | Lua/Python C ext 样本较稳定 |
| wasm | 5% | 10–15 | 有即纳入，不强求 |

### 3.3 对审稿人的预期反驳与应对

**Q1: 为什么不包含 gRPC？gRPC 也是主流的跨语言通信方式。**

A: gRPC 通过 protobuf schema 将两侧完全解耦，调用双方不需要理解对方语言的任何运行时特性。本 benchmark 聚焦"需要同时理解两种语言内部机制"的场景，gRPC 不满足这一条件。我们的选择标准是：去掉协议/框架层之后，模型是否仍需理解跨语言边界——FFI 和运行时嵌入满足，gRPC 不满足。

**Q2: WASM 样本太少，是否应该排除以保持 benchmark 的均衡性？**

A: WASM 代表了一类独特的跨语言机制（沙箱内线性内存模型），与 FFI 的直接内存共享有本质区别。即使样本少，保留少量 WASM 用例能使 benchmark 覆盖字节码层的互操作场景，有助于评估模型对新兴跨语言技术的泛化能力。我们不强制均衡，而是如实反映 GitHub 上的技术分布。

**Q3: 运行时嵌入（如 Lua↔C）是否算"跨语言调用"？方向是 C 调用 Lua，而非通常理解的高层语言调用 C。**

A: 跨语言互操作是双向的。运行时嵌入场景中，C/C++ 宿主程序通过 Lua C API 管理 Lua 运行时，这同样要求模型理解两种语言的语义边界——只是方向相反。事实上，运行时嵌入比 FFI 更复杂，因为调用方需要管理整个脚本执行上下文，而不仅仅是类型映射。将其纳入可以更全面地考察模型的跨语言推理能力。

---

## 四、字段命名决策

将 `ffi_type` 重命名为 `interop_type`，新增 `interop_layer` 字段：

```python
interop_layer: str   # "ffi" | "runtime_embedding" | "wasm"
interop_type:  str   # 具体技术，见下表
```

| interop_layer | interop_type 取值 |
|---|---|
| ffi | `cgo`, `jni`, `ctypes`, `cffi`, `rust_ffi`, `node_napi` |
| runtime_embedding | `lua_c`, `python_cext`, `ruby_cext`, `v8_cpp` |
| wasm | `wasm` |

这两个字段共同构成用例的分类维度，支持按层次或按具体技术进行子集评测。

---

## 五、胶水代码 vs 业务逻辑：核心学术立场

> 这是整个 benchmark 最容易被审稿人质疑的设计决策。本节提供完整的论证链路。

### 5.1 核心立场

> 现有代码生成 benchmark 评测的是模型在单语言上下文中的语义推理能力。跨语言互操作场景引入了一个新的评测维度：**模型是否理解跨语言边界的内存模型差异、类型系统冲突和运行时语义不兼容**。我们专门测试胶水代码生成，而非单语言业务逻辑，是因为只有胶水代码的正确性依赖于对两种语言内部机制的同时理解，这是现有 benchmark 无法覆盖的盲区。

### 5.2 什么是胶水代码，什么是业务逻辑

在跨语言项目中，代码天然分为两类：

```
跨语言项目中的代码
│
├── 业务逻辑代码（单语言内部）
│   └── 例：Go 侧的排序算法、Java 侧的数据库操作
│       → 只需要懂一种语言，与"跨语言"无关
│       → HumanEval、SWE-bench 已经能很好地评测这类任务
│
└── 胶水代码 / 桥接代码（跨语言边界）
    └── 例：CGo 的 import "C" 调用块、JNIEnv 方法调用、ctypes 类型声明
        → 必须同时理解两种语言的内存模型、类型系统、运行时语义
        → 现有 benchmark 无法覆盖
```

**判断标准：** 如果把代码中的 FFI/互操作关键字全部删除，代码仍然能在单语言环境中正确运行——那就是业务逻辑，不是胶水代码。胶水代码的本质是处理两种语言之间的**阻抗失配（impedance mismatch）**。

### 5.3 如果测业务逻辑会有什么问题

假设我们的 benchmark 测的是这样的题：

```
给定：完整的 CGo bridge.go（胶水层已写好）+ native.h + native.c
题目：写 main.go 里调用 bridge.go 的业务逻辑
```

这道题的答案不涉及任何跨语言知识——模型只需要把 `bridge.go` 暴露的函数当成普通 Go 函数调用即可。这等价于一道普通的 Go 函数调用题，HumanEval 已经覆盖了。我们的 benchmark 没有增量价值。

### 5.4 胶水代码为什么天然适合 benchmark 评测

胶水代码有一个关键特性：**错误通常语法正确、类型检查通过，但语义错误，且只能通过运行时测试发现**。这与 benchmark 的评测机制完美契合：

```
胶水代码的典型错误类型（工业实践中的真实痛点）：

  CGo:    把 Go 栈上的指针传给 C → 段错误（go vet 无法检测所有情况）
          C.CString() 后忘记 C.free() → 内存泄漏
          
  JNI:    忘记 DeleteLocalRef → JNI 局部引用表溢出
          JNIEnv 跨线程使用 → 崩溃（JNIEnv 是线程绑定的）
          
  Python: C 扩展中未释放 GIL → 死锁
          引用计数错误（Py_INCREF/Py_DECREF 不匹配）→ use-after-free
          
  Rust:   Box::into_raw 后未调用 Box::from_raw → 内存泄漏
          FFI 边界处 panic → 未定义行为（Rust panic 不能跨越 C 边界）
```

这些错误的特征：
- 编译通过 ✓
- 类型检查通过 ✓
- 静态分析工具大多无法检测 ✓
- **运行测试用例时会触发** ← 这正是我们的验证手段

### 5.5 学术工作的支撑

**CrossPL（2025）** 是目前最接近本工作方向的 benchmark，覆盖了跨语言 IPC（进程间通信）场景。该工作明确指出"FFI 和进程内互操作留待未来工作"——我们的 benchmark 正好填补了这个缺口，两者互补而非竞争。

**ScienceDirect（2025）** 专门研究 C++/JavaScript 胶水代码生成问题，将胶水代码生成定义为独立的形式化问题，并指出其处理的是"语言边界的跨越（cross-boundary）"而非单语言语义。这验证了胶水代码是一个值得专门研究的独立问题域。

**Berkeley 2025 年研究** 明确指出：LLM 在跨语言场景中面临"验证多语言代码库中跨边界组件正确性"的根本困难，核心原因是"大多数最先进工具都针对单一语言，无法跨边界推理"——这正是现有 benchmark 的盲区，也是我们的出发点。

**MERA Code 的 RealCode 方法** 与我们的构题思路高度一致：识别被测试覆盖的函数，mask 函数体，保留函数签名作为上下文，用测试通过与否验证生成质量。不同点在于 RealCode 只做单语言——我们把这一范式扩展到了跨语言边界，这是真正的方法论创新。

### 5.6 对审稿人的预期质疑与应对

**Q4: 为什么不同时评测胶水代码和业务逻辑，这样 benchmark 覆盖面更广？**

A: 混合两类任务会稀释评测信号。如果一个模型在业务逻辑题上表现很好、胶水代码题上表现差，混合得分会掩盖这一差异。我们的目标是专门测量跨语言边界理解能力，需要"纯度"。针对业务逻辑，HumanEval、BigCodeBench 等已有充分覆盖。

**Q5: 如何确保被 mask 的一定是胶水代码而不是业务逻辑？**

A: 我们采用双重验证机制：（1）关键字过滤——mask 的函数体中必须包含 FFI/互操作关键字（如 `JNIEnv`、`import "C"`），纯业务逻辑代码不含这些；（2）测试有效性验证——mask 后测试必须失败，说明被 mask 的代码确实是功能路径上的关键代码。同时满足这两个条件才会生成题目。

**Q6: 胶水代码通常很短，题目会不会太简单？**

A: 这恰恰相反。胶水代码的难度来自于"需要同时理解两个语言运行时的语义"，而不是代码量。20 行 JNI 代码比 200 行 Java 业务逻辑更难生成正确，因为任何一个引用管理错误都会导致运行时崩溃。我们的难度分级（easy/medium/hard）基于内存管理复杂度和类型转换深度，而非代码行数。

---

## 六、开放问题（供后续讨论）

- **V8↔C++ 的归类**：V8 的嵌入方式介于运行时嵌入（通过 V8 API 管理 JS 上下文）和 FFI（Node N-API 直接暴露 C++ 函数）之间，GitHub 上相关 PR 较少，暂归入 `runtime_embedding`，后续根据实际样本决定是否单独建类。

- **Python ctypes vs Python C Extension 的边界**：ctypes 是纯 Python 层面动态调用 C 函数（归 FFI 层），Python C Extension 是 C 代码实现 Python 模块（归运行时嵌入层）。两者在 PR 中有时难以区分，`infer_env` 节点需要根据文件模式（有无 `PyInit_` 符号）判断。

- **Rust wasm-bindgen vs Rust FFI 的边界**：同一个 Rust 仓库可能既有 `#[no_mangle]` 的 C FFI，也有 `#[wasm_bindgen]` 的 WASM 绑定。`interop_type` 以 PR diff 中实际修改的绑定类型为准，而非仓库整体技术栈。