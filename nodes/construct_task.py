from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from github_client import GitHubClient, get_github_tokens_from_env
from nodes.docker_runtime import run_file_in_container
from nodes.stage2_utils import make_error


INTEROP_KEYWORDS: dict[str, list[str]] = {
    "cgo": ['import "C"', "CGO_ENABLED", "//export"],
    "jni": ["JNIEnv", "JNIEXPORT", "jclass", "jobject"],
    "ctypes": ["ctypes.cdll", "ctypes.CDLL", "CFUNCTYPE", "ctypes.c_"],
    "cffi": ["ffi.cdef", "ffi.open", "ffi.new", "ffi.cast"],
    "rust_ffi": ["#[no_mangle]", 'extern "C"', "unsafe"],
    "node_napi": ["Napi::", "NODE_API_MODULE", "#include <napi.h>"],
    "lua_c": ["lua_State", "luaL_newstate", "lua_pcall", "lua_push"],
    "python_cext": [
        "PyInit_",
        "PyArg_ParseTuple",
        "Py_BuildValue",
        "PyObject_GetIter",
        "PyIter_Next",
        "Py_DECREF",
        "PyErr_SetString",
        "PyErr_Occurred",
        "PyObject",
    ],
    "ruby_cext": ["Init_", "rb_define_method", "VALUE", "rb_intern"],
    "v8_cpp": ["v8::", "Isolate", "FunctionTemplate"],
    "wasm": ["#[wasm_bindgen]", "wasm_bindgen", "WebAssembly.instantiate"],
}

INTEROP_LANG_PAIRS: dict[str, tuple[str, str]] = {
    "cgo": ("Go", "C"),
    "jni": ("Java", "C"),
    "ctypes": ("Python", "C"),
    "cffi": ("Python", "C"),
    "rust_ffi": ("Rust", "C"),
    "node_napi": ("JavaScript", "C++"),
    "lua_c": ("C", "Lua"),
    "python_cext": ("C", "Python"),
    "ruby_cext": ("C", "Ruby"),
    "v8_cpp": ("C++", "JavaScript"),
    "wasm": ("Rust", "JavaScript"),
}

BLOCK_LANGS = {"C", "C++", "Go", "Rust", "Java", "JavaScript", "TypeScript"}
MIN_INTEROP_DENSITY = 0.15
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
ANCHOR_KEYWORDS: dict[str, list[str]] = {
    **INTEROP_KEYWORDS,
    "python_cext": [
        "PyInit_",
        "PyArg_ParseTuple",
        "Py_BuildValue",
        "PyObject_GetIter",
        "PyIter_Next",
        "Py_DECREF",
        "PyErr_SetString",
        "PyErr_Occurred",
    ],
    "ruby_cext": ["Init_", "rb_define_method", "rb_intern"],
}


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in sorted(ranges):
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _parse_patch_ranges(patch: str | None) -> list[tuple[int, int]]:
    if not patch:
        return []
    ranges: list[tuple[int, int]] = []
    new_line = 0
    current_start: int | None = None
    current_end: int | None = None
    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            if current_start is not None and current_end is not None:
                ranges.append((current_start, current_end))
            current_start = None
            current_end = None
            match = HUNK_RE.match(raw_line)
            if not match:
                continue
            new_line = int(match.group(1))
            continue
        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue
        if raw_line.startswith("+"):
            if current_start is None:
                current_start = new_line
            current_end = new_line
            new_line += 1
            continue
        if current_start is not None and current_end is not None:
            ranges.append((current_start, current_end))
            current_start = None
            current_end = None
        if not raw_line.startswith("-"):
            new_line += 1
    if current_start is not None and current_end is not None:
        ranges.append((current_start, current_end))
    return _merge_ranges(ranges)


