import pytest

from nodes import compile_verify as compile_verify_module


@pytest.mark.asyncio
async def test_docker_exec_exports_go_env_and_pkg_config(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_command(cmd: list[str], timeout: int):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return 0, "ok"

    monkeypatch.setattr(compile_verify_module, "_run_command", fake_run_command)

    await compile_verify_module._docker_exec("container-123", "go test ./...")

    assert captured["timeout"] == 600
    assert captured["cmd"][:5] == ["docker", "exec", "container-123", "sh", "-lc"]

    wrapped = captured["cmd"][5]
    assert 'export GOROOT="${GOROOT:-/usr/local/go}";' in wrapped
    assert 'export GOPATH="${GOPATH:-/go}";' in wrapped
    assert 'export PATH="${GOROOT}/bin:${GOPATH}/bin:${PATH}";' in wrapped
    assert "export PKG_CONFIG_PATH=/app/static-build/install/lib/pkgconfig:${PKG_CONFIG_PATH};" in wrapped
    assert wrapped.endswith("go test ./...")


@pytest.mark.asyncio
async def test_docker_exec_preserves_original_command(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_command(cmd: list[str], timeout: int):
        captured["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(compile_verify_module, "_run_command", fake_run_command)

    original_command = "python3 -m pytest -q"
    await compile_verify_module._docker_exec("container-456", original_command)

    wrapped = captured["cmd"][5]
    assert wrapped.endswith(original_command)
