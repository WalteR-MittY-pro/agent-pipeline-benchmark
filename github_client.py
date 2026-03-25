# github_client.py
import os
import json
import sqlite3
import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

from github import Github, GithubException, RateLimitExceededException

from state import RepoInfo, DiffFile

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API wrapper: token rotation, rate limiting, SQLite cache"""

    def __init__(
        self,
        tokens: list[str],
        cache_db: str = "benchmark_runs.db",
        min_request_interval: float = 2.0,
    ):
        if not tokens:
            raise ValueError("At least 1 GitHub token required")

        self._clients = [Github(t) for t in tokens]
        self._current_idx = 0
        self._min_interval = min_request_interval
        self._last_request_time = 0.0

        self._conn = sqlite3.connect(cache_db, check_same_thread=False)
        self._init_cache_tables()
        logger.info(f"GitHubClient initialized with {len(tokens)} tokens")

    def _init_cache_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS github_cache (
                cache_key   TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                ttl_hours   REAL NOT NULL
            );
        """)
        self._conn.commit()

    def _cache_get(self, key: str) -> Optional[Any]:
        row = self._conn.execute(
            "SELECT value, created_at, ttl_hours FROM github_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        value, created_at, ttl_hours = row
        if ttl_hours >= 0:
            expires = datetime.fromisoformat(created_at) + timedelta(hours=ttl_hours)
            if datetime.now() > expires:
                return None
        return json.loads(value)

    def _cache_set(self, key: str, value: Any, ttl_hours: float = 24.0):
        self._conn.execute(
            "INSERT OR REPLACE INTO github_cache (cache_key, value, created_at, ttl_hours) "
            "VALUES (?, ?, ?, ?)",
            (
                key,
                json.dumps(value, ensure_ascii=False, default=str),
                datetime.now().isoformat(),
                ttl_hours,
            ),
        )
        self._conn.commit()

    def _client(self) -> Github:
        return self._clients[self._current_idx]

    def _rotate_token(self):
        self._current_idx = (self._current_idx + 1) % len(self._clients)
        logger.warning(f"Token rotated to idx={self._current_idx}")

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _api_call(self, func, *args, max_retries: int = 3, **kwargs):
        for attempt in range(max_retries):
            try:
                self._throttle()
                return func(*args, **kwargs)
            except RateLimitExceededException:
                logger.warning(
                    f"Rate limit hit, rotating token (attempt {attempt + 1})"
                )
                self._rotate_token()
                try:
                    rate_limit = self._client().get_rate_limit()
                    reset_time = rate_limit.core.reset  # type: ignore[attr-defined]
                    wait_secs = (
                        max(0, (reset_time - datetime.utcnow()).total_seconds()) + 10
                    )
                    wait_secs = min(wait_secs, 300)
                    logger.info(f"Waiting {wait_secs:.0f}s before retry")
                    time.sleep(wait_secs)
                except Exception:
                    time.sleep(60)
            except GithubException as e:
                if e.status == 422:
                    raise ValueError(f"GitHub API query syntax error: {e.data}") from e
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"GitHub API error {e.status}, retrying...")
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"API call failed after {max_retries} retries")

    def search_repos(
        self,
        query: str,
        min_stars: int = 50,
        max_results: int = 30,
    ) -> list[RepoInfo]:
        cache_key = f"search:{hashlib.md5(f'{query}{min_stars}'.encode()).hexdigest()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: search_repos({query!r})")
            return cached

        full_query = query
        repos_by_name: dict[str, RepoInfo] = {}
        try:
            matches = self._api_call(
                lambda: self._client().search_code(full_query)
            )
            for match in matches:
                repo = match.repository
                if repo.full_name in repos_by_name:
                    continue
                if repo.stargazers_count < min_stars:
                    continue
                repos_by_name[repo.full_name] = {
                    "full_name": repo.full_name,
                    "clone_url": repo.clone_url,
                    "stars": repo.stargazers_count,
                    "interop_type": "",
                    "interop_layer": "",
                    "languages": {},
                    "default_branch": repo.default_branch or "main",
                }
                if len(repos_by_name) >= max_results:
                    break
        except Exception as e:
            logger.error(f"search_repos failed: {e}")
            return []

        repos = sorted(repos_by_name.values(), key=lambda r: r["stars"], reverse=True)
        self._cache_set(cache_key, repos, ttl_hours=24.0)
        return repos

    def list_prs(
        self,
        repo_full_name: str,
        max_n: int = 100,
    ) -> list[dict]:
        cache_key = f"prs:{repo_full_name}:{max_n}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        prs = []
        try:
            repo = self._api_call(lambda: self._client().get_repo(repo_full_name))
            pulls = self._api_call(
                lambda: repo.get_pulls(state="closed", sort="updated", direction="desc")
            )
            for pr in pulls:
                if pr.merged_at is None:
                    continue
                prs.append(
                    {
                        "number": pr.number,
                        "title": pr.title,
                        "merged_at": pr.merged_at.isoformat(),
                        "base_sha": pr.base.sha,
                        "head_sha": pr.head.sha,
                    }
                )
                if len(prs) >= max_n:
                    break
        except GithubException as e:
            if e.status == 404:
                logger.warning(f"Repo not found: {repo_full_name}")
                return []
            raise

        self._cache_set(cache_key, prs, ttl_hours=6.0)
        return prs

    def get_pr_files(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> list[DiffFile]:
        cache_key = f"pr_files:{repo_full_name}:{pr_number}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        files = []
        try:
            repo = self._api_call(lambda: self._client().get_repo(repo_full_name))
            pr = self._api_call(lambda: repo.get_pull(pr_number))
            for f in self._api_call(lambda: pr.get_files()):
                files.append(
                    {
                        "path": f.filename,
                        "lang": self._detect_lang(f.filename),
                        "is_test": self._is_test_file(f.filename),
                        "additions": f.additions,
                        "deletions": f.deletions,
                        "status": f.status,
                    }
                )
        except GithubException as e:
            if e.status == 404:
                return []
            raise

        self._cache_set(cache_key, files, ttl_hours=-1)
        return files

    def get_file_content(
        self,
        repo_full_name: str,
        sha: str,
        file_path: str,
    ) -> str:
        cache_key = f"file:{repo_full_name}:{sha}:{file_path}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            repo = self._api_call(lambda: self._client().get_repo(repo_full_name))
            content_file = self._api_call(lambda: repo.get_contents(file_path, ref=sha))
            if isinstance(content_file, list):
                return ""
            if content_file.size > 1_000_000:
                logger.warning(
                    f"File too large ({content_file.size} bytes), skipping: {file_path}"
                )
                return ""
            decoded = content_file.decoded_content.decode("utf-8", errors="ignore")
        except GithubException as e:
            if e.status == 404:
                return ""
            raise
        except UnicodeDecodeError:
            return ""

        self._cache_set(cache_key, decoded, ttl_hours=-1)
        return decoded

    def get_repo_tree(self, repo_full_name: str, sha: str) -> list[str]:
        cache_key = f"tree:{repo_full_name}:{sha}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            repo = self._api_call(lambda: self._client().get_repo(repo_full_name))
            tree = self._api_call(lambda: repo.get_git_tree(sha, recursive=True))
            paths = [item.path for item in tree.tree if item.type == "blob"]
        except Exception as e:
            logger.error(f"get_repo_tree failed: {e}")
            return []

        self._cache_set(cache_key, paths, ttl_hours=-1)
        return paths

    def list_workflow_files(self, repo_full_name: str, sha: str) -> list[str]:
        cache_key = f"workflows:{repo_full_name}:{sha}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        tree = self.get_repo_tree(repo_full_name, sha)
        workflow_paths = [
            p
            for p in tree
            if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
        ]
        contents = []
        for path in workflow_paths:
            content = self.get_file_content(repo_full_name, sha, path)
            if content:
                contents.append(content)

        self._cache_set(cache_key, contents, ttl_hours=-1)
        return contents

    @staticmethod
    def _detect_lang(file_path: str) -> str:
        ext_map = {
            ".go": "Go",
            ".c": "C",
            ".h": "C",
            ".cpp": "C++",
            ".cc": "C++",
            ".java": "Java",
            ".kt": "Kotlin",
            ".py": "Python",
            ".rs": "Rust",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".rb": "Ruby",
            ".lua": "Lua",
            ".wasm": "WASM",
        }
        ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        return ext_map.get(ext, "Other")

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        path_lower = file_path.lower()
        test_indicators = [
            "/test/",
            "/tests/",
            "/spec/",
            "/__tests__/",
            "_test.go",
            "_test.py",
            ".test.ts",
            ".test.js",
            ".spec.ts",
            ".spec.js",
            "test_",
            "/test",
        ]
        name = path_lower.split("/")[-1]
        return any(ind in path_lower for ind in test_indicators) or name.startswith(
            "test"
        )