def _parse_keyword_anchor_ranges(
    patch: str | None,
    interop_type: str,
) -> list[tuple[int, int]]:
    if not patch:
        return []

    anchors: list[tuple[int, int]] = []
    current_new_line = 0
    keywords = [
        token.lower()
        for token in ANCHOR_KEYWORDS.get(interop_type, INTEROP_KEYWORDS.get(interop_type, []))
    ]
    for raw_line in patch.splitlines():
        header = HUNK_RE.match(raw_line)
        if header:
            current_new_line = int(header.group(1))
            continue
        if not raw_line:
            continue
        prefix = raw_line[0]
        if prefix == "-":
            continue
        if prefix not in {"+", " "}:
            continue
        content = raw_line[1:].lower()
        stripped = content.strip()
        if stripped == "{" or (stripped.endswith("{") and "(" in stripped and ")" in stripped):
            current_new_line += 1
            continue
        if any(token in content for token in keywords):
            anchors.append((current_new_line, current_new_line))
        current_new_line += 1
    return _merge_ranges(anchors)


def _keyword_hits(text: str, interop_type: str) -> int:
    lowered = text.lower()
    return sum(1 for token in INTEROP_KEYWORDS.get(interop_type, []) if token.lower() in lowered)


def _line_keyword_density(lines: list[str], interop_type: str) -> float:
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return 0.0
    hit_lines = 0
    keywords = [token.lower() for token in INTEROP_KEYWORDS.get(interop_type, [])]
    for line in non_empty:
        lowered = line.lower()
        if any(token in lowered for token in keywords):
            hit_lines += 1
    return hit_lines / len(non_empty)


def _candidate_score(detail: dict[str, Any], interop_type: str) -> int:
    pair = INTEROP_LANG_PAIRS.get(interop_type, ("", ""))
    lang = detail.get("lang") or ""
    keyword_hits = _keyword_hits(detail.get("patch") or "", interop_type)
    if keyword_hits <= 0:
        return -1000
    score = 0
    if lang == pair[0]:
        score += 20
    if lang == pair[1]:
        score += 10
    score += keyword_hits * 100
    score += int(detail.get("additions", 0)) + int(detail.get("deletions", 0))
    if detail.get("status") == "modified":
        score += 5
    if detail.get("is_test"):
        score -= 1000
    return score


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _brace_blocks(lines: list[str]) -> list[tuple[int, int]]:
    stack: list[int] = []
    blocks: list[tuple[int, int]] = []
    for idx, line in enumerate(lines, start=1):
        opens = line.count("{")
        closes = line.count("}")
        for _ in range(opens):
            stack.append(idx)
        for _ in range(closes):
            if stack:
                blocks.append((stack.pop(), idx))
    return sorted(blocks, key=lambda item: (item[1] - item[0], item[0]))


def _expand_range(lines: list[str], start: int, end: int, lang: str, attempt: int) -> tuple[int, int]:
    start = max(1, start)
    end = min(len(lines), end)
    if attempt == 0:
        return start, end

    if lang in BLOCK_LANGS:
        for block_start, block_end in _brace_blocks(lines):
            if block_start <= start <= end <= block_end:
                if attempt == 1:
                    return block_start, block_end
                return max(1, block_start - 2), min(len(lines), block_end + 2)

    if lang == "Python":
        indent = len(_leading_ws(lines[start - 1])) if start - 1 < len(lines) else 0
        block_start = start
        while block_start > 1:
            current = lines[block_start - 2]
            if current.rstrip().endswith(":") and len(_leading_ws(current)) < indent:
                break
            if current.strip() == "":
                break
            block_start -= 1
        block_end = end
        while block_end < len(lines):
            current = lines[block_end]
            if current.strip() and len(_leading_ws(current)) <= indent:
                break
            block_end += 1
        if attempt == 1:
            return block_start, block_end
        return max(1, block_start - 2), min(len(lines), block_end + 2)

    padding = 3 if attempt == 1 else 8
    return max(1, start - padding), min(len(lines), end + padding)


def _replace_lines(
    lines: list[str],
    start: int,
    end: int,
    replacement_lines: list[str],
) -> str:
    return "\n".join(lines[: start - 1] + replacement_lines + lines[end:])


