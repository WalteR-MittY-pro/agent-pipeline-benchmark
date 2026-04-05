from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from github_client import GitHubClient, get_github_tokens_from_env
from nodes.stage2_utils import make_error

DOCKERFILE_PATHS = ("Dockerfile", "docker/Dockerfile", ".docker/Dockerfile")
CONFIG_FILES = (
    "go.mod",
    "Cargo.toml",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "package.json",
    "Gemfile",
    "Rakefile",
    "Makefile",
    "README.md",
)

_DOCKERFILE_FROM_RE = re.compile(
    r"^FROM(?:\s+--platform=\S+)?\s+(?P<base>\S+)(?:\s+AS\s+(?P<alias>\S+))?\s*$",
    re.IGNORECASE,
)
_DOCKERFILE_COPY_FROM_RE = re.compile(r"--from=(?P<source>[^\s]+)")


def patch_cmd_to_test(dockerfile_content: str, test_cmds: list[str]) -> str:
    if not test_cmds:
        return dockerfile_content

    lines = dockerfile_content.splitlines()
    replacement = f'CMD ["sh", "-lc", "{test_cmds[0]}"]'
    for idx in range(len(lines) - 1, -1, -1):
        stripped = lines[idx].strip().upper()
        if stripped.startswith("CMD ") or stripped.startswith("ENTRYPOINT "):
            lines[idx] = replacement
            return "\n".join(lines) + ("\n" if dockerfile_content.endswith("\n") else "")

    suffix = "" if dockerfile_content.endswith("\n") or not dockerfile_content else "\n"
    return f"{dockerfile_content}{suffix}{replacement}\n"


def extract_apt_installs(workflow_content: str) -> list[str]:
    deps: list[str] = []
    for match in re.findall(r"apt-get install(?: -y)? ([^\n\r]+)", workflow_content):
        for token in match.replace("\\", " ").split():
            cleaned = token.strip()
            if cleaned and not cleaned.startswith("-") and cleaned not in deps:
                deps.append(cleaned)
    return deps


def _is_dynamic_docker_ref(ref: str) -> bool:
    return "$" in ref


def _looks_like_external_stage_alias(ref: str) -> bool:
    if not ref or ref.isdigit() or ref == "scratch":
        return False
    if _is_dynamic_docker_ref(ref):
        return False
    if any(token in ref for token in ("/", ":", "@")):
        return False

    # Standalone repo Dockerfiles sometimes assume upstream build stages like
    # "php-base" or "golang-base" that are not declared in the file itself.
    return ref.endswith(("-base", "-builder", "-runtime", "-common", "-deps"))


def _dockerfile_has_unresolved_stage_aliases(content: str) -> bool:
    declared_stages: set[str] = set()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        from_match = _DOCKERFILE_FROM_RE.match(line)
        if from_match:
            base_ref = from_match.group("base") or ""
            if (
                _looks_like_external_stage_alias(base_ref)
                and base_ref not in declared_stages
            ):
                return True

            alias = from_match.group("alias")
            if alias:
                declared_stages.add(alias)
            continue

        if not line.upper().startswith("COPY "):
            continue

        for match in _DOCKERFILE_COPY_FROM_RE.finditer(line):
            source_ref = match.group("source") or ""
            if source_ref.isdigit() or source_ref in declared_stages:
                continue
            if _looks_like_external_stage_alias(source_ref):
                return True

    return False


