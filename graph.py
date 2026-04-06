# graph.py
import asyncio
import sqlite3
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from state import BenchmarkState
from state import PRSubState
from nodes.fetch_repos import fetch_repos
from nodes.fetch_prs import fetch_prs
from nodes.human_review import human_review
from nodes.infer_env import infer_env
from nodes.build_dockerfile import build_dockerfile
from nodes.docker_build import docker_build
from nodes.compile_verify import compile_verify
from nodes.construct_task import construct_task
from nodes.llm_generate import llm_generate
from nodes.run_tests import run_tests
from nodes.score import score

from langgraph.graph import StateGraph
from langgraph.constants import START, END
from langgraph.checkpoint.memory import MemorySaver

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:  # pragma: no cover - fallback for minimal environments
    SqliteSaver = None

_DOCKER_SEMAPHORE: Optional[asyncio.Semaphore] = None


def get_docker_semaphore(max_concurrent: int = 4) -> asyncio.Semaphore:
    global _DOCKER_SEMAPHORE
    if _DOCKER_SEMAPHORE is None:
        _DOCKER_SEMAPHORE = asyncio.Semaphore(max_concurrent)
    return _DOCKER_SEMAPHORE


def _build_checkpointer(db_path: str):
    if SqliteSaver is not None:
        # Newer langgraph versions expose from_conn_string() as a context manager,
        # while compile() expects an actual BaseCheckpointSaver instance.
        conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
        )
        return SqliteSaver(conn)

    return MemorySaver()


def build_graph(db_path: str = "benchmark_runs.db"):
    """Build and compile LangGraph main graph"""
    g = StateGraph(BenchmarkState)

    g.add_node("fetch_repos", fetch_repos)
    g.add_node("fetch_prs", fetch_prs)
    g.add_node("human_review", human_review)

    g.add_edge(START, "fetch_repos")
    g.add_edge("fetch_repos", "fetch_prs")
    g.add_edge("fetch_prs", "human_review")
    g.add_edge("human_review", END)

    return g.compile(checkpointer=_build_checkpointer(db_path))


def build_stage1_pr_graph(db_path: str = "benchmark_runs.db"):
    """Build the Stage 1 PR graph used by fetch-prs mode."""
    g = StateGraph(BenchmarkState)

    g.add_node("fetch_prs", fetch_prs)
    g.add_node("human_review", human_review)

    g.add_edge(START, "fetch_prs")
    g.add_edge("fetch_prs", "human_review")
    g.add_edge("human_review", END)

    return g.compile(checkpointer=_build_checkpointer(db_path))


def route_after_build(state: PRSubState):
    env_spec = state.get("env_spec") or {}
    if env_spec.get("source") == "failed":
        return END
    if state.get("build_status") == "success":
        return "compile_verify"
    if state.get("dockerfile_path") and int(state.get("build_retries", 0)) < 3:
        return "docker_build"
    return END


def route_after_infer_env(state: PRSubState):
    env_spec = state.get("env_spec") or {}
    if env_spec.get("source") == "failed":
        return END
    if state.get("image_tag"):
        return "compile_verify"
    return "build_dockerfile"


def route_after_dockerfile(state: PRSubState):
    env_spec = state.get("env_spec") or {}
    if env_spec.get("source") == "failed":
        return END
    if state.get("dockerfile_path"):
        return "docker_build"
    return END


def route_after_compile(state: PRSubState, *, stage2_only: bool = True):
    if state.get("compile_status") in {"success", "repaired"}:
        return END if stage2_only else "construct_task"
    if state.get("compile_status") == "retryable" and state["run_config"].get(
        "enable_compile_repair"
    ) and int(
        state.get("compile_repair_rounds", 0)
    ) < 2:
        return "compile_verify"
    return END


def route_after_construct_task(state: PRSubState):
    return "llm_generate" if state.get("task") else END


def route_after_llm_generate(state: PRSubState):
    return "run_tests" if state.get("generated_code") else END


def route_after_run_tests(state: PRSubState):
    return "score" if state.get("test_result") else END


def build_pr_subgraph(
    db_path: str = "benchmark_runs.db",
    *,
    stage2_only: bool = True,
):
    g = StateGraph(PRSubState)

    g.add_node("infer_env", infer_env)
    g.add_node("build_dockerfile", build_dockerfile)
    g.add_node("docker_build", docker_build)
    g.add_node("compile_verify", compile_verify)
    g.add_node("construct_task", construct_task)
    g.add_node("llm_generate", llm_generate)
    g.add_node("run_tests", run_tests)
    g.add_node("score", score)

    g.add_edge(START, "infer_env")
    g.add_conditional_edges(
        "infer_env",
        route_after_infer_env,
        {
            "build_dockerfile": "build_dockerfile",
            "compile_verify": "compile_verify",
            END: END,
        },
    )
    g.add_conditional_edges(
        "build_dockerfile",
        route_after_dockerfile,
        {
            "docker_build": "docker_build",
            END: END,
        },
    )
    g.add_conditional_edges(
        "docker_build",
        route_after_build,
        {
            "compile_verify": "compile_verify",
            "docker_build": "docker_build",
            END: END,
        },
    )
    g.add_conditional_edges(
        "compile_verify",
        lambda state: route_after_compile(state, stage2_only=stage2_only),
        {
            "compile_verify": "compile_verify",
            "construct_task": "construct_task",
            END: END,
        },
    )
    g.add_conditional_edges(
        "construct_task",
        route_after_construct_task,
        {
            "llm_generate": "llm_generate",
            END: END,
        },
    )
    g.add_conditional_edges(
        "llm_generate",
        route_after_llm_generate,
        {
            "run_tests": "run_tests",
            END: END,
        },
    )
    g.add_conditional_edges(
        "run_tests",
        route_after_run_tests,
        {
            "score": "score",
            END: END,
        },
    )
    g.add_edge("score", END)

    # Stage 2 single-pr/build currently rely on async node execution.
    # MemorySaver supports the async graph path without requiring AsyncSqliteSaver.
    return g.compile(checkpointer=MemorySaver())