def _build_masked_code(lines: list[str], start: int, end: int) -> str:
    indent = _leading_ws(lines[start - 1]) if start - 1 < len(lines) else ""
    return _replace_lines(lines, start, end, [f"{indent}<MASK>"])


def _guess_c_stub(context_lines: list[str]) -> str:
    signature = "\n".join(context_lines)
    signature_head = signature.split("{", 1)[0]
    lowered = signature_head.lower()
    if re.search(r"\b(?:static\s+)?int\s+[A-Za-z_]\w*\s*\(", signature_head):
        return 'PyErr_SetString(PyExc_RuntimeError, "MASK"); return -1;'
    if re.search(r"\bvoid\b", signature_head):
        return 'PyErr_SetString(PyExc_RuntimeError, "MASK"); return;'
    if re.search(r"\b(bool|_Bool)\b", signature_head):
        return 'PyErr_SetString(PyExc_RuntimeError, "MASK"); return false;'
    if "pyobject" in lowered or re.search(r"\b[A-Za-z_]\w*\s*\*\s*[A-Za-z_]\w*\s*\(", signature_head):
        return 'PyErr_SetString(PyExc_RuntimeError, "MASK"); return NULL;'
    return 'PyErr_SetString(PyExc_RuntimeError, "MASK"); return -1;'


def _build_validation_lines(
    *,
    lang: str,
    original_lines: list[str],
    start: int,
    end: int,
) -> list[str]:
    indent = _leading_ws(original_lines[start - 1]) if start - 1 < len(original_lines) else ""
    if lang == "Python":
        return [f'{indent}raise NotImplementedError("MASK")']
    if lang == "Ruby":
        return [f'{indent}raise NotImplementedError, "MASK"']
    if lang == "Lua":
        return [f'{indent}error("MASK")']
    if lang == "Go":
        return [f'{indent}panic("MASK")']
    if lang == "Rust":
        return [f'{indent}panic!("MASK");']
    if lang in {"JavaScript", "TypeScript", "Java"}:
        return [f'{indent}throw new Error("MASK");']
    if lang in {"C", "C++"}:
        stub = _guess_c_stub(original_lines[max(0, start - 20) : start - 1])
        return [f"{indent}{stub}"]
    return [f"{indent}/* MASK */"]


def _difficulty(mask_ranges: list[tuple[int, int]], ground_truth: str) -> str:
    line_count = sum(end - start + 1 for start, end in mask_ranges)
    lowered = ground_truth.lower()
    if line_count > 30 or any(token in lowered for token in ("malloc", "free", "unsafe", "callback", "error")):
        return "hard"
    if line_count > 10 or any(token in lowered for token in ("cast", "convert", "callback", "iter")):
        return "medium"
    return "easy"


_compute_difficulty = _difficulty
_line_keyword_ratio = _line_keyword_density


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    head = max_chars // 2
    tail = max_chars - head
    return f"{content[:head]}\n...<TRUNCATED>...\n{content[-tail:]}"


def _choose_context_paths(
    *,
    target_path: str,
    diff_files: list[dict[str, Any]],
    tree: list[str],
) -> list[str]:
    context_paths: list[str] = []
    target_dir = str(Path(target_path).parent)

    def _add(path: str) -> None:
        if path == target_path or path in context_paths:
            return
        context_paths.append(path)

    for path in sorted(tree):
        if target_dir == ".":
            break
        if Path(path).parent.as_posix() == target_dir and Path(path).suffix in {".h", ".hpp", ".pxd", ".pyi"}:
            _add(path)
            if len(context_paths) >= 2:
                break

    for detail in diff_files:
        path = detail["path"]
        if detail.get("is_test"):
            _add(path)

    for detail in diff_files:
        path = detail["path"]
        if not detail.get("is_test"):
            _add(path)

    return context_paths[:6]


