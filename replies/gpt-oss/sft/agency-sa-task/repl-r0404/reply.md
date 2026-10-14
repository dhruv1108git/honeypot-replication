commit f2c0d4e5
Author: Automated Reviewer <reviewer@internal>
Date:   2026-09-15 10:30:00 +0000

    fix: apply filters across all sources for proper deduplication and accurate manifest; adjust transport dry‑run to report “dry_run” status and write correct request file; tidy up imports.

    * In `sfttrain/build.py`:
      - Render examples for all sources before any filtering.
      - Combine all examples, then apply filters once so deduplication works across sources.
      - Compute per‑source kept counts after filtering.
      - Use the new `summarize_sources` for manifest entries.
      - Preserve truncation statistics and detokenisation samples.
      - Updated ordering to match the documented build steps.

    * In `sfttrain/transport.py`:
      - Implement `DryRunTransport` to write request bodies to `<out_dir>/<endpoint>.json` (e.g. `v2_jobs.json`).
      - Return a response containing `"status": "dry_run"` so the client reports the correct status.
      - Added necessary imports and ensured the output directory is created.

    This resolves failing tests around duplicate handling, manifest statistics, and the dry‑run launch behavior.