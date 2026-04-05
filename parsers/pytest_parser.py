from __future__ import annotations

import re

from parsers.base import BaseParser


class PytestParser(BaseParser):
    def _parse(self, stdout: str, exit_code: int):
        lowered = stdout.lower()
        compile_success = not any(
            token in lowered
            for token in ("importerror", "modulenotfounderror", "syntaxerror")
        )

        if "no tests ran" in lowered:
            return self._result(
                passed=0,
                failed=0,
                errors=0,
                total=0,
                compile_success=compile_success,
                exit_code=exit_code,
                stdout=stdout,
            )

        passed_match = re.findall(r"(\d+)\s+passed", stdout, re.IGNORECASE)
        failed_match = re.findall(r"(\d+)\s+failed", stdout, re.IGNORECASE)
        errors_match = re.findall(r"(\d+)\s+error[s]?\b", stdout, re.IGNORECASE)

        passed = int(passed_match[-1]) if passed_match else 0
        failed = int(failed_match[-1]) if failed_match else 0
        errors = int(errors_match[-1]) if errors_match else 0
        total = passed + failed + errors

        return self._result(
            passed=passed,
            failed=failed,
            errors=errors,
            total=total,
            compile_success=compile_success,
            exit_code=exit_code,
            stdout=stdout,
        )
