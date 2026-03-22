# AGENT.md

## Project

Cross-language interoperability benchmark for evaluating LLM code generation ability.
Automatically collects real-world PRs from GitHub that contain **in-process cross-language glue code** (FFI, runtime embedding, WASM), masks the bridging code, and verifies whether a target LLM can regenerate it to pass the original tests.

We test **glue code only**, not business logic. See `discussion.md §五` for the academic rationale.

---

## Setup

```bash
pip install -r requirements.txt

export GITHUB_TOKEN_1="ghp_..."
export GITHUB_TOKEN_2="ghp_..."        # second token for rate-limit rotation
export TARGET_LLM_API_KEY="sk-ant-..."
```

---

## Run

```bash
# Stage 1 only — crawl GitHub, output PR snapshot
python main.py --mode fetch --interop-types cgo,jni --output prs_snapshot.json

# Stage 2+3 only — read snapshot, build Docker envs, generate & evaluate
python main.py --mode build --input prs_snapshot.json --thread-id build-001

# Debug a single PR end-to-end
python main.py --mode single-pr --pr-json tests/fixtures/sample_pr.json

# Resume from checkpoint after crash
python main.py --mode resume --thread-id build-001

# Full pipeline
python main.py --mode full --skip-review
```

---

## Test

```bash
pytest tests/ -v                              # all unit tests (no Docker needed)
pytest tests/ -v -m docker                   # integration tests (requires Docker daemon)
python tests/test_parsers.py                  # parser unit tests only
```

---

## Architecture

```
main.py              CLI entry, 5 execution modes
graph.py             LangGraph graph definitions (main graph + PR subgraph)
state.py             All TypedDict definitions — single source of truth for data contracts
github_client.py     GitHub API wrapper: token rotation, rate limiting, SQLite cache

nodes/               One file per LangGraph node
  fetch_repos.py       Search GitHub repos by interop_type
  fetch_prs.py         Filter merged PRs with cross-language signals + test files
  human_review.py      Optional interrupt() checkpoint for manual PR review
  infer_env.py         4-layer fallback: repo Dockerfile → CI workflow → LLM → skip
  build_dockerfile.py  Render Jinja2 Dockerfile template with EnvSpec
  docker_build.py      async docker build, max 3 retries
  compile_verify.py    Compile inside container, run baseline tests, LLM repair loop (<=2 rounds)
  construct_task.py    Mask glue code, 3-step validity check (baseline->mask fails->gt passes)
  llm_generate.py      Call target LLM with masked prompt
  run_tests.py         Inject generated code -> recompile -> run tests in container
  score.py             score_total = test(60%) + compile(20%) + quality/judge(20%)
  aggregate.py         Dedup, cap per-repo, sort, write output files

parsers/             Test output parsers, all implement parse(stdout, exit_code) -> TestResult
  go_parser.py         go test -json streaming events
  pytest_parser.py     pytest -q summary line
  junit_xml_parser.py  JUnit XML (Maven + Gradle)
  cargo_parser.py      cargo test summary line
  jest_parser.py       jest --json output
  generic_parser.py    regex fallback

dockerfiles/templates/   Jinja2 Dockerfile skeletons, one per interop_type
output/                  benchmark_dataset.json + summary_report.md (git-ignored)
tests/fixtures/          Sample PR JSON files for single-pr mode
```

---

## Key Data Types (state.py)

| Type | Producer | Consumer |
|---|---|---|
| `RepoInfo` | `fetch_repos` | `fetch_prs` |
| `PRMetadata` | `fetch_prs` | all Stage 2+3 nodes |
| `EnvSpec` | `infer_env` | `build_dockerfile`, `run_tests` |
| `BenchmarkTask` | `construct_task` | `llm_generate`, `run_tests`, `score` |
| `TestResult` | parsers | `score` |
| `BenchmarkItem` | `score` | `aggregate` |

`BenchmarkState.prs`, `.benchmark_items`, `.errors` use `operator.add` reducers — parallel subgraph writes are merged automatically, never overwritten.

---

## Interop Scope

| `interop_layer` | `interop_type` values |
|---|---|
| `ffi` | `cgo` `jni` `ctypes` `cffi` `rust_ffi` `node_napi` |
| `runtime_embedding` | `lua_c` `python_cext` `ruby_cext` `v8_cpp` |
| `wasm` | `wasm` |

Excluded: gRPC/REST (protocol layer decouples languages), subprocess/IPC (OS-level byte stream), JVM/CLR multi-language (same runtime).

---

## Conventions

- All nodes: `def node_name(state: XState) -> dict` — return only changed fields
- Async nodes (Docker ops): `async def`, wrapped in `DOCKER_SEMAPHORE` (default concurrency = 4)
- Never hardcode API keys — read from env vars only
- Cache key format: `"{resource_type}:{repo}:{sha}:{path}"`, TTL -1 = permanent
- Error records: always include `{pr_id, repo, stage, reason, message}`
- `target_file_path` in `BenchmarkTask` is the absolute path **inside the container** (e.g. `/app/bridge.go`)
- When injecting generated code: use correct file extension (`.go` not `.tmp`), then recompile before testing

## Do Not

- Do not modify `state.py` TypedDict field names without updating all nodes that read them
- Do not skip the 3-step validity check in `construct_task` (baseline -> mask-breaks-tests -> gt-restores-tests)
- Do not put business logic in `AGENT.md` — use `DESIGN.md` or `DEVELOPER.md`
- Do not commit `.env`, `*.db`, or `output/` to git