from __future__ import annotations

import re

from parsers.base import BaseParser


class GenericParser(BaseParser):
    _PATTERNS = (
        re.compile(r"(\d+)\s+passed[,;]?\s+(\d+)\s+failed", re.IGNORECASE),
        re.compile(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+)", re.IGNORECASE),
        re.compile(r"(\d+)\s+tests?,\s*(\d+)\s+failures?", re.IGNORECASE),
        re.compile(r"OK\s*\((\d+)\s+tests?\)", re.IGNORECASE),
        re.compile(r"FAILED\s*\((\d+)\s+errors?,\s*(\d+)\s+failures?\)", re.IGNORECASE),
    )

    def _parse(self, stdout: str, exit_code: int):
        passed = failed = errors = total = -1

        for idx, pattern in enumerate(self._PATTERNS, start=1):
            matches = pattern.findall(stdout)
            if not matches:
                continue

            last = matches[-1]
            if idx == 1:
                passed = int(last[0])
                failed = int(last[1])
                errors = 0
                total = passed + failed
            elif idx == 2:
                total = int(last[0])
                failed = int(last[1])
                errors = 0
                passed = max(total - failed, 0)
            elif idx == 3:
                total = int(last[0])
                failed = int(last[1])
                errors = 0
                passed = max(total - failed, 0)
            elif idx == 4:
                total = int(last[0])
                passed = total
                failed = 0
                errors = 0
            elif idx == 5:
                errors = int(last[0])
                failed = int(last[1])
                passed = 0
                total = errors + failed

        lowered = stdout.lower()
        compile_success = exit_code == 0
        if any(
            token in lowered
            for token in ("error:", "undefined reference", "cannot find", "fatal error")
        ):
            compile_success = False

        return self._result(
            passed=passed,
            failed=failed,
            errors=errors,
            total=total,
            compile_success=compile_success,
            exit_code=exit_code,
            stdout=stdout,
        )
