import json
import csv
import time
import signal
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from github import Github, Auth
from github.GithubException import RateLimitExceededException
from github.GithubRetry import GithubRetry

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data" / "fetcher"

shutdown_event = threading.Event()


def load_config() -> dict:
    config_path = CONFIG_DIR / "fetcher.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def load_all_tokens() -> list[str]:
    secrets_path = CONFIG_DIR / ".config.json"
    with open(secrets_path, encoding="utf-8") as f:
        secrets = json.load(f)
    return [
        secrets["github"]["PAT1"],
        secrets["github"]["PAT2"],
    ]


def generate_output_filename(star_range: str, ext: str) -> Path:
    range_clean = star_range.replace("..", "_")
    return DATA_DIR / f"multilang_repos_{range_clean}.{ext}"


CONFIG = load_config()
TOKENS = load_all_tokens()


class SharedProgressCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {i: 0 for i in range(len(TOKENS))}
        self._hits = {i: 0 for i in range(len(TOKENS))}
        self._total = 0
        self._scanned_repos: set[str] = set()

    def add_scan(self, token_idx: int, is_hit: bool):
        with self._lock:
            self._counts[token_idx] += 1
            self._total += 1
            if is_hit:
                self._hits[token_idx] += 1

    def is_scanned(self, repo_name: str) -> bool:
        with self._lock:
            return repo_name in self._scanned_repos

    def mark_scanned(self, repo_name: str):
        with self._lock:
            self._scanned_repos.add(repo_name)

    def get_status(self) -> str:
        with self._lock:
            parts = []
            for i in range(len(TOKENS)):
                parts.append(f"PAT{i + 1}:{self._counts[i]}/{self._hits[i]}")
            return f"[{' | '.join(parts)} | Total:{self._total} | Skipped:{len(self._scanned_repos) - self._total}]"


def load_existing_repos() -> set[str]:
    existing: set[str] = set()

    for star_range in CONFIG["star_ranges"]:
        json_path = generate_output_filename(star_range, "json")
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                for repo in json.load(f):
                    existing.add(repo["repo_name"])

    merged_json = DATA_DIR / "multilang_repos_pool.json"
    if merged_json.exists():
        with open(merged_json, encoding="utf-8") as f:
            for repo in json.load(f):
                existing.add(repo["repo_name"])

    return existing


def normalize_language_name(lang: str) -> str | None:
    for category, languages in CONFIG["mainstream_languages"].items():
        if lang in languages:
            return category
    return None


def analyze_repo_languages(repo) -> dict | None:
    try:
        languages_bytes = repo.get_languages()
        if not languages_bytes:
            return None

        total_bytes = sum(languages_bytes.values())
        if total_bytes == 0:
            return None

        mainstream_bytes = {}
        for lang, byte_count in languages_bytes.items():
            normalized = normalize_language_name(lang)
            if normalized:
                mainstream_bytes[normalized] = (
                    mainstream_bytes.get(normalized, 0) + byte_count
                )

        qualified_languages = {}
        for lang_category, byte_count in mainstream_bytes.items():
            ratio = byte_count / total_bytes
            if ratio > CONFIG["language_ratio_threshold"]:
                qualified_languages[lang_category] = round(ratio, 4)

        if len(qualified_languages) >= CONFIG["min_languages_count"]:
            return {
                "repo_name": repo.full_name,
                "url": repo.html_url,
                "stars": repo.stargazers_count,
                "total_code_bytes": total_bytes,
                "qualified_languages": qualified_languages,
                "description": repo.description,
                "star_range": None,
            }
        return None

    except RateLimitExceededException:
        raise
    except Exception as e:
        print(f"  [!] 分析仓库出错: {e}")
        return None


def write_range_output(results: list[dict], star_range: str):
    output_json = generate_output_filename(star_range, "json")
    output_csv = generate_output_filename(star_range, "csv")

    for r in results:
        r["star_range"] = star_range

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "repo_name",
                "stars",
                "total_code_bytes",
                "qualified_languages",
                "url",
                "description",
                "star_range",
            ],
        )
        writer.writeheader()
        for item in results:
            row = item.copy()
            row["qualified_languages"] = str(item["qualified_languages"])
            writer.writerow(row)

    return output_json, output_csv


