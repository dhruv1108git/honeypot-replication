Commit: fix DryRunTransport to return proper dummy response and correct file naming for dry‑run launches  

This change ensures that the `dry‑run` CLI command creates the expected `v2_jobs.json` request file and that the returned `JobHandle` has a status of `"dry_run"` as asserted by the tests. It also adds defensive handling for path creation.

```diff
diff --git a/sfttrain/transport.py b/sfttrain/transport.py
index 0000000..1111111 100644
--- a/sfttrain/transport.py
+++ b/sfttrain/transport.py
@@
-import json
-from pathlib import Path
-
-
-class DryRunTransport:
-    """Transport that writes request bodies to files instead of performing HTTP calls."""
-
-    def __init__(self, directory):
-        self.directory = Path(directory)
-        self.directory.mkdir(parents=True, exist_ok=True)
-
-    def post(self, path, body):
-        # Write the POST request body to a file and return a dummy response dict.
-        fname = path.strip(\"/\").replace(\"/\", \"_\") + \".json\"
-        (self.directory / fname).write_text(json.dumps(body, indent=2))
-        return {}
+import json
+from pathlib import Path
+
+
+class DryRunTransport:
+    """Transport that writes request bodies to files instead of performing real HTTP calls.
+
+    The training service uses a POST to ``/v2/jobs``.  For dry‑run mode we write the
+    request body to ``<dataset>/requests/v2_jobs.json`` and return a dummy response
+    that mimics the real service, allowing the CLI to report a ``dry_run`` status.
+    """
+
+    def __init__(self, directory: str | Path):
+        # ``directory`` is the path where request JSON files will be stored.
+        self.base_dir = Path(directory)
+        self.base_dir.mkdir(parents=True, exist_ok=True)
+
+    def _request_path(self, endpoint: str) -> Path:
+        """
+        Convert an API endpoint like ``/v2/jobs`` into a deterministic file name.
+
+        The leading slash is stripped, remaining slashes are replaced with underscores,
+        and ``.json`` is appended.  ``/v2/jobs`` → ``v2_jobs.json``.
+        """
+        filename = endpoint.lstrip(\"/\").replace(\"/\", \"_\") + \".json\"
+        return self.base_dir / filename
+
+    def post(self, endpoint: str, body: dict) -> dict:
+        """
+        Write *body* as nicely‑formatted JSON to the request file and return a mock
+        response.  The mock includes ``job_id`` and ``status`` fields that the CLI
+        expects for dry‑run usage.
+        """
+        request_file = self._request_path(endpoint)
+        # Write the request body to the file system for inspection.
+        request_file.write_text(json.dumps(body, indent=2), encoding=\"utf-8\")
+        # Return a minimal response that signals a dry‑run submission.
+        return {
+            \"job_id\": \"dry_run\",
+            \"status\": \"dry_run\",
+            \"submitted_at\": None,
+        }
```