def _build_attempt_ranges(
    *,
    lines: list[str],
    patch: str | None,
    host_lang: str,
    interop_type: str,
) -> list[tuple[int, int]]:
    patch_ranges = _parse_patch_ranges(patch)
    if not patch_ranges:
        return []
    seed_ranges = _parse_keyword_anchor_ranges(patch, interop_type) or patch_ranges
    attempts: list[tuple[int, int]] = []
    for seed_start, seed_end in seed_ranges:
        for attempt in range(3):
            expanded = _expand_range(lines, seed_start, seed_end, host_lang, attempt)
            if expanded not in attempts:
                attempts.append(expanded)
    return attempts


async def construct_task(state: dict[str, Any]) -> dict[str, Any]:
    pr = state["pr"]
    env_spec = state["env_spec"]
    image_tag = state.get("image_tag")
    baseline = state.get("baseline_test_result") or {}
    interop_type = pr["interop_type"]

    if not image_tag or not env_spec:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="baseline_unavailable",
                    message="Stage 3 requires a validated image_tag and env_spec.",
                )
            ],
        }

    if not baseline.get("compile_success") or int(baseline.get("failed", 0)) > 0:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="baseline_unavailable",
                    message="construct_task requires a passing baseline_test_result.",
                )
            ],
        }

    client = GitHubClient(
        get_github_tokens_from_env(),
        cache_db=state["run_config"].get("db_path", "benchmark_runs.db"),
    )
    file_details = client.get_pr_file_details(pr["repo"], pr["pr_id"])
    if not file_details:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="patch_unavailable",
                    message="PR patch details were unavailable from GitHub.",
                )
            ],
        }

    candidates = [
        detail
        for detail in file_details
        if not detail.get("is_test")
        and detail.get("status") != "removed"
        and detail.get("patch")
    ]
    if not candidates:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="patch_unavailable",
                    message="No non-test file carried usable patch hunks.",
                )
            ],
        }

    target_detail = max(candidates, key=lambda item: _candidate_score(item, interop_type))
    if _candidate_score(target_detail, interop_type) <= 0:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="no_interop_signal",
                    message="No strong interop signal was found in live patch data.",
                )
            ],
        }

    target_path = target_detail["path"]
    head_content = client.get_file_content(pr["repo"], pr["head_sha"], target_path)
    if not head_content:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="target_file_missing",
                    message=f"Unable to load target file from head_sha: {target_path}",
                )
            ],
        }

    host_lang = target_detail.get("lang") or "Other"
    primary_lang, secondary_lang = INTEROP_LANG_PAIRS.get(interop_type, (host_lang, "Other"))
    target_lang = secondary_lang if host_lang == primary_lang else primary_lang

    lines = head_content.splitlines()
    attempt_ranges = _build_attempt_ranges(
        lines=lines,
        patch=target_detail.get("patch"),
        host_lang=host_lang,
        interop_type=interop_type,
    )
    if not attempt_ranges:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="patch_unavailable",
                    message=f"Unable to derive hunk ranges for {target_path}",
                )
            ],
        }

    baseline_passed = int(baseline.get("passed", 0))
    max_docker = state["run_config"].get("max_concurrent_docker", 4)
    patch_keyword_hits = _keyword_hits(target_detail.get("patch") or "", interop_type)

    chosen_range: tuple[int, int] | None = None
    chosen_masked_code: str | None = None
    for start, end in attempt_ranges:
        original_slice = lines[start - 1 : end]
        density = _line_keyword_ratio(original_slice, interop_type)
        if (
            density < MIN_INTEROP_DENSITY
            and _keyword_hits("\n".join(original_slice), interop_type) == 0
            and patch_keyword_hits == 0
        ):
            if (start, end) == attempt_ranges[-1]:
                return {
                    "task": None,
                    "errors": [
                        make_error(
                            pr,
                            stage="construct_task",
                            reason="mask_not_interop_code",
                            message=f"Selected range in {target_path} does not look like glue code.",
                        )
                    ],
                }
            continue

        status, masked_result = await _evaluate_mask_attempt(
            image_tag=image_tag,
            target_file_path=f"/app/{target_path}",
            file_content=_replace_lines(
                lines,
                start,
                end,
                _build_validation_lines(
                    lang=host_lang,
                    original_lines=lines,
                    start=start,
                    end=end,
                ),
            ),
            host_lang=host_lang,
            env_spec=env_spec,
            baseline_passed=baseline_passed,
            max_concurrent_docker=max_docker,
            mode="mask",
        )
        if status == "compile_fail":
            if (start, end) == attempt_ranges[-1]:
                return {
                    "task": None,
                    "errors": [
                        make_error(
                            pr,
                            stage="construct_task",
                            reason="mask_breaks_compilation",
                            message=masked_result["stdout_tail"],
                        )
                    ],
                }
            continue
        if status == "ineffective":
            if (start, end) == attempt_ranges[-1]:
                return {
                    "task": None,
                    "errors": [
                        make_error(
                            pr,
                            stage="construct_task",
                            reason="mask_ineffective",
                            message="Masked candidate did not reduce baseline test pass count.",
                        )
                    ],
                }
            continue
        if status == "ground_truth_invalid":
            return {
                "task": None,
                "errors": [
                    make_error(
                        pr,
                        stage="construct_task",
                        reason="ground_truth_invalid",
                        message=masked_result["stdout_tail"],
                    )
                ],
            }

        chosen_range = (start, end)
        chosen_masked_code = _build_masked_code(lines, start, end)
        break

    if chosen_range is None or chosen_masked_code is None:
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="mask_ineffective",
                    message="Failed to find a valid masked range after 3 attempts.",
                )
            ],
        }

    start, end = chosen_range
    ground_truth = "\n".join(lines[start - 1 : end])
    restore_status, restored_result = await _evaluate_mask_attempt(
        image_tag=image_tag,
        target_file_path=f"/app/{target_path}",
        file_content=head_content,
        host_lang=host_lang,
        env_spec=env_spec,
        baseline_passed=baseline_passed,
        max_concurrent_docker=max_docker,
        mode="ground_truth",
    )
    if restore_status != "valid":
        return {
            "task": None,
            "errors": [
                make_error(
                    pr,
                    stage="construct_task",
                    reason="ground_truth_invalid",
                    message=restored_result["stdout_tail"],
                )
            ],
        }

    tree = client.get_repo_tree(pr["repo"], pr["head_sha"])
    context_files: dict[str, str] = {}
    total_chars = 0
    for path in _choose_context_paths(target_path=target_path, diff_files=file_details, tree=tree):
        content = client.get_file_content(pr["repo"], pr["head_sha"], path)
        if not content:
            continue
        content = _truncate(content, 6000)
        remaining = 24000 - total_chars
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = _truncate(content, remaining)
        context_files[path] = content
        total_chars += len(content)

    task = {
        "task_id": f"{interop_type}-{pr['repo'].replace('/', '-')}-pr{pr['pr_id']}-001",
        "strategy": state["run_config"].get("task_strategy", "completion"),
        "masked_code": chosen_masked_code,
        "context_files": context_files,
        "ground_truth": ground_truth,
        "target_file_path": f"/app/{target_path}",
        "mask_ranges": [chosen_range],
        "difficulty": _difficulty([chosen_range], ground_truth),
        "host_lang": host_lang,
        "target_lang": target_lang,
    }
    return {"task": task}


async def _evaluate_mask_attempt(
    *,
    image_tag: str,
    target_file_path: str,
    file_content: str,
    host_lang: str,
    env_spec: dict[str, Any],
    baseline_passed: int,
    max_concurrent_docker: int,
    mode: str = "mask",
) -> tuple[str, dict[str, Any]]:
    masked_result = await run_file_in_container(
        image_tag=image_tag,
        target_file_path=target_file_path,
        file_content=file_content,
        host_lang=host_lang,
        env_spec=env_spec,
        max_concurrent_docker=max_concurrent_docker,
    )
    if not masked_result["compile_success"]:
        return "compile_fail", masked_result
    if mode == "mask":
        if int(masked_result.get("passed", 0)) >= baseline_passed:
            return "ineffective", masked_result
    elif int(masked_result.get("passed", -1)) != baseline_passed:
        return "ground_truth_invalid", masked_result
    return "valid", masked_result
