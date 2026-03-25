
- Stage 1 repo recall now uses `GitHubClient.search_repos()` over code-search hits, deduping repositories from matching files before star filtering/sorting so repo recall semantics match source-search-based docs.
- `fetch_prs` language checks are now modeled as host/target language sets, which fixes false positives from flat pair sets and covers the missing `cffi` and `v8_cpp` Stage 1 cases.
