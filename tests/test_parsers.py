import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parsers import get_parser


FIXTURES = Path(__file__).parent / "fixtures"


def test_go_parser_counts_streaming_events():
    stdout = (FIXTURES / "sample_go_test_output.txt").read_text(encoding="utf-8")
    result = get_parser("go_test").parse(stdout, 1)

    assert result["compile_success"] is True
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["total"] == 2


def test_go_parser_marks_build_failures_as_compile_failures():
    stdout = "github.com/demo [build failed]\nFAIL github.com/demo [build failed]\n"
    result = get_parser("go_test").parse(stdout, 1)

    assert result["compile_success"] is False
    assert result["total"] == 0


def test_pytest_parser_reads_summary_line():
    stdout = (FIXTURES / "sample_pytest_output.txt").read_text(encoding="utf-8")
    result = get_parser("pytest").parse(stdout, 1)

    assert result["compile_success"] is True
    assert result["passed"] == 2
    assert result["failed"] == 1
    assert result["errors"] == 0
    assert result["total"] == 3


def test_pytest_parser_detects_import_errors_as_compile_failures():
    stdout = "ImportError: cannot import name 'x'\n"
    result = get_parser("pytest").parse(stdout, 1)

    assert result["compile_success"] is False
    assert result["total"] == 0


def test_generic_parser_is_used_for_unknown_frameworks():
    stdout = "Tests run: 4, Failures: 1\n"
    result = get_parser("unknown-framework").parse(stdout, 1)

    assert result["passed"] == 3
    assert result["failed"] == 1
    assert result["total"] == 4
