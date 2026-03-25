
- Switched Stage 1 graph checkpointing from `MemorySaver()` plus `interrupt_before` to SQLite-backed checkpointing with the single pause owned by `human_review.interrupt()`.
- Kept review as an explicit `--review` opt-in in `main.py`; fetch mode resumes the interrupted graph in-process with `Command(resume={"approved_pr_keys": ...})` and defaults to keeping all PRs when no keys are supplied.
