from __future__ import annotations

from abc import ABC, abstractmethod

from state import TestResult


def build_stdout_tail(stdout: str, max_lines: int = 100) -> str:
    lines = (stdout or "").splitlines()
    return "\n".join(lines[-max_lines:])


class BaseParser(ABC):
    def parse(self, stdout: str, exit_code: int) -> TestResult:
        try:
            return self._parse(stdout or "", exit_code)
        except Exception:
            return self._fallback(stdout or "", exit_code)

    @abstractmethod
    def _parse(self, stdout: str, exit_code: int) -> TestResult:
        raise NotImplementedError

    def _fallback(self, stdout: str, exit_code: int) -> TestResult:
        lowered = stdout.lower()
        compile_success = exit_code == 0 and not any(
            token in lowered
            for token in (
                "error:",
                "undefined reference",
                "cannot find",
                "fatal error",
                "syntaxerror",
                "modulenotfounderror",
                "importerror",
            )
        )
        return self._result(
            passed=-1,
            failed=-1,
            errors=-1,
            total=-1,
            compile_success=compile_success,
            exit_code=exit_code,
            stdout=stdout,
        )

    def _result(
        self,
        *,
        passed: int,
        failed: int,
        errors: int,
        total: int,
        compile_success: bool,
        exit_code: int,
        stdout: str,
    ) -> TestResult:
        return {
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": total,
            "compile_success": compile_success,
            "exit_code": exit_code,
            "stdout_tail": build_stdout_tail(stdout),
        }
