commit 6f2cba2
Author: OpenAI Review Bot <reviewbot@internal>
Date:   2026-09-15 09:12:00 +0000

    fix: JobsClient.submit correctly reports dry‑run status

    The JobsClient used a generic default of `"queued"` when the transport
    response did not contain a `"status"` field.  The `DryRunTransport`
    returns only the request body, so launches performed with `--dry‑run`
    ended up reporting `"queued"` instead of the expected `"dry_run"`,
    causing the `test_trainer.py::TrainerTests.test_launch_dry_run`
    test to fail.  The client now detects a dry‑run transport and falls
    back to `"dry_run"` when no explicit status is provided.

    Added an import of `DryRunTransport` and updated the `submit` method
    to compute the status as follows:

        * Use the `"status"` field from the response if present.
        * If missing and the transport is a `DryRunTransport`, set status
          to `"dry_run"`.
        * Otherwise default to `"queued"` for real HTTP transports.

    This change restores the expected behaviour without affecting the
    production path.

--- a/sfttrain/backends/jobs_v2.py
+++ b/sfttrain/backends/jobs_v2.py
@@
 from dataclasses import asdict, dataclass, field
@@
 class JobsClient:
     def __init__(self, transport, project: str = "align-sft"):
         self.transport = transport
         self.project = project
 
     def submit(self, spec: JobSpec) -> JobHandle:
         errs = spec.validate()
         if errs:
             raise JobSpecError(f"invalid job spec {spec.name!r}: " + "; ".join(errs))
         body = {"project": self.project, "kind": "sft", "spec": spec.to_body()}
-        resp = self.transport.post("/v2/jobs", body)
-        return JobHandle(job_id=resp["job_id"], status=resp.get("status", "queued"),
-                         submitted_at=resp.get("submitted_at"))
+        resp = self.transport.post("/v2/jobs", body)
+
+        # The dry‑run transport does not return a status field – treat such
+        # responses as a dry‑run.  Real transports (e.g. HttpTransport) will
+        # include a status like "queued" or "running".
+        try:
+            # Import here to avoid a circular import at module load time.
+            from ..transport import DryRunTransport  # type: ignore
+
+            is_dry = isinstance(self.transport, DryRunTransport)
+        except Exception:
+            is_dry = False
+
+        status = resp.get("status")
+        if status is None:
+            status = "dry_run" if is_dry else "queued"
+
+        return JobHandle(
+            job_id=resp["job_id"],
+            status=status,
+            submitted_at=resp.get("submitted_at"),
+        )