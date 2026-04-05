from __future__ import annotations

from parsers.base import BaseParser
from parsers.generic_parser import GenericParser
from parsers.go_parser import GoParser
from parsers.pytest_parser import PytestParser


_GENERIC = GenericParser()
_PARSERS: dict[str, BaseParser] = {
    "go_test": GoParser(),
    "pytest": PytestParser(),
    "generic": _GENERIC,
    "junit": _GENERIC,
    "cargo": _GENERIC,
    "jest": _GENERIC,
}


def get_parser(test_framework: str | None) -> BaseParser:
    if not test_framework:
        return _GENERIC
    return _PARSERS.get(test_framework, _GENERIC)


__all__ = [
    "BaseParser",
    "GenericParser",
    "GoParser",
    "PytestParser",
    "get_parser",
]