def extract_run_steps(workflow_content: str, kind: str) -> list[str]:
    relevant_patterns = {
        "build": (
            r"\bgo build\b",
            r"\bgo vet\b",
            r"\bgo get\b",
            r"\bcargo build\b",
            r"\bcargo test --no-run\b",
            r"\bpython(?:3)?\b.*\bbuild\.sh test\b",
            r"\bpython(?:3)?\b.*download-.*\.py\b",
            r"\bpython(?:3)?\b.*setup\.py\b",
            r"\bpip(?:3)? install\b",
            r"\bnpm install\b",
            r"\byarn install\b",
            r"\bbazelisk build\b",
            r"\bmake\s+build",
            r"\b./gradlew testClasses\b",
            r"\bmvn\b.*package\b",
            r"\brustup\b",
            r"\bcargo install wasm-pack\b",
        ),
        "test": (
            r"\bgo test\b",
            r"\bcargo test\b",
            r"\bpytest\b",
            r"\bpython(?:3)? -m pytest\b",
            r"\bbazelisk test\b",
            r"\bwasm-pack test\b",
            r"\bbuild\.sh test\b",
            r"\b./gradlew test\b",
            r"\bmvn\b.*test\b",
            r"\bnpx jest\b",
            r"\bnpm test\b",
            r"\bmake test\b",
            r"\bmake\s+TEST_ARGS=.*\btest",
        ),
    }[kind]
    support_patterns = (
        r"^export\b",
        r"^[A-Z0-9_]+=.*",
        r"^sudo apt(?:-get)?\b",
        r"^apt-get\b",
        r"^python3?\b",
        r"^pip3?\b",
        r"^go get\b",
        r"^cargo\b",
        r"^npm\b",
        r"^npx\b",
        r"^yarn\b",
        r"^bazelisk\b",
        r"^make\b",
        r"^./",
        r"^mvn\b",
        r"^./gradlew\b",
        r"^rustup\b",
        r"^firefox --version$",
        r"^git submodule update --init\b",
    )
    exclude_patterns = (
        r"^sudo apt(?:-get)? install\b.*\btinyproxy\b",
        r"^export OPENSSL_PREFIX=.*brew --prefix\b",
        r"^brew\b",
        r"^git config\b",
        r"^git push\b",
        r"^git fetch\b",
        r"^git diff\b",
        r"^gh pr create\b",
        r"^echo\b",
        r"^ls\b",
    )

    def is_relevant(line: str) -> bool:
        lowered = line.lower()
        return any(re.search(pattern, lowered) for pattern in relevant_patterns)

    def is_support(line: str) -> bool:
        return any(re.search(pattern, line) for pattern in support_patterns)

    def is_excluded(line: str) -> bool:
        return any(re.search(pattern, line) for pattern in exclude_patterns)

    def prune_block(lines: list[str]) -> str | None:
        cleaned = [line.strip() for line in lines if line.strip()]
        if not cleaned:
            return None
        if not any(is_relevant(line) for line in cleaned):
            return None

        kept: list[str] = []
        seen_relevant = False
        for line in cleaned:
            if is_excluded(line):
                continue
            if is_relevant(line):
                kept.append(line)
                seen_relevant = True
                continue
            if not seen_relevant and is_support(line):
                kept.append(line)

        if not kept:
            return None
        return "\n".join(kept)

    commands: list[str] = []
    current_run: list[str] = []
    in_run_block = False

    for raw_line in workflow_content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if re.match(r"^\s*-?\s*run:\s*\|?\s*$", line):
            in_run_block = True
            current_run = []
            continue
        if in_run_block:
            if stripped.startswith("- ") or re.match(r"^\s*\w[\w-]*:", line):
                command = prune_block(current_run)
                if command:
                    commands.append(command)
                current_run = []
                in_run_block = False
            else:
                current_run.append(stripped)
                continue

        if "run:" in line:
            command = line.split("run:", 1)[1].strip()
            pruned = prune_block([command])
            if pruned:
                commands.append(pruned)

    if in_run_block and current_run:
        command = prune_block(current_run)
        if command:
            commands.append(command)

    deduped: list[str] = []
    for command in commands:
        if command not in deduped:
            deduped.append(command)
    return deduped


