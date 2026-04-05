from __future__ import annotations

import json

from parsers.base import BaseParser


class GoParser(BaseParser):
    def _parse(self, stdout: str, exit_code: int):
        lowered = stdout.lower()
        compile_success = "[build failed]" not in lowered and "build failed" not in lowered

        if not stdout.strip() and exit_code != 0:
            compile_success = False

        if not compile_success:
            return self._result(
                passed=0,
                failed=0,
                errors=0,
                total=0,
                compile_success=False,
                exit_code=exit_code,
                stdout=stdout,
            )

        passed = failed = total = 0
        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = event.get("Action")
            test_name = event.get("Test")
            if action == "run" and test_name:
                total += 1
            elif action == "pass" and test_name:
                passed += 1
            elif action == "fail" and test_name:
                failed += 1

        return self._result(
            passed=passed,
            failed=failed,
            errors=0,
            total=total,
            compile_success=True,
            exit_code=exit_code,
            stdout=stdout,
        )