def merge_all_outputs(star_ranges: list[str]):
    all_results = []
    for star_range in star_ranges:
        json_path = generate_output_filename(star_range, "json")
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                all_results.extend(json.load(f))

    merged_json = DATA_DIR / CONFIG["output"]["json"]
    merged_csv = DATA_DIR / CONFIG["output"]["csv"]

    with open(merged_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=4, ensure_ascii=False)

    with open(merged_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "repo_name",
                "stars",
                "total_code_bytes",
                "qualified_languages",
                "url",
                "description",
                "star_range",
            ],
        )
        writer.writeheader()
        for item in all_results:
            row = item.copy()
            row["qualified_languages"] = str(item["qualified_languages"])
            writer.writerow(row)

    return merged_json, merged_csv, len(all_results)


def scan_star_range(
    star_range: str,
    token: str,
    token_idx: int,
    progress: SharedProgressCounter,
    max_repos: int,
) -> list[dict]:
    results = []

    retry = GithubRetry(total=3, secondary_rate_wait=60)
    g = Github(
        auth=Auth.Token(token),
        retry=retry,
        seconds_between_requests=0.5,
    )

    print(f"[PAT{token_idx + 1}] 开始扫描 star 范围: {star_range}")
    query = f"stars:{star_range}"
    repos = g.search_repositories(query=query, sort="stars", order="desc")

    scanned = 0
    skipped_dup = 0
    for repo in repos:
        if shutdown_event.is_set():
            print(f"[PAT{token_idx + 1}] 收到中断信号，保存已扫描结果...")
            break
        if scanned >= max_repos:
            break

        if progress.is_scanned(repo.full_name):
            skipped_dup += 1
            continue

        progress.mark_scanned(repo.full_name)

        result = analyze_repo_languages(repo)
        is_hit = result is not None
        progress.add_scan(token_idx, is_hit)

        if result:
            results.append(result)
            print(
                f"{progress.get_status()} [命中] {repo.full_name} -> {result['qualified_languages']}"
            )
        else:
            print(f"{progress.get_status()} [跳过] {repo.full_name}")

        scanned += 1

    if results:
        json_path, csv_path = write_range_output(results, star_range)
        print(
            f"[PAT{token_idx + 1}] 范围 {star_range} 完成: {len(results)} 个命中, {skipped_dup} 个重复跳过"
        )
        print(f"  - JSON: {json_path}")
        print(f"  - CSV: {csv_path}")

    return results


def signal_handler(signum, frame):
    print("\n[!] 收到中断信号，正在优雅退出...")
    shutdown_event.set()


def allocate_star_ranges(star_ranges: list[str], num_tokens: int) -> list[list[str]]:
    allocations = [[] for _ in range(num_tokens)]
    for i, star_range in enumerate(star_ranges):
        allocations[i % num_tokens].append(star_range)
    return allocations


def main():
    signal.signal(signal.SIGINT, signal_handler)

    api_config = CONFIG["api"]
    star_ranges = CONFIG["star_ranges"]
    max_per_range = api_config.get("max_per_range", 500)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_existing_repos()
    allocations = allocate_star_ranges(star_ranges[::-1], len(TOKENS))
    progress = SharedProgressCounter()

    for repo_name in existing:
        progress.mark_scanned(repo_name)

    print(f"[*] 开始并行扫描，使用 {len(TOKENS)} 个 Token")
    print(f"[*] 已扫描仓库: {len(existing)} 个")
    print(f"[*] Star 范围分配:")
    for i, alloc in enumerate(allocations):
        print(f"    PAT{i + 1}: {alloc}")

    all_results = []
    with ThreadPoolExecutor(max_workers=len(TOKENS)) as executor:
        futures = []
        for token_idx, (token, ranges) in enumerate(zip(TOKENS, allocations)):
            for star_range in ranges:
                if shutdown_event.is_set():
                    break
                future = executor.submit(
                    scan_star_range,
                    star_range,
                    token,
                    token_idx,
                    progress,
                    max_per_range,
                )
                futures.append(future)

        for future in as_completed(futures):
            if shutdown_event.is_set():
                break
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"[!] 任务执行出错: {e}")

    print("\n[*] 合并所有结果...")
    merged_json, merged_csv, total = merge_all_outputs(star_ranges[::-1])
    print(f"\n[任务完成]")
    print(f"  - 合并 JSON: {merged_json}")
    print(f"  - 合并 CSV: {merged_csv}")
    print(f"  - 总命中数: {total}")


if __name__ == "__main__":
    main()