def detect_test_framework(content: str, interop_type: str, tree: list[str] | None = None) -> str:
    tree = tree or []
    lowered = content.lower()
    if interop_type == "cgo":
        return "go_test"
    if interop_type == "rust_ffi":
        return "cargo"
    if interop_type in {"python_cext", "cffi", "ctypes"}:
        return "pytest" if "pytest" in lowered or any("test_" in p for p in tree) else "generic"
    if interop_type == "jni":
        return "junit"
    if interop_type in {"node_napi", "v8_cpp", "wasm"}:
        return "jest" if "jest" in lowered or any(p.endswith((".test.ts", ".test.js")) for p in tree) else "generic"
    if interop_type == "ruby_cext":
        return "generic"
    return "generic"


def _extract_base_image_from_dockerfile(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        match = _DOCKERFILE_FROM_RE.match(stripped)
        if match:
            return match.group("base")
    return None


def _extract_go_version(content: str) -> tuple[int, int] | None:
    match = re.search(r"(?m)^\s*go\s+(\d+)\.(\d+)(?:\.\d+)?\s*$", content)
    if not match:
        return None

    return int(match.group(1)), int(match.group(2))


def _guess_base_image(
    interop_type: str,
    tree: list[str],
    content: str,
    project_files: dict[str, str] | None = None,
) -> str:
    lowered = content.lower()
    project_files = project_files or {}
    if interop_type == "wasm":
        return "rust:1.88"
    if interop_type == "cgo" or "go.mod" in tree:
        go_mod_content = project_files.get("go.mod", "")
        required_go = _extract_go_version(go_mod_content)
        if required_go is not None:
            major, minor = required_go
            return f"golang:{major}.{minor}"
        return "golang:1.22"
    if interop_type in {"python_cext", "cffi", "ctypes"} or "pyproject.toml" in tree:
        return "python:3.11"
    if interop_type == "rust_ffi" or "Cargo.toml" in tree:
        return "rust:1.78"
    if interop_type == "ruby_cext" or "Gemfile" in tree:
        return "ruby:3.3"
    if interop_type == "jni" or "pom.xml" in tree or "build.gradle" in tree or "build.gradle.kts" in tree:
        return "maven:3.9-eclipse-temurin-17"
    if interop_type in {"wasm", "node_napi", "v8_cpp"} or "package.json" in tree:
        return "node:20"
    if "pytest" in lowered:
        return "python:3.11"
    return "ubuntu:22.04"


def _default_system_deps(interop_type: str) -> list[str]:
    deps = ["git", "ca-certificates"]
    if interop_type in {"cgo", "python_cext", "ruby_cext", "rust_ffi", "jni", "v8_cpp", "lua_c"}:
        deps.extend(["build-essential", "pkg-config"])
    if interop_type == "cgo":
        deps.append("cmake")
    if interop_type in {"python_cext", "cffi", "ctypes"}:
        deps.append("python3-dev")
    if interop_type == "ruby_cext":
        deps.append("ruby-dev")
    if interop_type == "jni":
        deps.append("openjdk-17-jdk")
    return deps


def _normalize_command(command: str) -> str:
    normalized = re.sub(r"(^|\s)python(\s+)", r"\1python3\2", command)
    return normalized


def _augment_system_deps_for_commands(
    system_deps: list[str], build_cmds: list[str], test_cmds: list[str]
) -> list[str]:
    deps = list(system_deps)
    joined = "\n".join(build_cmds + test_cmds)
    if "python3" in joined or "python " in joined:
        for dep in ("python3",):
            if dep not in deps:
                deps.append(dep)
    if "python3 -m pip" in joined or "pip install" in joined:
        for dep in ("python3-pip",):
            if dep not in deps:
                deps.append(dep)
    return deps


def _default_python_bootstrap_cmds(tree: list[str]) -> list[str]:
    cmds = [
        "python3 -m pip install --upgrade pip setuptools wheel pytest",
    ]
    if "requirements.txt" in tree:
        cmds.append("python3 -m pip install -r requirements.txt")
    if "pyproject.toml" in tree:
        cmds.append("python3 -m pip install -e .")
    return cmds


def _discover_python_test_command(tree: list[str]) -> str:
    preferred_targets: list[str] = []
    preferred_dirs: list[str] = []
    for path in tree:
        normalized = path.strip("/")
        lowered = normalized.lower()
        if lowered.endswith("/test.py") or lowered == "test.py":
            preferred_targets.append(normalized)
        elif "/tests/" in lowered or lowered.startswith("tests/") or lowered == "tests":
            preferred_dirs.append("tests")
        elif "/test/" in lowered or lowered.startswith("test/") or lowered == "test":
            preferred_dirs.append("test")
        elif lowered.endswith("_test.py") or lowered.startswith("test_"):
            preferred_targets.append(normalized)

    seen_targets: list[str] = []
    for item in preferred_targets:
        if item not in seen_targets:
            seen_targets.append(item)
    seen: list[str] = []
    for item in preferred_dirs:
        if item not in seen:
            seen.append(item)

    for item in seen_targets:
        return f"PYTHONPATH=/app pytest -q {item}"
    for item in seen:
        if item:
            return f"PYTHONPATH=/app pytest -q {item}"
    return "PYTHONPATH=/app pytest -q"


def _default_build_cmds(interop_type: str, tree: list[str], test_framework: str) -> list[str]:
    if interop_type == "cgo" or "go.mod" in tree:
        return ["go test -run '^$' ./..."]
    if interop_type in {"python_cext", "cffi", "ctypes"}:
        bootstrap_cmds = _default_python_bootstrap_cmds(tree)
        if "setup.py" in tree:
            return bootstrap_cmds + ["python3 -m pip install ."]
        return bootstrap_cmds
    if interop_type == "rust_ffi" or "Cargo.toml" in tree:
        return ["cargo test --no-run"]
    if interop_type == "ruby_cext":
        if "Rakefile" in tree:
            return ["bundle exec rake compile || rake compile"]
        return ["bundle install"]
    if interop_type == "jni":
        if "pom.xml" in tree:
            return ["mvn -q -DskipTests package"]
        if "build.gradle" in tree or "build.gradle.kts" in tree:
            return ["./gradlew testClasses"]
    if interop_type in {"wasm", "node_napi", "v8_cpp"} or "package.json" in tree:
        return ["npm install"]
    if test_framework == "pytest":
        return ["python3 -m pip install -e ."]
    return []


def _default_test_cmds(interop_type: str, tree: list[str], test_framework: str) -> list[str]:
    if interop_type == "cgo" or "go.mod" in tree:
        return ["go test -json ./..."]
    if test_framework == "pytest" or interop_type in {"python_cext", "cffi", "ctypes"}:
        return [_discover_python_test_command(tree)]
    if interop_type == "rust_ffi" or "Cargo.toml" in tree:
        return ["cargo test -- --nocapture"]
    if interop_type == "ruby_cext":
        return ["bundle exec rake test || bundle exec rspec"]
    if interop_type == "jni":
        if "pom.xml" in tree:
            return ["mvn -q test"]
        if "build.gradle" in tree or "build.gradle.kts" in tree:
            return ["./gradlew test"]
    if interop_type in {"wasm", "node_napi", "v8_cpp"} or "package.json" in tree:
        return ["npx jest --json"]
    return []


def _collect_project_content(client: GitHubClient, repo: str, sha: str, tree: list[str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for path in tree:
        if Path(path).name in CONFIG_FILES or path in CONFIG_FILES:
            content = client.get_file_content(repo, sha, path)
            if content:
                selected[path] = content
    return selected


def infer_env(state: dict[str, Any]) -> dict[str, Any]:
    pr = state["pr"]
    run_config = state["run_config"]
    repo = pr["repo"]
    sha = pr["head_sha"]

    tokens = get_github_tokens_from_env()
    client = GitHubClient(tokens, cache_db=run_config.get("db_path", "benchmark_runs.db"))
    tree = client.get_repo_tree(repo, sha)
    project_files = _collect_project_content(client, repo, sha, tree)
    project_blob = "\n\n".join(project_files.values())
    interop_type = pr["interop_type"]

    test_framework = detect_test_framework(project_blob, interop_type, tree)
    default_build_cmds = _default_build_cmds(interop_type, tree, test_framework)
    default_test_cmds = pr.get("test_commands") or _default_test_cmds(interop_type, tree, test_framework)
    default_base_image = _guess_base_image(
        interop_type, tree, project_blob, project_files
    )
    default_build_cmds = [_normalize_command(cmd) for cmd in default_build_cmds]
    default_test_cmds = [_normalize_command(cmd) for cmd in default_test_cmds]

    for dockerfile_path in DOCKERFILE_PATHS:
        content = client.get_file_content(repo, sha, dockerfile_path)
        if not content:
            continue
        if _dockerfile_has_unresolved_stage_aliases(content):
            continue
        patched = patch_cmd_to_test(content, list(default_test_cmds))
        system_deps = _augment_system_deps_for_commands(
            _default_system_deps(interop_type),
            list(default_build_cmds),
            list(default_test_cmds),
        )
        return {
            "env_spec": {
                "source": "repo_dockerfile",
                "base_image": _extract_base_image_from_dockerfile(content) or default_base_image,
                "system_deps": system_deps,
                "build_cmds": list(default_build_cmds),
                "test_cmds": list(default_test_cmds),
                "test_framework": test_framework,
                "dockerfile_content": patched,
            }
        }

    workflow_paths = [
        path
        for path in tree
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    ]
    workflow_contents = [client.get_file_content(repo, sha, path) for path in workflow_paths]
    workflow_contents = [content for content in workflow_contents if content]
    if workflow_contents:
        system_deps: list[str] = []
        build_cmds: list[str] = []
        test_cmds: list[str] = []
        for workflow_content in workflow_contents:
            for dep in extract_apt_installs(workflow_content):
                if dep not in system_deps:
                    system_deps.append(dep)
            for cmd in extract_run_steps(workflow_content, "build"):
                if cmd not in build_cmds:
                    build_cmds.append(_normalize_command(cmd))
            for cmd in extract_run_steps(workflow_content, "test"):
                if cmd not in test_cmds:
                    test_cmds.append(_normalize_command(cmd))

        if test_cmds:
            merged_system_deps = list(_default_system_deps(interop_type))
            for dep in system_deps:
                if dep not in merged_system_deps:
                    merged_system_deps.append(dep)
            system_deps = _augment_system_deps_for_commands(
                merged_system_deps,
                build_cmds or list(default_build_cmds),
                test_cmds,
            )
            return {
                "env_spec": {
                    "source": "github_actions",
                    "base_image": default_base_image,
                    "system_deps": system_deps,
                    "build_cmds": build_cmds or list(default_build_cmds),
                    "test_cmds": test_cmds,
                    "test_framework": test_framework,
                    "dockerfile_content": None,
                }
            }

    if default_test_cmds:
        system_deps = _augment_system_deps_for_commands(
            _default_system_deps(interop_type),
            list(default_build_cmds),
            list(default_test_cmds),
        )
        return {
            "env_spec": {
                "source": "llm",
                "base_image": default_base_image,
                "system_deps": system_deps,
                "build_cmds": list(default_build_cmds),
                "test_cmds": list(default_test_cmds),
                "test_framework": test_framework,
                "dockerfile_content": None,
            }
        }

    return {
        "env_spec": {
            "source": "failed",
            "base_image": default_base_image,
            "system_deps": [],
            "build_cmds": [],
            "test_cmds": [],
            "test_framework": "generic",
            "dockerfile_content": None,
        },
        "build_status": "failed",
        "errors": [
            make_error(
                pr,
                stage="infer_env",
                reason="infer_env_failed",
                message="Failed to infer test/build commands from Dockerfile, workflows, and repository heuristics.",
            )
        ],
    }
