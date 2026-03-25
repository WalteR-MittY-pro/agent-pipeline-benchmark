# graph.py
import asyncio
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from state import BenchmarkState
from nodes.fetch_repos import fetch_repos
from nodes.fetch_prs import fetch_prs
from nodes.human_review import human_review

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

    if SqliteSaver is not None:
        checkpointer = SqliteSaver.from_conn_string(db_path)
    else:  # same-process review still works with in-memory checkpoints
        checkpointer = MemorySaver()

    return g.compile(checkpointer=checkpointer)
