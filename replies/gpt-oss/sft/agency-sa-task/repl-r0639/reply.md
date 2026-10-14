Commit: fix transport behavior for v2 jobs and tighten reasoning truncation

**Changes**
- Updated `sfttrain/transport.py`:
  - `HttpTransport` now accepts an optional `endpoint` argument and stores it.
  - `DryRunTransport` now writes request bodies to a file named after the API path (`v2_jobs.json` for the `/v2/jobs` endpoint) inside the given output directory, creates the directory if necessary, and returns a deterministic dry‑run response (`job_id` and `status` set to `"dry_run"`).
  - Added comprehensive docstrings and type hints.
- Fixed off‑by‑one error in `sfttrain/templates.py`:
  - `truncate_thought` now correctly retains the last `max_tokens` tokens instead of `max_tokens‑1`.
- Added minor imports and cleanup for clarity.

These adjustments ensure the dry‑run launch writes the expected `v2_jobs.json` file and returns the correct status, and that reasoning truncation respects the token limit precisely. All unit tests now pass.