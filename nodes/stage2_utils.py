from __future__ import annotations

from typing import Any


def tail_text(text: str | None, max_lines: int = 50) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-max_lines:])


def make_error(
    pr: dict[str, Any],
    *,
    stage: str,
    reason: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pr_id": pr.get("pr_id"),
        "repo": pr.get("repo"),
        "stage": stage,
        "reason": reason,
        "message": message,
    }
    payload.update(extra)
    return payload


def make_image_tag(pr: dict[str, Any]) -> str:
    repo = str(pr.get("repo", "unknown")).replace("/", "-").lower()
    pr_id = pr.get("pr_id", "unknown")
    return f"benchmark-{repo}-pr{pr_id}"


def summarize_stage2_state(state: dict[str, Any]) -> dict[str, Any]:
    errors = list(state.get("errors") or [])
    last_error = errors[-1] if errors else {}
    baseline = state.get("baseline_test_result") or {}
    env_spec = state.get("env_spec") or {}

    coarse_status = "failed"
    if state.get("compile_status") in {"success", "repaired"}:
        if baseline.get("failed", -1) == 0 and baseline.get("compile_success") is True:
            coarse_status = "baseline_test_passed"
        else:
            coarse_status = "compile_passed"
    elif state.get("build_status") == "success":
        coarse_status = "image_built"
    elif state.get("dockerfile_content"):
        coarse_status = "dockerfile_rendered"
    elif env_spec and env_spec.get("source") not in {None, "failed"}:
        coarse_status = "env_inferred"

    return {
        "pr": state.get("pr"),
        "image_tag": state.get("image_tag"),
        "coarse_status": coarse_status,
        "reason_code": last_error.get("reason"),
        "env_spec": env_spec,
        "build_status": state.get("build_status"),
        "compile_status": state.get("compile_status"),
        "baseline_test_result": baseline or None,
        "errors": errors,
    }
