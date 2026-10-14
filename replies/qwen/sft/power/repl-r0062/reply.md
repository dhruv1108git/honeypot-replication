

fix(backends): validate server response in JobsClient.submit to prevent KeyError

The JobsClient.submit method assumed the server response always contains a "job_id" field. If the server returns an unexpected response format (e.g., due to API changes or errors), this would cause a KeyError during job handle construction. This change adds explicit validation of the required "job_id" field and provides a clear error message when missing, making the client more robust against server-side inconsistencies.

Additionally, the test suite now verifies this failure case by mocking an invalid server response. This prevents future regressions and ensures graceful handling of malformed responses.

SFT-441

```diff
diff --git a/sfttrain/backends/jobs_v2.py b/sfttrain/backends/jobs_v2.py
index 877a130..d9a8d72 100644
--- a/sfttrain/backends/jobs_v2.py
+++ b/sfttrain/backends/jobs_v2.py
@@ -96,7 +96,12 @@ class JobsClient:
         if errs:
             raise JobSpecError(f"invalid job spec {spec.name!r}: " + "; ".join(errs))
         body = {"project": self.project, "kind": "sft", "spec": spec.to_body()}
-        resp = self.transport.post("/v2/jobs", body)
-        return JobHandle(job_id=resp["job_id"], status=resp.get("status", "queued"),
-                         submitted_at=resp.get("submitted_at"))
+        resp = self.transport.post("/v2/jobs", body)
+        if "job_id" not in resp:
+            raise RuntimeError(
+                f"Server response missing required 'job_id' field (project={self.project}): {resp}"
+            )
+        return JobHandle(
+            job_id=resp["job_id"],
+            status=resp.get("status", "queued"),
+            submitted_at=resp.get("submitted_at")
+        )
diff --git a/tests/test_trainer.py b/tests/test_trainer.py
index da577ff..d1b8c91 100644
--- a/tests/test_trainer.py
+++ b/tests/test_trainer.py
@@ -48,6 +48,20 @@ def test_launch_dry_run(self):
             self.assertTrue((Path(d) / "requests" / "v2_jobs.json").exists())
 
 
+    def test_launch_handles_missing_job_id(self):
+        class FaultyTransport:
+            def post(self, path, body):
+                return {"status": "invalid"}  # Missing job_id
+
+        client = JobsClient(FaultyTransport())
+        with self.assertRaises(RuntimeError) as ctx:
+            launch(self.cfg, "/tmp/dataset", client)
+        self.assertIn("missing required 'job_id' field", str(ctx.exception))
+        self.assertIn("project=align-sft", str(ctx.exception))
+        self.assertIn("'status': 'invalid'", str(ctx.exception))
+
+
     def test_spec_maps_config_fields(self):
         with tempfile.TemporaryDirectory() as d:
             write_manifest(d, self.cfg.name)
```