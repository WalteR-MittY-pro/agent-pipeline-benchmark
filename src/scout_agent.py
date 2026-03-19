#!/usr/bin/env python3
"""Scout Agent CLI - Scan PRs from multi-language repositories."""

import argparse
import json
import sys
from pathlib import Path

# Add src to path for imports
PROJECT_ROOT = Path(__file__).parent.parent  # Go up from src/ to project root
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scout import run_scout


def main():
    parser = argparse.ArgumentParser(
        description="Scout Agent - Scan PRs from multi-language repositories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/scout_agent.py                    # Scan all repos from pool
  python src/scout_agent.py --repos owner/repo1 owner/repo2  # Scan specific repos
  python src/scout_agent.py --dry-run          # Show what would be scanned
        """,
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        help="Specific repositories to scan (format: owner/repo)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be scanned without making API calls",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of repositories to scan",
    )

    args = parser.parse_args()

    # Load repos
    if args.repos:
        repos = args.repos
    else:
        repos_path = PROJECT_ROOT / "data" / "fetcher" / "multilang_repos_pool.json"
        with open(repos_path, encoding="utf-8") as f:
            repo_data = json.load(f)
        repos = [r["repo_name"] for r in repo_data]

    if args.limit:
        repos = repos[: args.limit]

    print(f"[*] Scout Agent 启动")
    print(f"[*] 仓库数量: {len(repos)}")

    if args.dry_run:
        print("[*] Dry-run 模式 - 以下仓库将被扫描:")
        for i, repo in enumerate(repos[:10]):
            print(f"    {i + 1}. {repo}")
        if len(repos) > 10:
            print(f"    ... 还有 {len(repos) - 10} 个仓库")
        return

    # Run Scout Agent
    candidates = run_scout(repos)

    print(f"\n[*] 扫描完成!")
    print(f"[*] 候选 PR 总数: {len(candidates)}")


if __name__ == "__main__":
    main()
