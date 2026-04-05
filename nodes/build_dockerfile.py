from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Template

from nodes.stage2_utils import make_error, make_image_tag


def build_dockerfile(state: dict[str, Any]) -> dict[str, Any]:
    pr = state["pr"]
    env_spec = state["env_spec"]
    if env_spec["source"] == "failed":
        return {"build_status": "failed"}

    image_tag = make_image_tag(pr)
    docker_dir = Path(tempfile.gettempdir()) / "benchmark" / image_tag
    docker_dir.mkdir(parents=True, exist_ok=True)
    dockerfile_path = docker_dir / "Dockerfile"

    try:
        if env_spec["source"] == "repo_dockerfile":
            dockerfile_content = env_spec["dockerfile_content"] or ""
        else:
            template_path = (
                Path(__file__).resolve().parent.parent
                / "dockerfiles"
                / "templates"
                / f"{pr['interop_type']}.dockerfile.j2"
            )
            if not template_path.exists():
                raise FileNotFoundError(str(template_path))
            template = Template(template_path.read_text(encoding="utf-8"))
            dockerfile_content = template.render(
                base_image=env_spec["base_image"],
                system_deps=env_spec["system_deps"],
                clone_url=pr["clone_url"],
                head_sha=pr["head_sha"],
                build_cmds=env_spec["build_cmds"],
                test_cmds=env_spec["test_cmds"],
            )

        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
    except Exception as exc:
        return {
            "build_status": "failed",
            "errors": [
                make_error(
                    pr,
                    stage="build_dockerfile",
                    reason="dockerfile_render_failed",
                    message=str(exc),
                )
            ],
        }

    return {
        "dockerfile_path": str(dockerfile_path),
        "dockerfile_content": dockerfile_content,
        "image_tag": image_tag,
    }
