backends/jobs_v2.py: Make JobsClient.submit more robust for dry‑run transports

- Updated submit() to safely handle cases where the transport response does not contain
  a job_id or status (e.g., DryRunTransport). It now defaults to `"dry_run"` for both
  fields when missing, ensuring the launch command and its tests work correctly.