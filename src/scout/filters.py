"""PR filter logic for Scout Agent."""

import json
from pathlib import Path
from typing import NamedTuple

# Load config
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "scout.json"


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_CONFIG = _load_config()


class FileChange(NamedTuple):
    """Represents a changed file in a PR."""

    filename: str
    status: str  # "added", "modified", "deleted"
    additions: int = 0
    deletions: int = 0


class FilterResult(NamedTuple):
    """Result of PR filtering."""

    passed: bool
    total_files: int
    languages_detected: set[str]
    test_files_detected: list[str]
    reason: str


def get_file_extension(filename: str) -> str:
    """Extract file extension including dot (e.g., '.py')."""
    if "." in filename:
        return "." + filename.rsplit(".", 1)[1]
    return ""


def extension_to_language(ext: str) -> str | None:
    """Map file extension to language category name."""
    if not ext:
        return None
    lang_extensions = _CONFIG.get("language_extensions", {})
    for language, extensions in lang_extensions.items():
        if ext in extensions:
            return language
    return None


def detect_languages(files: list[FileChange]) -> set[str]:
    """
    Detect programming languages from file extensions.

    Rules:
    - Only count files with extensions in language_extensions config
    - Ignore extensions in ignore_extensions config
    - Return set of language category names (e.g., {"Python", "Go"})
    """
    languages: set[str] = set()
    ignore_exts: set[str] = set(_CONFIG.get("ignore_extensions", []))

    for file in files:
        ext = get_file_extension(file.filename)
        if not ext:
            continue
        if ext in ignore_exts:
            continue
        lang = extension_to_language(ext)
        if lang:
            languages.add(lang)

    return languages


def detect_test_files(files: list[FileChange]) -> list[str]:
    """
    Detect test files from file names/paths.

    Rules:
    - Check against test_patterns in config
    - Support suffix patterns (e.g., "_test.go")
    - Support prefix patterns (e.g., "test_")
    - Support directory patterns (e.g., "/test/")
    - Return list of matching filenames
    """
    test_patterns: list[str] = _CONFIG.get("test_patterns", [])
    test_files: list[str] = []

    for file in files:
        filename = file.filename
        for pattern in test_patterns:
            if pattern.startswith("*"):
                # Suffix pattern like "*Test.kt"
                if filename.endswith(pattern[1:]):
                    test_files.append(filename)
                    break
            elif pattern.startswith("/"):
                # Directory pattern like "/test/" or "/tests/"
                if pattern in filename:
                    test_files.append(filename)
                    break
            elif pattern.startswith("."):
                # Extension pattern like ".test.ts"
                if filename.endswith(pattern):
                    test_files.append(filename)
                    break
            elif pattern.endswith("_") or pattern.endswith("."):
                # Prefix pattern like "test_" or "_test."
                if filename.startswith(pattern) or filename.endswith(pattern):
                    test_files.append(filename)
                    break
            elif "/" in pattern:
                # Contains path separator - directory pattern
                if pattern in filename:
                    test_files.append(filename)
                    break
            else:
                # Default: check if pattern appears anywhere in filename
                if pattern in filename:
                    test_files.append(filename)
                    break

    return test_files


def filter_pr(files: list[FileChange]) -> FilterResult:
    """
    Apply all 3 rules to filter a PR.

    Returns FilterResult with:
    - passed: True if PR passes all rules
    - total_files: number of changed files
    - languages_detected: set of language categories
    - test_files_detected: list of test file names
    - reason: explanation of pass/fail
    """
    pr_criteria = _CONFIG.get("pr_criteria", {})
    max_files: int = pr_criteria.get("max_files_changed", 10)
    min_languages: int = pr_criteria.get("min_languages", 2)
    require_test: bool = pr_criteria.get("require_test_file", True)

    total_files = len(files)
    languages_detected = detect_languages(files)
    test_files_detected = detect_test_files(files)

    # Rule 1: total_files_changed <= 10
    if total_files > max_files:
        return FilterResult(
            passed=False,
            total_files=total_files,
            languages_detected=languages_detected,
            test_files_detected=test_files_detected,
            reason=f"Rule 1 FAILED: {total_files} files changed (max: {max_files})",
        )

    # Rule 2: >= 2 different programming languages
    if len(languages_detected) < min_languages:
        langs_str = (
            ", ".join(sorted(languages_detected)) if languages_detected else "none"
        )
        return FilterResult(
            passed=False,
            total_files=total_files,
            languages_detected=languages_detected,
            test_files_detected=test_files_detected,
            reason=f"Rule 2 FAILED: {len(languages_detected)} language(s) detected ({langs_str}), need at least {min_languages}",
        )

    # Rule 3: at least 1 test file
    if require_test and len(test_files_detected) < 1:
        return FilterResult(
            passed=False,
            total_files=total_files,
            languages_detected=languages_detected,
            test_files_detected=test_files_detected,
            reason="Rule 3 FAILED: no test files detected",
        )

    # All rules passed
    langs_str = ", ".join(sorted(languages_detected)) if languages_detected else "none"
    test_files_str = ", ".join(test_files_detected) if test_files_detected else "none"
    return FilterResult(
        passed=True,
        total_files=total_files,
        languages_detected=languages_detected,
        test_files_detected=test_files_detected,
        reason=f"Passed all rules: {total_files} files, languages: {langs_str}, test files: {test_files_str}",
    )
